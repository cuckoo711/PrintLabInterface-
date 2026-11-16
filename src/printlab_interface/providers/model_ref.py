"""`prefix:model` identifiers, the way a model is named everywhere in the sidecar.

The prefix names a provider instance the user configured (for example `deepseek`),
the rest is the upstream model id. Only the first colon splits, because upstream ids
may contain colons themselves (for example `ollama` tags).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ModelRefError(ValueError):
    pass


@dataclass(frozen=True)
class ModelRef:
    prefix: str
    model: str

    def __str__(self) -> str:
        return f"{self.prefix}:{self.model}"


def validate_prefix(prefix: str) -> str:
    if not _PREFIX.fullmatch(prefix or ""):
        raise ModelRefError("provider prefix must be 1-32 chars: lowercase letters, digits, '-' or '_', starting with a letter")
    return prefix


def parse(value: str) -> ModelRef:
    if not isinstance(value, str) or ":" not in value:
        raise ModelRefError("model must look like 'prefix:model'")
    prefix, model = value.split(":", 1)
    validate_prefix(prefix)
    if not model.strip() or len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ModelRefError("model id is empty, too long or contains control characters")
    return ModelRef(prefix, model.strip())
