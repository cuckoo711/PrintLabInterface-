"""The only module the rest of the sidecar uses to reach PrintLab.

PrintLab is optional. Every method returns a structured answer even when PrintLab is
missing, stopped, or an unexpected version, so the sidecar always starts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ...config import Settings
from .http import HttpUnavailable, PrintLabHttp
from .policy import PolicyError
from .runner import PrintLabRunner, RunnerError


@dataclass
class Capabilities:
    cli: bool = False
    http: bool = False
    version: str | None = None
    features: list[str] = field(default_factory=list)
    root: str | None = None
    reason: str | None = None

    @property
    def online(self) -> bool:
        return self.cli or self.http


class PrintLabAdapter:
    def __init__(self, settings: Settings, *, http: PrintLabHttp | None = None, runner: PrintLabRunner | None = None):
        self.settings = settings
        self.runner: PrintLabRunner | None = runner
        if runner is None and settings.printlab_root is not None:
            self.runner = PrintLabRunner(
                Path(settings.printlab_root), settings.run_dir,
                timeout_s=settings.cli_timeout_s, max_output_bytes=settings.cli_max_output_bytes,
            )
        self.http = http or PrintLabHttp(settings.printlab_url, timeout_s=settings.http_timeout_s)

    def capabilities(self) -> Capabilities:
        caps = Capabilities(root=str(self.settings.printlab_root) if self.settings.printlab_root else None)
        reasons: list[str] = []
        if self.settings.printlab_root is None:
            reasons.append("PrintLab root not configured")
        elif self.runner is None or not self.runner.available():
            reasons.append("PrintLab CLI not found")
        else:
            caps.cli = True
        try:
            health = self.http.get("/api/health")
            if isinstance(health, dict) and health.get("ok") is True:
                caps.http = True
                caps.version = str(health.get("version")) if health.get("version") is not None else None
                features = health.get("features")
                caps.features = [str(f) for f in features] if isinstance(features, list) else []
            else:
                reasons.append("PrintLab health check did not report ok")
        except HttpUnavailable as exc:
            reasons.append(str(exc))
        caps.reason = "; ".join(reasons) if reasons else None
        return caps

    def read_status(self) -> dict:
        """Best effort status: HTTP first (cheap), then the CLI. Never raises."""
        try:
            data = self.http.get("/api/overview")
            return {"source": "http", "online": True, "data": data}
        except HttpUnavailable:
            pass
        if self.runner is not None and self.runner.available():
            try:
                result = self.runner.run(["status"])
                return {"source": "cli", "online": True, "data": result.data, "duration_ms": result.duration_ms}
            except (RunnerError, PolicyError) as exc:
                return {"source": "cli", "online": False, "error": str(exc)}
        return {"source": None, "online": False, "error": "PrintLab is not available"}

    def describe(self) -> dict:
        caps = self.capabilities()
        return {**asdict(caps), "online": caps.online}

    def close(self) -> None:
        self.http.close()
