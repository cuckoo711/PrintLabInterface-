"""Choosing among several API keys for one provider, and what a failure does to a key.

Written from the behaviour described in the reference project's documentation; no code
was copied. Rules:
  * a session keeps the key it started on (provider-side prompt caches are per account),
    unless that key is cooling down or disabled;
  * otherwise the usable key with the lowest priority number;
  * if every key is cooling down, the one that recovers first, so the caller still gets
    the upstream error instead of an invented one;
  * a request moves to another key only when the key itself was at fault.

Failure classification (cooldowns live in memory; only `invalid` is persisted by the caller):
  401                         key rejected          -> disabled as "invalid" until edited
  402, or 429 that says the     allowance used up     -> cool down 30 minutes
    allowance is used up
  403                         forbidden             -> cool down 10 minutes
  other 429                   rate limited          -> Retry-After, else 60 seconds
  anything else               says nothing about the key
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

MINUTE = 60.0
_QUOTA_WORDS = re.compile(r"quota|insufficient|exceeded your current|billing|credit|balance|余额|额度", re.I)


@dataclass
class KeyEntry:
    id: str
    priority: int = 100
    disabled: bool = False
    invalid: bool = False  # persisted by the caller after a 401


@dataclass(frozen=True)
class Fault:
    kind: str  # "invalid" | "quota" | "forbidden" | "rate_limited" | "neutral"
    cooldown_s: float = 0.0


def classify_failure(status: int | None, message: str = "", retry_after: float | None = None) -> Fault:
    if status == 401:
        return Fault("invalid")
    if status == 402:
        return Fault("quota", 30 * MINUTE)
    if status == 429:
        if _QUOTA_WORDS.search(message or ""):
            return Fault("quota", 30 * MINUTE)
        wait = retry_after if retry_after and retry_after > 0 else 60.0
        return Fault("rate_limited", min(wait, 30 * MINUTE))
    if status == 403:
        return Fault("forbidden", 10 * MINUTE)
    return Fault("neutral")


class KeyPool:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, sticky_limit: int = 5000):
        self._clock = clock
        self._lock = threading.Lock()
        self._cooldown_until: dict[tuple[str, str], float] = {}
        self._sticky: dict[tuple[str, str], str] = {}
        self._sticky_limit = sticky_limit

    def _cooling(self, provider: str, key_id: str, now: float) -> float | None:
        until = self._cooldown_until.get((provider, key_id))
        return until if until is not None and until > now else None

    def select(self, provider: str, keys: list[KeyEntry], *, session: str | None = None, exclude: set[str] | None = None) -> KeyEntry | None:
        exclude = exclude or set()
        with self._lock:
            now = self._clock()
            usable = [k for k in keys if not k.disabled and not k.invalid and k.id not in exclude]
            if not usable:
                return None
            ready = [k for k in usable if self._cooling(provider, k.id, now) is None]
            if not ready:
                # Everything is resting: take the one that recovers first.
                return min(usable, key=lambda k: self._cooldown_until.get((provider, k.id), 0.0))
            if session is not None:
                pinned = self._sticky.get((provider, session))
                for key in ready:
                    if key.id == pinned:
                        return key
            choice = min(ready, key=lambda k: (k.priority, k.id))
            if session is not None:
                if len(self._sticky) >= self._sticky_limit:
                    self._sticky.pop(next(iter(self._sticky)))
                self._sticky[(provider, session)] = choice.id
            return choice

    def report_failure(self, provider: str, key: KeyEntry, status: int | None, message: str = "", retry_after: float | None = None) -> Fault:
        fault = classify_failure(status, message, retry_after)
        with self._lock:
            if fault.kind == "invalid":
                key.invalid = True
            elif fault.cooldown_s:
                self._cooldown_until[(provider, key.id)] = self._clock() + fault.cooldown_s
        return fault

    def report_success(self, provider: str, key_id: str) -> None:
        with self._lock:
            self._cooldown_until.pop((provider, key_id), None)

    def cooldown_remaining(self, provider: str, key_id: str) -> float:
        with self._lock:
            until = self._cooling(provider, key_id, self._clock())
            return 0.0 if until is None else until - self._clock()

    def should_try_next_key(self, fault: Fault, *, output_started: bool) -> bool:
        """Switch keys only if the key was at fault and nothing has been streamed yet."""
        return fault.kind != "neutral" and not output_started
