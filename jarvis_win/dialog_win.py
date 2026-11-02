"""Windows v1 dialog patch: exact identity proof, human hand-off, no keystrokes.

Phase 4a is the whole implementation. The closed key vocabulary is inherited
unchanged from upstream. A synthetic ``/dev/ttywin<hwnd>`` identity lets the
existing server validation and spoken hand-off flow run, but ``answer()``
always returns ``not_found`` after re-checking ownership. There is no
SendInput call, no free text, and no front-window fallback.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import win32

log = logging.getLogger("jarvis.windows.dialog")

TOKEN_RE = re.compile(r"^/dev/ttywin([0-9a-f]+)$")
TOKEN_TTL_SEC = 300.0
SEND_KEYS_ENABLED = False

# token -> (session pid, hwnd, monotonic timestamp)
_TOKENS: dict[str, tuple[int, int, float]] = {}


def identity_token(hwnd: int) -> str:
    """An opaque identity that upstream ``normalize_tty`` already accepts."""
    return f"/dev/ttywin{int(hwnd):x}"


def hwnd_from_token(token: str | None) -> int | None:
    match = TOKEN_RE.fullmatch(str(token or "").strip())
    return int(match.group(1), 16) if match else None


def _remember(pid: int, window: win32.SessionWindow) -> str:
    now = time.monotonic()
    for key, (_pid, _hwnd, created) in list(_TOKENS.items()):
        if now - created > TOKEN_TTL_SEC:
            _TOKENS.pop(key, None)
    token = identity_token(window.hwnd)
    _TOKENS[token] = (int(pid), int(window.hwnd), now)
    return token


def _lookup(token: str) -> tuple[int, int] | None:
    now = time.monotonic()
    entry = _TOKENS.get(token)
    if not entry:
        return None
    pid, hwnd, created = entry
    if now - created > TOKEN_TTL_SEC:
        _TOKENS.pop(token, None)
        return None
    return pid, hwnd


def reset_state() -> None:
    """Test helper and defence against stale identity tokens."""
    _TOKENS.clear()


def apply(module: Any, *,
          probe: Callable[..., win32.SessionWindow | None] | None = None) -> Any:
    """Patch an already-imported upstream ``dialog`` module in place."""
    find_window = probe or win32.find_session_window
    reset_state()

    def tty_for_pid(pid: Any) -> str | None:
        window = find_window(pid)
        if window is None:
            return None
        return _remember(int(pid), window)

    async def tty_for_pid_async(pid: Any) -> str | None:
        return await asyncio.to_thread(module.tty_for_pid, pid)

    async def find_terminal_tab(tty: str | None):
        want = module.normalize_tty(tty)
        if hwnd_from_token(want) is None:
            return None
        entry = _lookup(want or "")
        if entry is None:
            return None
        pid, hwnd = entry
        window = find_window(pid)
        # Ownership is re-proved at use time; a reused pid or moved window
        # must not inherit the old identity.
        if window is None or window.hwnd != hwnd:
            _TOKENS.pop(want or "", None)
            return None
        return module.TerminalTab(window_id=int(hwnd), tab_index=0, tty=want or "")

    async def answer(pid: int, key: str) -> str:
        normalized = module.normalize_key(key)
        if normalized is None:
            log.warning("refusing a key outside the closed vocabulary")
            return module.BAD_KEY
        try:
            tty = await module.tty_for_pid_async(pid)
            if tty is None:
                return module.NO_TTY
            tab = await module.find_terminal_tab(tty)
            if tab is None:
                return module.NOT_FOUND
            # This is the entire v1 behaviour: JARVIS has already read the
            # session name and key aloud; the human presses the key.
            log.info("Windows v1 display-only hand-off: pid=%s hwnd=%s key=%s",
                     pid, tab.window_id, normalized)
            return module.NOT_FOUND
        except Exception as e:
            log.warning("display-only hand-off failed: %s", e, exc_info=True)
            return module.FAILED

    def disabled_send_script(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("Phase 4b is disabled: no keystroke script is generated")

    module.tty_for_pid = tty_for_pid
    module.tty_for_pid_async = tty_for_pid_async
    module.find_terminal_tab = find_terminal_tab
    module.answer = answer
    module._send_script = disabled_send_script
    module.WINDOWS_SEND_KEYS_ENABLED = SEND_KEYS_ENABLED
    module.probe_session_window = win32.probe_session_window
    return module
