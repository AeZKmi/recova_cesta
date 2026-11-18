"""
Prepočet uložených pokusov novou logikou hodnotenia – bez spúšťania Whisper.

Číta data/attempts.sqlite3 LEN NA ČÍTANIE, z uloženého prepisu (transcript)
a istoty modelu (confidence) znovu vypočíta hviezdičky a vypíše:
  * ktoré pokusy sa zmenili (staré → nové hviezdičky),
  * zhodu s hodnotením dospelého pred zmenou a po nej.

Použitie:  python tools/rescore.py [--db data/attempts.sqlite3] [--accept-stars 2]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring import ScoringConfig, evaluate  # noqa: E402


def rescore(rows: list[dict], graphemes: dict, cfg: ScoringConfig) -> list[dict]:
    out = []
    for r in rows:
        if (r.get("exercise") or "word") != "word" or r.get("mode") == "phoneme":
            continue                     # hlásky a slabiky hodnotil fonémový model
        text = r["transcript"] or ""
        conf = r["confidence"] if r["confidence"] is not None else 0.5
        asr = {"text": text, "words": [(w, conf) for w in text.split()], "no_speech_prob": 0.0}
        ev = evaluate(r["word"], graphemes.get(r["phoneme"], r["phoneme"].lower()), asr, cfg)
        out.append({"id": r["id"], "word": r["word"], "transcript": text, "old": r["stars"],
                    "new": ev.stars, "adult": r["manual_override"]})
    return out


def agreement(items: list[dict], key: str, accept: int) -> tuple[int, int]:
    lab = [i for i in items if i["adult"] is not None]
    return sum((i[key] >= accept) == bool(i["adult"]) for i in lab), len(lab)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "attempts.sqlite3")
    ap.add_argument("--accept-stars", type=int, default=2)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM attempts ORDER BY id")]
    words = json.loads((ROOT / "data" / "words.json").read_text(encoding="utf-8"))["phonemes"]
    items = rescore(rows, {k: v["grapheme"] for k, v in words.items()}, ScoringConfig())

    changed = [i for i in items if i["old"] != i["new"]]
    print(f"Pokusov: {len(items)}, zmenených: {len(changed)}\n")
    print("| id | slovo | prepis | pôvodne | teraz | dospelý |")
    print("| --- | --- | --- | --- | --- | --- |")
    for i in changed:
        adult = {None: "", 1: "uznal", 0: "neuznal"}[i["adult"]]
        print(f"| {i['id']} | {i['word']} | {i['transcript']} | {'★' * i['old'] or '0'} | "
              f"{'★' * i['new'] or '0'} | {adult} |")
    for key, name in (("old", "pôvodné"), ("new", "nové")):
        ok, n = agreement(items, key, a.accept_stars)
        if n:
            print(f"\nZhoda s dospelým ({name} hodnotenie, uznané = ≥ {a.accept_stars} ★): "
                  f"{ok}/{n} = {100 * ok / n:.0f} %")


if __name__ == "__main__":
    main()
