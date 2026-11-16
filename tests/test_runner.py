from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from printlab_interface.adapters.printlab import runner as runner_mod
from printlab_interface.adapters.printlab.policy import PolicyError
from printlab_interface.adapters.printlab.runner import (
    ENV_ALLOW, DirtyTreeError, PrintLabRunner, RunnerError, build_env,
)


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    """A directory that looks enough like PrintLab for the runner's availability check."""
    root = tmp_path / "PrintLab"
    script = runner_mod.cli_script(root)
    script.parent.mkdir(parents=True)
    script.write_text("# stub")
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r: set())
    return root


def make_runner(root, tmp_path, **kw):
    return PrintLabRunner(root, tmp_path / "run", **kw)


def test_refused_command_never_starts_a_process(fake_root, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or FakeProc())
    r = make_runner(fake_root, tmp_path)
    for argv in (["approve", "P1", "J1"], ["submit", "P1", "J1", "--execute"], ["reconcile", "P1"]):
        with pytest.raises(PolicyError):
            r.run(argv, allow_write=True)
    assert called == []


def test_success_parses_json_and_uses_run_dir_not_printlab_root(fake_root, tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return FakeProc(stdout=json.dumps({"ok": True}).encode())

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = make_runner(fake_root, tmp_path).run(["status"])
    assert result.data == {"ok": True}
    assert Path(seen["cwd"]) == tmp_path / "run"
    assert Path(seen["cwd"]) != fake_root and fake_root not in Path(seen["cwd"]).parents


def test_exit_zero_with_empty_output_is_an_error(fake_root, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"", returncode=0))
    with pytest.raises(RunnerError, match="empty output"):
        make_runner(fake_root, tmp_path).run(["status"])


def test_nonzero_exit_reports_stderr(fake_root, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stderr=b'{"error":"boom"}', returncode=2))
    with pytest.raises(RunnerError, match="exited 2"):
        make_runner(fake_root, tmp_path).run(["status"])


def test_non_json_output_is_an_error(fake_root, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"not json"))
    with pytest.raises(RunnerError, match="not JSON"):
        make_runner(fake_root, tmp_path).run(["status"])


def test_oversized_output_is_rejected(fake_root, tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"1" * 5000))
    with pytest.raises(RunnerError, match="exceeded"):
        make_runner(fake_root, tmp_path, max_output_bytes=1024).run(["status"])


def test_timeout_is_reported(fake_root, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RunnerError, match="timed out"):
        make_runner(fake_root, tmp_path, timeout_s=1).run(["status"])


def test_missing_cli_means_offline_not_a_crash(tmp_path):
    r = make_runner(tmp_path / "nowhere", tmp_path)
    assert r.available() is False
    with pytest.raises(RunnerError, match="offline"):
        r.run(["status"])


def test_environment_is_whitelisted_and_has_no_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak-1234567890")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("PLI_ANYTHING", "x")
    env = build_env(tmp_path)
    assert set(env) <= set(ENV_ALLOW) | {"PYTHONUTF8", "PRINTLAB_ROOT"}
    assert "OPENAI_API_KEY" not in env and "HTTPS_PROXY" not in env and "PLI_ANYTHING" not in env
    assert env["PYTHONUTF8"] == "1" and env["PRINTLAB_ROOT"] == str(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows system variables")
def test_whitelist_covers_the_windows_minimum_that_once_caused_empty_output():
    required = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PROGRAMDATA", "COMSPEC", "TEMP"}
    assert required <= set(ENV_ALLOW)
    env = build_env(Path("."))
    assert required <= set(env), f"missing in real environment: {required - set(env)}"


def test_read_call_that_changes_the_tree_is_blocked_and_blocks_later_writes(fake_root, tmp_path, monkeypatch):
    snaps = iter([set(), {"?? stray.txt"}])
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r: next(snaps))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"{}"))
    r = make_runner(fake_root, tmp_path)
    with pytest.raises(DirtyTreeError):
        r.run(["status"])
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r_: set())
    with pytest.raises(DirtyTreeError, match="blocked"):
        r.run(["handoff", "P1"], allow_write=True)


def test_write_call_leaving_untracked_file_blocks_the_next_write(fake_root, tmp_path, monkeypatch):
    snaps = iter([set(), {"?? %SystemDrive%/x.db"}])
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r: next(snaps))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"{}"))
    r = make_runner(fake_root, tmp_path)
    with pytest.raises(DirtyTreeError):
        r.run(["handoff", "P1"], allow_write=True)
    assert r.write_blocked_reason


def test_write_call_touching_only_tracked_files_is_reported_not_blocked(fake_root, tmp_path, monkeypatch):
    snaps = iter([set(), {" M Context/lessons.md"}])
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r: next(snaps))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=b"{}"))
    result = make_runner(fake_root, tmp_path).run(["handoff", "P1"], allow_write=True)
    assert result.tree_changes == [" M Context/lessons.md"]


def test_runner_module_contains_no_shell_true():
    source = Path(runner_mod.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert sys.version_info >= (3, 11)
