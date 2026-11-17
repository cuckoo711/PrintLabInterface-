"""Passphrase login with a browser session. Replaces "go and find data/admin_token".

How it works
  * The first time anyone opens a page, no passphrase exists yet. The page offers to set one (or to make one up and show
    it once). Setting is possible only while none exists, and only from this machine. After that it is closed for good.
  * Only a slow, salted hash of the passphrase is stored (scrypt). The passphrase itself is never stored or logged.
  * Logging in gives a random session id in an HttpOnly, SameSite=Strict cookie. Only a hash of that id is stored, so a copy
    of the database cannot be used to log in. Sessions end after 12 hours or when the person logs out.
  * Every change a browser makes must also carry the session's CSRF value in a header, and a request that the browser says
    comes from another site is refused. A cookie is easier to abuse from another web page than a header token, so these
    two checks are not optional.
  * Wrong passphrases are slowed down and then locked out for a while, for the whole machine, not per address.

The older ``x-admin-token`` header still works for command-line use and for the tests. The pages no longer mention it.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_passphrase (
    id       INTEGER PRIMARY KEY CHECK (id = 1),
    salt     BLOB NOT NULL,
    hash     BLOB NOT NULL,
    n        INTEGER NOT NULL,
    r        INTEGER NOT NULL,
    p        INTEGER NOT NULL,
    set_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    sid_hash   TEXT PRIMARY KEY,
    csrf       TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""
COOKIE = "pli_session"
CSRF_HEADER = "x-csrf-token"
SESSION_SECONDS = 12 * 3600
MIN_LENGTH = 10
MAX_LENGTH = 200
SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MAX_SESSIONS = 20
FAILURES_BEFORE_LOCK = 5
LOCK_SECONDS = 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthError(ValueError):
    pass


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _hash(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)


def has_passphrase(conn: sqlite3.Connection) -> bool:
    init(conn)
    return conn.execute("SELECT 1 FROM auth_passphrase WHERE id = 1").fetchone() is not None


def generate_passphrase() -> str:
    """Four short random words' worth of entropy, easy to read out and to type. About 60 bits."""
    return "-".join(secrets.token_hex(2) for _ in range(5))


def _check_strength(passphrase: str) -> None:
    if not isinstance(passphrase, str) or not MIN_LENGTH <= len(passphrase) <= MAX_LENGTH:
        raise AuthError(f"口令需要 {MIN_LENGTH} 到 {MAX_LENGTH} 个字符")
    if len(set(passphrase)) < 4:
        raise AuthError("口令太单一，请换一个")
    if passphrase != passphrase.strip():
        raise AuthError("口令开头和结尾不能是空格")


def set_passphrase(conn: sqlite3.Connection, passphrase: str, *, now: float | None = None) -> None:
    """Only while none exists. The insert itself enforces that, so two racing requests cannot both win."""
    init(conn)
    _check_strength(passphrase)
    salt = secrets.token_bytes(16)
    digest = _hash(passphrase, salt, **SCRYPT)
    try:
        conn.execute("INSERT INTO auth_passphrase(id, salt, hash, n, r, p, set_at) VALUES(1,?,?,?,?,?,?)",
                     (salt, digest, SCRYPT["n"], SCRYPT["r"], SCRYPT["p"], time.time() if now is None else now))
    except sqlite3.IntegrityError:
        raise AuthError("已经设置过口令，不能再用这个入口设置") from None


def verify_passphrase(conn: sqlite3.Connection, passphrase: str) -> bool:
    init(conn)
    row = conn.execute("SELECT salt, hash, n, r, p FROM auth_passphrase WHERE id = 1").fetchone()
    if row is None or not isinstance(passphrase, str) or len(passphrase) > MAX_LENGTH:
        return False
    return hmac.compare_digest(_hash(passphrase, row["salt"], row["n"], row["r"], row["p"]), row["hash"])


# ---------------------------------------------------------------- lockout (in memory; a restart clears it, which is fine for a local app)
class Lockout:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._until = 0.0

    def remaining(self) -> int:
        with self._lock:
            return max(0, int(self._until - self._clock() + 0.999))

    def failed(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= FAILURES_BEFORE_LOCK:
                self._until = self._clock() + LOCK_SECONDS * (2 ** min(self._failures - FAILURES_BEFORE_LOCK, 4))

    def succeeded(self) -> None:
        with self._lock:
            self._failures = 0
            self._until = 0.0


# ---------------------------------------------------------------- sessions
@dataclass
class Session:
    csrf: str
    expires_at: float


def _sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, *, now: float | None = None) -> tuple[str, str]:
    init(conn)
    t = time.time() if now is None else now
    conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (t,))
    extra = conn.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] - (MAX_SESSIONS - 1)
    if extra > 0:  # keep the newest ones; an old forgotten browser must not lock a new login out
        conn.execute("DELETE FROM auth_sessions WHERE sid_hash IN (SELECT sid_hash FROM auth_sessions ORDER BY created_at LIMIT ?)", (extra,))
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    conn.execute("INSERT INTO auth_sessions(sid_hash, csrf, created_at, expires_at) VALUES(?,?,?,?)", (_sid_hash(sid), csrf, t, t + SESSION_SECONDS))
    return sid, csrf


def find_session(conn: sqlite3.Connection, sid: str, *, now: float | None = None) -> Session | None:
    if not sid or len(sid) > 200:
        return None
    init(conn)
    t = time.time() if now is None else now
    row = conn.execute("SELECT csrf, expires_at FROM auth_sessions WHERE sid_hash = ?", (_sid_hash(sid),)).fetchone()
    if row is None or row["expires_at"] <= t:
        return None
    return Session(row["csrf"], row["expires_at"])


def end_session(conn: sqlite3.Connection, sid: str) -> None:
    init(conn)
    conn.execute("DELETE FROM auth_sessions WHERE sid_hash = ?", (_sid_hash(sid or ""),))


def end_all_sessions(conn: sqlite3.Connection) -> None:
    init(conn)
    conn.execute("DELETE FROM auth_sessions")


def set_cookie(response: Response, sid: str, *, secure: bool) -> None:
    response.set_cookie(COOKIE, sid, max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=secure, path="/")


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


# ---------------------------------------------------------------- request checks
def check_origin(request: Request) -> None:
    """Refuse a request that a browser says came from another site, or whose Origin is not this service."""
    if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
        raise HTTPException(status_code=403, detail="cross-site request refused")
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        if origin.split("://", 1)[-1].lower() != host.lower():
            raise HTTPException(status_code=403, detail="origin does not match")


def session_from_request(request: Request, conn: sqlite3.Connection) -> Session | None:
    return find_session(conn, request.cookies.get(COOKIE, ""))


def csrf_ok(request: Request, session: Session) -> bool:
    supplied = request.headers.get(CSRF_HEADER, "")
    return bool(supplied) and hmac.compare_digest(supplied.encode(), session.csrf.encode())
