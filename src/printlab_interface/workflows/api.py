"""Workflow API. Every route needs the admin token. A run is only ever moved by these calls."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..security import require_admin
from .engine import EngineError, WorkflowEngine

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


class StartIn(BaseModel):
    workflow: str = Field(min_length=1, max_length=32)
    request_id: str = Field(min_length=8, max_length=80)
    project: str = Field(default="", max_length=64)
    brief: str = Field(default="", max_length=4000)
    model: str = Field(default="", max_length=200)


class AnswerIn(BaseModel):
    answer: str = Field(pattern="^(yes|no)$")


def _engine(request: Request) -> WorkflowEngine:
    return request.app.state.workflows_engine


async def _call(fn, *args, **kwargs):
    """Engine calls block while a stage runs (a model call can take a while), so keep them off the event loop."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.get("/workflows")
def list_workflows(request: Request):
    return [
        {"name": w.name, "description": w.description, "model": w.model, "valid": w.valid, "problems": list(w.problems),
         "needs_project": w.needs_project, "stages": [{"id": s.id, "kind": s.kind} for s in w.stages]}
        for w in sorted(_engine(request).workflows.values(), key=lambda w: w.name)
    ]


@router.get("/workflow-runs")
def list_runs(request: Request, limit: int = 30):
    return _engine(request).list_runs(limit)


@router.get("/workflow-runs/{run_id}")
def get_run(run_id: str, request: Request):
    try:
        return _engine(request).view(run_id).as_dict()
    except EngineError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


@router.post("/workflow-runs")
async def start_run(body: StartIn, request: Request, response: Response):
    view, created = await _call(_engine(request).start, body.workflow, request_id=body.request_id, project=body.project, brief=body.brief, model=body.model)
    response.status_code = 201 if created else 200  # a replayed request_id returns the existing run, not a new one
    return {**view.as_dict(), "created": created}


@router.post("/workflow-runs/{run_id}/answer")
async def answer_run(run_id: str, body: AnswerIn, request: Request):
    return (await _call(_engine(request).answer, run_id, body.answer)).as_dict()


@router.post("/workflow-runs/{run_id}/retry")
async def retry_run(run_id: str, request: Request):
    return (await _call(_engine(request).retry, run_id)).as_dict()


@router.post("/workflow-runs/{run_id}/stop")
async def stop_run(run_id: str, request: Request):
    return (await _call(_engine(request).stop, run_id)).as_dict()
