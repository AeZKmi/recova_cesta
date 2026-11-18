"""
Práca na úrovni hlások (foném).

Obsahuje:
  * g2p()          – prevod slovenského slova na postupnosť foném (IPA),
  * normalize_phones() – zjednotenie výstupu fonémového modelu,
  * align()        – zarovnanie očakávaných a rozpoznaných foném (Levenshtein so spätným chodom),
  * evaluate_phonemes() – hodnotenie pokusu na úrovni hlások: je cieľová hláska
                     vyslovená, nahradená (napr. r → l) alebo vynechaná?

Modul nemá externé závislosti (rovnako ako scoring.py), dá sa testovať samostatne.

Slovenský pravopis je takmer fonologický, preto stačí súbor pravidiel. Pravidlá sú
zámerne zjednodušené (bez asimilácie znelosti vo vnútri slova a bez výnimiek
pri mäkčení de/te/ne); pre cieľové hlásky R, Š, L, C, K to nevadí, lebo ich
zjednodušenie nemení. Pozri README, kapitola „Hlásky“.
"""
from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass, field

from scoring import ScoringConfig, finalize, levenshtein

# --------------------------------------------------------------------------
# Inventár
# --------------------------------------------------------------------------

VOWELS = {"a", "aː", "ɛ", "ɛː", "i", "iː", "ɔ", "ɔː", "u", "uː", "ə", "æ", "e", "o", "y", "ɪ", "ʊ"}

# Cieľové hlásky hry: ktoré fonémy predstavujú hlásku v očakávanej výslovnosti
# (target) a ktoré výstupy modelu sa uznajú ako jej správna realizácia (accept).
# Uvulárne ʁ / ʀ pri R je typická chyba (ráčkovanie), preto NIE je v accept.
TARGETS = {
    "R": {"target": {"r", "rː"}, "accept": {"r", "rː", "ɾ", "r̩"}},
    "Š": {"target": {"ʃ"}, "accept": {"ʃ", "ʂ"}},
    "L": {"target": {"l", "lː", "ʎ"}, "accept": {"l", "lː", "ʎ", "ɫ", "l̩"}},
    "C": {"target": {"ts"}, "accept": {"ts"}},
    "K": {"target": {"k"}, "accept": {"k"}},
}

# skupiny „podobných“ foném – ich zámena stojí pri zarovnaní menej (0,5);
# zámena samohlásky za spoluhlásku stojí viac (1,4), aby sa zarovnávali „rovnaké druhy“
_GROUPS = [
    {"p", "b"}, {"t", "d"}, {"c", "ɟ"}, {"k", "g"}, {"f", "v"}, {"s", "z"}, {"ʃ", "ʒ"},
    {"x", "ɦ", "h"}, {"ts", "dz"}, {"tʃ", "dʒ"}, {"t", "c"}, {"d", "ɟ"}, {"n", "ɲ"},
    {"l", "ʎ"}, {"v", "u̯", "w"}, {"j", "i̯"},
]

# --------------------------------------------------------------------------
# Grafémy → fonémy
# --------------------------------------------------------------------------

_DIGRAPHS = {"dž": ["dʒ"], "dz": ["dz"], "ch": ["x"]}
_LETTERS = {
    "a": ["a"], "á": ["aː"], "ä": ["ɛ"], "b": ["b"], "c": ["ts"], "č": ["tʃ"], "d": ["d"],
    "ď": ["ɟ"], "e": ["ɛ"], "é": ["ɛː"], "f": ["f"], "g": ["g"], "h": ["ɦ"], "i": ["i"],
    "í": ["iː"], "j": ["j"], "k": ["k"], "l": ["l"], "ĺ": ["lː"], "ľ": ["ʎ"], "m": ["m"],
    "n": ["n"], "ň": ["ɲ"], "o": ["ɔ"], "ó": ["ɔː"], "ô": ["u", "ɔ"], "p": ["p"], "q": ["k", "v"],
    "r": ["r"], "ŕ": ["rː"], "s": ["s"], "š": ["ʃ"], "t": ["t"], "ť": ["c"], "u": ["u"],
    "ú": ["uː"], "v": ["v"], "w": ["v"], "x": ["k", "s"], "y": ["i"], "ý": ["iː"],
    "z": ["z"], "ž": ["ʒ"],
}
_SOFTEN = {"d": "ɟ", "t": "c", "n": "ɲ"}          # pred e, i, í (de, te, ne, di, ti, ni)
_DEVOICE = {"b": "p", "d": "t", "ɟ": "c", "g": "k", "z": "s", "ʒ": "ʃ", "ɦ": "x",
            "dz": "ts", "dʒ": "tʃ"}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def g2p_word(word: str) -> list[str]:
    """Jedno slovo → zoznam foném (IPA)."""
    w = "".join(ch for ch in _nfc(word) if ch.isalpha())
    out: list[str] = []
    i = 0
    while i < len(w):
        two = w[i:i + 2]
        if two in _DIGRAPHS:
            out += _DIGRAPHS[two]
            i += 2
            continue
        ch = w[i]
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch in _SOFTEN and nxt in ("e", "i", "í"):
            out.append(_SOFTEN[ch])
        else:
            out += _LETTERS.get(ch, [])
        i += 1
    # v na konci slabiky → u̯ (lev, krv)
    for k, p in enumerate(out):
        if p == "v" and (k == len(out) - 1 or out[k + 1] not in VOWELS):
            out[k] = "u̯"
    # spodobovanie na konci slova (dub → [dup])
    if out and out[-1] in _DEVOICE:
        out[-1] = _DEVOICE[out[-1]]
    return out


