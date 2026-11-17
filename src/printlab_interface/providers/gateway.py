"""One entry point for model calls: `Gateway.complete(...)`.

Resolves `prefix:model`, picks a key from the pool, calls LiteLLM, classifies failures,
moves to another key when (and only when) the key was at fault, and records usage.
Plaintext keys exist only inside `_call_once`; nothing here logs or returns them.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from urllib.parse import quote

from .. import db
from ..redact import redact
from . import model_card, store
from ._litellm import litellm
from .key_pool import Fault, KeyEntry, KeyPool
from .model_ref import ModelRefError, parse

# litellm routes by its own provider names; our "kind" maps onto them.
_LITELLM_PREFIX = {
    "openai": "openai", "anthropic": "anthropic", "deepseek": "deepseek", "gemini": "gemini",
    "openrouter": "openrouter", "ollama": "ollama", "openai_compatible": "openai",
}
_REASONING = {"none", "low", "medium", "high"}
MAX_TOOLS = 32
MAX_ATTEMPTS = 3
MAX_MESSAGES = 200
MAX_TOTAL_CHARS = 400_000


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class CallResult:
    text: str
    model: str
    key_label: str
    attempts: int
    usage: dict[str, int | None]
    finish_reason: str | None
    cost_usd: float | None = None
    warnings: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)  # [{"id", "name", "arguments"}]

    @property
    def truncated(self) -> bool:
        """True when the provider stopped because of the output limit; the text may end mid-sentence."""
        return (self.finish_reason or "").lower() in {"length", "max_tokens", "max_output_tokens"}


def _scrub(text: str, secrets_: list[str]) -> str:
    """Remove every occurrence of each known secret, including common transformed forms."""
    for secret in secrets_:
        if not secret or len(secret) < 8:
            continue
        for form in {secret, secret.lower(), secret.upper(), quote(secret, safe="")}:
            text = text.replace(form, "***")
    return text


def _status_of(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        return float(headers.get("retry-after")) if headers and headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


MAX_TOOL_ARGS_CHARS = 8_000
MAX_STREAM_CHARS = 100_000


def _collect_stream(stream: Any, on_delta: Callable[[str], None], should_stop: Callable[[], bool] | None, state: dict) -> Any:
    """Read a streamed completion to the end and return it shaped like a non-streamed response.

    `on_delta` sees each piece of text as it arrives. `state["output"]` turns True the moment the first piece of text has been
    handed on, because from then on a failure must not be retried on another key (the person has already seen output).
    A stop request ends the read early and closes the stream; the caller decides what a stopped reply means.
    """
    parts: list[str] = []
    size = 0
    calls: dict[int, dict] = {}
    finish: str | None = None
    usage = None
    try:
        for chunk in stream:
            if should_stop is not None and should_stop():
                break
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = chunk_usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            finish = getattr(choice, "finish_reason", None) or finish
            delta = getattr(choice, "delta", None)
            piece = getattr(delta, "content", None)
            if isinstance(piece, str) and piece:
                parts.append(piece)
                size += len(piece)
                state["output"] = True
                on_delta(piece)
                if size > MAX_STREAM_CHARS:
                    finish = "length"
                    break
            for position, call in enumerate(getattr(delta, "tool_calls", None) or []):
                index = getattr(call, "index", None)
                slot = calls.setdefault(index if isinstance(index, int) else position, {"id": "", "name": "", "arguments": ""})
                fn = getattr(call, "function", None)
                if isinstance(getattr(call, "id", None), str) and call.id:
                    slot["id"] = call.id
                if isinstance(getattr(fn, "name", None), str):
                    slot["name"] += fn.name
                if isinstance(getattr(fn, "arguments", None), str):
                    slot["arguments"] += fn.arguments
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - a stream that cannot be closed is already finished
                pass
    tool_calls = [SimpleNamespace(id=c["id"], function=SimpleNamespace(name=c["name"], arguments=c["arguments"] or "{}"))
                  for _, c in sorted(calls.items())]
    message = SimpleNamespace(content="".join(parts), tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=usage)


def _tool_calls_of(message: Any) -> list[dict]:
    """Normalise the provider's tool calls. Arguments stay a string; the tool gateway parses and validates them."""
    out: list[dict] = []
    for call in getattr(message, "tool_calls", None) or []:
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", None)
        args = getattr(fn, "arguments", None)
        call_id = getattr(call, "id", None)
        if not isinstance(name, str) or not isinstance(call_id, str) or not call_id:
            continue  # a malformed call is dropped rather than guessed at
        args = args if isinstance(args, str) else "{}"
        out.append({"id": call_id[:80], "name": name[:80], "arguments": args[:MAX_TOOL_ARGS_CHARS]})
    return out


