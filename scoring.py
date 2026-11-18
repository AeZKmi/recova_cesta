"""
Hodnotenie výslovnosti na základe výstupu Whisper (a analyze() pre celý pokus).

Modul nemá žiadne externé závislosti, aby sa dal samostatne testovať
(tests/test_scoring.py) a použiť aj v nástroji tools/compare_models.py.

Princíp hodnotenia (popísaný v README, kap. "Ako sa počíta skóre"):
  1. Normalizácia textu (malé písmená, bez interpunkcie, diakritika ZOSTÁVA –
     rozdiel s/š, c/č je presne to, čo logopéd sleduje).
  2. Nájdenie slova v prepise, ktoré sa najviac podobá cieľovému slovu
     (dieťa môže povedať "to je ryba").
  3. Textová podobnosť (normalizovaná Levenshteinova vzdialenosť na znakoch)
     a istota modelu (pravdepodobnosť slova z Whisper) sa skombinujú do skóre 0–100.
  4. Ak v rozpoznanom slove chýba cieľová hláska, skóre sa obmedzí (cap).
  5. Skóre sa prevedie na hviezdičky podľa prahov 60 / 75 / 91 %, ktoré
     používa platforma LogoHra (Kováč et al., Electronics 2026, 15, 3165).
  6. Presná zhoda s cieľovým slovom (a cieľová hláska na mieste) = vždy 3 hviezdičky.
     Dĺžka samohlások sa pri porovnaní ignoruje (Whisper ju často zamieňa).

Hodnotenie na úrovni hlások je v module phonetics.py; funkcia combine() nižšie
spája obe hodnotenia (režim "hybrid"), analyze() vyhodnotí celý pokus.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field

# --------------------------------------------------------------------------
# Konfigurácia hodnotenia (dá sa prepísať v config.py)
# --------------------------------------------------------------------------

@dataclass
class ScoringConfig:
    # váha textovej podobnosti a istoty modelu (súčet = 1)
    weight_similarity: float = 0.7
    weight_confidence: float = 0.3
    # prahy pre 1, 2 a 3 hviezdičky (LogoHra: 60–74 → 1, 75–90 → 2, ≥91 → 3)
    star_thresholds: tuple[int, int, int] = (60, 75, 91)
    # maximálne skóre, ak cieľová hláska v rozpoznanom slove chýba
    missing_target_cap: float = 74.0
    # najviac hviezdičiek, ak cieľová hláska chýba (1 = povzbudenie, 0 = prísne)
    missing_target_max_stars: int = 1
    # ak je pravdepodobnosť "ticha" vyššia a podobnosť nízka → nič nepočul
    no_speech_threshold: float = 0.6
    # dĺžka samohlások (á/a, í/i, ...) sa pri porovnaní neberie do úvahy
    ignore_vowel_length: bool = True
    # hybrid: fonémový model môže znížiť hodnotenie slova, ak cieľovú hlásku
    # počul nahradenú, len ak je dostatočne istý
    phoneme_veto_min_confidence: float = 0.5


# Typické "halucinácie" Whisper na tichu/šume v slovenčine a češtine.
HALLUCINATIONS = [
    r"titulky", r"ďakujem za pozornosť", r"dakujem za pozornost",
    r"^(ďakujem|dakujem|děkuji|dekuji)( (ďakujem|dakujem|děkuji|dekuji))*$",
    r"děkuji za pozornost", r"odoberajte", r"subscribe", r"www\.", r"\.sk\b", r"\.cz\b",
]

# Grafémy, ktoré obsahujú iné grafémy (pri hláske C sa nesmie počítať "ch").
_EXCLUDE = {"c": ["ch"], "d": ["dz", "dž"]}


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Malé písmená, NFC, len písmená a medzery. Diakritika ostáva."""
    text = unicodedata.normalize("NFC", text or "").lower()
    text = re.sub(r"[^\w\s]|[\d_]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_LENGTH = str.maketrans({"á": "a", "ä": "a", "é": "e", "í": "i", "ó": "o", "ô": "o",
                         "ú": "u", "ý": "y", "ŕ": "r", "ĺ": "l"})


def strip_length(text: str) -> str:
    """Odstráni dĺžku samohlások (a slabičných ŕ, ĺ); š, č, ž, ľ, ď, ť, ň zostávajú."""
    return (text or "").translate(_LENGTH)


