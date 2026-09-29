"""Configuration helpers that keep process environment variables authoritative."""
from __future__ import annotations

import os
import sys


def environment_value(name: str) -> str | None:
    """Read a configured value without serialising or logging it.

    A fresh Windows process normally receives user environment values from its
    launcher.  IDE launchers can retain an older environment block, so use the
    persisted per-user value only as a fallback.  Explicit process settings
    always win and non-Windows deployments remain environment-only.
    """
    value = os.getenv(name)
    if value or sys.platform != "win32":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) and value else None
    except (FileNotFoundError, OSError):
        return None
