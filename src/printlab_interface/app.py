"""FastAPI application. Starts with or without PrintLab."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__, db, redact
from .adapters.printlab import PrintLabAdapter
from .config import Settings, load_settings

log = logging.getLogger("printlab_interface")


def create_app(settings: Settings | None = None, adapter: PrintLabAdapter | None = None) -> FastAPI:
    settings = settings or load_settings()
    redact.install()
    redact.install(log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.run_dir.mkdir(parents=True, exist_ok=True)
        with db.session(settings.db_path) as conn:
            db.record_audit(conn, "system", "startup", "service", "ok", f"version={__version__}")
        app.state.adapter = adapter or PrintLabAdapter(settings)
        try:
            yield
        finally:
            app.state.adapter.close()

    app = FastAPI(title="PrintLabInterface", version=__version__, lifespan=lifespan)
    app.state.settings = settings

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

    @app.get("/api/audit")
    def audit(limit: int = 50) -> list[dict]:
        with db.session(settings.db_path) as conn:
            return db.recent_audit(conn, limit)

    return app
