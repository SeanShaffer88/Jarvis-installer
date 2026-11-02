"""Patch ``session_watch`` for Windows pid liveness and pipe-aware steerability."""

from __future__ import annotations

from typing import Any

from . import transport, win32


def pid_alive(pid: Any) -> bool:
    """Use OpenProcess/GetExitCodeProcess instead of Unix ``os.kill(pid, 0)``."""
    return win32.pid_alive(pid)


def _steerable(self: Any) -> bool:
    return transport.transport_exists(getattr(self, "socket_path", None))


def apply(module: Any) -> Any:
    module.pid_alive = pid_alive
    module.transport_exists = transport.transport_exists
    module.RosterEntry.steerable = property(_steerable)
    return module