def levenshtein(a, b) -> int:
    """Editačná vzdialenosť pre reťazce aj zoznamy (slová pri WER)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """1.0 = zhodné, 0.0 = úplne odlišné (na úrovni znakov)."""
    if not a and not b:
        return 1.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def _mask(word: str, grapheme: str) -> tuple[str, str]:
    """Normalizuje slovo a zakryje dlhšie grafémy (pri 'c' sa nepočíta 'ch')."""
    masked, grapheme = normalize(word), grapheme.lower()
    for longer in _EXCLUDE.get(grapheme, []):
        masked = masked.replace(longer, "#" * len(longer))
    return masked, grapheme


def count_grapheme(word: str, grapheme: str) -> int:
    """Počet výskytov grafémy; pri 'c' sa nepočíta 'ch' a pod."""
    masked, grapheme = _mask(word, grapheme)
    return masked.count(grapheme)


def target_positions(word: str, grapheme: str) -> list[str]:
    """Pozície hlásky v slove: 'initial', 'medial', 'final'."""
    masked, grapheme = _mask(word, grapheme)
    out = []
    for m in re.finditer(re.escape(grapheme), masked):
        if m.start() == 0:
            out.append("initial")
        elif m.end() == len(masked):
            out.append("final")
        else:
            out.append("medial")
    return out


def is_hallucination(text: str) -> bool:
    variants = (normalize(text), (text or "").lower())
    return any(re.search(p, t) for p in HALLUCINATIONS for t in variants)


# --------------------------------------------------------------------------
# Hodnotenie jedného pokusu
# --------------------------------------------------------------------------

@dataclass
class Evaluation:
    verdict: str                 # "ok" | "partial" | "wrong" | "no_speech"
    score: float                 # 0–100
    stars: int                   # 0–3
    recognized_text: str         # celý prepis z Whisper
    matched_word: str            # slovo z prepisu porovnávané s cieľom
    similarity: float            # 0–1
    confidence: float            # 0–1 (pravdepodobnosť slova z Whisper)
    target_sound_ok: bool        # obsahuje rozpoznané slovo cieľovú hlásku?
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def best_match(target: str, words: list[tuple[str, float]],
               ignore_length: bool = True) -> tuple[str, float, float]:
    """
    Nájde v rozpoznaných slovách kandidáta najpodobnejšieho cieľovému slovu.
    Skúša jednotlivé slová aj spojenie dvoch susedných (Whisper niekedy
    rozdelí slovo, napr. "kro kodíl"). Vracia (slovo, podobnosť, istota).
    """
    target = normalize(target)
    cands: list[tuple[str, float]] = []
    clean = [(normalize(w), p) for w, p in words if normalize(w)]
    for i, (w, p) in enumerate(clean):
        cands.append((w, p))
        if i + 1 < len(clean):
            w2, p2 = clean[i + 1]
            cands.append((w + w2, min(p, p2)))
    if not cands:
        return "", 0.0, 0.0
    key = strip_length if ignore_length else (lambda x: x)
    sim = lambda w: similarity(key(target), key(w))  # noqa: E731
    best = max(cands, key=lambda c: (sim(c[0]), c[1]))
    return best[0], sim(best[0]), float(best[1])


def stars_for(score: float, thresholds=(60, 75, 91)) -> int:
    return sum(score >= t for t in thresholds)


def finalize(sim: float, conf: float, target_ok: bool, exact: bool,
             cfg: ScoringConfig) -> tuple[float, int, str]:
    """
    Spoločné pre slová aj hlásky: skóre z podobnosti a istoty, strop pri chybnej
    cieľovej hláske, presná zhoda = 3 hviezdičky. Vracia (skóre, hviezdičky, verdikt).
    """
    score = 100.0 * (cfg.weight_similarity * sim + cfg.weight_confidence * conf)
    if not target_ok:
        score = min(score, cfg.missing_target_cap)
    if exact:
        # presná zhoda: nízka istota modelu nesmie zobrať správne slovo hviezdičku
        score = max(score, cfg.star_thresholds[2])
    score = round(score, 1)
    stars = stars_for(score, cfg.star_thresholds)
    if not target_ok:
        stars = min(stars, cfg.missing_target_max_stars)
    return score, stars, "ok" if exact else ("partial" if stars >= 1 else "wrong")


def evaluate(target_word: str, target_grapheme: str, asr: dict,
             cfg: ScoringConfig | None = None) -> Evaluation:
    """
    asr = {"text": str, "words": [(slovo, pravdepodobnosť), ...],
           "no_speech_prob": float}
    """
    cfg = cfg or ScoringConfig()
    text = (asr.get("text") or "").strip()
    words = asr.get("words") or [(w, 0.5) for w in text.split()]
    notes: list[str] = []

    if not normalize(text) or not words:
        return Evaluation("no_speech", 0, 0, text, "", 0, 0, False, ["empty"])

    matched, sim, conf = best_match(target_word, words, cfg.ignore_vowel_length)

    if is_hallucination(text) and sim < 0.5:
        return Evaluation("no_speech", 0, 0, text, matched, sim, conf, False, ["hallucination"])
    if asr.get("no_speech_prob", 0) > cfg.no_speech_threshold and sim < 0.5:
        return Evaluation("no_speech", 0, 0, text, matched, sim, conf, False, ["no_speech_prob"])

    key = strip_length if cfg.ignore_vowel_length else (lambda x: x)
    need = count_grapheme(key(target_word), key(target_grapheme))
    target_ok = count_grapheme(key(matched), key(target_grapheme)) >= need
    if not target_ok:
        notes.append(f"missing_target:{target_grapheme}")
    score, stars, verdict = finalize(sim, conf, target_ok, sim == 1.0 and target_ok, cfg)
    return Evaluation(verdict, score, stars, text, matched, round(sim, 3),
                      round(conf, 3), target_ok, notes)


def combine(word_ev: "Evaluation | None", ph_ev, cfg: ScoringConfig | None = None) -> dict:
    """
    Režim "hybrid": slovo hodnotí Whisper (čo dieťa povedalo), hlásku fonémový
    model (ako to povedalo). Ak fonémový model s dostatočnou istotou počul cieľovú
    hlásku nahradenú alebo vynechanú, hviezdičky sa obmedzia rovnako ako pri
    chýbajúcej hláske v slove. Opačne fonémový model hodnotenie nezvyšuje.

    Vracia slovník s výsledným hodnotením a režimom ("word" | "phoneme" | "hybrid").
    """
    cfg = cfg or ScoringConfig()
    if word_ev is None and ph_ev is None:
        raise ValueError("Chýba hodnotenie")
    if word_ev is None:
        return {"mode": "phoneme", "verdict": ph_ev.verdict, "score": ph_ev.score,
                "stars": ph_ev.stars, "target_sound_ok": ph_ev.target_ok, "notes": list(ph_ev.notes)}
    out = {"mode": "word", "verdict": word_ev.verdict, "score": word_ev.score,
           "stars": word_ev.stars, "target_sound_ok": word_ev.target_sound_ok,
           "notes": list(word_ev.notes)}
    if ph_ev is None:
        return out
    out["mode"] = "hybrid"
    veto = (word_ev.verdict != "no_speech" and ph_ev.verdict != "no_speech"
            and not ph_ev.target_ok and ph_ev.confidence >= cfg.phoneme_veto_min_confidence)
    if veto:
        out["target_sound_ok"] = False
        out["score"] = round(min(out["score"], cfg.missing_target_cap), 1)
        out["stars"] = min(stars_for(out["score"], cfg.star_thresholds), cfg.missing_target_max_stars)
        out["verdict"] = "partial" if out["stars"] >= 1 else "wrong"
        out["notes"].append("phoneme_veto")
    return out


# --------------------------------------------------------------------------
# Celý pokus (server aj tools/compare_models.py hodnotia rovnako)
# --------------------------------------------------------------------------
# Režimy: word (len model pre slová), phoneme (len fonémový model), hybrid (slovo
# hodnotí model pre slová, cieľovú hlásku fonémový model), text_fallback (hláska
# alebo slabika bez fonémového modelu – porovná sa len prepis, nespoľahlivé).

EXERCISES = ("word", "syllable", "sound")


def needs(exercise: str, have_word: bool, have_phoneme: bool) -> tuple[bool, bool]:
    """Ktoré modely treba spustiť: (slová, fonémy)."""
    if exercise == "word":
        return have_word, have_phoneme
    # hláska a slabika: Whisper hľadá slová, preto ho použijeme len ako núdzové riešenie
    return (not have_phoneme) and have_word, have_phoneme


def analyze(target_text: str, phoneme_key: str, grapheme: str, exercise: str,
            word_out: dict | None, ph_out: dict | None, cfg: ScoringConfig | None = None) -> dict:
    from phonetics import evaluate_phonemes, expected_phones
    cfg = cfg or ScoringConfig()
    if exercise not in EXERCISES:
        raise ValueError(f"Neznáme cvičenie {exercise}")

    word_ev = evaluate(target_text, grapheme, word_out, cfg) if word_out is not None else None
    ph_ev = None
    if ph_out is not None:
        exp = expected_phones(target_text, exercise, phoneme_key)
        ph_ev = evaluate_phonemes(exp, ph_out.get("phones") or [], phoneme_key, exercise, cfg)

    final = combine(word_ev, ph_ev, cfg)
    if exercise != "word" and ph_ev is None:
        final["mode"] = "text_fallback"
    main = word_ev or ph_ev
    return {
        **final,
        "exercise": exercise,
        "recognized_text": word_ev.recognized_text if word_ev else (ph_out or {}).get("text", ""),
        "matched_word": word_ev.matched_word if word_ev else "",
        "similarity": main.similarity if main else 0,
        "confidence": main.confidence if main else 0,
        "word_stars": word_ev.stars if word_ev else None,
        "phonemes": None if ph_ev is None else {**ph_ev.to_dict(), "summary": ph_ev.summary()},
    }


# --------------------------------------------------------------------------
# Metriky pre testovanie (tools/compare_models.py)
# --------------------------------------------------------------------------

def wer(reference: str, hypothesis: str) -> tuple[int, int]:
    """Vracia (počet chýb, počet slov referencie) – sčítava sa cez celý dataset."""
    r, h = normalize(reference).split(), normalize(hypothesis).split()
    return levenshtein(r, h), max(len(r), 1)


def cer(reference: str, hypothesis: str) -> tuple[int, int]:
    r = normalize(reference).replace(" ", "")
    h = normalize(hypothesis).replace(" ", "")
    return levenshtein(r, h), max(len(r), 1)
