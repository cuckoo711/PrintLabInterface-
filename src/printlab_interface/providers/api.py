"""Admin API for providers, keys, model cards and test calls. Keys are write-only."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db
from ..security import require_admin
from . import model_card, store
from .gateway import Gateway, GatewayError
from .model_ref import ModelRefError, parse

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


class ProviderIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    kind: str
    api_base: str | None = Field(default=None, max_length=300)


class KeyIn(BaseModel):
    label: str = Field(default="key", max_length=60)
    api_key: str = Field(min_length=8, max_length=500, repr=False)
    priority: int = Field(default=100, ge=0, le=10000)


class EnabledIn(BaseModel):
    enabled: bool


class OverrideIn(BaseModel):
    values: dict[str, bool | int | float | None]


class ChatIn(BaseModel):
    model: str
    messages: list[dict]
    session: str | None = Field(default=None, max_length=100)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    timeout_s: float = Field(default=60, ge=1, le=600)


def _gateway(request: Request) -> Gateway:
    return request.app.state.gateway


def _conn(request: Request):
    conn = db.connect(request.app.state.settings.db_path)
    store.init(conn)
    return conn


def _guard(fn):
    try:
        return fn()
    except (store.StoreError, ModelRefError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/providers")
def list_providers(request: Request):
    conn = _conn(request)
    try:
        return store.list_providers(conn)
    finally:
        conn.close()


@router.post("/providers", status_code=201)
def create_provider(body: ProviderIn, request: Request):
    conn = _conn(request)
    try:
        p = _guard(lambda: store.add_provider(conn, body.prefix, body.name, body.kind, body.api_base))
        db.record_audit(conn, "admin", "provider_add", p.prefix, "ok", f"kind={p.litellm_kind}")
        return {"prefix": p.prefix, "name": p.name, "kind": p.litellm_kind, "api_base": p.api_base, "enabled": p.enabled}
    finally:
        conn.close()


@router.patch("/providers/{prefix}")
def update_provider(prefix: str, body: EnabledIn, request: Request):
    conn = _conn(request)
    try:
        _guard(lambda: store.set_enabled(conn, prefix, body.enabled))
        db.record_audit(conn, "admin", "provider_enable", prefix, "ok", f"enabled={body.enabled}")
        return {"prefix": prefix, "enabled": body.enabled}
    finally:
        conn.close()


@router.delete("/providers/{prefix}", status_code=204)
def remove_provider(prefix: str, request: Request):
    conn = _conn(request)
    try:
        _guard(lambda: store.delete_provider(conn, prefix))
        db.record_audit(conn, "admin", "provider_delete", prefix, "ok")
    finally:
        conn.close()


@router.post("/providers/{prefix}/keys", status_code=201)
def create_key(prefix: str, body: KeyIn, request: Request):
    conn = _conn(request)
    try:
        saved = _guard(lambda: store.add_key(conn, prefix, body.label, body.api_key, body.priority))
        db.record_audit(conn, "admin", "key_add", prefix, "ok", f"id={saved['id']}")  # never the key
        return saved
    finally:
        conn.close()


@router.delete("/providers/{prefix}/keys/{key_id}", status_code=204)
def delete_key(prefix: str, key_id: str, request: Request):
    conn = _conn(request)
    try:
        _guard(lambda: store.remove_key(conn, prefix, key_id))
        db.record_audit(conn, "admin", "key_delete", prefix, "ok", f"id={key_id}")
    finally:
        conn.close()


@router.get("/models/{prefix}/{model:path}/card")
def get_card(prefix: str, model: str, request: Request):
    try:
        return _gateway(request).card_for(f"{prefix}:{model}").as_dict()
    except (store.StoreError, ModelRefError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/models/{prefix}/{model:path}/override")
def put_override(prefix: str, model: str, body: OverrideIn, request: Request):
    conn = _conn(request)
    try:
        _guard(lambda: store.set_override(conn, prefix, model, {k: v for k, v in body.values.items() if v is not None}))
        db.record_audit(conn, "admin", "override_set", f"{prefix}:{model}", "ok")
    finally:
        conn.close()
    return _gateway(request).card_for(f"{prefix}:{model}").as_dict()


@router.post("/chat")
def chat(body: ChatIn, request: Request):
    """Single non-streaming completion. Streaming and agent loops come in P3."""
    try:
        result = _gateway(request).complete(
            body.model, body.messages, session=body.session, max_tokens=body.max_tokens, temperature=body.temperature,
            reasoning_effort=body.reasoning_effort, timeout_s=body.timeout_s,
        )
    except GatewayError as exc:
        code = 502 if exc.status and exc.status >= 500 else (exc.status if exc.status in {401, 402, 403, 429} else 400)
        raise HTTPException(status_code=code, detail=str(exc)) from None
    return {"text": result.text, "model": result.model, "usage": result.usage, "attempts": result.attempts,
            "finish_reason": result.finish_reason, "cost_usd": result.cost_usd, "warnings": result.warnings}
