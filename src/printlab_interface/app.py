"""FastAPI application. Starts with or without PrintLab."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, db, redact, security, web
from .adapters.printlab import PrintLabAdapter
from .agents import api as agents_api
from .agents.definition import load_dir
from .agents.loop import AgentRunner
from .agents.manager import RunManager
from .config import Settings, load_settings
from .providers import api as providers_api
from .providers.gateway import Gateway
from .tools.gateway import ToolGateway
from .tools.native import NativeTools
from .workflows import api as workflows_api
from .workflows.definition import load_dir as load_workflows
from .workflows.engine import WorkflowEngine

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
        app.state.agents = load_dir(settings.agents_dir)
        docs_dir = settings.printlab_root / "docs" if settings.printlab_root else None
        tool_gateway = ToolGateway(app.state.adapter.runner, audit_db=lambda: db.connect(settings.db_path),
                                   native=NativeTools(docs_dir, settings.web_allow_hosts))
        agent_runner = AgentRunner(app.state.gateway, tool_gateway)
        app.state.runs = RunManager(settings.db_path, agent_runner)
        interrupted = app.state.runs.recover()
        if interrupted:
            log.warning("marked %d unfinished run(s) from a previous process as interrupted", interrupted)
        app.state.workflows_engine = WorkflowEngine(
            settings.db_path, settings.data_dir / "workflow_checkpoints.db", app.state.agents, agent_runner,
            app.state.adapter.runner, load_workflows(settings.workflows_dir, app.state.agents))
        stopped = app.state.workflows_engine.recover()
        if stopped:
            log.warning("marked %d workflow run(s) from a previous process as interrupted", stopped)
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
    app.add_middleware(security.HostGuard, hosts=security.allowed_hosts(settings.port) | set(settings.extra_hosts))

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
    app.include_router(agents_api.router)
    app.include_router(workflows_api.router)
    app.include_router(web.router)
    return app
