"""The agent loop: ask the model, run the tools it asks for, feed the results back.

Hard limits, all enforced here and not left to the model:
  * at most `ceiling.max_turns` model calls per run;
  * at most MAX_TOOL_CALLS_PER_TURN tool calls in one reply, and MAX_TOOL_CALLS_TOTAL per run;
  * a wall-clock budget for the whole run;
  * the caller can cancel between steps;
  * a model that repeats an identical failing call is stopped, not allowed to spin.
A run always ends with a status the caller can show: done, max_turns, timeout, cancelled, error.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..providers.gateway import CallResult, Gateway, GatewayError
from ..tools.gateway import ToolGateway
from ..tools.registry import TOOLS
from .definition import AgentDefinition, Ceiling

MAX_TOOL_CALLS_PER_TURN = 4
MAX_TOOL_CALLS_TOTAL = 16
MAX_RUN_SECONDS = 180.0
MAX_USER_CHARS = 8_000
MAX_HISTORY_MESSAGES = 60


@dataclass
class Event:
    kind: str  # "text" | "tool_call" | "tool_result" | "status" | "usage"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    status: str  # "done" | "max_turns" | "timeout" | "cancelled" | "error"
    text: str
    turns: int
    tool_calls: int
    usage: dict[str, int]
    error: str | None = None
    history: list[dict] = field(default_factory=list)


class Cancel:
    """Set from another thread to stop a run at the next step boundary."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()


def _calls_of(result: CallResult) -> list[dict]:
    return result.tool_calls or []


class AgentRunner:
    def __init__(self, models: Gateway, tools: ToolGateway, *, clock: Callable[[], float] = time.monotonic):
        self.models = models
        self.tools = tools
        self._clock = clock

    def run(self, agent: AgentDefinition, user_text: str, *, history: list[dict] | None = None, model: str | None = None,
            cancel: Cancel | None = None, session: str | None = None, ceiling: Ceiling | None = None,
            on_event: Callable[[Event], None] | None = None) -> RunResult:
        emit = on_event or (lambda e: None)
        effective = (ceiling or agent.ceiling)
        if ceiling is not None:  # an override may only narrow the agent's own ceiling
            effective = agent.ceiling.narrow(set(ceiling.tools), ceiling.max_turns)
        model_value = model or agent.model
        if not model_value:
            return RunResult("error", "", 0, 0, {}, "no model chosen: set `model` in the agent file or pass one")
        if agent.degraded:
            return RunResult("error", "", 0, 0, {}, "agent definition is invalid: " + "; ".join(agent.problems))
        if not isinstance(user_text, str) or not user_text.strip() or len(user_text) > MAX_USER_CHARS:
            return RunResult("error", "", 0, 0, {}, f"message must be 1-{MAX_USER_CHARS} characters")

        tool_schemas = self.tools.schemas(effective.tools)
        messages: list[dict] = [{"role": "system", "content": agent.prompt}]
        messages += [m for m in (history or [])[-MAX_HISTORY_MESSAGES:] if m.get("role") in {"user", "assistant"}]
        messages.append({"role": "user", "content": user_text})

        started = self._clock()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        total_calls = 0
        last_failed: tuple[str, str] | None = None
        text = ""

        def finish(status: str, error: str | None = None, turns: int = 0) -> RunResult:
            emit(Event("status", {"status": status}))
            return RunResult(status, text, turns, total_calls, usage, error, messages[1:])

        for turn in range(1, effective.max_turns + 1):
            if cancel is not None and cancel.is_set:
                return finish("cancelled", turns=turn - 1)
            if self._clock() - started > MAX_RUN_SECONDS:
                return finish("timeout", turns=turn - 1)
            remaining = max(1.0, min(60.0, MAX_RUN_SECONDS - (self._clock() - started)))
            try:
                result = self.models.complete(model_value, messages, session=session, timeout_s=remaining, tools=tool_schemas or None)
            except GatewayError as exc:
                return finish("error", str(exc)[:300], turn - 1)
            for key in usage:
                usage[key] += int(result.usage.get(key) or 0)
            calls = _calls_of(result)
            if result.text:
                text = result.text
                emit(Event("text", {"text": result.text}))
            if not calls:
                messages.append({"role": "assistant", "content": result.text})
                return finish("done", turns=turn)

            if len(calls) > MAX_TOOL_CALLS_PER_TURN:
                calls = calls[:MAX_TOOL_CALLS_PER_TURN]
            messages.append({"role": "assistant", "content": result.text or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
            for call in calls:
                if cancel is not None and cancel.is_set:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": "Error: the run was cancelled."})
                    continue
                if total_calls >= MAX_TOOL_CALLS_TOTAL:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": "Error: tool call budget for this run is used up."})
                    continue
                total_calls += 1
                emit(Event("tool_call", {"name": call["name"]}))
                outcome = self.tools.call(agent.name, call["name"], call["arguments"], effective.tools, allow_write=effective.allow_write)
                emit(Event("tool_result", {"name": call["name"], "ok": outcome.ok, "refused": outcome.refused}))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": outcome.content})
                signature = (call["name"], str(call["arguments"]))
                if not outcome.ok and last_failed == signature:
                    return finish("error", f"stopped: '{call['name']}' failed twice with identical arguments", turn)
                last_failed = None if outcome.ok else signature
            if cancel is not None and cancel.is_set:
                return finish("cancelled", turns=turn)
        return finish("max_turns", turns=effective.max_turns)

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[Event]:
        """Run to completion and yield the events in order. Streaming of token deltas comes with real providers."""
        events: list[Event] = []
        result = self.run(*args, on_event=events.append, **kwargs)
        yield from events
        yield Event("usage", {"usage": result.usage, "turns": result.turns, "tool_calls": result.tool_calls, "status": result.status, "error": result.error})
