from __future__ import annotations

import sys

import pytest

from printlab_interface import fsprivate, security

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS ACL behaviour")

BROAD = {"BUILTIN\\Users", "NT AUTHORITY\\Authenticated Users", "Everyone", "BUILTIN\\Administrators"}


def test_make_private_removes_broad_groups_and_keeps_the_owner(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("x")
    assert BROAD & set(fsprivate.readers_of(f)), "precondition: temp files normally inherit broad access"
    fsprivate.make_private(f)
    readers = set(fsprivate.readers_of(f))
    assert not (BROAD & readers), readers
    assert any(r.lower().endswith("\\" + __import__("os").environ.get("USERNAME", "").lower()) for r in readers), readers
    assert f.read_text() == "x"  # the owner can still read it


def test_token_file_is_private_from_the_first_byte_and_is_repaired_if_it_was_not(tmp_path):
    token = security.load_or_create_token(tmp_path)
    path = tmp_path / security.TOKEN_FILE
    assert not (BROAD & set(fsprivate.readers_of(path)))
    assert path.read_text().strip() == token
    # Simulate an older token that was written with inherited (broad) permissions.
    import subprocess
    subprocess.run(["icacls", str(path), "/reset"], capture_output=True, timeout=30)
    assert BROAD & set(fsprivate.readers_of(path))
    assert security.load_or_create_token(tmp_path) == token
    assert not (BROAD & set(fsprivate.readers_of(path)))


def test_make_private_failure_is_reported_not_swallowed(tmp_path):
    with pytest.raises(Exception):
        fsprivate.make_private(tmp_path / "does-not-exist.txt")
