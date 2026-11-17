"""Routes for setting the passphrase, logging in and out. These are the only routes that cannot demand a login."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth, db

router = APIRouter(prefix="/api/auth")
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


class PassphraseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: str = Field(min_length=1, max_length=auth.MAX_LENGTH, repr=False)


class SetupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: str | None = Field(default=None, max_length=auth.MAX_LENGTH, repr=False)  # empty: make one up and show it once


def _conn(request: Request):
    conn = db.connect(request.app.state.settings.db_path)
    auth.init(conn)
    return conn


def _lockout(request: Request) -> auth.Lockout:
    if not hasattr(request.app.state, "lockout"):
        request.app.state.lockout = auth.Lockout()
    return request.app.state.lockout


def _secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _from_this_machine(request: Request) -> None:
    client = request.client.host if request.client else ""
    if client not in LOOPBACK:
        raise HTTPException(status_code=403, detail="只能在本机设置口令")


@router.get("/state")
def state(request: Request):
    """What the login page needs to know. Says nothing that helps an attacker: only whether a passphrase exists and whether this browser is in."""
    conn = _conn(request)
    try:
        session = auth.session_from_request(request, conn)
        return {"passphrase_set": auth.has_passphrase(conn), "logged_in": session is not None,
                "csrf": session.csrf if session else None, "locked_seconds": _lockout(request).remaining()}
    finally:
        conn.close()


@router.post("/setup", status_code=201)
def setup(body: SetupIn, request: Request, response: Response):
    """First-time setup. Works only while no passphrase exists, only from this machine, and only from this site."""
    auth.check_origin(request)
    _from_this_machine(request)
    conn = _conn(request)
    try:
        if auth.has_passphrase(conn):
            raise HTTPException(status_code=409, detail="已经设置过口令")
        shown = None
        passphrase = body.passphrase
        if not passphrase:
            passphrase = shown = auth.generate_passphrase()
        try:
            auth.set_passphrase(conn, passphrase)
        except auth.AuthError as exc:
            raise HTTPException(status_code=409 if "已经" in str(exc) else 422, detail=str(exc)) from None
        sid, csrf = auth.create_session(conn)
        db.record_audit(conn, "admin", "passphrase_set", "auth", "ok", "generated" if shown else "chosen")  # never the passphrase
        auth.set_cookie(response, sid, secure=_secure(request))
        return {"csrf": csrf, "generated_passphrase": shown}
    finally:
        conn.close()


@router.post("/login")
def login(body: PassphraseIn, request: Request, response: Response):
    auth.check_origin(request)
    lock = _lockout(request)
    wait = lock.remaining()
    if wait:
        raise HTTPException(status_code=429, detail=f"尝试次数太多，请 {wait} 秒后再试")
    conn = _conn(request)
    try:
        if not auth.verify_passphrase(conn, body.passphrase):
            lock.failed()
            db.record_audit(conn, "admin", "login", "auth", "refused", "")
            raise HTTPException(status_code=401, detail="口令不对")
        lock.succeeded()
        sid, csrf = auth.create_session(conn)
        db.record_audit(conn, "admin", "login", "auth", "ok", "")
        auth.set_cookie(response, sid, secure=_secure(request))
        return {"csrf": csrf}
    finally:
        conn.close()


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.check_origin(request)
    conn = _conn(request)
    try:
        session = auth.session_from_request(request, conn)
        if session is not None and not auth.csrf_ok(request, session):
            raise HTTPException(status_code=403, detail="csrf token missing or wrong")
        auth.end_session(conn, request.cookies.get(auth.COOKIE, ""))
        auth.clear_cookie(response)
        return {"ok": True}
    finally:
        conn.close()
