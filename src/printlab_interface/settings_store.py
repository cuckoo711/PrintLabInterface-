"""A few settings the person can change from the admin page, kept in the sidecar's own database.

Right now there is one: the default model. It is used when neither the message nor the role file names a model, so a
plain chat works without typing "prefix:model" every time. Priority everywhere: what was typed for this run, then the
role file, then this default. The value is only ever a model reference such as ``mimo:mimo-v2.6-flash``; it is checked
against the provider list when it is saved, so a typo is refused instead of failing on the first message.
"""
from __future__ import annotations

import sqlite3

from .providers import store
from .providers.model_ref import ModelRefError, parse

DEFAULT_MODEL_KEY = "default_model"


class SettingError(ValueError):
    pass


def get_default_model(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (DEFAULT_MODEL_KEY,)).fetchone()
    return row["value"] if row else ""


def set_default_model(conn: sqlite3.Connection, value: str) -> str:
    """Save (or, with an empty value, clear) the default model. Returns what is now stored."""
    value = (value or "").strip()
    if value == "":
        conn.execute("DELETE FROM meta WHERE key = ?", (DEFAULT_MODEL_KEY,))
        return ""
    try:
        ref = parse(value)
    except ModelRefError as exc:
        raise SettingError(str(exc)) from None
    store.init(conn)
    known = {p["prefix"]: p for p in store.list_providers(conn)}
    if ref.prefix not in known:
        raise SettingError(f"没有叫 {ref.prefix!r} 的供应商；已有：{', '.join(sorted(known)) or '（还没有）'}")
    if not known[ref.prefix]["enabled"]:
        raise SettingError(f"供应商 {ref.prefix!r} 目前是停用的")
    stored = f"{ref.prefix}:{ref.model}"
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (DEFAULT_MODEL_KEY, stored))
    return stored
