"""Mailbox and schedule routes. Every route needs the admin token."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import db
from ..security import require_admin
from . import mailbox
from .scheduler import ScheduleError, Scheduler

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


def _scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


@router.get("/mailbox")
def list_mailbox(request: Request, unread: bool = False, limit: int = 50):
    with db.session(request.app.state.settings.db_path) as conn:
        return {"unread": mailbox.unread_count(conn), "messages": mailbox.list_messages(conn, unread_only=unread, limit=limit)}


@router.post("/mailbox/{message_id}/ack")
def ack_message(request: Request, message_id: int):
    with db.session(request.app.state.settings.db_path) as conn:
        if not mailbox.ack(conn, message_id):
            raise HTTPException(status_code=404, detail="no unread message with this id")
    return {"ok": True}


@router.get("/scheduler")
def scheduler_state(request: Request):
    s = _scheduler(request)
    return {"enabled": s.enabled, "running": s._thread is not None, "tick_seconds": s.tick_s, "schedules": s.list()}


@router.post("/schedules", status_code=201)
def create_schedule(request: Request, body: dict[str, Any]):
    try:
        return _scheduler(request).create(body)
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.patch("/schedules/{schedule_id}")
def update_schedule(request: Request, schedule_id: str, body: dict[str, Any]):
    try:
        return _scheduler(request).update(schedule_id, body)
    except ScheduleError as exc:
        raise HTTPException(status_code=404 if str(exc) == "unknown schedule" else 422, detail=str(exc)) from None


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(request: Request, schedule_id: str):
    try:
        _scheduler(request).delete(schedule_id)
    except ScheduleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/schedules/{schedule_id}/run")
def run_schedule_now(request: Request, schedule_id: str):
    """One manual run. It still counts against the caps, and an agent schedule still needs its caps to exist."""
    s = _scheduler(request)
    try:
        s.get(schedule_id)
    except ScheduleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if not s.enabled:
        raise HTTPException(status_code=409, detail="the scheduler is switched off (set PLI_SCHEDULER=1 and restart)")
    ran = s.run_one(schedule_id, manual=True)
    return {"ran": ran, "schedule": s.get(schedule_id)}
