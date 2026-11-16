"""Configuration export for the admin page.

What is in it: providers (prefix, name, kind, base address, on/off), key METADATA (id, label, the short
hint shown in the admin list, priority, flags), model-card overrides, and schedules (including the
stored prompts).

What is never in it: a key in any form. Not the plain text and not the sealed blob either. The sealed
blob only opens for this Windows user on this machine, so it would be useless elsewhere, and a file
that holds it is a file worth stealing. After a restore on another machine, keys are entered again.

There is no import. Restoring by hand from the file is deliberate for now: an import that creates
schedules or providers from a file is another way to switch on unattended spending.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from . import __version__
from .providers import store

FORMAT = 1


def export_config(conn: sqlite3.Connection, schedules: list[dict], *, now: float | None = None) -> dict[str, Any]:
    store.init(conn)
    overrides = [{"prefix": r["prefix"], "model": r["model"], "values": json.loads(r["override_json"])}
                 for r in conn.execute("SELECT prefix, model, override_json FROM model_overrides ORDER BY prefix, model").fetchall()]
    return {
        "format": FORMAT,
        "app_version": __version__,
        "exported_at": time.time() if now is None else now,
        "note": "No API keys are included, in any form. Enter keys again after restoring.",
        "providers": store.list_providers(conn),  # keys appear as id/label/hint/priority/flags only
        "model_overrides": overrides,
        "schedules": [{k: v for k, v in s.items() if k not in {"seen_seq", "errors_in_a_row"}} for s in schedules],
    }
