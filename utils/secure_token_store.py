# -*- coding: utf-8 -*-
"""Token protection helpers.

On Windows this uses DPAPI, so encrypted tokens can only be decrypted by the
same Windows user account. If DPAPI is unavailable, callers get the original
value back so development and tests keep working.
"""

from __future__ import annotations

import base64


DPAPI_PREFIX = "dpapi:"


def is_protected_token(value: str) -> bool:
    return isinstance(value, str) and value.startswith(DPAPI_PREFIX)


def protect_token(token: str) -> str:
    if not token or is_protected_token(token):
        return token or ""
    try:
        import win32crypt

        encrypted = win32crypt.CryptProtectData(
            token.encode("utf-8"),
            "wuthering-waves-scancer-token",
            None,
            None,
            None,
            0,
        )
        return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
    except Exception:
        return token


def unprotect_token(value: str) -> str:
    if not value:
        return ""
    if not is_protected_token(value):
        return value
    try:
        import win32crypt

        encrypted = base64.b64decode(value[len(DPAPI_PREFIX):])
        decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
        return decrypted.decode("utf-8")
    except Exception:
        return ""
