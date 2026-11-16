"""Persistent provider registry: providers, their sealed keys, and model-card overrides.

API keys are sealed (see secrets.py) before they touch the database and are only
unsealed inside `keys_for_call`. Listings expose masked values only.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from .. import secrets
from .key_pool import KeyEntry
from .model_ref import ModelRefError, validate_prefix

STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    prefix        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    litellm_kind  TEXT NOT NULL,
    api_base      TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_keys (
    id            TEXT PRIMARY KEY,
    prefix        TEXT NOT NULL REFERENCES providers(prefix) ON DELETE CASCADE,
    label         TEXT NOT NULL,
    sealed        TEXT NOT NULL,
    hint          TEXT NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 100,
    disabled      INTEGER NOT NULL DEFAULT 0,
    invalid       INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS model_overrides (
    prefix        TEXT NOT NULL REFERENCES providers(prefix) ON DELETE CASCADE,
    model         TEXT NOT NULL,
    override_json TEXT NOT NULL,
    PRIMARY KEY (prefix, model)
);
"""
# litellm provider families we accept. Anything else is rejected rather than guessed.
KINDS = {"openai", "anthropic", "deepseek", "gemini", "openrouter", "ollama", "openai_compatible"}
MAX_PROVIDERS = 50
MAX_KEYS_PER_PROVIDER = 20


class StoreError(ValueError):
    pass


@dataclass(frozen=True)
class Provider:
    prefix: str
    name: str
    litellm_kind: str
    api_base: str | None
    enabled: bool


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(STORE_SCHEMA)


def _validate_base(url: str | None, kind: str) -> str | None:
    if url is None or url == "":
        if kind == "openai_compatible":
            raise StoreError("openai_compatible providers need an api_base")
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StoreError("api_base must be an http(s) URL")
    if parsed.username or parsed.password:
        raise StoreError("api_base must not embed credentials")
    return url.rstrip("/")


def add_provider(conn: sqlite3.Connection, prefix: str, name: str, kind: str, api_base: str | None = None) -> Provider:
    try:
        validate_prefix(prefix)
    except ModelRefError as exc:
        raise StoreError(str(exc)) from None
    if kind not in KINDS:
        raise StoreError(f"unsupported provider kind; choose one of {sorted(KINDS)}")
    if not name.strip() or len(name) > 100:
        raise StoreError("name must be 1-100 characters")
    base = _validate_base(api_base, kind)
    if conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0] >= MAX_PROVIDERS:
        raise StoreError("too many providers")
    try:
        conn.execute(
            "INSERT INTO providers(prefix,name,litellm_kind,api_base,enabled,created_at) VALUES(?,?,?,?,1,?)",
            (prefix, name.strip(), kind, base, time.time()),
        )
    except sqlite3.IntegrityError:
        raise StoreError(f"prefix '{prefix}' already exists") from None
    return get_provider(conn, prefix)


def get_provider(conn: sqlite3.Connection, prefix: str) -> Provider:
    row = conn.execute("SELECT * FROM providers WHERE prefix=?", (prefix,)).fetchone()
    if row is None:
        raise StoreError(f"unknown provider '{prefix}'")
    return Provider(row["prefix"], row["name"], row["litellm_kind"], row["api_base"], bool(row["enabled"]))


