"""Runtime settings for the sidecar.

Every value has a default so the service starts with no configuration at all.
PrintLab is optional: if its root is missing the adapter reports "offline".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRINTLAB_ROOT = REPO_ROOT.parent / "PrintLab"


def _int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8019
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    printlab_root: Path | None = field(default_factory=lambda: DEFAULT_PRINTLAB_ROOT)
    printlab_url: str = "http://127.0.0.1:8018"
    cli_timeout_s: int = 60
    cli_max_output_bytes: int = 1_000_000
    http_timeout_s: float = 5.0
    # Extra Host header values to accept. Empty in production. Only test fixtures set it,
    # because Starlette's test client sends "Host: testserver".
    extra_hosts: frozenset[str] = frozenset()

    agents_dir: Path = field(default_factory=lambda: REPO_ROOT / "config" / "agents")
    workflows_dir: Path = field(default_factory=lambda: REPO_ROOT / "config" / "workflows")

    @property
    def run_dir(self) -> Path:
        """Working directory for child processes. Never PrintLab's own tree."""
        return self.data_dir / "run"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "interface.db"


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Build settings from the environment. Loopback only: any other host is refused."""
    source = os.environ if env is None else env
    previous = dict(os.environ)
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        host = source.get("PLI_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("PLI_HOST must be a loopback address; the service has no authentication yet")
        root_raw = source.get("PLI_PRINTLAB_ROOT")
        root: Path | None
        if root_raw is None:
            root = DEFAULT_PRINTLAB_ROOT
        elif root_raw.strip() == "":
            root = None  # explicit opt-out: run without PrintLab
        else:
            root = Path(root_raw).expanduser().resolve()
        data_raw = source.get("PLI_DATA_DIR")
        return Settings(
            host=host,
            port=_int("PLI_PORT", 8019, 1, 65535),
            data_dir=Path(data_raw).expanduser().resolve() if data_raw else REPO_ROOT / "data",
            printlab_root=root,
            printlab_url=source.get("PLI_PRINTLAB_URL", "http://127.0.0.1:8018").rstrip("/"),
            cli_timeout_s=_int("PLI_CLI_TIMEOUT_S", 60, 1, 600),
            cli_max_output_bytes=_int("PLI_CLI_MAX_OUTPUT_BYTES", 1_000_000, 1024, 50_000_000),
        )
    finally:
        if env is not None:
            os.environ.clear()
            os.environ.update(previous)


def optional_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
