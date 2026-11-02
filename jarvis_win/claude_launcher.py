"""Make every JARVIS child process use native Claude Code on Windows."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping

from . import win_paths

log = logging.getLogger("jarvis.windows.claude")


class ClaudeLaunchError(RuntimeError):
    """Raised rather than letting Windows fail with WinError 193."""


def resolve_claude(explicit: str | os.PathLike[str] | None = None,
                   env: Mapping[str, str] | None = None,
                   finder: Callable[..., str | None] | None = None) -> str | None:
    """Absolute path to native claude.exe, or None. No fallback to 'claude'."""
    find = finder or win_paths.find_claude
    return find(explicit=explicit, env=env)


def looks_like_claude_shim(value: str) -> bool:
    suffix = Path(value).suffix.lower()
    return suffix in {".cmd", ".bat", ".ps1", ".vbs", ".js"}


def ensure_native_claude(command: Iterable[str], *,
                         explicit: str | os.PathLike[str] | None = None,
                         env: Mapping[str, str] | None = None,
                         resolver: Callable[..., str | None] | None = None) -> list[str]:
    """Replace the first argv entry with a proven native claude.exe.

    ``brain.command()`` and ``RunExecutor._command()`` are patched to pass a
    plain ``claude`` token through ``shlex.split`` first, so a Windows path
    containing spaces or backslashes never reaches shlex. This function then
    swaps in the absolute native path.
    """
    argv = list(command)
    if not argv:
        raise ClaudeLaunchError("empty Claude command")
    first = str(argv[0])
    resolve = resolver or resolve_claude
    explicit_path = explicit or (first if Path(first).is_absolute() else None)
    native = resolve(explicit=explicit_path, env=env)
    if native is None:
        if looks_like_claude_shim(first):
            raise ClaudeLaunchError(
                "npm's claude.cmd shim cannot be spawned by asyncio; install "
                "native Claude Code (winget install Anthropic.ClaudeCode)")
        raise ClaudeLaunchError(
            "native claude.exe was not found; install Claude Code's native "
            "Windows build and log in once")
    if looks_like_claude_shim(native):
        raise ClaudeLaunchError(f"refusing non-native Claude shim: {native}")
    argv[0] = native
    return argv


def environment(explicit: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Launcher environment with JARVIS_CLAUDE_PATH pinned to the native .exe."""
    result = dict(os.environ if env is None else env)
    native = resolve_claude(explicit=explicit if explicit else result.get("JARVIS_CLAUDE_PATH"),
                            env=result)
    if native:
        result["JARVIS_CLAUDE_PATH"] = native
    else:
        result.pop("JARVIS_CLAUDE_PATH", None)
    return result
