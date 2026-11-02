"""Windows toast notifier with argv-only untrusted text.

The PowerShell script is fixed on disk. Title, message, and subtitle from a
Claude Code transcript are passed as separate argv strings and assigned via
XmlDocument ``InnerText`` — never spliced into script or XML source.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import APP_USER_MODEL_ID, win_paths

log = logging.getLogger("jarvis.windows.notifier")
TOAST_SCRIPT = Path(__file__).with_name("ShowToast.ps1")
_APP_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Injectable process boundary for tests.
_SPAWN = asyncio.create_subprocess_exec


def app_id() -> str:
    value = str(os.environ.get("JARVIS_TOAST_APP_ID") or APP_USER_MODEL_ID)
    return value if _APP_ID_RE.fullmatch(value) else APP_USER_MODEL_ID


def available() -> bool:
    return (sys.platform == "win32"
            and win_paths.find_powershell() is not None
            and TOAST_SCRIPT.is_file())


def command(title: str, message: str, subtitle: str = "") -> list[str]:
    powershell = win_paths.find_powershell()
    if powershell is None:
        raise OSError("powershell.exe not found")
    # No -Command, no shell string, and no untrusted text in the script path.
    return [
        powershell,
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(TOAST_SCRIPT),
        "-AppId", app_id(),
        "-Title", str(title or ""),
        "-Message", str(message or ""),
        "-Subtitle", str(subtitle or ""),
    ]


async def notify(title: str, message: str, *, subtitle: str = "") -> bool:
    try:
        if not available():
            log.warning("Windows toast unavailable")
            return False
        safe_title = _truncate(str(title or ""), 120)
        safe_message = _truncate(str(message or ""), 300)
        safe_subtitle = _truncate(str(subtitle or ""), 120)
        argv = command(safe_title, safe_message, safe_subtitle)
        try:
            proc = await _SPAWN(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            log.warning("could not spawn toast helper: %s", e)
            return False
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            log.warning("toast helper timed out")
            return False
        if proc.returncode != 0:
            # Deliberately do not log stderr: it can echo untrusted toast text.
            log.warning("toast helper exited %s", proc.returncode)
            return False
        return True
    except Exception as e:
        log.warning("unexpected toast failure: %s", e)
        return False


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def apply(module: Any) -> Any:
    module.available = available
    module.notify = notify
    module._NOTIFY_SCRIPT = "# Windows toast: fixed ShowToast.ps1, values via argv only\n"
    module.WINDOWS_TOAST_APP_ID = app_id()
    return module
