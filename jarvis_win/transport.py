"""Cross-session steering transport for Windows.

Spike A has NOT yet established what Claude Code writes into a Windows roster
entry. This module therefore supports both plausible transports without
inventing one:

* ``socket.AF_UNIX`` — available on Windows 10 1803+ for filesystem paths.
* ``\\\\.\\pipe\\...`` — Win32 named pipes, opened with CreateFileW/WaitNamedPipeW.

No `pywin32` dependency is needed. The native pipe API is injected in tests.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

log = logging.getLogger("jarvis.windows.transport")

SENT = "sent"
NOT_LIVE = "not_live"
REFUSED = "refused"
FAILED = "failed"

PIPE_PREFIX = "\\\\.\\pipe\\"
PIPE_PREFIX_FORWARD = "//./pipe/"
NAMED_PIPE_AVAILABLE = 0xFFFFFFFF
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PipeAPI(Protocol):
    def wait(self, path: str, timeout_ms: int) -> bool: ...
    def write(self, path: str, payload: bytes, timeout_ms: int) -> None: ...


class NativePipeAPI:
    """Minimal ctypes named-pipe client: WaitNamedPipeW + CreateFileW + WriteFile."""

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80

    def _dll(self):
        if sys.platform != "win32":
            raise OSError("named pipes require Windows")
        return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    def wait(self, path: str, timeout_ms: int) -> bool:
        try:
            dll = self._dll()
            dll.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
            dll.WaitNamedPipeW.restype = ctypes.c_int
            ms = max(1, min(int(timeout_ms), 0xFFFFFFFE))
            return bool(dll.WaitNamedPipeW(path, ms))
        except Exception as e:
            log.debug("WaitNamedPipeW failed: %s", e)
            return False

    def write(self, path: str, payload: bytes, timeout_ms: int) -> None:
        dll = self._dll()
        dll.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p]
        dll.CreateFileW.restype = ctypes.c_void_p
        dll.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        dll.WriteFile.restype = ctypes.c_int
        dll.CloseHandle.argtypes = [ctypes.c_void_p]
        dll.CloseHandle.restype = ctypes.c_int

        if not self.wait(path, timeout_ms):
            raise OSError(121, "named pipe was not available before timeout")

        desired = self.GENERIC_READ | self.GENERIC_WRITE
        handle = dll.CreateFileW(path, desired, 0, None, self.OPEN_EXISTING,
                                 self.FILE_ATTRIBUTE_NORMAL, None)
        if handle in (None, INVALID_HANDLE_VALUE):
            raise OSError(ctypes.get_last_error(), "CreateFileW could not open the named pipe")
        try:
            buffer = ctypes.create_string_buffer(payload)
            written = ctypes.c_uint32(0)
            ok = dll.WriteFile(handle, ctypes.cast(buffer, ctypes.c_void_p),
                               len(payload), ctypes.byref(written), None)
            if not ok:
                raise OSError(ctypes.get_last_error(), "WriteFile failed")
            if written.value != len(payload):
                raise OSError("short write to named pipe")
        finally:
            dll.CloseHandle(handle)


def normalize_pipe_path(path: str) -> str:
    """Canonicalise forward-slash spellings to ``\\\\.\\pipe\\...``."""
    value = str(path or "").strip().replace("/", "\\")
    if value.lower().startswith("\\\\?\\pipe\\"):
        value = PIPE_PREFIX + value[len("\\\\?\\pipe\\"):]
    return value


def is_named_pipe_path(path: str | None) -> bool:
    if not path:
        return False
    value = normalize_pipe_path(path)
    return value.lower().startswith(PIPE_PREFIX.lower())


def classify_socket_path(path: str | None) -> str:
    """One of ``missing``, ``named_pipe``, or ``unix_socket``."""
    if not path or not str(path).strip():
        return "missing"
    return "named_pipe" if is_named_pipe_path(path) else "unix_socket"


def build_payload(prompt: str, token: str | None = None) -> bytes | None:
    """One JSON auth line (optional) plus one JSON user line, exactly like Mac."""
    text = str(prompt or "").strip()
    if not text:
        return None
    if token is None:
        token = os.getenv("CLAUDE_CODE_MESSAGING_TOKEN", "")
    lines: list[str] = []
    if token:
        lines.append(json.dumps({"type": "auth", "token": token}))
    lines.append(json.dumps({"type": "user",
                             "message": {"role": "user", "content": text}}))
    return ("\n".join(lines) + "\n").encode("utf-8")


def transport_exists(path: str | None, *, pipe_api: PipeAPI | None = None,
                     exists: Callable[[str], bool] | None = None) -> bool:
    """Cheap liveness check used by ``RosterEntry.steerable``."""
    kind = classify_socket_path(path)
    if kind == "missing":
        return False
    value = str(path)
    if kind == "named_pipe":
        api = pipe_api or NativePipeAPI()
        try:
            return api.wait(normalize_pipe_path(value), 1)
        except Exception:
            return False
    check = exists or (lambda p: Path(p).exists())
    try:
        return bool(check(value))
    except OSError:
        return False


def send_payload(socket_path: str | None, prompt: str, timeout: float = 5.0, *,
                 token: str | None = None, pipe_api: PipeAPI | None = None,
                 socket_module: Any = socket,
                 exists: Callable[[str], bool] | None = None) -> str:
    """Deliver one prompt. Outcomes match upstream ``session_steer.py``."""
    payload = build_payload(prompt, token=token)
    if payload is None:
        return REFUSED
    kind = classify_socket_path(socket_path)
    if kind == "missing":
        return NOT_LIVE
    path = str(socket_path)
    timeout_ms = max(1, int(float(timeout) * 1000))

    if kind == "named_pipe":
        api = pipe_api or NativePipeAPI()
        pipe_path = normalize_pipe_path(path)
        try:
            if not api.wait(pipe_path, timeout_ms):
                return NOT_LIVE
            api.write(pipe_path, payload, timeout_ms)
            return SENT
        except FileNotFoundError:
            return NOT_LIVE
        except OSError as e:
            # ERROR_SEM_TIMEOUT is a live-server timeout, not proof of death;
            # report a failed send rather than claiming no session exists.
            log.debug("named pipe send failed: %s", e)
            return FAILED
        except Exception as e:
            log.debug("named pipe send failed: %s", e)
            return FAILED

    check = exists or (lambda p: Path(p).exists())
    try:
        if not check(path):
            return NOT_LIVE
    except OSError:
        return NOT_LIVE

    af_unix = getattr(socket_module, "AF_UNIX", None)
    if af_unix is None:
        return FAILED
    sock = None
    try:
        sock = socket_module.socket(af_unix, socket_module.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall(payload)
        return SENT
    except (ConnectionRefusedError, FileNotFoundError):
        return NOT_LIVE
    except OSError:
        return FAILED
    except Exception as e:
        log.debug("AF_UNIX send failed: %s", e)
        return FAILED
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
