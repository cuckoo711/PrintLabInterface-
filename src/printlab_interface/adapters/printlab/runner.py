"""Run the PrintLab CLI as a child process, safely.

Guarantees, each covered by a test:
  * the policy decides first; a refused call never starts a process;
  * the child gets a whitelisted environment only (no provider keys, no proxies);
  * the child's working directory is the sidecar's own run dir, never PrintLab's tree;
  * time, output size and concurrency are bounded;
  * exit code 0 with empty output is an error, not a success;
  * PrintLab's git status is compared before and after, and any new untracked or
    modified path is reported (and blocks later write calls).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .policy import PolicyError, check_cli

# Windows system variables the shell and Python need. A narrower set was observed to give
# exit 0 with empty output and to create a literal "%SystemDrive%" directory in the cwd.
ENV_ALLOW: tuple[str, ...] = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "ALLUSERSPROFILE",
    "PUBLIC", "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
)
_MAX_CONCURRENT = 2
_slots = threading.BoundedSemaphore(_MAX_CONCURRENT)


class RunnerError(RuntimeError):
    pass


class DirtyTreeError(RunnerError):
    """PrintLab's working tree changed in a way the call did not account for."""


@dataclass
class CliResult:
    argv: list[str]
    tier: str
    exit_code: int
    data: object
    duration_ms: int
    tree_changes: list[str] = field(default_factory=list)


def build_env(root: Path) -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PRINTLAB_ROOT"] = str(root)
    return env


def cli_script(root: Path) -> Path:
    name = "printlab.ps1" if os.name == "nt" else "printlab"
    return root / "Harness" / "bin" / name


def command_line(root: Path, argv: list[str]) -> list[str]:
    script = str(cli_script(root))
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *argv]
    return [script, *argv]


def git_snapshot(root: Path) -> set[str] | None:
    """Paths git reports as changed or untracked, or None when git cannot answer."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True, timeout=30, env=build_env(root), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {entry.decode("utf-8", "replace") for entry in proc.stdout.split(b"\0") if entry}


class PrintLabRunner:
    def __init__(self, root: Path, run_dir: Path, *, timeout_s: int = 60, max_output_bytes: int = 1_000_000):
        self.root = root
        self.run_dir = run_dir
        self.timeout_s = timeout_s
        self.max_output_bytes = max_output_bytes
        self.write_blocked_reason: str | None = None

    def available(self) -> bool:
        return cli_script(self.root).is_file()

    def run(self, argv: list[str], *, allow_write: bool = False) -> CliResult:
        verdict = check_cli(argv, allow_write=allow_write)  # raises PolicyError before any process
        if verdict.tier == "write" and self.write_blocked_reason:
            raise DirtyTreeError(f"write calls are blocked: {self.write_blocked_reason}")
        if not self.available():
            raise RunnerError("PrintLab CLI not found; PrintLab is offline")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        before = git_snapshot(self.root)
        if not _slots.acquire(timeout=self.timeout_s):
            raise RunnerError("too many concurrent PrintLab calls")
        try:
            import time

            started = time.perf_counter()
            try:
                proc = subprocess.run(
                    command_line(self.root, argv),
                    capture_output=True, timeout=self.timeout_s,
                    env=build_env(self.root), cwd=str(self.run_dir), check=False,
                )
            except subprocess.TimeoutExpired:
                raise RunnerError(f"PrintLab call timed out after {self.timeout_s}s") from None
            duration = int((time.perf_counter() - started) * 1000)
        finally:
            _slots.release()

        if len(proc.stdout) > self.max_output_bytes:
            raise RunnerError(f"PrintLab output exceeded {self.max_output_bytes} bytes")
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        err = proc.stderr[:4000].decode("utf-8", errors="replace").strip()

        changes = self._tree_changes(before, verdict.tier)
        if proc.returncode != 0:
            raise RunnerError(f"PrintLab exited {proc.returncode}: {err or out[:400]}")
        if not out:
            raise RunnerError("PrintLab returned exit 0 with empty output; treating as failure")
        try:
            data = json.loads(out)
        except ValueError as exc:
            raise RunnerError(f"PrintLab output is not JSON: {exc}") from None
        return CliResult(list(argv), verdict.tier, proc.returncode, data, duration, changes)

    def _tree_changes(self, before: set[str] | None, tier: str) -> list[str]:
        """Compare git status around the call. A read call must change nothing."""
        after = git_snapshot(self.root)
        if before is None or after is None:
            return []
        added = sorted(after - before)
        if added and tier == "read":
            self.write_blocked_reason = f"a read call changed PrintLab's tree: {added[:5]}"
            raise DirtyTreeError(self.write_blocked_reason)
        if added:
            # A write call may legitimately touch tracked or ignored files; untracked files
            # appearing in git status are the signal that something escaped the data folders.
            untracked = [a for a in added if a.startswith("??")]
            if untracked:
                self.write_blocked_reason = f"a write call left untracked files: {untracked[:5]}"
                raise DirtyTreeError(self.write_blocked_reason)
        return added
