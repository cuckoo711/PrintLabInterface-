"""Runs agents in background threads and hands their events to HTTP streams.

Rules:
  * one active run per session (a second request is refused, not queued);
  * a global cap on concurrent runs, so a loop of requests cannot exhaust the machine;
  * every run has a Cancel handle addressable by run id;
  * the event queue is bounded; a slow or absent reader never blocks the run, it just
    loses intermediate events (the final status is always kept);
  * the user's message and the assistant's reply are stored by the manager, not by the model.
"""
from __future__ import annotations

import queue
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import db
from .. import settings_store
from . import sessions
from .definition import AgentDefinition
from .loop import AgentRunner, Cancel, Event, RunResult

MAX_CONCURRENT_RUNS = 3
EVENT_QUEUE_SIZE = 200
_SENTINEL = object()


class RunRefused(RuntimeError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class ActiveRun:
    run_id: str
    session_id: str
    cancel: Cancel
    events: "queue.Queue[object]" = field(default_factory=lambda: queue.Queue(maxsize=EVENT_QUEUE_SIZE))
    thread: threading.Thread | None = None
    result: RunResult | None = None


class RunManager:
    def __init__(self, db_path: Path, runner: AgentRunner, *, max_concurrent: int = MAX_CONCURRENT_RUNS):
        self.db_path = db_path
        self.runner = runner
        self.max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._active: dict[str, ActiveRun] = {}       # run_id -> run
        self._by_session: dict[str, str] = {}          # session_id -> run_id

    def _conn(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        sessions.init(conn)
        return conn

    def recover(self) -> int:
        conn = self._conn()
        try:
            return sessions.abandon_unfinished(conn)
        finally:
            conn.close()

    def _default_model(self) -> str:
        conn = self._conn()
        try:
            return settings_store.get_default_model(conn)
        finally:
            conn.close()

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def start(self, agent: AgentDefinition, session_id: str, user_text: str, model: str | None) -> ActiveRun:
        chosen = model or agent.model or self._default_model()
        if not chosen:
            raise RunRefused("还没有选模型：在页面的“模型”框里填，或到管理后台设一个默认模型", 400)
        if agent.degraded:
            raise RunRefused("agent definition is invalid: " + "; ".join(agent.problems), 400)
        conn = self._conn()
        try:
            try:
                session = sessions.get(conn, session_id)
            except sessions.SessionError as exc:
                raise RunRefused(str(exc), 404) from None
            if session.agent != agent.name:
                raise RunRefused("this session belongs to a different agent", 400)
            with self._lock:
                if session_id in self._by_session:
                    raise RunRefused("this session already has a run in progress")
                if len(self._active) >= self.max_concurrent:
                    raise RunRefused("too many runs in progress; try again shortly", 429)
                try:
                    history = sessions.history(conn, session_id)
                    sessions.add_message(conn, session_id, "user", user_text)
                except sessions.SessionError as exc:
                    raise RunRefused(str(exc), 400) from None
                run_id = sessions.start_run(conn, session_id, chosen)
                active = ActiveRun(run_id, session_id, Cancel())
                self._active[run_id] = active
                self._by_session[session_id] = run_id
        finally:
            conn.close()
        thread = threading.Thread(target=self._work, args=(active, agent, user_text, history, chosen), name=f"run-{run_id}", daemon=True)
        active.thread = thread
        thread.start()
        return active

    def _push(self, active: ActiveRun, item: object, *, must_keep: bool = False) -> None:
        try:
            active.events.put_nowait(item)
        except queue.Full:
            if must_keep:
                try:
                    active.events.get_nowait()  # drop the oldest to make room for the terminal event
                except queue.Empty:
                    pass
                try:
                    active.events.put_nowait(item)
                except queue.Full:
                    pass

    def _work(self, active: ActiveRun, agent: AgentDefinition, user_text: str, history: list[dict], model: str) -> None:
        tools_used: list[str] = []

        def on_event(event: Event) -> None:
            if event.kind == "tool_call":
                tools_used.append(str(event.data.get("name")))
            # A piece of streamed text may be dropped when the reader is slow: the whole reply follows as a "text" event.
            # Everything else is kept, at the cost of the oldest queued item.
            self._push(active, event, must_keep=event.kind != "text_delta")

        result = RunResult("error", "", 0, 0, {}, "run did not start")
        try:
            result = self.runner.run(agent, user_text, history=history, model=model, cancel=active.cancel,
                                     session=active.session_id, on_event=on_event)
        except Exception as exc:  # noqa: BLE001 - a thread must never die silently
            result = RunResult("error", "", 0, 0, {}, f"{type(exc).__name__}: {str(exc)[:200]}")
        finally:
            conn = self._conn()
            try:
                if result.text and result.status in {"done", "truncated", "max_turns", "timeout", "cancelled"}:
                    try:
                        sessions.add_message(conn, active.session_id, "assistant", result.text)
                    except sessions.SessionError:
                        pass
                sessions.finish_run(conn, active.run_id, status=result.status, turns=result.turns, tool_calls=result.tool_calls,
                                    tools=tools_used, usage=result.usage, error=result.error)
            finally:
                conn.close()
            active.result = result
            self._push(active, Event("end", {"status": result.status, "error": result.error, "turns": result.turns,
                                              "tool_calls": result.tool_calls, "usage": result.usage}), must_keep=True)
            self._push(active, _SENTINEL, must_keep=True)
            with self._lock:
                self._active.pop(active.run_id, None)
                if self._by_session.get(active.session_id) == active.run_id:
                    self._by_session.pop(active.session_id, None)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            active = self._active.get(run_id)
        if active is None:
            return False
        active.cancel.set()
        return True

    def get(self, run_id: str) -> ActiveRun | None:
        with self._lock:
            return self._active.get(run_id)

    @staticmethod
    def drain(active: ActiveRun, *, poll_s: float = 0.25, idle_limit_s: float = 300.0,
              is_disconnected: Callable[[], bool] | None = None):
        """Yield events until the run ends. If the reader goes away the run is cancelled."""
        idle = 0.0
        while True:
            try:
                item = active.events.get(timeout=poll_s)
            except queue.Empty:
                idle += poll_s
                if is_disconnected is not None and is_disconnected():
                    active.cancel.set()
                    return
                if idle >= idle_limit_s:
                    active.cancel.set()
                    return
                continue
            idle = 0.0
            if item is _SENTINEL:
                return
            yield item
