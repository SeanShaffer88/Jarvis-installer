"""Windows preflight: native Claude, credential-file expiry, neutral grants."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from . import claude_launcher, transport

log = logging.getLogger("jarvis.windows.preflight")

CREDENTIAL_FILENAMES = (".credentials.json", "credentials.json")


def _child_env(module: Any) -> dict[str, str]:
    claude_env = getattr(module, "claude_env", None)
    if claude_env is None:
        import importlib
        claude_env = importlib.import_module("claude_env")
    return dict(claude_env.child_env())


def credential_candidates(config_dir: Path, env: Mapping[str, str] | None = None) -> list[Path]:
    source = dict(os.environ)
    if env:
        source.update({str(k): str(v) for k, v in env.items()})
    home = Path(source.get("USERPROFILE") or Path.home())
    config = Path(config_dir)
    roots = [config, home / ".claude",
             Path(source.get("APPDATA") or home / "AppData" / "Roaming") / "Claude Code"]
    out: list[Path] = []
    for root in roots:
        for name in CREDENTIAL_FILENAMES:
            path = root / name
            if path not in out:
                out.append(path)
    return out


def _read_expiry(paths: list[Path]) -> float | None:
    """Read only an expiry timestamp; never log or return token material."""
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        oauth = data.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            continue
        expires = oauth.get("refreshTokenExpiresAt")
        if isinstance(expires, (int, float)) and not isinstance(expires, bool):
            return float(expires) / 1000.0
    return None


def apply(module: Any) -> Any:
    """Patch an imported upstream ``preflight`` module in place."""
    Check = module.Check
    STATUS_OK = module.STATUS_OK
    STATUS_WARN = module.STATUS_WARN
    STATUS_FAIL = module.STATUS_FAIL

    async def read_oauth_refresh_expiry(config_dir: Path,
                                        timeout: float = module.DEFAULT_CHECK_TIMEOUT) -> float | None:
        del timeout  # local file read, no subprocess
        return await asyncio.to_thread(_read_expiry, credential_candidates(config_dir))

    async def check_claude_cli(timeout: float = module.DEFAULT_CHECK_TIMEOUT) -> Any:
        claude = claude_launcher.resolve_claude()
        if claude is None:
            return Check(
                name="claude_cli", status=STATUS_FAIL,
                message="Native claude.exe is not available; npm's claude.cmd shim is not usable.",
                remedy=("Open a terminal and run: winget install Anthropic.ClaudeCode "
                        "— then open a new terminal."))
        rc, stdout, stderr = await module._run_subprocess(claude, "--version", timeout=timeout)
        if rc != 0:
            return Check(name="claude_cli", status=STATUS_WARN,
                         message=f"`claude --version` failed: {(stderr or stdout).strip() or f'exit {rc}'}",
                         remedy="Run `claude --version` yourself to see what's wrong.")
        version = module._parse_version(stdout) or module._parse_version(stderr)
        if version is None:
            return Check(name="claude_cli", status=STATUS_WARN,
                         message=f"Could not parse a version: {stdout.strip()!r}",
                         remedy=f"Confirm Claude Code is {module.MIN_CLAUDE_VERSION_STR} or newer.")
        version_str = ".".join(str(part) for part in version)
        if version < module.MIN_CLAUDE_VERSION:
            return Check(name="claude_cli", status=STATUS_FAIL,
                         message=f"claude {version_str} is older than {module.MIN_CLAUDE_VERSION_STR}.",
                         remedy="Run `winget upgrade Anthropic.ClaudeCode` or `claude update`.")
        return Check(name="claude_cli", status=STATUS_OK,
                     message=f"Native claude {version_str} is available.")

    async def check_claude_login(timeout: float = module.DEFAULT_CHECK_TIMEOUT) -> Any:
        claude = claude_launcher.resolve_claude()
        if claude is None:
            return Check(name="claude_login", status=STATUS_WARN,
                         message="Can't check login: native claude.exe is not available.",
                         remedy="Install native Claude Code, then run `claude` and log in.")
        env = _child_env(module)
        config_dir = module._config_dir_from_env(env)
        where = f"config dir: {config_dir}"
        rc, stdout, stderr = await module._run_subprocess(
            claude, "auth", "status", timeout=timeout, env=env)
        if rc != 0:
            return Check(name="claude_login", status=STATUS_FAIL,
                         message=f"`claude auth status` failed ({where}): {(stderr or stdout).strip() or f'exit {rc}'}",
                         remedy="Run `claude` and log in.")
        try:
            data = json.loads(stdout)
        except (ValueError, TypeError):
            return Check(name="claude_login", status=STATUS_WARN,
                         message=f"Could not parse `claude auth status` output ({where}).",
                         remedy="Run `claude auth status` yourself to confirm you're logged in.")
        if not isinstance(data, dict) or not data.get("loggedIn"):
            return Check(name="claude_login", status=STATUS_FAIL,
                         message=f"Claude Code is not logged in ({where}).",
                         remedy="Run `claude` in a terminal and log in — the voice brain uses your subscription, not an API key.")
        email = data.get("email")
        message = f"Logged in as {email} ({where})." if email else f"Logged in ({where})."
        if data.get("authMethod") == "claude.ai":
            expires_at = await module._read_oauth_refresh_expiry(config_dir, timeout)
            if expires_at is None:
                message += (" Could not independently verify the OAuth refresh-token "
                            "expiry from the Windows credentials file; this is unknown, not a failure.")
            elif expires_at <= time.time():
                when = datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M")
                return Check(name="claude_login", status=STATUS_FAIL,
                             message=(f"Claude Code reports logged in, but its OAuth refresh token "
                                      f"expired on {when} and cannot be refreshed."),
                             remedy="Run `claude` in a terminal and log in again.")
            else:
                message += " OAuth refresh token is current."
        return Check(name="claude_login", status=STATUS_OK, message=message)

    async def check_accessibility(timeout: float = module.DEFAULT_CHECK_TIMEOUT) -> Any:
        del timeout
        return Check(name="accessibility", status=STATUS_OK,
                     message="Not applicable on Windows; v1 alerts and never sends keystrokes.")

    def check_screen_recording_sync() -> Any:
        return Check(name="screen_recording", status=STATUS_OK,
                     message="No Windows Screen Recording grant exists; the blank-frame check still applies.")

    module._read_oauth_refresh_expiry = read_oauth_refresh_expiry
    module._check_claude_cli = check_claude_cli
    module._check_claude_login = check_claude_login
    module._check_accessibility = check_accessibility
    module._check_screen_recording_sync = check_screen_recording_sync
    module._ASYNC_CHECKS = (check_claude_cli, check_claude_login, check_accessibility)
    module._SYNC_CHECKS = tuple(
        check_screen_recording_sync if getattr(fn, "__name__", "") == "_check_screen_recording_sync" else fn
        for fn in module._SYNC_CHECKS
    )
    module.WINDOWS_CREDENTIAL_CANDIDATES = CREDENTIAL_FILENAMES
    return module
