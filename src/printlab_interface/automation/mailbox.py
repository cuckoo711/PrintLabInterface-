"""A small mailbox in the sidecar's own database.

Who writes: the scheduler (patrol findings, scheduled agent reports) and the admin API.
Who reads: the person, through the admin API. Messages are data; nothing in a message is ever
executed or fed back to a model as an instruction.

Bounded on purpose: body length, subject length, and a hard row cap (read messages are dropped first).
Text goes through the redactor before it is stored.
"""
from __future__ import annotations

import sqlite3
import time

from ..redact import redact

MAILBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS mailbox (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL NOT NULL,
    sender    TEXT NOT NULL,
    recipient TEXT NOT NULL,
    kind      TEXT NOT NULL,
    severity  TEXT NOT NULL CHECK (severity IN ('info','warn','error')),
    subject   TEXT NOT NULL,
    body      TEXT NOT NULL,
    read_at   REAL
);
CREATE INDEX IF NOT EXISTS mailbox_unread ON mailbox(recipient, read_at);
"""
MAX_ROWS = 500
MAX_SUBJECT = 160
MAX_BODY = 4000
SEVERITIES = ("info", "warn", "error")


class MailboxError(ValueError):
    pass


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(MAILBOX_SCHEMA)


def post(conn: sqlite3.Connection, sender: str, recipient: str, kind: str, severity: str, subject: str, body: str = "",
         *, now: float | None = None) -> int:
    if severity not in SEVERITIES:
        raise MailboxError(f"severity must be one of {list(SEVERITIES)}")
    for label, value, limit in (("sender", sender, 64), ("recipient", recipient, 64), ("kind", kind, 40)):
        if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 for c in value):
            raise MailboxError(f"{label} must be 1-{limit} characters of plain text")
    if not isinstance(subject, str) or not subject.strip():
        raise MailboxError("subject is required")
    init(conn)
    cur = conn.execute(
        "INSERT INTO mailbox(at, sender, recipient, kind, severity, subject, body) VALUES(?,?,?,?,?,?,?)",
        (time.time() if now is None else now, sender, recipient, kind, severity,
         redact(subject.strip())[:MAX_SUBJECT], redact(body or "")[:MAX_BODY]))
    message_id = int(cur.lastrowid)
    excess = conn.execute("SELECT COUNT(*) FROM mailbox").fetchone()[0] - MAX_ROWS
    if excess > 0:  # read messages first, then the oldest of the rest
        conn.execute("DELETE FROM mailbox WHERE id IN (SELECT id FROM mailbox ORDER BY read_at IS NULL, id LIMIT ?)", (excess,))
    return message_id


def list_messages(conn: sqlite3.Connection, *, recipient: str | None = None, unread_only: bool = False, limit: int = 50) -> list[dict]:
    init(conn)
    limit = max(1, min(int(limit), 200))
    clauses, args = [], []
    if recipient:
        clauses.append("recipient = ?")
        args.append(recipient)
    if unread_only:
        clauses.append("read_at IS NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(f"SELECT * FROM mailbox {where} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def ack(conn: sqlite3.Connection, message_id: int, *, now: float | None = None) -> bool:
    init(conn)
    cur = conn.execute("UPDATE mailbox SET read_at = ? WHERE id = ? AND read_at IS NULL",
                       (time.time() if now is None else now, int(message_id)))
    return cur.rowcount == 1


def unread_count(conn: sqlite3.Connection, recipient: str | None = None) -> int:
    init(conn)
    if recipient:
        return conn.execute("SELECT COUNT(*) FROM mailbox WHERE read_at IS NULL AND recipient = ?", (recipient,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM mailbox WHERE read_at IS NULL").fetchone()[0]
