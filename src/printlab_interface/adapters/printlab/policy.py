"""Which PrintLab CLI invocations the sidecar may run. Deny by default.

Three tiers:
  * READ   - no state change. Allowed.
  * WRITE  - changes files only through PrintLab's own versioned, idempotent commands.
             Allowed only when the caller asks for write access explicitly.
  * NEVER  - anything that can approve, submit, reconcile, resend, or drive the
             printer or the official Studio. Refused unconditionally, and a NEVER
             entry beats every allow entry. This list is code, not configuration.

Why NEVER is unconditional: approval binds a physical plate-clear confirmation that
software cannot verify, and the H2C firmware already rejects some third-party commands.
"""
from __future__ import annotations

from dataclasses import dataclass

# (command, subcommand or None). None means the command has no subcommand tier.
READ: frozenset[tuple[str, str | None]] = frozenset(
    {
        ("status", None),
        ("context", None),
        ("materials", None),
        ("doctor", None),
        ("dispatch-plan", None),
        ("confirmation", None),
        ("workspace", "show"),
        ("workspace", "profiles"),
        ("workspace", "connection"),
        ("shop", "list"),
        ("prepared", "list"),
        ("onboarding", "status"),
        ("constraints", "show"),
        ("design-check", None),
        ("inspect-project", None),
        ("inspect-slice", None),
        ("native-inspect", None),
    }
)

WRITE: frozenset[tuple[str, str | None]] = frozenset(
    {
        ("new", None),
        ("build", None),
        ("export-project", None),
        ("preview", None),
        ("slice", None),
        ("handoff", None),
        ("review", None),
        ("record-confirmation", None),
        ("workspace", "note"),
        ("workspace", "device"),
        ("constraints", "capture"),
        ("taste", "record"),
        ("shop", "confirm"),
        ("shop", "sync"),
        ("shop", "stock"),
        ("material-intake", None),
        # `history` refreshes a cache file under PrintLab/Library/References/PrintHistory.
        # It never touches the printer, but it is a write, so it is not in READ.
        ("history", None),
    }
)

# Commands whose every subcommand is forbidden.
NEVER_COMMANDS: frozenset[str] = frozenset(
    {
        "approve",
        "submit",
        "reconcile",
        "retry",
        "register-cancel",
        "studio-copy",
        "studio-bridge",
        "native-check",  # reads live X2D telemetry and talks to the device path
        "history-recover",
        "image3d",
        "publish",
    }
)
# Specific (command, subcommand) pairs forbidden even though the command is otherwise usable.
NEVER_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("prepared", "register"),
        ("prepared", "check"),
        ("workspace", "connect"),
        ("workspace", "profile"),
        ("shop", "supplier"),
        ("shop", "fulfill"),
        ("onboarding", "host"),
        ("onboarding", "adopt-device"),
        ("onboarding", "answer"),
        ("onboarding", "reserve-role"),
        ("onboarding", "record-role"),
        ("onboarding", "release-role"),
        ("onboarding", "discover"),
    }
)

# HTTP: GET only, and never the prepared-print surface that can start work.
HTTP_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/api/health",
    "/api/overview",
    "/api/device",
    "/api/projects",
    "/api/library",
    "/api/shop",
    "/api/history",
    "/api/onboarding",
    "/api/documents/",
    "/api/files/",
)
HTTP_NEVER_PREFIXES: tuple[str, ...] = ("/api/prepared",)


class PolicyError(PermissionError):
    """Raised before any process or request is started."""


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    tier: str  # "read" | "write" | "never" | "unknown"
    reason: str


def _split(argv: list[str]) -> tuple[str, str | None]:
    if not argv:
        raise PolicyError("empty command")
    command = argv[0]
    if command.startswith("-"):
        raise PolicyError("global options before the command are not allowed")
    sub: str | None = None
    if len(argv) > 1 and not argv[1].startswith("-"):
        sub = argv[1]
    return command, sub


def classify(argv: list[str]) -> Verdict:
    command, sub = _split(argv)
    if command in NEVER_COMMANDS:
        return Verdict(False, "never", f"'{command}' is permanently refused")
    if sub is not None and (command, sub) in NEVER_PAIRS:
        return Verdict(False, "never", f"'{command} {sub}' is permanently refused")
    # Exact (command, subcommand) match first.
    if sub is not None:
        if (command, sub) in READ:
            return Verdict(True, "read", "read-only command")
        if (command, sub) in WRITE:
            return Verdict(True, "write", "file-writing command through PrintLab's own CLI")
    # Commands with no subcommand tier: `sub` is then just a positional argument (e.g. `context P001`).
    if (command, None) in READ:
        return Verdict(True, "read", "read-only command")
    if (command, None) in WRITE:
        return Verdict(True, "write", "file-writing command through PrintLab's own CLI")
    return Verdict(False, "unknown", f"'{command}' is not on the allow list")


def check_cli(argv: list[str], *, allow_write: bool = False) -> Verdict:
    """Return the verdict, raising PolicyError when the call must not run."""
    verdict = classify(argv)
    if not verdict.allowed:
        raise PolicyError(verdict.reason)
    if verdict.tier == "write" and not allow_write:
        raise PolicyError(f"'{argv[0]}' writes files and write access was not requested")
    # No argument may smuggle a dangerous flag. Execution flags are never passed by the sidecar.
    for token in argv[1:]:
        if token in {"--execute", "--send", "--start"}:
            raise PolicyError(f"flag {token} is permanently refused")
    return verdict


def check_http(method: str, path: str) -> None:
    if method.upper() != "GET":
        raise PolicyError(f"HTTP {method.upper()} is refused; the sidecar only reads over HTTP")
    clean = path.split("?", 1)[0]
    if ".." in clean.split("/") or "\\" in clean:
        raise PolicyError("path traversal is refused")
    for prefix in HTTP_NEVER_PREFIXES:
        if clean.startswith(prefix):
            raise PolicyError(f"{prefix} is permanently refused")
    if not any(clean == p.rstrip("/") or clean.startswith(p) for p in HTTP_ALLOWED_PREFIXES):
        raise PolicyError(f"path {clean} is not on the allow list")
