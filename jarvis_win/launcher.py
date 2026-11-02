"""Hidden JARVIS launcher, health check, browser opener, and stop switch.

Starts ``server.py --host 127.0.0.1`` with the Windows overlay active, waits
for ``/api/health``, then opens one fixed origin. The PID file is verified
against the process command line before Stop kills anything.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from . import APP_USER_MODEL_ID, win32, win_paths
except ImportError:  # direct execution from a Start-menu shortcut
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from jarvis_win import APP_USER_MODEL_ID, win32, win_paths

CREATE_NO_WINDOW = 0x08000000
DEFAULT_PORT = 8340
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_ORIGIN = f"https://localhost:{DEFAULT_PORT}"
DEFAULT_APP_ID = APP_USER_MODEL_ID


def default_app_root() -> Path:
    return Path(os.getenv("JARVIS_APP_ROOT") or Path(__file__).resolve().parent.parent)


def load_runtime(app_root: Path) -> dict[str, Any]:
    path = app_root / "runtime.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def origin(runtime: dict[str, Any]) -> str:
    return str(runtime.get("origin") or DEFAULT_ORIGIN).rstrip("/")


def health_url(runtime: dict[str, Any]) -> str:
    return origin(runtime) + "/api/health"


def health_ok(runtime: dict[str, Any], timeout: float = 1.0) -> bool:
    context = ssl._create_unverified_context() if origin(runtime).startswith("https:") else None
    try:
        with urllib.request.urlopen(health_url(runtime), timeout=timeout, context=context) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def pid_file(app_root: Path) -> Path:
    return app_root / "data" / "jarvis.pid"


def python_for_server(app_root: Path, runtime: dict[str, Any]) -> str:
    pythonw = Path(str(runtime.get("pythonw") or app_root / ".venv" / "Scripts" / "pythonw.exe"))
    python = Path(str(runtime.get("venv_python") or app_root / ".venv" / "Scripts" / "python.exe"))
    if pythonw.is_file():
        return str(pythonw)
    if python.is_file():
        return str(python)
    return sys.executable


def child_env(app_root: Path, runtime: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    old_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(app_root) + (os.pathsep + old_path if old_path else "")
    env["JARVIS_APP_ROOT"] = str(app_root)
    env["JARVIS_WINDOWS_OVERLAY"] = "1"
    env["JARVIS_TOAST_APP_ID"] = str(runtime.get("app_user_model_id") or DEFAULT_APP_ID)
    env["JARVIS_PORT"] = str(runtime.get("port") or DEFAULT_PORT)
    env["JARVIS_SCHEME"] = str(runtime.get("scheme") or "https")
    env["JARVIS_BIND_HOST"] = str(runtime.get("bind_host") or DEFAULT_BIND_HOST)
    env["PYTHONIOENCODING"] = "utf-8"
    native = runtime.get("claude")
    if native:
        env["JARVIS_CLAUDE_PATH"] = str(native)
    return env


def open_page(runtime: dict[str, Any], target: str) -> int:
    if target == "none":
        return 0
    url = origin(runtime) + ("/dashboard" if target == "dashboard" else "/")
    chrome = win_paths.find_chrome()
    if chrome:
        subprocess.Popen([chrome, url], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    startfile = getattr(os, "startfile", None)
    if startfile:
        startfile(url)  # type: ignore[attr-defined]
        return 0
    print("Chrome was not found; open " + url, file=sys.stderr)
    return 1


def command_line(pid: int) -> str | None:
    """Read one process command line through CIM; refuse to kill on doubt."""
    if os.name != "nt":
        return None
    powershell = win_paths.find_powershell()
    if not powershell:
        return None
    safe_pid = int(pid)
    script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={safe_pid}').CommandLine"
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=CREATE_NO_WINDOW)
        return (result.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def start(app_root: Path, runtime: dict[str, Any], target: str = "voice") -> int:
    if health_ok(runtime):
        return open_page(runtime, target)
    pid_path = pid_file(app_root)
    existing = None
    try:
        existing = int(pid_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pass
    if existing and win32.pid_alive(existing):
        print("JARVIS is already starting; waiting for its health check.")
    else:
        server = app_root / "server.py"
        if not server.exists():
            print("server.py is missing from the installation.", file=sys.stderr)
            return 1
        python = python_for_server(app_root, runtime)
        argv = [python, str(server),
                "--host", str(runtime.get("bind_host") or DEFAULT_BIND_HOST),
                "--port", str(runtime.get("port") or DEFAULT_PORT)]
        kwargs: dict[str, Any] = {
            "cwd": str(app_root),
            "env": child_env(app_root, runtime),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        proc = subprocess.Popen(argv, **kwargs)
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(f"{proc.pid}\n", encoding="ascii")
    for _ in range(60):
        if health_ok(runtime):
            return open_page(runtime, target)
        time.sleep(0.5)
    print("JARVIS did not become healthy on " + health_url(runtime), file=sys.stderr)
    return 1


def stop(app_root: Path, runtime: dict[str, Any]) -> int:
    del runtime
    pid_path = pid_file(app_root)
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        print("JARVIS is not running.")
        return 0
    if not win32.pid_alive(pid):
        pid_path.unlink(missing_ok=True)
        print("JARVIS is not running.")
        return 0
    cmdline = command_line(pid)
    if not cmdline or "server.py" not in cmdline or str(app_root).lower() not in cmdline.lower():
        print("Refusing to stop an unverified process; PID may have been reused.",
              file=sys.stderr)
        return 2
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10, check=False,
                                creationflags=CREATE_NO_WINDOW)
        success = result.returncode == 0
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            success = True
        except OSError:
            success = False
    if success:
        pid_path.unlink(missing_ok=True)
        print("JARVIS stopped.")
        return 0
    print("Could not stop JARVIS.", file=sys.stderr)
    return 1


def status(app_root: Path, runtime: dict[str, Any]) -> int:
    try:
        pid = int(pid_file(app_root).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pid = None
    payload = {
        "health": health_ok(runtime),
        "running": bool(pid and win32.pid_alive(pid)),
        "pid": pid,
        "origin": origin(runtime),
        "overlay": "jarvis_win.hook",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["health"] else 1


def preflight(app_root: Path, runtime: dict[str, Any]) -> int:
    python = python_for_server(app_root, runtime)
    if str(Path(python).name).lower().startswith("pythonw"):
        python = str(Path(python).with_name("python.exe"))
    script = Path(__file__).with_name("preflight_cli.py")
    result = subprocess.run(
        [python, str(script), "--app-root", str(app_root),
         "--output", str(app_root / "logs" / "preflight.json"),
         "--text-output", str(app_root / "logs" / "preflight.txt")],
        cwd=str(app_root), env=child_env(app_root, runtime),
        capture_output=True, text=True, timeout=60, check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    print(result.stdout or result.stderr or "Preflight finished.")
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS Windows launcher")
    parser.add_argument("--app-root", default=str(default_app_root()))
    sub = parser.add_subparsers(dest="command", required=True)
    starter = sub.add_parser("start")
    starter.add_argument("--open", dest="target", choices=("voice", "dashboard", "none"),
                         default="voice")
    sub.add_parser("stop")
    sub.add_parser("status")
    opener = sub.add_parser("open")
    opener.add_argument("--target", choices=("voice", "dashboard"), default="voice")
    sub.add_parser("preflight")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_root = Path(args.app_root).resolve()
    runtime = load_runtime(app_root)
    if args.command == "start":
        return start(app_root, runtime, args.target)
    if args.command == "stop":
        return stop(app_root, runtime)
    if args.command == "status":
        return status(app_root, runtime)
    if args.command == "open":
        return open_page(runtime, args.target)
    if args.command == "preflight":
        return preflight(app_root, runtime)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
