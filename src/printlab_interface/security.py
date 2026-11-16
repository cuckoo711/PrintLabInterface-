"""Local access control for the sidecar.

The service listens on loopback only, but that alone does not stop a web page in the
user's browser from reaching it (DNS rebinding) or another local program from calling it.
Two checks:
  * Host header allow-list: the request must be addressed to a loopback name and our port;
  * admin token on every route that touches providers or keys. The token is random,
    created on first start, stored in data/admin_token, and never logged or returned.
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
    expected: str = request.app.state.admin_token
    supplied = request.headers.get(HEADER, "")
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="admin token required")
