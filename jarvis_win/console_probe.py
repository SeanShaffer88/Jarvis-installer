"""Isolated console-window probe: prints one HWND, or 0.

Run as ``python -I console_probe.py <pid>`` in a short-lived helper process.
``-I`` prevents our sitecustomize import hook from loading. FreeConsole and
AttachConsole are safe here because they affect only this helper, never the
long-lived JARVIS server.
"""

from __future__ import annotations

import ctypes
import sys


def console_window(pid: int) -> int:
    if sys.platform != "win32":
        return 0
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.FreeConsole.argtypes = []
    kernel.FreeConsole.restype = ctypes.c_int
    kernel.AttachConsole.argtypes = [ctypes.c_uint]
    kernel.AttachConsole.restype = ctypes.c_int
    kernel.GetConsoleWindow.argtypes = []
    kernel.GetConsoleWindow.restype = ctypes.c_void_p

    kernel.FreeConsole()
    if not kernel.AttachConsole(int(pid)):
        return 0
    try:
        hwnd = kernel.GetConsoleWindow()
        return int(hwnd or 0)
    finally:
        kernel.FreeConsole()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        pid = int(args[0])
        if pid <= 0:
            raise ValueError
        print(console_window(pid))
    except Exception:
        print(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
