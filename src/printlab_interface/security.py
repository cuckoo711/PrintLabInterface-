"""Local access control for the sidecar.

The service listens on loopback only, but that alone does not stop a web page in the
user's browser from reaching it (DNS rebinding) or another local program from calling it.
Two checks:
  * Host header allow-list: the request must be addressed to a loopback name and our port;
  * proof of who is asking on every route that touches providers or keys. A person proves it with a passphrase they set
    themselves and a browser session (see auth.py). A script proves it with the older token header: a random token created
    on first start and stored in data/admin_token, never logged or returned.
"""
from __future__ import annotations

import hmac
import os
import secrets as _secrets
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .fsprivate import make_private

TOKEN_FILE = "admin_token"
HEADER = "x-admin-token"


def load_or_create_token(data_dir: Path) -> str:
    path = data_dir / TOKEN_FILE
    data_dir.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            make_private(path)  # repair a token created before this protection existed
            return value
    value = _secrets.token_urlsafe(32)
    # Create empty, lock the file down, and only then write the secret into it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    make_private(path)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")
    return value


def allowed_hosts(port: int) -> set[str]:
    names = ("127.0.0.1", "localhost", "[::1]")
    return {f"{n}:{port}" for n in names} | {n for n in names}


class HostGuard(BaseHTTPMiddleware):
    def __init__(self, app, hosts: set[str]):
        super().__init__(app)
        self.hosts = {h.lower() for h in hosts}

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        if host not in self.hosts:
            return JSONResponse({"detail": "host not allowed"}, status_code=400)
        return await call_next(request)


def require_admin(request: Request) -> None:
    supplied = request.headers.get(HEADER, "")
    if supplied:
        expected: str = request.app.state.admin_token
        if hmac.compare_digest(supplied.encode(), expected.encode()):
            return
        raise HTTPException(status_code=401, detail="admin token required")
    # A browser session. Every request is checked for its origin; every change also needs the session's CSRF value.
    from . import auth, db

    with db.session(request.app.state.settings.db_path) as conn:
        session = auth.session_from_request(request, conn)
    if session is None:
        raise HTTPException(status_code=401, detail="login required")
    auth.check_origin(request)
    if request.method not in auth.SAFE_METHODS and not auth.csrf_ok(request, session):
        raise HTTPException(status_code=403, detail="csrf token missing or wrong")
