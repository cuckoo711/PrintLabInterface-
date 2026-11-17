"""Conversation storage for agents.

What is stored: the user's and the assistant's text, and for each run its status, token
counts and the names of the tools that ran. What is NOT stored: raw tool results. They hold
device details, can be large, and are always fetched again from PrintLab when needed.

Everything is bounded: sessions per agent, messages per session, characters per message.
Text is passed through the redactor before it is written.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass

from ..redact import redact

SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    title       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_updated ON sessions(updated_at);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,
    turns         INTEGER NOT NULL DEFAULT 0,
    tool_calls    INTEGER NOT NULL DEFAULT 0,
    tools_json    TEXT NOT NULL DEFAULT '[]',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    started_at    REAL NOT NULL,
    finished_at   REAL
);
"""
MAX_SESSIONS_PER_AGENT = 200
MAX_MESSAGES_PER_SESSION = 400
MAX_MESSAGE_CHARS = 20_000
MAX_TITLE_CHARS = 80


class SessionError(ValueError):
    pass


@dataclass(frozen=True)
class Session:
    id: str
    agent: str
    title: str
    created_at: float
    updated_at: float


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SESSION_SCHEMA)


def _title_from(text: str) -> str:
    line = " ".join(text.split())[:MAX_TITLE_CHARS]
    return redact(line) or "New chat"


def create(conn: sqlite3.Connection, agent: str, first_message: str = "") -> Session:
    count = conn.execute("SELECT COUNT(*) FROM sessions WHERE agent=?", (agent,)).fetchone()[0]
    if count >= MAX_SESSIONS_PER_AGENT:
        raise SessionError(f"too many sessions for '{agent}'; delete some first")
    now = time.time()
    sid = uuid.uuid4().hex[:16]
    conn.execute("INSERT INTO sessions(id,agent,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                 (sid, agent, _title_from(first_message), now, now))
    return Session(sid, agent, _title_from(first_message), now, now)


def get(conn: sqlite3.Connection, session_id: str) -> Session:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise SessionError("unknown session")
    return Session(row["id"], row["agent"], row["title"], row["created_at"], row["updated_at"])


def list_sessions(conn: sqlite3.Connection, agent: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    if agent:
        rows = conn.execute("SELECT * FROM sessions WHERE agent=? ORDER BY updated_at DESC LIMIT ?", (agent, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete(conn: sqlite3.Connection, session_id: str) -> None:
    get(conn, session_id)
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def add_message(conn: sqlite3.Connection, session_id: str, role: str, content: str) -> None:
    get(conn, session_id)
    if role not in {"user", "assistant"}:
        raise SessionError("role must be user or assistant")
    if not isinstance(content, str) or not content.strip():
        raise SessionError("message is empty")
    n = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0]
    if n >= MAX_MESSAGES_PER_SESSION:
        raise SessionError("this session is full; start a new one")
    now = time.time()
    conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                 (session_id, role, redact(content)[:MAX_MESSAGE_CHARS], now))
    conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))


def history(conn: sqlite3.Connection, session_id: str, limit: int = 60) -> list[dict]:
    """The most recent messages in chronological order, as the model expects them."""
    get(conn, session_id)
    limit = max(1, min(int(limit), MAX_MESSAGES_PER_SESSION))
    rows = conn.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def messages(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    get(conn, session_id)
    rows = conn.execute("SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    return [dict(r) for r in rows]


PAGE_DEFAULT = 40
PAGE_MAX = 100


def messages_page(conn: sqlite3.Connection, session_id: str, before: int | None = None, limit: int = PAGE_DEFAULT) -> tuple[list[dict], bool]:
    """One page of messages, oldest first: the `limit` messages just before id `before` (or the newest ones).
    Also says whether anything older exists, so the page knows whether to keep offering to load more."""
    get(conn, session_id)
    limit = max(1, min(int(limit), PAGE_MAX))
    if before is None:
        rows = conn.execute("SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                            (session_id, limit + 1)).fetchall()
    else:
        rows = conn.execute("SELECT id, role, content, created_at FROM messages WHERE session_id=? AND id<? ORDER BY id DESC LIMIT ?",
                            (session_id, int(before), limit + 1)).fetchall()
    more = len(rows) > limit
    return [dict(r) for r in reversed(rows[:limit])], more


def start_run(conn: sqlite3.Connection, session_id: str, model: str) -> str:
    get(conn, session_id)
    run_id = uuid.uuid4().hex[:16]
    conn.execute("INSERT INTO runs(id,session_id,model,status,started_at) VALUES(?,?,?,?,?)", (run_id, session_id, model[:200], "running", time.time()))
    return run_id


def finish_run(conn: sqlite3.Connection, run_id: str, *, status: str, turns: int, tool_calls: int, tools: list[str],
               usage: dict, error: str | None) -> None:
    conn.execute(
        "UPDATE runs SET status=?, turns=?, tool_calls=?, tools_json=?, prompt_tokens=?, completion_tokens=?, error=?, finished_at=? WHERE id=?",
        (status, int(turns), int(tool_calls), json.dumps(sorted(set(tools))), int(usage.get("prompt_tokens") or 0),
         int(usage.get("completion_tokens") or 0), redact(error or "")[:500] or None, time.time(), run_id),
    )


def list_runs(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    get(conn, session_id)
    out = []
    for r in conn.execute("SELECT * FROM runs WHERE session_id=? ORDER BY started_at", (session_id,)).fetchall():
        d = dict(r)
        d["tools"] = json.loads(d.pop("tools_json"))
        out.append(d)
    return out


def abandon_unfinished(conn: sqlite3.Connection) -> int:
    """After a crash or restart no run can still be going; mark leftovers so the UI is truthful."""
    cur = conn.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (time.time(),))
    return cur.rowcount
