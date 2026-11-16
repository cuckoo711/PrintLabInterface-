"""Log and audit redaction. Applied before anything is written or returned."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    # Provider and Bambuddy style keys
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bbb_[A-Za-z0-9_\-]{8,}"), "bb_***"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.I), "Bearer ***"),
    # key=value / "key": "value" for sensitive names
    (
        re.compile(
            r"(?i)(\"?(?:api[_-]?key|access[_-]?code|password|passwd|secret|token|authorization)\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}]+)"
        ),
        r"\1***",
    ),
    # Private LAN addresses are device identifiers, not secrets, but keep them out of shared logs.
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "192.168.*.*"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - a logging filter must never break the caller
            pass
        return True


def install(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in target.filters):
        target.addFilter(RedactingFilter())
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
