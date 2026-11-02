"""Small ctypes-only Windows API layer.

No pywin32 dependency. Every method is behind an injectable API object so the
identity/permission logic can be unit-tested on Linux with fakes. The native
implementation loads Win32 DLLs lazily and is only used on ``win32``.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("jarvis.windows.win32")

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
TH32CS_SNAPPROCESS = 0x00000002
CREATE_NO_WINDOW = 0x08000000

TRUSTED_TERMINAL_HOSTS = frozenset({
    "windowsterminal.exe", "openconsole.exe", "conhost.exe",
    "powershell.exe", "pwsh.exe", "cmd.exe",
})


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    process_name: str
    visible: bool
    foreground: bool


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    parent_pid: int
    name: str


@dataclass(frozen=True)
class SessionWindow:
    hwnd: int
    pid: int
    title: str
    process_name: str
    confidence: str
    host_pid: int
    console_hwnd: int = 0


class Win32API(Protocol):
    def pid_alive(self, pid: int) -> bool: ...
    def windows(self) -> list[WindowInfo]: ...
    def window_by_hwnd(self, hwnd: int) -> WindowInfo | None: ...
    def process_chain(self, pid: int, max_hops: int = 6) -> list[ProcessInfo]: ...
    def console_hwnd(self, pid: int, timeout: float = 1.0) -> int: ...
    def monitor_rects(self) -> list[tuple[int, int, int, int]]: ...


class UnavailableWin32API:
    """Inert API used for imports and tests on non-Windows hosts."""

    def pid_alive(self, pid: int) -> bool:
        return _posix_pid_alive(pid)

    def windows(self) -> list[WindowInfo]:
        return []

    def window_by_hwnd(self, hwnd: int) -> WindowInfo | None:
        return None

    def process_chain(self, pid: int, max_hops: int = 6) -> list[ProcessInfo]:
        return []

    def console_hwnd(self, pid: int, timeout: float = 1.0) -> int:
        return 0

    def monitor_rects(self) -> list[tuple[int, int, int, int]]:
        return []


class NativeWin32API:
    """Win32 implementation using ctypes and an isolated console probe."""

    def _kernel(self):
        if sys.platform != "win32":
            raise OSError("kernel32 requires Windows")
        return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    def _user(self):
        if sys.platform != "win32":
            raise OSError("user32 requires Windows")
        return ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]

    # -- processes ---------------------------------------------------------

    def pid_alive(self, pid: int) -> bool:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        kernel = self._kernel()
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.GetExitCodeProcess.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int

        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if handle in (None, ctypes.c_void_p(-1).value):
            # A same-user live process can still refuse limited query access.
            # Unknown is safer than announcing a live session as gone.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_uint32(0)
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return ctypes.get_last_error() == ERROR_ACCESS_DENIED
            return code.value == STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)

    def process_name(self, pid: int) -> str:
        try:
            kernel = self._kernel()
            kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                          ctypes.c_wchar_p,
                                                          ctypes.POINTER(ctypes.c_uint32)]
            kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
            if handle in (None, ctypes.c_void_p(-1).value):
                return f"pid:{pid}"
            try:
                size = ctypes.c_uint32(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    return Path(buffer.value).name or f"pid:{pid}"
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            pass
        return f"pid:{pid}"

    def process_chain(self, pid: int, max_hops: int = 6) -> list[ProcessInfo]:
        """Target pid and its ancestor chain via Toolhelp32, never PowerShell."""
        if sys.platform != "win32":
            return []

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32),
                ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_uint32),
                ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel = self._kernel()
        kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel.Process32FirstW.restype = ctypes.c_int
        kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel.Process32NextW.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]

        snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (None, ctypes.c_void_p(-1).value):
            return []
        table: dict[int, ProcessInfo] = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            guard = 0
            while more and guard < 10000:
                guard += 1
                name = str(entry.szExeFile).split("\x00", 1)[0]
                table[int(entry.th32ProcessID)] = ProcessInfo(
                    pid=int(entry.th32ProcessID),
                    parent_pid=int(entry.th32ParentProcessID),
                    name=name,
                )
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)

        chain: list[ProcessInfo] = []
        current = int(pid)
        seen: set[int] = set()
        for _ in range(max(0, max_hops) + 1):
            info = table.get(current)
            if info is None or current in seen:
                break
            seen.add(current)
            chain.append(info)
            if info.parent_pid <= 0 or info.parent_pid == current:
                break
            current = info.parent_pid
        return chain

    def console_hwnd(self, pid: int, timeout: float = 1.0) -> int:
        """Ask an isolated helper to attach to the target console briefly."""
        if sys.platform != "win32":
            return 0
        probe = Path(__file__).with_name("console_probe.py")
        executable = Path(sys.executable)
        if executable.name.lower().startswith("pythonw"):
            executable = executable.with_name("python.exe")
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": max(0.2, float(timeout)),
            "stdin": subprocess.DEVNULL,
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            result = subprocess.run([str(executable), "-I", str(probe), str(int(pid))], **kwargs)
            first = (result.stdout or "").strip().splitlines()
            return int(first[0]) if first else 0
        except Exception:
            return 0

    # -- windows -----------------------------------------------------------

    def _read_window(self, hwnd: int, foreground_hwnd: int,
                     include_hidden: bool = False) -> WindowInfo | None:
        user = self._user()
        user.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user.IsWindowVisible.restype = ctypes.c_int
        user.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user.GetWindowTextLengthW.restype = ctypes.c_int
        user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user.GetWindowTextW.restype = ctypes.c_int
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_uint32)]
        user.GetWindowThreadProcessId.restype = ctypes.c_uint32

        visible = bool(user.IsWindowVisible(hwnd))
        if not visible and not include_hidden:
            return None
        length = int(user.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(hwnd, buffer, length + 1)
        title = (buffer.value or "").strip()
        if not title:
            return None
        pid = ctypes.c_uint32(0)
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowInfo(
            hwnd=int(hwnd or 0), pid=int(pid.value), title=title,
            process_name=self.process_name(int(pid.value)), visible=visible,
            foreground=int(hwnd or 0) == foreground_hwnd,
        )

    def window_by_hwnd(self, hwnd: int) -> WindowInfo | None:
        try:
            user = self._user()
            user.GetForegroundWindow.argtypes = []
            user.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = int(user.GetForegroundWindow() or 0)
            return self._read_window(int(hwnd), foreground, include_hidden=True)
        except Exception:
            return None

    def windows(self) -> list[WindowInfo]:
        if sys.platform != "win32":
            return []
        user = self._user()
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)  # type: ignore[attr-defined]
        user.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
        user.EnumWindows.restype = ctypes.c_int
        user.GetForegroundWindow.argtypes = []
        user.GetForegroundWindow.restype = ctypes.c_void_p
        foreground = int(user.GetForegroundWindow() or 0)
        out: list[WindowInfo] = []

        def collect(hwnd: ctypes.c_void_p, _lparam: ctypes.c_void_p) -> int:
            try:
                info = self._read_window(int(hwnd or 0), foreground)
                if info is not None:
                    out.append(info)
            except Exception:
                pass
            return 1

        callback = WNDENUMPROC(collect)
        user.EnumWindows(callback, None)
        return out

    def monitor_rects(self) -> list[tuple[int, int, int, int]]:
        if sys.platform != "win32":
            return []

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        user = self._user()
        MONITORENUMPROC = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p)
        user.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                             MONITORENUMPROC, ctypes.c_void_p]
        user.EnumDisplayMonitors.restype = ctypes.c_int
        rects: list[tuple[int, int, int, int]] = []

        def collect(_monitor: ctypes.c_void_p, _dc: ctypes.c_void_p,
                    rect_ptr: ctypes.c_void_p, _data: ctypes.c_void_p) -> int:
            try:
                if rect_ptr:
                    rect = ctypes.cast(rect_ptr, ctypes.POINTER(RECT)).contents
                    rects.append((int(rect.left), int(rect.top),
                                  int(rect.right), int(rect.bottom)))
            except Exception:
                pass
            return 1

        callback = MONITORENUMPROC(collect)
        user.EnumDisplayMonitors(None, None, callback, None)
        return sorted(rects, key=lambda r: (r[1], r[0]))


def default_api() -> Win32API:
    return NativeWin32API() if sys.platform == "win32" else UnavailableWin32API()


def _posix_pid_alive(pid: int) -> bool:
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def pid_alive(pid: Any, api: Win32API | None = None) -> bool:
    """Windows-safe liveness check; replaces ``os.kill(pid, 0)``."""
    source = api or default_api()
    try:
        return bool(source.pid_alive(pid))
    except Exception:
        return False


def list_windows(api: Win32API | None = None) -> list[WindowInfo]:
    source = api or default_api()
    try:
        return list(source.windows())
    except Exception:
        return []


def monitor_rects(api: Win32API | None = None) -> list[tuple[int, int, int, int]]:
    source = api or default_api()
    try:
        return list(source.monitor_rects())
    except Exception:
        return []


def _trusted(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRUSTED_TERMINAL_HOSTS or any(
        host in lowered for host in ("windowsterminal", "openconsole", "conhost"))


def find_session_window(pid: Any, api: Win32API | None = None,
                        max_hops: int = 6) -> SessionWindow | None:
    """Prove one exact pid → host → HWND identity, or return None.

    There is deliberately no front-window fallback. If more than one window
    could belong to a host, the answer is None — the same safe ``not_found``
    outcome the Mac code uses for a non-Terminal host.
    """
    try:
        target = int(pid)
    except (TypeError, ValueError):
        return None
    if target <= 0:
        return None
    source = api or default_api()
    try:
        if not source.pid_alive(target):
            return None
        windows = [w for w in source.windows() if w.visible and w.title]
        direct = [w for w in windows if w.pid == target]
        if len(direct) == 1:
            win = direct[0]
            return SessionWindow(win.hwnd, target, win.title, win.process_name,
                                 "direct", win.pid)

        console_hwnd = int(source.console_hwnd(target) or 0)
        console_win = None
        if console_hwnd and hasattr(source, "window_by_hwnd"):
            console_win = source.window_by_hwnd(console_hwnd)
        if console_win and console_win.visible and console_win.title \
                and _trusted(console_win.process_name):
            return SessionWindow(console_win.hwnd, target, console_win.title,
                                 console_win.process_name, "console",
                                 console_win.pid, console_hwnd)

        chain = list(source.process_chain(target, max_hops=max_hops))
        if console_win:
            chain.extend(source.process_chain(console_win.pid, max_hops=max_hops))
        seen_pids: set[int] = set()
        for process in chain:
            if process.pid in seen_pids:
                continue
            seen_pids.add(process.pid)
            candidates = [w for w in windows
                          if w.pid == process.pid
                          and (_trusted(w.process_name) or _trusted(process.name))]
            if len(candidates) == 1:
                win = candidates[0]
                return SessionWindow(win.hwnd, target, win.title, win.process_name,
                                     "lineage", process.pid, console_hwnd)
            if len(candidates) > 1 and console_hwnd:
                exact = [w for w in candidates if w.hwnd == console_hwnd]
                if len(exact) == 1:
                    win = exact[0]
                    return SessionWindow(win.hwnd, target, win.title,
                                         win.process_name, "console-lineage",
                                         process.pid, console_hwnd)
        return None
    except Exception as e:
        log.debug("session window probe failed: %s", e)
        return None


def probe_session_window(pid: Any, api: Win32API | None = None) -> dict[str, Any]:
    """Structured Spike C output; never sends input."""
    try:
        target = int(pid)
    except (TypeError, ValueError):
        return {"pid": None, "verified": False, "reason": "invalid pid"}
    source = api or default_api()
    alive = pid_alive(target, source)
    console_hwnd = int(source.console_hwnd(target) or 0) if alive else 0
    chain = source.process_chain(target) if alive else []
    windows = list_windows(source)
    result = find_session_window(target, source)
    return {
        "pid": target,
        "alive": alive,
        "verified": result is not None,
        "hwnd": result.hwnd if result else None,
        "confidence": result.confidence if result else None,
        "console_hwnd": console_hwnd,
        "host_pid": result.host_pid if result else None,
        "window_title": result.title if result else None,
        "process_chain": [{"pid": p.pid, "parent_pid": p.parent_pid, "name": p.name}
                          for p in chain],
        "visible_windows": [{"hwnd": w.hwnd, "pid": w.pid, "title": w.title,
                             "process_name": w.process_name,
                             "foreground": w.foreground} for w in windows],
        "reason": ("one exact identity proven" if result
                   else "no exact identity; v1 must alert and press nothing"),
        "sends_input": False,
    }