def g2p(text: str) -> list[str]:
    """Text (aj viac slov) → fonémy; hranice slov sa nezachovávajú."""
    out: list[str] = []
    for w in _nfc(text).split():
        out += g2p_word(w)
    return out


# --------------------------------------------------------------------------
# Výstup fonémového modelu
# --------------------------------------------------------------------------

_SYMBOL_MAP = {
    "e": "ɛ", "o": "ɔ", "ɡ": "g", "h": "ɦ", "ɹ": "ɹ", "ʦ": "ts", "ʧ": "tʃ", "ʣ": "dz", "ʤ": "dʒ",
    "ɐ": "a", "ɑ": "a", "ʌ": "a", "ɒ": "ɔ", "ɪ": "i", "ʊ": "u", "y": "i", "ɨ": "i",
}
_MERGE = {("t", "s"): "ts", ("t", "ʃ"): "tʃ", ("d", "z"): "dz", ("d", "ʒ"): "dʒ"}
_SEPARATORS = {"", " ", "|", "<s>", "</s>", "<unk>", "<pad>", "[PAD]", "[UNK]"}


def normalize_phone(p: str) -> str:
    p = unicodedata.normalize("NFC", p).replace("͡", "").replace("ˈ", "").replace("ˌ", "")
    long = p.endswith("ː")
    base = p[:-1] if long else p
    base = _SYMBOL_MAP.get(base, base)
    return base + ("ː" if long else "")


def normalize_phones(phones) -> list[tuple[str, float]]:
    """
    Zjednotí výstup modelu: odstráni oddeľovače a prízvuk, zlúči rozdelené
    afrikáty (t + s → ts). Vstup: [(fonéma, pravdepodobnosť)] alebo [fonéma].
    """
    items = [(p, 1.0) if isinstance(p, str) else (p[0], float(p[1])) for p in phones or []]
    clean = [(normalize_phone(p), pr) for p, pr in items if p not in _SEPARATORS]
    clean = [(p, pr) for p, pr in clean if p]
    out: list[tuple[str, float]] = []
    for p, pr in clean:
        if out and (out[-1][0], p) in _MERGE:
            prev, ppr = out.pop()
            out.append((_MERGE[(prev, p)], min(ppr, pr)))
        else:
            out.append((p, pr))
    return out


def _base(p: str) -> str:
    """Pri samohláskach sa dĺžka neporovnáva (rovnako ako v scoring.py)."""
    return p[:-1] if p.endswith("ː") and p[:-1] in VOWELS else p


def sub_cost(a: str, b: str) -> float:
    a, b = _base(a), _base(b)
    if a == b:
        return 0.0
    if a in VOWELS and b in VOWELS:
        return 0.5
    if any(a in g and b in g for g in _GROUPS):
        return 0.5
    if (a in VOWELS) != (b in VOWELS):
        return 1.4          # samohláska ↔ spoluhláska: radšej vloženie + vynechanie
    return 1.0


def align(expected: list[str], recognized: list[str]) -> tuple[float, list[tuple[int | None, int | None]]]:
    """
    Vážená Levenshteinova vzdialenosť so spätným chodom.
    Vracia (cena, páry indexov) – None znamená vynechanú/vloženú fonému.
    """
    n, m = len(expected), len(recognized)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = float(i)
    for j in range(1, m + 1):
        d[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + sub_cost(expected[i - 1], recognized[j - 1]))
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + sub_cost(expected[i - 1], recognized[j - 1]):
            pairs.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            pairs.append((i - 1, None)); i -= 1
        else:
            pairs.append((None, j - 1)); j -= 1
    return d[n][m], pairs[::-1]