def list_providers(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM providers ORDER BY prefix").fetchall():
        keys = conn.execute("SELECT id,label,hint,priority,disabled,invalid FROM provider_keys WHERE prefix=? ORDER BY priority,id", (row["prefix"],)).fetchall()
        out.append({
            "prefix": row["prefix"], "name": row["name"], "kind": row["litellm_kind"],
            "api_base": row["api_base"], "enabled": bool(row["enabled"]),
            "keys": [{"id": k["id"], "label": k["label"], "hint": k["hint"], "priority": k["priority"],
                      "disabled": bool(k["disabled"]), "invalid": bool(k["invalid"])} for k in keys],
        })
    return out


def set_enabled(conn: sqlite3.Connection, prefix: str, enabled: bool) -> None:
    get_provider(conn, prefix)
    conn.execute("UPDATE providers SET enabled=? WHERE prefix=?", (1 if enabled else 0, prefix))


def delete_provider(conn: sqlite3.Connection, prefix: str) -> None:
    get_provider(conn, prefix)
    conn.execute("DELETE FROM provider_keys WHERE prefix=?", (prefix,))
    conn.execute("DELETE FROM model_overrides WHERE prefix=?", (prefix,))
    conn.execute("DELETE FROM providers WHERE prefix=?", (prefix,))


def add_key(conn: sqlite3.Connection, prefix: str, label: str, api_key: str, priority: int = 100) -> dict:
    get_provider(conn, prefix)
    api_key = (api_key or "").strip()
    if len(api_key) < 8 or any(c.isspace() for c in api_key):
        raise StoreError("api key looks malformed (too short or contains whitespace)")
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 10000:
        raise StoreError("priority must be an integer 0-10000")
    if conn.execute("SELECT COUNT(*) FROM provider_keys WHERE prefix=?", (prefix,)).fetchone()[0] >= MAX_KEYS_PER_PROVIDER:
        raise StoreError("too many keys for this provider")
    key_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO provider_keys(id,prefix,label,sealed,hint,priority,created_at) VALUES(?,?,?,?,?,?,?)",
        (key_id, prefix, (label or "key")[:60], secrets.seal(api_key), secrets.mask(api_key), priority, time.time()),
    )
    return {"id": key_id, "label": (label or "key")[:60], "hint": secrets.mask(api_key), "priority": priority}


def remove_key(conn: sqlite3.Connection, prefix: str, key_id: str) -> None:
    cur = conn.execute("DELETE FROM provider_keys WHERE prefix=? AND id=?", (prefix, key_id))
    if cur.rowcount == 0:
        raise StoreError("unknown key")


def set_key_state(conn: sqlite3.Connection, key_id: str, *, disabled: bool | None = None, invalid: bool | None = None) -> None:
    if disabled is not None:
        conn.execute("UPDATE provider_keys SET disabled=? WHERE id=?", (1 if disabled else 0, key_id))
    if invalid is not None:
        conn.execute("UPDATE provider_keys SET invalid=? WHERE id=?", (1 if invalid else 0, key_id))


def key_entries(conn: sqlite3.Connection, prefix: str) -> list[KeyEntry]:
    rows = conn.execute("SELECT id,priority,disabled,invalid FROM provider_keys WHERE prefix=?", (prefix,)).fetchall()
    return [KeyEntry(r["id"], r["priority"], bool(r["disabled"]), bool(r["invalid"])) for r in rows]


def reveal_key(conn: sqlite3.Connection, key_id: str) -> str:
    """The only function that returns a plaintext key. Callers must not log the result."""
    row = conn.execute("SELECT sealed FROM provider_keys WHERE id=?", (key_id,)).fetchone()
    if row is None:
        raise StoreError("unknown key")
    return secrets.reveal(row["sealed"])


def get_override(conn: sqlite3.Connection, prefix: str, model: str) -> dict:
    row = conn.execute("SELECT override_json FROM model_overrides WHERE prefix=? AND model=?", (prefix, model)).fetchone()
    return json.loads(row["override_json"]) if row else {}


def set_override(conn: sqlite3.Connection, prefix: str, model: str, override: dict) -> None:
    from .model_card import FIELDS

    get_provider(conn, prefix)
    unknown = set(override) - set(FIELDS)
    if unknown:
        raise StoreError(f"unknown model-card fields: {sorted(unknown)}")
    conn.execute(
        "INSERT INTO model_overrides(prefix,model,override_json) VALUES(?,?,?) "
        "ON CONFLICT(prefix,model) DO UPDATE SET override_json=excluded.override_json",
        (prefix, model, json.dumps(override, sort_keys=True)),
    )
