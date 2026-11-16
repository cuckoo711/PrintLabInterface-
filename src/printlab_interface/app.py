"""FastAPI application. Starts with or without PrintLab."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, db, redact, security
from .adapters.printlab import PrintLabAdapter
from .config import Settings, load_settings
from .providers import api as providers_api
from .providers.gateway import Gateway

log = logging.getLogger("printlab_interface")


def create_app(settings: Settings | None = None, adapter: PrintLabAdapter | None = None, gateway: Gateway | None = None) -> FastAPI:
    settings = settings or load_settings()
    redact.install()
    redact.install(log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.run_dir.mkdir(parents=True, exist_ok=True)
        app.state.admin_token = security.load_or_create_token(settings.data_dir)
        with db.session(settings.db_path) as conn:
            db.record_audit(conn, "system", "startup", "service", "ok", f"version={__version__}")
        app.state.adapter = adapter or PrintLabAdapter(settings)
        app.state.gateway = gateway or Gateway(settings.db_path)
        log.info("admin token stored at %s (not logged)", settings.data_dir / security.TOKEN_FILE)
        try:
            yield
        finally:
            app.state.adapter.close()

    app = FastAPI(title="PrintLabInterface", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body echoes each rejected value under "input". For a key field that
        # would send a (possibly real) secret back to the caller and into any response log.
        problems = [{"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "invalid value")), "type": e.get("type", "")}
                    for e in exc.errors()]
        return JSONResponse({"detail": problems}, status_code=422)
    app.add_middleware(security.HostGuard, hosts=security.allowed_hosts(settings.port) | {"testserver"})

    @app.get("/healthz")
    def healthz() -> dict:
        # Independent of PrintLab by design: the sidecar is healthy even when PrintLab is down.
        return {"ok": True, "version": __version__, "service": "printlab-interface"}

    @app.get("/api/printlab")
    def printlab_state() -> dict:
        return app.state.adapter.describe()

    @app.get("/api/printlab/status")
    def printlab_status() -> dict:
        return app.state.adapter.read_status()

    @app.get("/api/audit", dependencies=[Depends(security.require_admin)])
    def audit(limit: int = 50) -> list[dict]:
        with db.session(settings.db_path) as conn:
            return db.recent_audit(conn, limit)

    app.include_router(providers_api.router)
    return app