def phone_error_rate(expected: list[str], recognized: list[str]) -> tuple[int, int]:
    """PER ako (počet chýb, dĺžka referencie) – nevážená vzdialenosť, sčítava sa cez dataset."""
    return levenshtein([_base(p) for p in expected], [_base(p) for p in recognized]), max(len(expected), 1)


# --------------------------------------------------------------------------
# Hodnotenie pokusu
# --------------------------------------------------------------------------

@dataclass
class PhonemeEvaluation:
    verdict: str                  # ok | partial | wrong | no_speech
    score: float
    stars: int
    expected: str                 # očakávané fonémy oddelené medzerou
    recognized: str               # rozpoznané fonémy
    similarity: float             # 1 − vážená vzdialenosť / dĺžka
    confidence: float             # priemerná pravdepodobnosť rozpoznaných foném
    target_ok: bool               # všetky výskyty cieľovej hlásky sú správne
    detail: list[dict] = field(default_factory=list)   # pre každý výskyt hlásky
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Krátky popis pre logopéda, napr. 'r→l' alebo 'r ✓'."""
        parts = []
        for d in self.detail:
            if d["status"] == "ok":
                parts.append(f"{d['expected']} ✓")
            elif d["status"] == "substituted":
                parts.append(f"{d['expected']}→{d['got']}")
            else:
                parts.append(f"{d['expected']} vynechané")
        return ", ".join(parts)


def target_phone(phoneme_key: str) -> str:
    return sorted(TARGETS[phoneme_key]["target"], key=len)[0]


def expected_phones(text: str, exercise: str, phoneme_key: str) -> list[str]:
    """Očakávané fonémy pre úlohu: izolovaná hláska = jedna fonéma, inak g2p."""
    if exercise == "sound":
        return [target_phone(phoneme_key)]
    return g2p(text)


def evaluate_phonemes(expected: list[str], recognized, phoneme_key: str,
                      exercise: str = "word", cfg=None) -> PhonemeEvaluation:
    """
    expected   – očakávané fonémy (expected_phones),
    recognized – výstup modelu [(fonéma, pravdepodobnosť)],
    exercise   – "word" | "syllable" | "sound".
    """
    cfg = cfg or ScoringConfig()
    rec = normalize_phones(recognized)
    rec_p = [p for p, _ in rec]
    exp_s = " ".join(expected)
    if not rec_p:
        return PhonemeEvaluation("no_speech", 0, 0, exp_s, "", 0, 0, False, [], ["empty"])

    target = TARGETS[phoneme_key]
    conf = sum(pr for _, pr in rec) / len(rec)
    detail: list[dict] = []

    if exercise == "sound":
        # izolovaná hláska ("rrrr"): samohlásky okolo sa ignorujú, rozhoduje,
        # či spoluhlásky v nahrávke sú cieľová hláska
        cons = [p for p in rec_p if _base(p) not in VOWELS]
        good = [p for p in cons if p in target["accept"]]
        sim = len(good) / len(cons) if cons else 0.0
        target_ok = bool(good) and sim >= 0.5
        got = good[0] if good else (cons[0] if cons else None)
        detail.append({"index": 0, "expected": expected[0], "got": got,
                       "status": "ok" if target_ok else ("substituted" if got else "deleted")})
    else:
        cost, pairs = align(expected, rec_p)
        sim = max(0.0, 1.0 - cost / max(len(expected), len(rec_p)))
        for ei, rj in pairs:
            if ei is None or expected[ei] not in target["target"]:
                continue
            got = rec_p[rj] if rj is not None else None
            status = "ok" if got in target["accept"] else ("substituted" if got else "deleted")
            detail.append({"index": ei, "expected": expected[ei], "got": got, "status": status})
        target_ok = bool(detail) and all(d["status"] == "ok" for d in detail)

    notes: list[str] = []
    if not target_ok:
        notes.append("target:" + ",".join(f"{d['expected']}>{d['got'] or '-'}"
                                          for d in detail if d["status"] != "ok"))
    score, stars, verdict = finalize(sim, conf, target_ok, sim >= 0.999 and target_ok, cfg)
    return PhonemeEvaluation(verdict, score, stars, exp_s, " ".join(rec_p), round(sim, 3),
                             round(conf, 3), target_ok, detail, notes)
