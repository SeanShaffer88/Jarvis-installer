"""Windows action executor: argument lists only, no AppleScript or shell strings."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from . import win_paths

log = logging.getLogger("jarvis.windows.actions")

CREATE_NEW_CONSOLE = 0x00000010
_SPAWN = asyncio.create_subprocess_exec


async def _run(argv: list[str], timeout: float = 10.0,
               creationflags: int | None = None) -> tuple[int, str]:
    kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if os.name == "nt" and creationflags:
        kwargs["creationflags"] = creationflags
    try:
        proc = await _SPAWN(*argv, **kwargs)
    except OSError as e:
        log.warning("could not spawn %s: %s", argv[0] if argv else "?", e)
        return -1, str(e)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.communicate()
        except Exception:
            pass
        return -1, "timed out"
    return (proc.returncode if proc.returncode is not None else -1,
            err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err or ""))


async def _mark_terminal_as_jarvis(revert_after: float = 5.0) -> None:
    """No Ocean theme marker on Windows Terminal; cosmetic only."""
    return None


async def _revert_terminal_theme(profile_name: str) -> None:
    return None


async def open_terminal(command: str = "") -> dict:
    wt = win_paths.find_windows_terminal()
    powershell = win_paths.find_powershell()
    if wt and powershell:
        argv = [wt, "new-tab", "--title", "JARVIS", "--", powershell,
                "-NoExit", "-NoProfile"]
        if command:
            argv += ["-Command", str(command)]
        rc, err = await _run(argv, timeout=10.0)
        success = rc == 0
    elif powershell:
        argv = [powershell, "-NoExit", "-NoProfile"]
        if command:
            argv += ["-Command", str(command)]
        rc, err = await _run(argv, timeout=10.0,
                             creationflags=CREATE_NEW_CONSOLE)
        success = rc == 0
    else:
        err = "neither wt.exe nor powershell.exe was found"
        success = False
    if not success:
        log.error("open_terminal failed: %s", err)
    return {"success": success,
            "confirmation": "Terminal is open, sir." if success
            else "I had trouble opening Terminal, sir."}


async def open_browser(url: str, browser: str = "chrome") -> dict:
    wanted = str(browser or "chrome").strip().lower()
    if wanted == "firefox":
        app_name, binary = "Firefox", win_paths.find_firefox()
    else:
        app_name, binary = "Chrome", win_paths.find_chrome()
    if binary is None:
        log.error("%s was not found", app_name)
        return {"success": False,
                "confirmation": f"{app_name} is not installed, sir."}
    # The URL is one argv entry. PowerShell/Start-Process source is not used,
    # so quotes and backslashes in a model-supplied URL cannot become code.
    rc, err = await _run([binary, str(url)], timeout=10.0)
    success = rc == 0
    if not success:
        log.error("open_browser (%s) failed: %s", app_name, err)
    return {"success": success,
            "confirmation": f"Pulled that up in {app_name}, sir." if success
            else f"{app_name} ran into a problem, sir."}


async def open_chrome(url: str) -> dict:
    return await open_browser(url, "chrome")


async def get_chrome_tab_info() -> dict:
    """Windows v1 deliberately returns empty; callers already tolerate it."""
    return {}


def _vscode_command(path: str) -> list[str] | None:
    code = win_paths.find_code()
    if code:
        return [code, str(path)]
    return None


async def open_in_editor(path: str) -> dict:
    argv = _vscode_command(path)
    editor = "VS Code" if argv else "your editor"
    if argv:
        rc, err = await _run(argv, timeout=10.0)
        success = rc == 0
        if not success:
            log.error("open_in_editor failed: %s", err)
    else:
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            log.error("no VS Code and os.startfile is unavailable")
            return {"success": False, "editor": editor,
                    "confirmation": "I couldn't open an editor, sir."}
        try:
            await asyncio.to_thread(startfile, str(path))
            success = True
        except OSError as e:
            log.error("os.startfile failed: %s", e)
            success = False
    return {"success": success, "editor": editor,
            "confirmation": f"Opened that in {editor}, sir." if success
            else f"{editor} wouldn't open that, sir."}


def apply(module: Any) -> Any:
    module._mark_terminal_as_jarvis = _mark_terminal_as_jarvis
    module._revert_terminal_theme = _revert_terminal_theme
    module.open_terminal = open_terminal
    module.open_browser = open_browser
    module.open_chrome = open_chrome
    module.get_chrome_tab_info = get_chrome_tab_info
    module._vscode_command = _vscode_command
    module.open_in_editor = open_in_editor
    return module
