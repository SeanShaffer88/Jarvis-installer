"""Small stand-ins for upstream module APIs. No upstream source is copied here."""

from __future__ import annotations

import asyncio
import re
import shlex
import types
from dataclasses import dataclass
from pathlib import Path


def dialog_module() -> types.ModuleType:
    module = types.ModuleType("dialog")
    module.SENT = "sent"
    module.NO_TTY = "no_tty"
    module.NOT_FOUND = "not_found"
    module.NOT_PERMITTED = "not_permitted"
    module.FAILED = "failed"
    module.BAD_KEY = "bad_key"

    @dataclass(frozen=True)
    class TerminalTab:
        window_id: int
        tab_index: int
        tty: str

    aliases = {"return": "return", "enter": "return", "yes": "return", "y": "return",
               "escape": "escape", "esc": "escape", "no": "escape", "n": "escape"}

    def normalize_key(key):
        if not isinstance(key, str):
            return None
        value = key.strip().lower()
        if value in aliases:
            return aliases[value]
        return value if len(value) == 1 and value in "123456789" else None

    def normalize_tty(tty):
        if not tty or tty.strip() in ("", "??"):
            return None
        value = tty.strip()
        if not value.startswith("/dev/"):
            value = "/dev/" + value
        return value if re.fullmatch(r"/dev/tty[a-zA-Z0-9]+", value) else None

    module.TerminalTab = TerminalTab
    module.normalize_key = normalize_key
    module.normalize_tty = normalize_tty
    module.spoken_key = lambda value: value.capitalize()
    module.tty_for_pid = lambda pid: None

    async def tty_for_pid_async(pid):
        return await asyncio.to_thread(module.tty_for_pid, pid)

    async def find_terminal_tab(tty):
        return None

    async def answer(pid, key):
        return module.FAILED

    module.tty_for_pid_async = tty_for_pid_async
    module.find_terminal_tab = find_terminal_tab
    module._send_script = lambda tab, key: "osascript"
    module.answer = answer
    return module


def notifier_module() -> types.ModuleType:
    module = types.ModuleType("notifier")
    module._TITLE_MAX = 120
    module._SUBTITLE_MAX = 120
    module._MESSAGE_MAX = 300
    module._TIMEOUT_SECONDS = 5.0
    module._NOTIFY_SCRIPT = "osascript source"
    module._truncate = lambda text, limit: text if len(text) <= limit else text[:limit - 1] + "…"
    module.available = lambda: False

    async def notify(title, message, *, subtitle=""):
        return False

    module.notify = notify
    return module


def screen_module() -> types.ModuleType:
    module = types.ModuleType("screen")

    class ScreenError(Exception):
        pass

    @dataclass
    class Shot:
        png: bytes
        width: int
        height: int

    @dataclass
    class Window:
        app: str
        title: str
        frontmost: bool

    def _is_blank(pixels):
        if not pixels:
            return False
        for channel in range(3):
            values = [pixel[channel] for pixel in pixels]
            mean = sum(values) / len(values)
            if sum(abs(value - mean) for value in values) / len(values) >= 1.5:
                return False
        return True

    module.ScreenError = ScreenError
    module.Shot = Shot
    module.Window = Window
    module._is_blank = _is_blank
    module._NO_PERMISSION = "no permission"
    module.SHOT_MAX_EDGE = 1280
    module.MAX_SHOT_BYTES = 4_000_000
    module.MAX_WINDOWS = 12
    module.BLANK_SAMPLE_EDGE = 32
    module.BLANK_MAD = 1.5
    module.screen_recording_granted = lambda: False

    async def capture_screen(display=None):
        raise ScreenError("not captured")

    async def list_windows():
        return []

    module.capture_screen = capture_screen
    module.list_windows = list_windows
    return module


def preflight_module() -> types.ModuleType:
    module = types.ModuleType("preflight")

    @dataclass(frozen=True)
    class Check:
        name: str
        status: str
        message: str
        remedy: str | None = None

    module.Check = Check
    module.STATUS_OK = "ok"
    module.STATUS_WARN = "warn"
    module.STATUS_FAIL = "fail"
    module.DEFAULT_CHECK_TIMEOUT = 5.0
    module.MIN_CLAUDE_VERSION = (2, 1, 224)
    module.MIN_CLAUDE_VERSION_STR = "2.1.224"
    module._parse_version = lambda text: tuple(map(int, re.search(r"(\d+)\.(\d+)\.(\d+)", text).groups())) if re.search(r"(\d+)\.(\d+)\.(\d+)", text) else None
    module._config_dir_from_env = lambda env: Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    module.claude_env = types.SimpleNamespace(child_env=lambda: {})

    async def run_subprocess(*args, timeout=5.0, env=None):
        return 0, "2.1.259 (Claude Code)", ""

    async def read_expiry(config_dir, timeout=5.0):
        return None

    def _check_screen_recording_sync():
        return Check("dummy", "ok", "ok")

    async def dummy_async(timeout=5.0):
        return Check("dummy", "ok", "ok")

    module._run_subprocess = run_subprocess
    module._read_oauth_refresh_expiry = read_expiry
    module._ASYNC_CHECKS = (dummy_async,)
    module._SYNC_CHECKS = (_check_screen_recording_sync,)
    return module


def brain_module() -> types.ModuleType:
    module = types.ModuleType("brain")

    @dataclass
    class BrainConfig:
        claude_path: str | None = None
        model: str = "sonnet"

    class Brain:
        def __init__(self, config):
            self.config = config
            self._claude = config.claude_path or "claude"

        def command(self):
            return shlex.split(self._claude) + ["-p", "--model", self.config.model]

    class RunExecutor:
        def __init__(self, claude_path=None):
            self._claude_path = claude_path or "claude"

        def _command(self, run_id, resume_from=None, model=None):
            return shlex.split(self._claude_path) + ["-p", "--session-id", run_id]

    module.BrainConfig = BrainConfig
    module.Brain = Brain
    module.RunExecutor = RunExecutor
    return module


def session_watch_module() -> types.ModuleType:
    module = types.ModuleType("session_watch")

    @dataclass(frozen=True)
    class RosterEntry:
        socket_path: str | None

        @property
        def steerable(self):
            return bool(self.socket_path) and Path(self.socket_path).exists()

    module.RosterEntry = RosterEntry
    module.pid_alive = lambda pid: False
    return module


def session_steer_module() -> types.ModuleType:
    module = types.ModuleType("session_steer")
    module.SENT = "sent"
    module.NOT_LIVE = "not_live"
    module.REFUSED = "refused"
    module.FAILED = "failed"
    module.post_to_session = lambda *args, **kwargs: module.FAILED
    return module


class FakeAsyncProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self, input=None):
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


class FakeSyncProcess:
    def __init__(self, output="", returncode=0):
        self.output = output
        self.returncode = returncode
        self.terminated = False

    def communicate(self):
        return self.output, None

    def terminate(self):
        self.terminated = True

    def wait(self):
        return self.returncode
