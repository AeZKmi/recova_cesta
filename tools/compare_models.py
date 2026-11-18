"""
Porovnanie neurónových sietí na rozpoznávanie reči – podklad pre kapitolu
„Testovanie a vyhodnotenie“.

Každý model spracuje rovnakú sadu nahrávok a vyhodnotí sa presne tak, ako
hodnotí hra (scoring.analyze). Ak sú zadané model pre slová aj fonémový model,
vypočíta sa navyše ich kombinácia (režim hybrid) – bez opätovného rozpoznávania.

Metriky (pre všetky nahrávky aj zvlášť pre hlásku / slabiky / slová):
  WER, CER      – chyby prepisu slov (modely pre slová)
  PER           – chyby na úrovni foném (fonémové modely)
  target_acc    – zhoda „hláska v poriadku áno/nie“ s anotáciou
  false_accept  – podiel CHYBNÝCH výslovností, ktoré model uznal (dieťa dostane pochvalu za chybu)
  false_reject  – podiel SPRÁVNYCH výslovností, ktoré model neuznal (dieťa je zbytočne opravované)
  error_recall / error_precision – ako dobre model zachytáva chyby výslovnosti
  latencia (priemer, p95), RTF, čas načítania

Manifest = CSV so stĺpcami
  path, reference [, phoneme, exercise, adult_label, actual_text]
(stiahnete ho z panela pre logopéda: /api/manifest.csv).
  reference   – cieľové slovo / slabika / hláska,
  actual_text – čo dieťa naozaj povedalo (napr. "lyba"); najlepší zdroj pravdy,
  adult_label – 1 = dospelý výslovnosť uznal, 0 = neuznal.

Príklad:
  python tools/compare_models.py --manifest manifest.csv --models \\
      small,large-v3-turbo,phoneme:facebook/wav2vec2-xlsr-53-espeak-cv-ft
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phonetics import evaluate_phonemes, expected_phones, g2p, phone_error_rate  # noqa: E402
from scoring import ScoringConfig, analyze, cer, normalize, wer  # noqa: E402

GROUPS = ("all", "sound", "syllable", "word")


# ------------------------------------------------------------------ dáta ---

def load_manifest(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        p = Path(r["path"])
        if not p.is_absolute():
            r["path"] = str((path.parent / p).resolve())
        r["exercise"] = (r.get("exercise") or "word").strip() or "word"
        r["phoneme"] = (r.get("phoneme") or "").strip()
    return rows


def ground_truth(row: dict) -> tuple[str | None, bool | None]:
    """
    (čo dieťa naozaj povedalo, je cieľová hláska správne?) – None = nevieme.
    Prednosť má zápis actual_text; inak „uznal“ znamená, že povedalo cieľ.
    """
    said = (row.get("actual_text") or "").strip() or None
    label = (row.get("adult_label") or "").strip()
    if said is None and label == "1":
        said = row["reference"]
    truth_ok = None
    if label in ("0", "1"):
        truth_ok = label == "1"
    elif said is not None and row.get("phoneme"):
        exp = expected_phones(row["reference"], row["exercise"], row["phoneme"])
        ev = evaluate_phonemes(exp, g2p(said), row["phoneme"], row["exercise"])
        truth_ok = ev.target_ok
    return said, truth_ok


# --------------------------------------------------------------- metriky ---

def _pct(a: float, b: float):
    return round(100 * a / b, 1) if b else None


def summarize(records: list[dict], accept_stars: int = 2) -> dict:
    """records: jeden riadok = jedna nahrávka vyhodnotená jedným systémom."""
    n = len(records)
    res: dict = {"n": n}
    ew = tw = ec = tc = ep = tp_ = 0
    for r in records:
        said = r.get("said")
        if said is None:
            continue
        if r["kind"] in ("words", "hybrid"):
            e, t = wer(said, r["text"]); ew += e; tw += t
            e, t = cer(said, r["text"]); ec += e; tc += t
        if r["kind"] in ("phonemes", "hybrid") and r["exercise"] != "sound" and r.get("phones") is not None:
            e, t = phone_error_rate(g2p(said), r["phones"]); ep += e; tp_ += t
    res["WER_%"] = _pct(ew, tw)
    res["CER_%"] = _pct(ec, tc)
    res["PER_%"] = _pct(ep, tp_)

    lab = [r for r in records if r.get("truth_ok") is not None]
    res["labelled"] = len(lab)
    res["target_acc_%"] = _pct(sum(r["target_ok"] == r["truth_ok"] for r in lab), len(lab))
    acc = [(r["stars"] >= accept_stars, r["truth_ok"]) for r in lab]
    good = [a for a, t in acc if t]
    bad = [a for a, t in acc if not t]
    res["decision_acc_%"] = _pct(sum(a == t for a, t in acc), len(acc))
    res["false_accept_%"] = _pct(sum(bad), len(bad))
    res["false_reject_%"] = _pct(sum(not a for a in good), len(good))
    caught = sum(not a for a in bad)                       # chyba správne neuznaná
    flagged = sum(not a for a, _ in acc)                   # všetky neuznané
    res["error_recall_%"] = _pct(caught, len(bad))
    res["error_precision_%"] = _pct(caught, flagged)
    res["avg_stars"] = round(st.mean(r["stars"] for r in records), 2) if records else None

    lat = sorted(r["latency_ms"] for r in records)
    res["lat_mean_ms"] = round(st.mean(lat)) if lat else None
    res["lat_p95_ms"] = lat[int(0.95 * (len(lat) - 1))] if lat else None
    rtf = [r["latency_ms"] / 1000 / r["duration"] for r in records if r.get("duration")]
    res["RTF"] = round(st.mean(rtf), 3) if rtf else None
    return res


def make_record(system: str, kind: str, row: dict, res: dict, latency: int, duration: float) -> dict:
    said, truth_ok = row["_truth"]
    ph = res.get("phonemes") or {}
    return {
        "system": system, "kind": kind, "path": row["path"], "exercise": row["exercise"],
        "phoneme": row["phoneme"], "reference": row["reference"], "said": said,
        "truth_ok": truth_ok, "text": res["recognized_text"],
        "phones": ph.get("recognized", "").split() if ph else None,
        "phone_detail": ph.get("summary", "") if ph else "",
        "target_ok": bool(res["target_sound_ok"]), "stars": res["stars"], "score": res["score"],
        "verdict": res["verdict"], "mode": res["mode"], "latency_ms": latency, "duration": duration,
    }


# ------------------------------------------------------------ spustenie ---

def grapheme_for(phoneme: str, words: dict) -> str:
    return words.get(phoneme, {}).get("grapheme", phoneme.lower()) if phoneme else ""


def run_model(spec: str, rows: list[dict], device: str, compute_type: str) -> tuple[object, list[dict]]:
    from asr import create_recognizer
    print(f"\n=== {spec} ===")
    rec = create_recognizer(spec, device, compute_type)
    print(f"  načítaný za {rec.load_seconds} s")
    outs = []
    for i, r in enumerate(rows, 1):
        try:
            out = rec.transcribe(r["path"])
        except Exception as exc:   # poškodená nahrávka – pokračujeme
            print(f"  [{i}/{len(rows)}] CHYBA {r['path']}: {exc}")
            out = {"text": "", "words": [], "phones": [] if rec.kind == "phonemes" else None,
                   "no_speech_prob": 1.0, "duration": 0, "latency_ms": 0}
        outs.append(out)
        print(f"  [{i}/{len(rows)}] {r['reference']!r:>12} → {out['text']!r} ({out['latency_ms']} ms)")
    return rec, outs


def evaluate_system(system: str, kind: str, rows: list[dict], words: dict, cfg: ScoringConfig,
                    word_outs: list | None, ph_outs: list | None) -> list[dict]:
    recs = []
    for i, r in enumerate(rows):
        wo = word_outs[i] if word_outs else None
        po = ph_outs[i] if ph_outs else None
        g = grapheme_for(r["phoneme"], words) or normalize(r["reference"])[:1]
        key = r["phoneme"] if r["phoneme"] in words else None
        if po is not None and key is None:
            po = None                       # bez známej hlásky sa fonémy hodnotiť nedajú
        if wo is None and po is None:
            continue
        res = analyze(r["reference"], key or "R", g, r["exercise"], wo, po, cfg)
        latency = sum(o["latency_ms"] for o in (wo, po) if o)
        duration = (wo or po)["duration"]
        recs.append(make_record(system, kind, r, res, latency, duration))
    return recs


def to_markdown(summary: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n| " + " | ".join("---" for _ in cols) + " |\n"
    body = "".join("| " + " | ".join("" if s.get(c) is None else str(s.get(c)) for c in cols) + " |\n"
                   for s in summary)
    return head + body


MD_COLS = ["system", "group", "n", "labelled", "WER_%", "CER_%", "PER_%", "target_acc_%",
           "false_accept_%", "false_reject_%", "error_recall_%", "lat_mean_ms", "lat_p95_ms", "RTF", "load_s"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--models", default="small,phoneme:facebook/wav2vec2-xlsr-53-espeak-cv-ft",
                    help="identifikátory oddelené čiarkou (pozri asr.py)")
    ap.add_argument("--no-hybrid", action="store_true", help="nepočítať kombinácie slovo + fonémy")
    ap.add_argument("--accept-stars", type=int, default=2,
                    help="od koľkých hviezdičiek sa výslovnosť považuje za uznanú (predvolene 2)")
    ap.add_argument("--limit", type=int, default=0, help="len prvých N nahrávok (na skúšku)")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute-type", default="default")
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    a = ap.parse_args()

    rows = load_manifest(a.manifest)
    if a.limit:
        rows = rows[:a.limit]
    missing = [r["path"] for r in rows if not Path(r["path"]).exists()]
    rows = [r for r in rows if Path(r["path"]).exists()]
    if missing:
        print(f"⚠ {len(missing)} nahrávok neexistuje, preskakujem (napr. {missing[0]})")
    if not rows:
        sys.exit("Manifest neobsahuje žiadne existujúce nahrávky.")
    for r in rows:
        r["_truth"] = ground_truth(r)
    words = json.loads((ROOT / "data" / "words.json").read_text(encoding="utf-8"))["phonemes"]
    cfg = ScoringConfig()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = a.out / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    systems = []          # (názov, druh, word_outs, ph_outs, load_s)
    word_runs, ph_runs = [], []
    for spec in [s.strip() for s in a.models.split(",") if s.strip()]:
        rec, outs = run_model(spec, rows, a.device, a.compute_type)
        name = rec.spec
        with open(out_dir / f"raw_{len(systems)}.jsonl", "w", encoding="utf-8") as f:
            for r, o in zip(rows, outs):
                f.write(json.dumps({"system": name, "path": r["path"], **o}, ensure_ascii=False) + "\n")
        if rec.kind == "phonemes":
            systems.append((name, "phonemes", None, outs, rec.load_seconds))
            ph_runs.append((name, outs, rec.load_seconds))
        else:
            systems.append((name, "words", outs, None, rec.load_seconds))
            word_runs.append((name, outs, rec.load_seconds))
        del rec
    if not a.no_hybrid:
        for wn, wo, wl in word_runs:
            for pn, po, pl in ph_runs:
                systems.append((f"{wn} + {pn}", "hybrid", wo, po, round(wl + pl, 1)))

    details, summary = [], []
    for name, kind, wo, po, load_s in systems:
        recs = evaluate_system(name, kind, rows, words, cfg, wo, po)
        details += recs
        for g in GROUPS:
            part = recs if g == "all" else [r for r in recs if r["exercise"] == g]
            if part:
                summary.append({"system": name, "kind": kind, "group": g, "load_s": load_s,
                                **summarize(part, a.accept_stars)})

    def write_csv(name, data):
        keys = list(dict.fromkeys(k for d in data for k in d))
        with open(out_dir / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows([{k: (" ".join(v) if isinstance(v, list) else v) for k, v in d.items()} for d in data])

    write_csv("details.csv", details)
    write_csv("summary.csv", summary)
    n_lab = sum(r["_truth"][1] is not None for r in rows)
    md = (f"# Porovnanie modelov ({time.strftime('%Y-%m-%d %H:%M')})\n\n"
          f"Nahrávok: {len(rows)}, z toho anotovaných: {n_lab}. "
          f"Uznané = aspoň {a.accept_stars} ★.\n\n" + to_markdown(summary, MD_COLS))
    (out_dir / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Uložené do {out_dir}")


if __name__ == "__main__":
    main()
