"""Encrypt-at-rest secret storage.

Windows: DPAPI (CryptProtectData), bound to the current Windows user, so a copied
database cannot be decrypted on another account or machine.
Other platforms: no cipher is bundled, so storing a secret is refused unless the
caller supplies an explicit key via PLI_SECRET_KEY. Plain text is never an option.

Secrets are returned only to code that calls `reveal()`. API responses use `mask()`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys

_PREFIX_DPAPI = "dpapi1:"
_PREFIX_KEYED = "keyed1:"


class SecretError(RuntimeError):
    pass


def mask(secret: str) -> str:
    """Never reveal more than a short prefix; short secrets reveal nothing."""
    if not secret or len(secret) < 12:
        return "***"
    return f"{secret[:3]}***{secret[-2:]}"


# ---- Windows DPAPI ---------------------------------------------------------
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise SecretError("DPAPI operation failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ---- keyed fallback (stdlib only) -----------------------------------------
def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:n]


def _keyed(data: bytes, protect: bool) -> bytes:
    raw = os.environ.get("PLI_SECRET_KEY", "")
    if len(raw) < 16:
        raise SecretError("PLI_SECRET_KEY (16+ characters) is required to store secrets on this platform")
    master = hashlib.sha256(raw.encode()).digest()
    enc_key = hmac.new(master, b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"mac", hashlib.sha256).digest()
    if protect:
        nonce = os.urandom(16)
        body = bytes(a ^ b for a, b in zip(data, _stream(enc_key, nonce, len(data))))
        tag = hmac.new(mac_key, nonce + body, hashlib.sha256).digest()
        return nonce + body + tag
    nonce, body, tag = data[:16], data[16:-32], data[-32:]
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + body, hashlib.sha256).digest()):
        raise SecretError("secret failed integrity check")
    return bytes(a ^ b for a, b in zip(body, _stream(enc_key, nonce, len(body))))


def seal(secret: str) -> str:
    if not secret:
        raise SecretError("empty secret")
    data = secret.encode("utf-8")
    if sys.platform == "win32" and os.environ.get("PLI_SECRET_KEY", "") == "":
        return _PREFIX_DPAPI + base64.b64encode(_dpapi(data, True)).decode("ascii")
    return _PREFIX_KEYED + base64.b64encode(_keyed(data, True)).decode("ascii")


def reveal(sealed: str) -> str:
    if sealed.startswith(_PREFIX_DPAPI):
        if sys.platform != "win32":
            raise SecretError("DPAPI secret cannot be read on this platform")
        return _dpapi(base64.b64decode(sealed[len(_PREFIX_DPAPI):]), False).decode("utf-8")
    if sealed.startswith(_PREFIX_KEYED):
        return _keyed(base64.b64decode(sealed[len(_PREFIX_KEYED):]), False).decode("utf-8")
    raise SecretError("unknown secret format; refusing to treat it as plain text")
