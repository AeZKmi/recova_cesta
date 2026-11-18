"""
Ukladanie pokusov do SQLite (štandardná knižnica Pythonu, žiadny server).

Deti sú evidované iba pod pseudonymom (kód, napr. "D07"). Meno ani iné
identifikačné údaje aplikácia nepožaduje ani neukladá.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS children (
    code          TEXT PRIMARY KEY,
    consent_audio INTEGER NOT NULL DEFAULT 0,   -- súhlas rodiča s ukladaním nahrávok
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    child_code      TEXT NOT NULL REFERENCES children(code) ON DELETE CASCADE,
    session_id      TEXT,
    phoneme         TEXT NOT NULL,
    level           INTEGER,
    word            TEXT NOT NULL,
    positions       TEXT,            -- initial/medial/final
    attempt_no      INTEGER,
    transcript      TEXT,
    matched_word    TEXT,
    similarity      REAL,
    confidence      REAL,
    target_sound_ok INTEGER,
    score           REAL,
    stars           INTEGER,
    verdict         TEXT,
    manual_override INTEGER,         -- NULL = bez zásahu, 1 = dospelý uznal, 0 = neuznal
    final_stars     INTEGER,         -- hviezdičky po prípadnom zásahu dospelého
    latency_ms      INTEGER,
    audio_seconds   REAL,
    model           TEXT,
    prompt_mode     TEXT,            -- nepoužíva sa (zostáva kvôli starším záznamom)
    audio_path      TEXT,            -- názov súboru v data/audio
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    exercise          TEXT DEFAULT 'word',   -- word | syllable | sound
    mode              TEXT,                  -- word | phoneme | hybrid | text_fallback
    expected_phones   TEXT,                  -- očakávané fonémy (IPA)
    recognized_phones TEXT,                  -- fonémy z fonémového modelu
    phone_similarity  REAL,
    phone_confidence  REAL,
    phone_target_ok   INTEGER,
    phone_detail      TEXT,                  -- napr. "r→l"
    phoneme_model     TEXT,
    actual_text       TEXT                   -- čo dieťa naozaj povedalo (zapisuje dospelý)
);
CREATE INDEX IF NOT EXISTS idx_attempts_child ON attempts(child_code);
"""


@contextmanager
def connect():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)


def _one(con, sql: str, args) -> dict | None:
    row = con.execute(sql, args).fetchone()
    return dict(row) if row else None


def _attempt(con, attempt_id: int) -> dict | None:
    return _one(con, "SELECT * FROM attempts WHERE id = ?", (attempt_id,))


def upsert_child(code: str, consent_audio: bool) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO children(code, consent_audio) VALUES (?, ?) "
            "ON CONFLICT(code) DO UPDATE SET consent_audio = excluded.consent_audio",
            (code, int(consent_audio)),
        )


def get_child(code: str) -> dict | None:
    with connect() as con:
        return _one(con, "SELECT * FROM children WHERE code = ?", (code,))


def list_children() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT c.code, c.consent_audio, c.created_at, COUNT(a.id) AS attempts, "
            "MAX(a.created_at) AS last_attempt FROM children c "
            "LEFT JOIN attempts a ON a.child_code = c.code GROUP BY c.code ORDER BY c.code"
        ).fetchall()
        return [dict(r) for r in rows]


def insert_attempt(data: dict) -> int:
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    with connect() as con:
        cur = con.execute(f"INSERT INTO attempts ({cols}) VALUES ({marks})", tuple(data.values()))
        return cur.lastrowid


def set_override(attempt_id: int, correct: bool | None) -> dict | None:
    """Zásah dospelého: uznať (3 ★), neuznať (0 ★) alebo zrušiť zásah (None)."""
    with connect() as con:
        if correct is None:
            con.execute("UPDATE attempts SET manual_override = NULL, final_stars = stars "
                        "WHERE id = ?", (attempt_id,))
        else:
            con.execute("UPDATE attempts SET manual_override = ?, final_stars = ? WHERE id = ?",
                        (int(correct), 3 if correct else 0, attempt_id))
        return _attempt(con, attempt_id)


def set_actual_text(attempt_id: int, text: str | None) -> dict | None:
    """Anotácia: čo dieťa naozaj povedalo (napr. 'lyba'). Slúži na porovnanie modelov."""
    text = (text or "").strip() or None
    with connect() as con:
        con.execute("UPDATE attempts SET actual_text = ? WHERE id = ?", (text, attempt_id))
        return _attempt(con, attempt_id)


def resolve_audio(path: str | None) -> str | None:
    """
    Cesta k nahrávke v data/audio. Ukladá sa len názov súboru; staršie záznamy
    majú absolútnu cestu (aj z iného priečinka) – použije sa z nej tiež len názov.
    """
    if not path:
        return None
    p = config.AUDIO_DIR / Path(path.replace("\\", "/")).name
    return str(p) if p.exists() else None


def get_attempt(attempt_id: int) -> dict | None:
    with connect() as con:
        return _attempt(con, attempt_id)


def list_attempts(child_code: str | None = None, limit: int = 500) -> list[dict]:
    q, args = "SELECT * FROM attempts", []
    if child_code:
        q += " WHERE child_code = ?"
        args.append(child_code)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


def stats(child_code: str) -> list[dict]:
    """Súhrn podľa hlásky: počet pokusov, priemerné skóre, úspešnosť, zhoda ASR s dospelým."""
    with connect() as con:
        rows = con.execute(
            """
            SELECT phoneme,
                   COALESCE(exercise, 'word')                      AS exercise,
                   COUNT(*)                                        AS attempts,
                   COUNT(DISTINCT word)                            AS words,
                   ROUND(AVG(score), 1)                            AS avg_score,
                   ROUND(AVG(final_stars), 2)                      AS avg_stars,
                   ROUND(100.0 * AVG(final_stars >= 1), 1)         AS success_pct,
                   ROUND(100.0 * AVG(target_sound_ok), 1)          AS target_ok_pct,
                   ROUND(100.0 * AVG(phone_target_ok), 1)          AS phone_ok_pct,
                   SUM(manual_override IS NOT NULL)                AS overrides,
                   ROUND(AVG(latency_ms))                          AS avg_latency_ms
            FROM attempts WHERE child_code = ?
            GROUP BY phoneme, COALESCE(exercise, 'word') ORDER BY phoneme, exercise
            """,
            (child_code,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_child(code: str) -> list[str]:
    """Právo na vymazanie (GDPR čl. 17): zmaže dieťa, pokusy, vráti cesty k nahrávkam."""
    with connect() as con:
        paths = [r[0] for r in con.execute(
            "SELECT audio_path FROM attempts WHERE child_code = ? AND audio_path IS NOT NULL",
            (code,))]
        con.execute("DELETE FROM attempts WHERE child_code = ?", (code,))
        con.execute("DELETE FROM children WHERE code = ?", (code,))
        return paths
