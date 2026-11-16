"""Make a file readable by the current user only.

`os.chmod(0o600)` does nothing useful on NTFS: the file keeps the ACL it inherited, which on
a data drive normally lets every local user read it. On Windows we replace the ACL with an
explicit one (current user + SYSTEM, inheritance removed). Elsewhere chmod is correct.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path


class PrivateFileError(RuntimeError):
    pass


def _text(data: bytes | None) -> str:
    """Console output is in the system code page (GBK on Chinese Windows), not UTF-8."""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace").strip()


def _current_sid() -> str:
    out = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True, encoding="ascii", errors="replace", timeout=15)
    return next(csv.reader(out.splitlines()))[1]


def make_private(path: Path) -> None:
    path = Path(path)
    if sys.platform != "win32":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    sid = _current_sid()
    flags = "OICI" if path.is_dir() else ""
    sddl = f"D:P(A;{flags};FA;;;{sid})(A;{flags};FA;;;SY)"
    script = (
        '$ErrorActionPreference="Stop"; '
        "$item = Get-Item -LiteralPath $env:PLI_PRIVATE_PATH -Force; "
        "$acl = if ($item.PSIsContainer) { New-Object System.Security.AccessControl.DirectorySecurity } "
        "else { New-Object System.Security.AccessControl.FileSecurity }; "
        "$acl.SetSecurityDescriptorSddlForm($env:PLI_PRIVATE_SDDL, [System.Security.AccessControl.AccessControlSections]::Access); "
        # Set-Acl also writes audit rules and needs SeSecurityPrivilege, which ordinary accounts lack.
        # The .NET overloads below change the access rules only.
        "if ($item.PSIsContainer) { [System.IO.Directory]::SetAccessControl($env:PLI_PRIVATE_PATH, $acl) } "
        "else { [System.IO.File]::SetAccessControl($env:PLI_PRIVATE_PATH, $acl) }"
    )
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
                                                                "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PSMODULEPATH"}}
    env["PLI_PRIVATE_PATH"] = str(path.resolve())
    env["PLI_PRIVATE_SDDL"] = sddl
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, env=env, timeout=30)
    if proc.returncode != 0:
        raise PrivateFileError(f"could not restrict {path.name}: {_text(proc.stderr)[:200]}")


def readers_of(path: Path) -> list[str]:
    """Identities that can read the file (Windows only); used by tests and diagnostics."""
    if sys.platform != "win32":
        return []
    script = "(Get-Acl -LiteralPath $env:PLI_PRIVATE_PATH).Access | ForEach-Object { $_.IdentityReference.Value }"
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "PSMODULEPATH"}}
    env["PLI_PRIVATE_PATH"] = str(Path(path).resolve())
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, env=env, timeout=30)
    return [line.strip() for line in _text(out.stdout).splitlines() if line.strip()]
