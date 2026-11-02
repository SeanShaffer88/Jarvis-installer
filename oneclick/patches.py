"""One-click-mode patches applied to already-imported upstream modules.

The existing Windows overlay is kept intact for the Inno Setup path. These
extra in-memory patches make the frozen GUI path avoid every user-facing
terminal, editor, shell, and restart console.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from . import win

log = logging.getLogger("jarvis.oneclick.patches")


def apply_actions(module: Any, *, find_chrome=None, spawn=None) -> Any:
    """No Terminal, no VS Code, no Git Bash; Chrome is the only visible app."""
    chrome_finder = find_chrome or win.find_chrome
    spawner = spawn or win.spawn_hidden

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def open_terminal(command: str = "") -> dict:
        del command
        return {"success": False,
                "confirmation": "Terminal windows are disabled in one-click mode, sir."}

    async def open_in_editor(path: str) -> dict:
        del path
        return {"success": False, "editor": "none",
                "confirmation": "Editors are disabled in one-click mode, sir."}

    async def open_browser(url: str, browser: str = "chrome") -> dict:
        chrome = chrome_finder()
        if not chrome:
            return {"success": False,
                    "confirmation": "Chrome is not installed, sir."}
        try:
            spawner([chrome, str(url)])
            return {"success": True,
                    "confirmation": "Pulled that up in Chrome, sir."}
        except OSError as exc:
            log.warning("could not open Chrome: %s", exc)
            return {"success": False,
                    "confirmation": "Chrome ran into a problem, sir."}

    async def open_chrome(url: str) -> dict:
        return await open_browser(url, "chrome")

    async def get_chrome_tab_info() -> dict:
        return {}

    def no_vscode(path: str) -> None:
        del path
        return None

    module._mark_terminal_as_jarvis = _noop
    module._revert_terminal_theme = _noop
    module.open_terminal = open_terminal
    module.open_in_editor = open_in_editor
    module.open_browser = open_browser
    module.open_chrome = open_chrome
    module.get_chrome_tab_info = get_chrome_tab_info
    module._vscode_command = no_vscode
    module._ONECLICK_NO_TERMINAL = True
    return module


def apply_notifier(module: Any, *, spawn=None) -> Any:
    """Fixed toast script, argv-only text, hidden PowerShell helper."""
    from jarvis_win import notifier_win

    spawner = spawn or asyncio.create_subprocess_exec

    def available() -> bool:
        return notifier_win.available()

    async def notify(title: str, message: str, *, subtitle: str = "") -> bool:
        try:
            if not available():
                return False
            argv = notifier_win.command(
                notifier_win._truncate(str(title or ""), 120),
                notifier_win._truncate(str(message or ""), 300),
                notifier_win._truncate(str(subtitle or ""), 120),
            )
            kwargs: dict[str, Any] = {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
            }
            if os.name == "nt":
                kwargs["creationflags"] = win.hidden_creationflags()
                kwargs["startupinfo"] = win.hidden_startupinfo()
            proc = await spawner(*argv, **kwargs)
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.communicate()
                except Exception:
                    pass
                return False
            return proc.returncode == 0
        except Exception as exc:
            log.warning("one-click toast failed: %s", exc)
            return False

    module.available = available
    module.notify = notify
    module._ONECLICK_HIDDEN_TOAST = True
    return module


def _gui_words(text: str) -> str:
    replacements = (
        ("Open a terminal and run: winget install Anthropic.ClaudeCode — then open a new terminal.",
         "JARVIS Setup installs native Claude Code for you."),
        ("Run `claude` in a terminal and log in.",
         "Use the JARVIS sign-in button to open your browser."),
        ("Run `claude` and log in.", "Use the JARVIS sign-in button."),
        ("terminal", "setup window"),
        ("Terminal", "setup window"),
        ("PowerShell", "hidden helper"),
        ("VS Code", "editor"),
        ("Git Bash", "command window"),
        ("winget", "JARVIS Setup"),
        ("`claude`", "Claude Code"),
    )
    result = str(text or "")
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def _rewrite_check(check: Any) -> Any:
    message = _gui_words(str(getattr(check, "message", "")))
    remedy = _gui_words(str(getattr(check, "remedy", "")))
    try:
        check.message = message
        check.remedy = remedy
        return check
    except Exception:
        pass
    if dataclasses.is_dataclass(check):
        try:
            return dataclasses.replace(check, message=message, remedy=remedy)
        except Exception:
            pass
    clone = copy.copy(check)
    try:
        clone.message = message
        clone.remedy = remedy
    except Exception:
        pass
    return clone


def apply_preflight(module: Any) -> Any:
    """Remove terminal/CLI instructions from first-run check wording."""
    async_checks: list[Any] = []
    for original in tuple(getattr(module, "_ASYNC_CHECKS", ())):
        async def wrapped(*args: Any, _fn=original, **kwargs: Any) -> Any:
            return _rewrite_check(await _fn(*args, **kwargs))
        async_checks.append(wrapped)
    module._ASYNC_CHECKS = tuple(async_checks)
    module._ONECLICK_PLAIN_WORDS = True
    return module


def apply_server(module: Any, *, exe: str | None = None, spawn=None) -> Any:
    """Make MCP/restart use this same hidden .exe instead of python server.py."""
    target_exe = exe or sys.executable
    spawner = spawn or win.spawn_hidden
    original_mcp = module._write_mcp_config

    def write_mcp_config(home: Path) -> Path:
        path = original_mcp(home)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers")
            reserved = getattr(module, "RESERVED_SERVER_NAME", "jarvis")
            if isinstance(servers, dict) and isinstance(servers.get(reserved), dict):
                servers[reserved]["command"] = target_exe
                servers[reserved]["args"] = ["--mcp"]
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
        except (OSError, ValueError, TypeError) as exc:
            log.warning("could not rewrite frozen MCP config: %s", exc)
        return path

    async def api_restart() -> dict:
        async def restart_later() -> None:
            await asyncio.sleep(2)
            spawner([target_exe, "--server"],
                    env=dict(os.environ))
            os._exit(0)
        asyncio.create_task(restart_later())
        return {"status": "restarting"}

    module._write_mcp_config = write_mcp_config
    module.api_restart = api_restart
    module._ONECLICK_FROZEN_SERVER = True
    return module


def apply_all(*, exe: str | None = None,
              modules: dict[str, ModuleType] | None = None,
              spawn=None) -> None:
    source = sys.modules if modules is None else modules
    actions = source.get("actions")
    notifier = source.get("notifier")
    preflight = source.get("preflight")
    server = source.get("server")
    if actions is not None:
        apply_actions(actions, spawn=spawn)
    if notifier is not None:
        apply_notifier(notifier, spawn=spawn)
    if preflight is not None:
        apply_preflight(preflight)
    if server is not None:
        apply_server(server, exe=exe, spawn=spawn)
