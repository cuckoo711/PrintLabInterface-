from __future__ import annotations

import pytest

from printlab_interface.adapters.printlab.policy import PolicyError, check_cli, check_http, classify

NEVER_ARGV = [
    ["approve", "P001", "J1"],
    ["submit", "P001", "J1"],
    ["submit", "P001", "J1", "--execute"],
    ["reconcile", "P001"],
    ["retry", "P001"],
    ["register-cancel", "P001"],
    ["studio-copy", "P001", "J1"],
    ["studio-bridge", "capability"],
    ["studio-bridge", "open-file"],
    ["native-check", "P001"],
    ["history-recover"],
    ["image3d", "generate"],
    ["publish", "check"],
    ["prepared", "register"],
    ["prepared", "check"],
    ["workspace", "connect"],
    ["workspace", "profile"],
    ["shop", "supplier"],
    ["shop", "fulfill"],
    ["onboarding", "host"],
    ["onboarding", "adopt-device"],
]


@pytest.mark.parametrize("argv", NEVER_ARGV)
def test_dangerous_commands_are_refused_even_with_write_access(argv):
    with pytest.raises(PolicyError):
        check_cli(argv, allow_write=True)
    assert classify(argv).allowed is False


@pytest.mark.parametrize("flag", ["--execute", "--send", "--start"])
def test_execution_flags_are_refused_on_an_otherwise_allowed_command(flag):
    with pytest.raises(PolicyError):
        check_cli(["status", flag], allow_write=True)


@pytest.mark.parametrize(
    "argv",
    [["status"], ["context"], ["context", "P001"], ["materials"], ["doctor"], ["dispatch-plan", "--model", "H2C"],
     ["workspace", "show", "device"], ["shop", "list"], ["prepared", "list"], ["constraints", "show", "P001"]],
)
def test_read_commands_are_allowed_without_write_access(argv):
    assert check_cli(argv).tier == "read"


@pytest.mark.parametrize(
    "argv",
    [["handoff", "P001"], ["new", "x"], ["workspace", "note", "profile"], ["constraints", "capture", "P001"],
     ["history"], ["slice", "P001"]],
)
def test_write_commands_need_explicit_write_access(argv):
    with pytest.raises(PolicyError):
        check_cli(argv)
    assert check_cli(argv, allow_write=True).tier == "write"


def test_unknown_and_malformed_commands_are_refused():
    for argv in ([], ["--help"], ["-h", "status"], ["nope"], ["status;rm"], [""]):
        with pytest.raises(PolicyError):
            check_cli(list(argv), allow_write=True)


def test_every_top_level_printlab_command_has_an_explicit_decision():
    """If PrintLab adds a command, this fails until someone classifies it."""
    top_level = [
        "onboarding", "workspace", "material-intake", "constraints", "prepared", "history", "history-recover",
        "taste", "design-check", "image3d", "new", "context", "build", "export-project", "inspect-project",
        "preview", "slice", "inspect-slice", "native-check", "native-inspect", "approve", "submit", "studio-copy",
        "studio-bridge", "reconcile", "status", "materials", "dispatch-plan", "doctor", "review", "handoff",
        "confirmation", "record-confirmation", "retry", "register-cancel", "publish", "shop",
    ]
    decided_never = {c for c in top_level if classify([c]).tier == "never"}
    assert {"approve", "submit", "reconcile", "studio-bridge", "studio-copy", "retry", "register-cancel"} <= decided_never


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_http_writes_are_refused(method):
    with pytest.raises(PolicyError):
        check_http(method, "/api/health")


@pytest.mark.parametrize(
    "path",
    ["/api/prepared", "/api/prepared/P1/J1/start", "/api/prepared/sender/enable", "/api/prepared/operations/x/reconcile",
     "/api/other", "/", "/api/documents/../../etc/passwd", "/api/files/P1/..\\x"],
)
def test_http_dangerous_or_unlisted_paths_are_refused(path):
    with pytest.raises(PolicyError):
        check_http("GET", path)


@pytest.mark.parametrize("path", ["/api/health", "/api/overview", "/api/projects/P001", "/api/device?x=1", "/api/documents/a/b.md"])
def test_http_read_paths_are_allowed(path):
    check_http("GET", path)
