"""Read-only HTTP client for the PrintLab workbench (GET only, allow-listed paths)."""
from __future__ import annotations

import httpx

from .policy import check_http

_MAX_BODY_BYTES = 5_000_000


class HttpUnavailable(RuntimeError):
    """PrintLab is not reachable or answered with something unusable."""


class PrintLabHttp:
    def __init__(self, base_url: str, *, timeout_s: float = 5.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout_s, follow_redirects=False, trust_env=False, transport=transport,
        )

    def get(self, path: str) -> object:
        check_http("GET", path)  # raises PolicyError before any request is sent
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise HttpUnavailable(f"PrintLab HTTP unreachable: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise HttpUnavailable(f"PrintLab HTTP {response.status_code} for {path.split('?', 1)[0]}")
        if len(response.content) > _MAX_BODY_BYTES:
            raise HttpUnavailable("PrintLab response too large")
        try:
            return response.json()
        except ValueError:
            raise HttpUnavailable("PrintLab response is not JSON") from None

    def close(self) -> None:
        self._client.close()
