"""Hidden Windows helpers for the one-click bootstrapper.

The user never opens Terminal, PowerShell, VS Code, Git Bash, or a command
line. Every helper below is spawned with ``CREATE_NO_WINDOW`` and a hidden
``STARTUPINFO``; all commands are argument lists, never shell strings.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from . import core
from .core import Paths
from ._env_windows import WindowsStore

Runner = Callable[..., "CommandResult"]
Spinner = Callable[..., subprocess.Popen]


class SetupError(RuntimeError):
    """A plain-words failure the GUI can show without a console."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


@dataclass(frozen=True)
class SetupResult:
    chrome: str
    claude: str | None
    openssl: str | None
    logged_in: bool
    started: bool


def hidden_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def hidden_startupinfo():
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return info


def run_hidden(argv: list[str], *, timeout: float = 120.0,
               cwd: str | os.PathLike[str] | None = None,
               env: Mapping[str, str] | None = None,
               input_text: str | None = None,
               redactor: core.Redactor | None = None) -> CommandResult:
    """Run one argument-list command with no visible console window."""
    kwargs: dict[str, object] = {
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "shell": False,
        "creationflags": hidden_creationflags(),
        "startupinfo": hidden_startupinfo(),
    }
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if env is not None:
        kwargs["env"] = {str(k): str(v) for k, v in env.items()}
    try:
        proc = subprocess.run(argv, input=input_text, timeout=timeout,
                              check=False, **kwargs)
    except FileNotFoundError as exc:
        raise SetupError(f"Could not find {Path(argv[0]).name}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SetupError(f"{Path(argv[0]).name} timed out") from exc
    output = proc.stdout or ""
    if redactor:
        output = redactor.redact(output)
    return CommandResult(int(proc.returncode), output)


def spawn_hidden(argv: list[str], *, cwd: str | os.PathLike[str] | None = None,
                 env: Mapping[str, str] | None = None,
                 stdin=None) -> subprocess.Popen:
    """Start a detached helper with no visible console window."""
    kwargs: dict[str, object] = {
        "stdin": stdin if stdin is not None else subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "shell": False,
        "creationflags": hidden_creationflags(),
        "startupinfo": hidden_startupinfo(),
        "close_fds": True,
    }
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if env is not None:
        kwargs["env"] = {str(k): str(v) for k, v in env.items()}
    return subprocess.Popen(argv, **kwargs)


def find_chrome(env: Mapping[str, str] | None = None) -> str | None:
    for candidate in core.chrome_candidates(env):
        if core.is_native_exe(candidate):
            return str(candidate)
    return None


def find_claude(env: Mapping[str, str] | None = None) -> str | None:
    """Native claude.exe only; .cmd/.bat shims are never accepted."""
    for candidate in core.claude_candidates(env):
        if core.is_native_exe(candidate):
            return str(candidate)
    return None


def find_openssl(paths: Paths, env: Mapping[str, str] | None = None) -> str | None:
    if core.is_native_exe(paths.openssl):
        return str(paths.openssl)
    found = shutil.which("openssl.exe", path=str(env.get("PATH", "")) if env else None)
    if found and core.is_native_exe(found):
        return found
    return None


def ensure_chrome(*, run: Runner, env: Mapping[str, str] | None = None,
                  progress: Callable[[str], None]) -> str:
    progress("Checking Google Chrome…")
    found = find_chrome(env)
    if found:
        return found
    progress("Installing Google Chrome silently…")
    result = run(core.winget_argv("Google.Chrome"))
    if result.returncode != 0:
        raise SetupError("Google Chrome could not be installed automatically.")
    found = find_chrome(env)
    if not found:
        raise SetupError("Google Chrome was installed but could not be located.")
    return found


def ensure_claude(*, run: Runner, env: Mapping[str, str] | None = None,
                  progress: Callable[[str], None]) -> str:
    progress("Checking native Claude Code…")
    found = find_claude(env)
    if found:
        return found
    progress("Installing native Claude Code silently…")
    result = run(core.winget_argv("Anthropic.ClaudeCode"))
    if result.returncode != 0:
        raise SetupError("Native Claude Code could not be installed automatically.")
    found = find_claude(env)
    if not found:
        raise SetupError("Only a non-native Claude shim was found; install the native build.")
    return found


def login_status(claude: str, *, run: Runner,
                 env: Mapping[str, str] | None = None) -> bool:
    result = run([claude, "auth", "status"], timeout=30.0, env=env)
    if result.returncode != 0:
        return False
    text = result.stdout.strip()
    start = text.find("{")
    if start < 0:
        return False
    try:
        data = json.loads(text[start:])
    except (ValueError, TypeError):
        return False
    return bool(isinstance(data, dict) and data.get("loggedIn"))


def login_process(claude: str, *, env: Mapping[str, str] | None = None) -> subprocess.Popen:
    """Start browser OAuth hidden; the GUI sends Enter after the user signs in."""
    child_env = dict(os.environ if env is None else env)
    core.scrub_anthropic(child_env)
    return subprocess.Popen(
        [claude, "auth", "login"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=hidden_creationflags(),
        startupinfo=hidden_startupinfo(),
        env=child_env,
    )


def finish_login(process: subprocess.Popen, *, timeout: float = 60.0) -> None:
    """Send the single Enter Claude Code asks for after browser login."""
    try:
        if process.stdin:
            process.stdin.write("\n")
            process.stdin.flush()
        process.wait(timeout=timeout)
    except Exception:
        try:
            process.terminate()
        except Exception:
            pass


def write_env_and_acl(paths: Paths, api_key: str, *, run: Runner,
                      env: Mapping[str, str] | None = None) -> None:
    """Write the Fish key to an external, user-only .env without logging it."""
    try:
        store = WindowsStore()
        if not api_key.strip():
            existing = dict(core.parse_env(store.reuse(paths.env_file))).get("FISH_API_KEY", "").strip()
            if not existing:
                raise SetupError("A Fish Audio API key is required for the voice.")
            return
        core._update_env_with_store(paths.env_file, {"FISH_API_KEY": api_key.strip()},
                                    acl=store.secure_temp, store=store)
    except SetupError:
        raise
    except Exception as primary:
        error = SetupError("The voice settings could not be saved securely.")
        error.persistence_error = primary
        raise error from None


def ensure_dirs(paths: Paths) -> None:
    paths.app_root.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    (paths.data_dir / "jarvis").mkdir(parents=True, exist_ok=True)


def ensure_cert(paths: Paths, openssl: str, *, run: Runner,
                env: Mapping[str, str] | None = None) -> None:
    if paths.cert.exists() and paths.key.exists():
        return
    argv = core.certificate_argv(openssl, paths.cert, paths.key, san=True)
    result = run(argv, cwd=paths.app_root, env=env)
    if result.returncode != 0:
        result = run(core.certificate_argv(openssl, paths.cert, paths.key, san=False),
                     cwd=paths.app_root, env=env)
    if result.returncode != 0 or not (paths.cert.exists() and paths.key.exists()):
        raise SetupError("The localhost certificate could not be generated.")
    run(core.acl_argv(paths.key, env))


def write_runtime(paths: Paths, claude: str | None, openssl: str | None,
                  ref: str) -> None:
    paths.runtime.write_text(
        core.json_dumps(core.runtime_document(paths, claude, openssl, ref)),
        encoding="utf-8")


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def startup_shortcut_argv(paths: Paths, exe: str) -> list[str]:
    """Hidden PowerShell creates a per-user Startup shortcut; no task/CLI UI."""
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
        + _ps_quote(str(paths.startup)) + ");"
        + "$s.TargetPath=" + _ps_quote(exe) + ";"
        + "$s.Arguments='--launch';"
        + "$s.WorkingDirectory=" + _ps_quote(str(paths.app_root)) + ";"
        + "$s.Save()"
    )
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    return [powershell, "-NoProfile", "-NonInteractive", "-WindowStyle",
            "Hidden", "-Command", script]


def create_startup_shortcut(paths: Paths, exe: str, *, run: Runner) -> None:
    paths.startup.parent.mkdir(parents=True, exist_ok=True)
    result = run(startup_shortcut_argv(paths, exe), timeout=30.0)
    if result.returncode != 0:
        raise SetupError("The Start-with-Windows shortcut could not be created.")


def health_ok(*, timeout: float = 0.7) -> bool:
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(core.HEALTH_URL, timeout=timeout,
                                    context=context) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def server_environment(paths: Paths, claude: str | None) -> dict[str, str]:
    env = dict(os.environ)
    core.scrub_anthropic(env)
    env["JARVIS_ONECLICK_APP_ROOT"] = str(paths.app_root)
    env["JARVIS_APP_ROOT"] = str(paths.bundle)
    env["JARVIS_ENV_FILE"] = str(paths.env_file)
    env["JARVIS_DATA_DIR"] = str(paths.data_dir)
    env["JARVIS_CLAUDE_PATH"] = claude or ""
    env["JARVIS_PORT"] = str(core.PORT)
    env["JARVIS_SCHEME"] = "https"
    env["JARVIS_BIND_HOST"] = core.BIND_HOST
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(paths.playwright)
    env["JARVIS_TOAST_APP_ID"] = core.APP_USER_MODEL_ID
    env["JARVIS_WINDOWS_OVERLAY"] = "1"
    return env


def start_server(exe: str, paths: Paths, claude: str | None, *,
                 spawn: Spinner, progress: Callable[[str], None]) -> None:
    """Start the same .exe in hidden --server mode, then wait for health."""
    if health_ok():
        return
    progress("Starting JARVIS…")
    spawn([exe, "--server"], cwd=paths.app_root,
          env=server_environment(paths, claude))
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if health_ok():
            return
        time.sleep(0.5)
    raise SetupError("JARVIS did not become healthy on https://localhost:8340.")


def open_chrome(chrome: str, url: str, *, spawn: Spinner) -> None:
    spawn([chrome, url], stdin=None)


def setup_all(api_key: str, paths: Paths, *,
              progress: Callable[[str], None] = lambda _: None,
              run: Runner = run_hidden,
              spawn: Spinner = spawn_hidden,
              login_prompt: Callable[[subprocess.Popen], None] | None = None,
              env: Mapping[str, str] | None = None,
              ref: str = "",
              exe: str | None = None,
              start: bool = True) -> SetupResult:
    """First-run flow: key → hidden prereqs → local files → browser → Chrome."""
    redactor = core.Redactor([api_key.strip()] if api_key.strip() else [])
    def say(message: str) -> None:
        progress(redactor.redact(message))

    ensure_dirs(paths)
    say("Saving your voice key…")
    write_env_and_acl(paths, api_key, run=run, env=env)
    chrome = ensure_chrome(run=run, env=env, progress=say)
    claude = ensure_claude(run=run, env=env, progress=say)
    openssl = find_openssl(paths, env)
    if not openssl:
        raise SetupError("A bundled Windows openssl.exe is required; rebuild the .exe with --openssl.")
    say("Creating the localhost certificate…")
    ensure_cert(paths, openssl, run=run, env=env)
    write_runtime(paths, claude, openssl, ref)

    logged_in = login_status(claude, run=run, env=env)
    if not logged_in:
        say("Opening your browser for Claude sign-in…")
        process = login_process(claude, env=env)
        if login_prompt:
            login_prompt(process)
        finish_login(process)
        logged_in = login_status(claude, run=run, env=env)

    target_exe = exe or sys.executable
    create_startup_shortcut(paths, target_exe, run=run)
    started = False
    if start:
        start_server(target_exe, paths, claude, spawn=spawn, progress=say)
        open_chrome(chrome, core.VOICE_URL, spawn=spawn)
        started = True
    say("JARVIS is ready.")
    return SetupResult(chrome=chrome, claude=claude, openssl=openssl,
                       logged_in=logged_in, started=started)
