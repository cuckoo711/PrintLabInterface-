"""Static chat page. Three fixed files; nothing is looked up from a request path."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

_DIR = Path(__file__).parent
# name in the URL -> (file, content type). Anything not listed is a 404; there is no path parameter.
_FILES = {
    "": ("chat.html", "text/html; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "login.js": ("login.js", "text/javascript; charset=utf-8"),
    "proposal.js": ("proposal.js", "text/javascript; charset=utf-8"),
    "thread.js": ("thread.js", "text/javascript; charset=utf-8"),
    "admin": ("admin.html", "text/html; charset=utf-8"),
    "admin.js": ("admin.js", "text/javascript; charset=utf-8"),
}
# No inline script or style, no remote origins, no framing. connect-src 'self' lets the page call this API only.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

router = APIRouter()


def _serve(name: str) -> Response:
    filename, media = _FILES[name]
    return Response((_DIR / filename).read_bytes(), media_type=media, headers=HEADERS)


@router.get("/chat", include_in_schema=False)
@router.get("/chat/", include_in_schema=False)
def chat_page() -> Response:
    return _serve("")


@router.get("/chat/app.css", include_in_schema=False)
def chat_css() -> Response:
    return _serve("app.css")


@router.get("/chat/app.js", include_in_schema=False)
def chat_js() -> Response:
    return _serve("app.js")


@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
def admin_page() -> Response:
    return _serve("admin")


@router.get("/admin/admin.js", include_in_schema=False)
def admin_js() -> Response:
    return _serve("admin.js")


@router.get("/admin/app.css", include_in_schema=False)
def admin_css() -> Response:
    return _serve("app.css")


@router.get("/chat/login.js", include_in_schema=False)
def login_js() -> Response:
    return _serve("login.js")


@router.get("/chat/thread.js", include_in_schema=False)
def thread_js() -> Response:
    return _serve("thread.js")


@router.get("/chat/proposal.js", include_in_schema=False)
def proposal_js() -> Response:
    return _serve("proposal.js")