def _validate_messages(messages: list[dict]) -> None:
    if not isinstance(messages, list) or not messages or len(messages) > MAX_MESSAGES:
        raise GatewayError("messages must be a non-empty list (max %d)" % MAX_MESSAGES)
    total = 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant", "tool"}:
            raise GatewayError("each message needs a valid role")
        content = m.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise GatewayError("message content must be text or a list of parts")
        if m["role"] == "tool" and not (isinstance(m.get("tool_call_id"), str) and m["tool_call_id"]):
            raise GatewayError("a tool message needs a tool_call_id")
        if m["role"] != "tool" and content is None and not m.get("tool_calls"):
            raise GatewayError("a message needs content unless it carries tool calls")
        total += len(content) if isinstance(content, str) else len(str(content))
    if total > MAX_TOTAL_CHARS:
        raise GatewayError("request too large")


class Gateway:
    def __init__(self, db_path: Path, *, pool: KeyPool | None = None, call: Callable[..., Any] | None = None):
        self.db_path = db_path
        self.pool = pool or KeyPool()
        self._call = call or litellm.completion

    def _conn(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        store.init(conn)
        return conn

    @staticmethod
    def _secrets_in_use(conn: sqlite3.Connection, prefix: str) -> list[str]:
        """Plaintext keys of this provider, held only long enough to scrub an error message."""
        out: list[str] = []
        for row in conn.execute("SELECT id FROM provider_keys WHERE prefix=?", (prefix,)).fetchall():
            try:
                out.append(store.reveal_key(conn, row["id"]))
            except Exception:  # noqa: BLE001 - an unreadable key cannot be echoed back anyway
                continue
        return out

    def card_for(self, model_value: str) -> model_card.ModelCard:
        ref = parse(model_value)
        conn = self._conn()
        try:
            provider = store.get_provider(conn, ref.prefix)
            return model_card.resolve(
                ref.model, litellm_provider=_LITELLM_PREFIX[provider.litellm_kind],
                override=store.get_override(conn, ref.prefix, ref.model),
            )
        finally:
            conn.close()

    def complete(
        self, model_value: str, messages: list[dict], *, session: str | None = None, max_tokens: int | None = None,
        temperature: float | None = None, reasoning_effort: str | None = None, timeout_s: float = 60.0,
        response_format: dict | None = None, mock_response: Any = None, tools: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None, should_stop: Callable[[], bool] | None = None,
    ) -> CallResult:
        """One model call. With `on_delta` the reply is streamed: each piece of text is handed to it as it arrives, and the
        result is still the whole reply. `should_stop` is polled between pieces so a cancel does not wait for the model."""
        _validate_messages(messages)
        if tools is not None and (not isinstance(tools, list) or len(tools) > MAX_TOOLS):
            raise GatewayError(f"tools must be a list of at most {MAX_TOOLS} definitions")
        try:
            ref = parse(model_value)
        except ModelRefError as exc:
            raise GatewayError(str(exc)) from None
        if reasoning_effort is not None and reasoning_effort not in _REASONING:
            raise GatewayError(f"reasoning_effort must be one of {sorted(_REASONING)}")
        if temperature is not None and not 0 <= temperature <= 2:
            raise GatewayError("temperature must be between 0 and 2")
        if not 1 <= timeout_s <= 600:
            raise GatewayError("timeout_s must be between 1 and 600")

        conn = self._conn()
        try:
            try:
                provider = store.get_provider(conn, ref.prefix)
            except store.StoreError as exc:
                raise GatewayError(str(exc)) from None
            if not provider.enabled:
                raise GatewayError(f"provider '{ref.prefix}' is disabled")
            card = model_card.resolve(
                ref.model, litellm_provider=_LITELLM_PREFIX[provider.litellm_kind],
                override=store.get_override(conn, ref.prefix, ref.model),
            )
            try:
                out_cap = model_card.clamp_max_tokens(card, max_tokens)
            except ValueError as exc:
                raise GatewayError(str(exc)) from None
            if response_format is not None and card.get("supports_response_schema") is False:
                raise GatewayError("this model's card says it does not support structured output")

            tried: set[str] = set()
            last_error: GatewayError | None = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                entries = store.key_entries(conn, ref.prefix)
                # A provider without keys (for example a local Ollama) is allowed to run keyless.
                keyless = not entries and provider.litellm_kind in {"ollama", "openai_compatible"}
                entry: KeyEntry | None = None
                if not keyless:
                    entry = self.pool.select(ref.prefix, entries, session=session, exclude=tried)
                    if entry is None:
                        raise last_error or GatewayError(f"no usable API key for '{ref.prefix}'")
                    tried.add(entry.id)
                started = time.perf_counter()
                state = {"output": False}
                try:
                    response = self._call_once(provider, ref.model, messages, entry, conn, out_cap, temperature,
                                               reasoning_effort, timeout_s, response_format, mock_response, tools,
                                               stream=on_delta is not None)
                    if on_delta is not None and not hasattr(response, "choices"):
                        response = _collect_stream(response, on_delta, should_stop, state)
                except Exception as exc:  # noqa: BLE001 - classified below
                    status = _status_of(exc)
                    fault: Fault = (self.pool.report_failure(ref.prefix, entry, status, str(exc), _retry_after(exc))
                                    if entry else Fault("neutral"))
                    if entry and fault.kind == "invalid":
                        store.set_key_state(conn, entry.id, invalid=True)
                    db.record_audit(conn, "gateway", "model_call", f"{ref.prefix}:{ref.model}", f"error:{type(exc).__name__}",
                                    f"status={status} fault={fault.kind} attempt={attempt}")
                    # Upstream errors sometimes echo the credential they rejected. Erase the exact key
                    # text first (works for any key shape), then run the general redactor on top.
                    safe = redact(_scrub(str(exc), self._secrets_in_use(conn, ref.prefix)))[:300]
                    last_error = GatewayError(f"{type(exc).__name__}: {safe}", status=status,
                                              retryable=fault.kind in {"rate_limited", "quota", "forbidden", "invalid"})
                    if self.pool.should_try_next_key(fault, output_started=state["output"]) and attempt < MAX_ATTEMPTS:
                        continue
                    raise last_error from None
                if entry:
                    self.pool.report_success(ref.prefix, entry.id)
                result = self._to_result(response, f"{ref.prefix}:{ref.model}", entry, attempt, card)
                db.record_audit(conn, "gateway", "model_call", f"{ref.prefix}:{ref.model}", "ok",
                                f"ms={int((time.perf_counter() - started) * 1000)} tokens={result.usage.get('total_tokens')} attempt={attempt}")
                return result
            raise last_error or GatewayError("model call failed")
        finally:
            conn.close()

    def _call_once(self, provider, model, messages, entry, conn, out_cap, temperature, reasoning_effort, timeout_s, response_format, mock_response, tools=None, stream=False):
        kwargs: dict[str, Any] = {
            "model": f"{_LITELLM_PREFIX[provider.litellm_kind]}/{model}", "messages": messages,
            "timeout": timeout_s, "num_retries": 0,  # retries are the pool's job, so cost and key choice stay visible
        }
        if provider.api_base:
            kwargs["api_base"] = provider.api_base
        if entry is not None:
            kwargs["api_key"] = store.reveal_key(conn, entry.id)
        if out_cap is not None:
            kwargs["max_tokens"] = out_cap
        if temperature is not None:
            kwargs["temperature"] = temperature
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}  # the last chunk then carries the token counts
        if mock_response is not None:
            kwargs["mock_response"] = mock_response
        return self._call(**kwargs)

    @staticmethod
    def _to_result(response, model: str, entry: KeyEntry | None, attempt: int, card: model_card.ModelCard) -> CallResult:
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", None)
        cost = None
        in_p, out_p = card.get("input_cost_per_token"), card.get("output_cost_per_token")
        if in_p is not None and out_p is not None and pt is not None and ct is not None:
            cost = pt * in_p + ct * out_p
        return CallResult(
            text=choice.message.content or "", model=model, key_label=(entry.id if entry else "keyless"), attempts=attempt,
            usage={"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": getattr(usage, "total_tokens", None)},
            finish_reason=getattr(choice, "finish_reason", None), cost_usd=cost, warnings=list(card.warnings),
            tool_calls=_tool_calls_of(choice.message),
        )
