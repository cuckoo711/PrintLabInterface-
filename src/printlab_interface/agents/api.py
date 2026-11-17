"""Chat API: agents, sessions, runs. Every route needs the admin token."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import db
from ..redact import redact
from ..security import require_admin
from . import sessions
from .manager import RunManager, RunRefused

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


class SessionIn(BaseModel):
    agent: str = Field(min_length=1, max_length=32)


class RunIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    model: str | None = Field(default=None, max_length=200)


def _conn(request: Request):
    conn = db.connect(request.app.state.settings.db_path)
    sessions.init(conn)
    return conn


def _agents(request: Request) -> dict:
    return request.app.state.agents


def _manager(request: Request) -> RunManager:
    return request.app.state.runs


def _session_or_404(conn, session_id: str):
    try:
        return sessions.get(conn, session_id)
    except sessions.SessionError:
        raise HTTPException(status_code=404, detail="unknown session") from None


@router.get("/agents")
def list_agents(request: Request):
    return [
        {"name": a.name, "description": a.description, "model": a.model, "tools": sorted(a.ceiling.tools),
         "max_turns": a.ceiling.max_turns, "degraded": a.degraded, "problems": list(a.problems)}
        for a in sorted(_agents(request).values(), key=lambda a: a.name)
    ]


@router.get("/sessions")
def list_sessions(request: Request, agent: str | None = None, limit: int = 50):
    conn = _conn(request)
    try:
        return sessions.list_sessions(conn, agent, limit)
    finally:
        conn.close()


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, request: Request):
    if body.agent not in _agents(request):
        raise HTTPException(status_code=404, detail="unknown agent")
    conn = _conn(request)
    try:
        try:
            s = sessions.create(conn, body.agent)
        except sessions.SessionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"id": s.id, "agent": s.agent, "title": s.title}
    finally:
        conn.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    conn = _conn(request)
    try:
        s = _session_or_404(conn, session_id)
        # Only the newest page: a long conversation is read in pages, older ones come from /messages?before=
        page, more = sessions.messages_page(conn, session_id)
        return {"id": s.id, "agent": s.agent, "title": s.title, "messages": page, "has_more": more,
                "runs": sessions.list_runs(conn, session_id)}
    finally:
        conn.close()


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, request: Request, before: int | None = Query(default=None, ge=1), limit: int = Query(default=sessions.PAGE_DEFAULT, ge=1, le=sessions.PAGE_MAX)):
    conn = _conn(request)
    try:
        _session_or_404(conn, session_id)
        page, more = sessions.messages_page(conn, session_id, before, limit)
        return {"messages": page, "has_more": more}
    finally:
        conn.close()


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request):
    conn = _conn(request)
    try:
        _session_or_404(conn, session_id)
        if session_id in _manager(request)._by_session:
            raise HTTPException(status_code=409, detail="a run is in progress; cancel it first")
        sessions.delete(conn, session_id)
        db.record_audit(conn, "admin", "session_delete", session_id, "ok")
    finally:
        conn.close()


def _sse(event: str, data: dict) -> str:
    # Redact again at the edge: the stream is the one place data leaves the process.
    return f"event: {event}\ndata: {redact(json.dumps(data, ensure_ascii=False))}\n\n"


@router.post("/sessions/{session_id}/run")
async def run_session(session_id: str, body: RunIn, request: Request):
    conn = _conn(request)
    try:
        s = _session_or_404(conn, session_id)
    finally:
        conn.close()
    agent = _agents(request).get(s.agent)
    if agent is None:
        raise HTTPException(status_code=404, detail="the agent for this session no longer exists")
    manager = _manager(request)
    try:
        active = await asyncio.to_thread(manager.start, agent, session_id, body.message, body.model)
    except RunRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    async def stream() -> AsyncIterator[str]:
        yield _sse("start", {"run_id": active.run_id, "session_id": session_id})
        loop = asyncio.get_running_loop()
        iterator = manager.drain(active, is_disconnected=lambda: False)
        sentinel = object()
        while True:
            item = await loop.run_in_executor(None, lambda: next(iterator, sentinel))
            if item is sentinel:
                break
            if await request.is_disconnected():
                active.cancel.set()
            yield _sse(item.kind, item.data)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    if not _manager(request).cancel(run_id):
        raise HTTPException(status_code=404, detail="no such run in progress")
    return {"run_id": run_id, "cancelling": True}
