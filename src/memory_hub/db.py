"""SQLite database init and CRUD operations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from src import config

_DB_PATH: str | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = config.get("memory", "db_path", "data/rll.db")
    p = Path(_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_norms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    field        TEXT NOT NULL,
    min_val      REAL,
    max_val      REAL,
    max_std_dev  REAL,
    max_gap_ms   INTEGER,
    severity     TEXT NOT NULL DEFAULT 'hard',
    updated_at   TEXT,
    UNIQUE(topic, field)
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id    TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    topics        TEXT,
    frame_count   INTEGER DEFAULT 0,
    quality_score REAL,
    status        TEXT NOT NULL DEFAULT 'PENDING',
    version       INTEGER NOT NULL DEFAULT 1,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    report_id   TEXT PRIMARY KEY,
    episode_id  TEXT NOT NULL REFERENCES episodes(episode_id),
    created_at  TEXT NOT NULL,
    anomalies   TEXT,
    annotation  TEXT,
    confidence  REAL,
    verdict     TEXT,
    source      TEXT NOT NULL DEFAULT 'FULL'
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key   TEXT PRIMARY KEY,
    response    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_patterns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id  TEXT,
    pattern     TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);
"""


def init_db() -> None:
    """Create tables if they don't exist and purge expired LLM cache."""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
    _purge_expired_cache()


def _purge_expired_cache() -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM llm_cache WHERE expires_at < ?", (now,))



def upsert_episode(ep: dict) -> None:
    import json
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO episodes (episode_id, session_id, started_at, ended_at, topics,
                                  frame_count, quality_score, status, version, notes)
            VALUES (:episode_id, :session_id, :started_at, :ended_at, :topics,
                    :frame_count, :quality_score, :status, :version, :notes)
            ON CONFLICT(episode_id) DO UPDATE SET
                ended_at      = excluded.ended_at,
                topics        = excluded.topics,
                frame_count   = excluded.frame_count,
                quality_score = excluded.quality_score,
                status        = excluded.status,
                version       = excluded.version,
                notes         = excluded.notes
            """,
            {
                **ep,
                "topics": json.dumps(ep.get("topics", [])),
            },
        )


def update_episode_status(episode_id: str, status: str, notes: str | None = None) -> None:
    with get_conn() as conn:
        if notes is not None:
            conn.execute(
                "UPDATE episodes SET status = ?, notes = ?, version = version + 1 WHERE episode_id = ?",
                (status, notes, episode_id),
            )
        else:
            conn.execute(
                "UPDATE episodes SET status = ?, version = version + 1 WHERE episode_id = ?",
                (status, episode_id),
            )


def get_episodes(status: str | None = None, limit: int = 100) -> list[dict]:
    import json
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE status = ? ORDER BY started_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("topics"):
            d["topics"] = json.loads(d["topics"])
        result.append(d)
    return result


def get_episode(episode_id: str) -> dict | None:
    import json
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("topics"):
        d["topics"] = json.loads(d["topics"])
    return d



def insert_report(rep: dict) -> None:
    import json
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO reports
                (report_id, episode_id, created_at, anomalies, annotation, confidence, verdict, source)
            VALUES
                (:report_id, :episode_id, :created_at, :anomalies, :annotation, :confidence, :verdict, :source)
            """,
            {**rep, "anomalies": json.dumps(rep.get("anomalies", []))},
        )


def get_report_by_episode(episode_id: str) -> dict | None:
    import json
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE episode_id = ? ORDER BY created_at DESC LIMIT 1",
            (episode_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("anomalies"):
        d["anomalies"] = json.loads(d["anomalies"])
    return d



def llm_cache_get(key: str) -> str | None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT response FROM llm_cache WHERE cache_key = ? AND expires_at > ?",
            (key, now),
        ).fetchone()
    return row["response"] if row else None


def llm_cache_set(key: str, response: str, ttl_hours: int = 24) -> None:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=ttl_hours)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (key, response, now.isoformat(), expires),
        )



def insert_rejected_pattern(episode_id: str, pattern: str, reason: str) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rejected_patterns (episode_id, pattern, reason, created_at) VALUES (?, ?, ?, ?)",
            (episode_id, pattern, reason, now),
        )


def get_metrics_summary() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM episodes GROUP BY status"
        ).fetchall()
        avg_score = conn.execute(
            "SELECT AVG(quality_score) FROM episodes WHERE quality_score IS NOT NULL"
        ).fetchone()[0]
    return {
        "total_episodes": total,
        "by_status": {r["status"]: r["cnt"] for r in by_status},
        "avg_quality_score": round(avg_score, 3) if avg_score else None,
    }
