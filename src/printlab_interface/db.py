"""SQLite storage owned by the sidecar. Never shares a file or a table with PrintLab."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL    NOT NULL,
    actor       TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    outcome     TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at);
"""
SCHEMA_VERSION = "1"
MAX_DETAIL_CHARS = 2000


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
    return conn


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def record_audit(conn: sqlite3.Connection, actor: str, action: str, target: str, outcome: str, detail: str = "") -> None:
    from .redact import redact

    conn.execute(
        "INSERT INTO audit(at, actor, action, target, outcome, detail) VALUES(?,?,?,?,?,?)",
        (time.time(), actor, action, target, outcome, redact(detail)[:MAX_DETAIL_CHARS]),
    )


def recent_audit(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
