"""
Rečová cesta – webový server hry.

Spustenie:   python server.py
Potom v prehliadači otvorte  http://127.0.0.1:8000
Panel pre logopéda:          http://127.0.0.1:8000/terapeut

Modely sa vyberajú v config.py (ASR_MODEL pre slová, PHONEME_MODEL pre hlásky).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
from asr import load_audio
from scoring import EXERCISES, analyze, needs, target_positions

STATIC = config.BASE_DIR / "static"
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
# načítajú sa pri štarte; v testoch sa dajú nahradiť falošnými rozpoznávačmi
recognizer = None          # model pre slová (Whisper a pod.)
phoneme_recognizer = None  # model pre hlásky (fonémy)
phoneme_error = ""         # prečo fonémový model nie je k dispozícii
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="asr")   # oba modely súčasne


def load_words() -> dict:
    with open(config.WORDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_models() -> None:
    """Načíta modely podľa config.py. Fonémový model je nepovinný."""
    global recognizer, phoneme_recognizer, phoneme_error
    from asr import create_recognizer
    threads = config.ASR_THREADS
    if not threads and config.PHONEME_MODEL:      # oba modely počítajú súčasne → deliť jadrá
        threads = max(1, (os.cpu_count() or 2) // 2)
    print(f"Načítavam model pre slová '{config.ASR_MODEL}' (prvýkrát sa sťahuje)…")
    rec = create_recognizer(config.ASR_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE_TYPE, threads)
    print(f"  pripravený za {rec.load_seconds} s")
    if rec.kind == "phonemes":          # ako hlavný model je zvolený fonémový
        phoneme_recognizer = rec
    else:
        recognizer = rec
    if config.PHONEME_MODEL and phoneme_recognizer is None:
        print(f"Načítavam model pre hlásky '{config.PHONEME_MODEL}'…")
        try:
            phoneme_recognizer = create_recognizer(config.PHONEME_MODEL, config.WHISPER_DEVICE,
                                                   threads=threads)
            print(f"  pripravený za {phoneme_recognizer.load_seconds} s")
        except ImportError as exc:
            phoneme_error = (f"chýbajú knižnice ({exc.name}); nainštalujte "
                             "pip install -r requirements-phoneme.txt")
        except Exception as exc:  # napr. model sa nedá stiahnuť
            phoneme_error = f"model sa nepodarilo načítať: {exc}"
        if phoneme_error:
            print(f"  ⚠ Fonémový model nie je k dispozícii – {phoneme_error}")
    def on_cpu(r):
        ct = "int8" if config.WHISPER_COMPUTE_TYPE.startswith("int8") else "default"
        return create_recognizer(r.spec, "cpu", ct, threads)

    # Zahriatie zároveň overí, že model naozaj počíta. Typicky Windows s grafikou NVIDIA
    # bez knižníc CUDA (cublas64_12.dll): model sa načíta na GPU, ale každý výpočet zlyhá
    # alebo visí → taký model sa hneď presunie na CPU.
    if recognizer:
        recognizer = warm_up(recognizer, on_cpu)
    if phoneme_recognizer:
        phoneme_recognizer = warm_up(phoneme_recognizer, on_cpu)
    print(f"Vlákna CPU na model: {threads or 'predvolené'} (jadier: {os.cpu_count()})")


def warm_up(r, on_cpu):
    """Prvý výpočet pri štarte. Ak zlyhá mimo CPU, vráti ten istý model načítaný na CPU."""
    t0 = time.perf_counter()
    try:
        r.warm_up()
        print(f"  {r.spec} zahriaty za {time.perf_counter() - t0:.1f} s")
        return r
    except Exception as exc:
        if config.WHISPER_DEVICE == "cpu":
            print(f"  ⚠ Zahriatie modelu {r.spec} zlyhalo: {exc}")
            return r
        print(f"  ⚠ {r.spec} na grafickej karte nefunguje ({exc}) – prepínam na CPU…")
    try:
        cpu = on_cpu(r)
        t0 = time.perf_counter()
        cpu.warm_up()
        print(f"  {cpu.spec} beží na CPU, zahriaty za {time.perf_counter() - t0:.1f} s")
        return cpu
    except Exception as exc:
        print(f"  ⚠ Model {r.spec} nefunguje ani na CPU: {exc}")
        return r


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    if recognizer is None and phoneme_recognizer is None:
        load_models()
    print(f"Otvorte http://{config.HOST}:{config.PORT}")
    yield


app = FastAPI(title="Rečová cesta", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def check_code(code: str) -> str:
    if not CODE_RE.match(code or ""):
        raise HTTPException(400, "Kód dieťaťa môže obsahovať len písmená bez diakritiky, čísla, - a _ (max. 20 znakov).")
    return code


# ---------------------------------------------------------------- stránky ---

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/terapeut", include_in_schema=False)
def therapist_page():
    return FileResponse(STATIC / "therapist.html")


# ------------------------------------------------------------------- API ---

@app.get("/api/config")
def get_config():
    return {
        "model": recognizer.spec if recognizer else None,
        "phoneme_model": phoneme_recognizer.spec if phoneme_recognizer else None,
        "phoneme_error": phoneme_error,
        "star_thresholds": config.SCORING.star_thresholds,
        "max_attempts": config.MAX_ATTEMPTS,
        "max_record_seconds": config.MAX_RECORD_SECONDS,
        "recognize_timeout_seconds": config.RECOGNIZE_TIMEOUT_SECONDS,
    }


@app.get("/api/words")
def get_words():
    return load_words()["phonemes"]


class ChildIn(BaseModel):
    code: str
    consent_audio: bool = False


@app.post("/api/children")
def create_child(child: ChildIn):
    db.upsert_child(check_code(child.code), child.consent_audio)
    return db.get_child(child.code)


@app.get("/api/children")
def get_children():
    return db.list_children()


@app.delete("/api/children/{code}")
def delete_child(code: str):
    for p in db.delete_child(check_code(code)):
        p = db.resolve_audio(p)
        if p:
            try:
                os.remove(p)
            except OSError:
                pass
    return {"deleted": code}


@app.post("/api/recognize")
def recognize(
    audio: UploadFile = File(...),
    word: str = Form(...),
    phoneme: str = Form(...),
    level: int = Form(1),
    child_code: str = Form(...),
    session_id: str = Form(""),
    attempt_no: int = Form(1),
    exercise: str = Form("word"),
):
    check_code(child_code)
    words = load_words()["phonemes"]
    if phoneme not in words:
        raise HTTPException(400, f"Neznáma hláska {phoneme}")
    if exercise not in EXERCISES:
        raise HTTPException(400, f"Neznáme cvičenie {exercise}")
    grapheme = words[phoneme]["grapheme"]
    child = db.get_child(child_code) or {"consent_audio": 0}

    run_word, run_phoneme = needs(exercise, recognizer is not None, phoneme_recognizer is not None)
    if not run_word and not run_phoneme:
        raise HTTPException(503, "Nie je načítaný žiadny model rozpoznávania reči.")

    data = audio.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Nahrávka je príliš veľká.")
    if not data:
        raise HTTPException(422, "Nahrávka je prázdna.")

    # uloženie nahrávky: so súhlasom do data/audio, inak dočasne a hneď zmazať
    suffix = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
              "audio/wav": ".wav"}.get((audio.content_type or "").split(";")[0], ".webm")
    if child["consent_audio"]:
        path = config.AUDIO_DIR / f"{child_code}_{uuid.uuid4().hex[:10]}{suffix}"
    else:
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        path = Path(tmp)
    path.write_bytes(data)

    t0 = time.perf_counter()
    deadline = t0 + config.RECOGNIZE_TIMEOUT_SECONDS
    try:
        samples = load_audio(path)          # dekóduje sa raz, oba modely dostanú to isté pole
        jobs = [pool.submit(r.transcribe, samples, deadline) if run else None
                for r, run in ((recognizer, run_word), (phoneme_recognizer, run_phoneme))]
        word_out, ph_out = (j.result() if j else None for j in jobs)
    except TimeoutError:                    # prehliadač už to vzdal
        path.unlink(missing_ok=True)
        print(f"  ⚠ {word}: vynechané – čakalo dlhšie ako {config.RECOGNIZE_TIMEOUT_SECONDS} s")
        raise HTTPException(503, "Server je preťažený, skús to znova.")
    except Exception as exc:  # poškodená/prázdna nahrávka
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Nahrávku sa nepodarilo spracovať: {exc}")
    if not child["consent_audio"]:
        path.unlink(missing_ok=True)

    res = analyze(word, phoneme, grapheme, exercise, word_out, ph_out, config.SCORING)
    ph = res["phonemes"] or {}
    latency = round((time.perf_counter() - t0) * 1000)   # dekódovanie + oba modely (bežia súčasne)
    duration = (word_out or ph_out)["duration"]
    parts = [f"{name} {out['latency_ms'] / 1000:.1f} s" for name, out in
             (("slovo", word_out), ("hlásky", ph_out)) if out]
    print(f"  {word}: {', '.join(parts)}, spolu {latency / 1000:.1f} s (nahrávka {duration} s)")
    if latency > config.RECOGNIZE_TIMEOUT_SECONDS * 500:
        print("  ⚠ Rozpoznávanie je pomalé – v start.py zvoľte menší model (base) "
              "alebo vypnite fonémový model.")

    attempt_id = db.insert_attempt({
        "child_code": child_code, "session_id": session_id, "phoneme": phoneme,
        "level": level if exercise == "word" else None, "word": word,
        "positions": ",".join(target_positions(word, grapheme)) if exercise != "sound" else "",
        "attempt_no": attempt_no, "transcript": res["recognized_text"],
        "matched_word": res["matched_word"], "similarity": res["similarity"],
        "confidence": res["confidence"], "target_sound_ok": int(res["target_sound_ok"]),
        "score": res["score"], "stars": res["stars"], "verdict": res["verdict"],
        "final_stars": res["stars"], "latency_ms": latency, "audio_seconds": duration,
        "model": recognizer.spec if run_word else None,
        "audio_path": path.name if child["consent_audio"] else None,
        "exercise": exercise, "mode": res["mode"],
        "expected_phones": ph.get("expected"), "recognized_phones": ph.get("recognized"),
        "phone_similarity": ph.get("similarity"), "phone_confidence": ph.get("confidence"),
        "phone_target_ok": None if not ph else int(ph["target_ok"]),
        "phone_detail": ph.get("summary"),
        "phoneme_model": phoneme_recognizer.spec if run_phoneme else None,
    })
    return {"attempt_id": attempt_id, **res, "latency_ms": latency, "audio_seconds": duration}


class OverrideIn(BaseModel):
    correct: bool | None   # true = uznať, false = neuznať, null = zrušiť zásah


@app.post("/api/attempts/{attempt_id}/override")
def override(attempt_id: int, body: OverrideIn):
    row = db.set_override(attempt_id, body.correct)
    if not row:
        raise HTTPException(404, "Pokus neexistuje")
    return row


class LabelIn(BaseModel):
    actual_text: str | None   # čo dieťa naozaj povedalo, napr. "lyba"; prázdne = zmazať


@app.post("/api/attempts/{attempt_id}/label")
def label(attempt_id: int, body: LabelIn):
    if body.actual_text and len(body.actual_text) > 100:
        raise HTTPException(400, "Príliš dlhý text")
    row = db.set_actual_text(attempt_id, body.actual_text)
    if not row:
        raise HTTPException(404, "Pokus neexistuje")
    return row


@app.get("/api/attempts")
def attempts(child_code: str | None = None, limit: int = 500):
    return db.list_attempts(child_code, limit)


@app.get("/api/stats/{child_code}")
def stats(child_code: str):
    return db.stats(check_code(child_code))


@app.get("/api/attempts/{attempt_id}/audio")
def attempt_audio(attempt_id: int):
    row = db.get_attempt(attempt_id)
    path = db.resolve_audio(row["audio_path"]) if row else None
    if not path:
        raise HTTPException(404, "Nahrávka nie je uložená")
    return FileResponse(path)


def csv_response(rows: list[list], name: str, bom: str = "") -> StreamingResponse:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return StreamingResponse(iter([bom + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export.csv")
def export_csv(child_code: str | None = None):
    rows = db.list_attempts(child_code, limit=1_000_000)
    table = [list(rows[0])] + [list(r.values()) for r in rows] if rows else []
    return csv_response(table, f"pokusy_{child_code or 'vsetky'}.csv", bom="\ufeff")


@app.get("/api/manifest.csv")
def manifest_csv():
    """
    Zoznam uložených nahrávok pre tools/compare_models.py.
    reference   = cieľové slovo/slabika/hláska,
    adult_label = dospelý výslovnosť uznal (1), neuznal (0), nezasiahol (prázdne),
    actual_text = čo dieťa naozaj povedalo (ak to dospelý zapísal).
    """
    table = [["path", "reference", "phoneme", "exercise", "adult_label", "actual_text", "child_code"]]
    for r in db.list_attempts(limit=1_000_000):
        path = db.resolve_audio(r["audio_path"])
        if path:
            table.append([path, r["word"], r["phoneme"], r.get("exercise") or "word",
                          "" if r["manual_override"] is None else r["manual_override"],
                          r.get("actual_text") or "", r["child_code"]])
    return csv_response(table, "manifest.csv")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
