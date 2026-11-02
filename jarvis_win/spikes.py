"""Phase 0 spike probes. Read-only unless an explicit transport test is requested."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from . import claude_launcher, transport, win32
    from .preflight_win import credential_candidates
except ImportError:  # direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from jarvis_win import claude_launcher, transport, win32
    from jarvis_win.preflight_win import credential_candidates


def bootstrap(app_root: Path) -> None:
    app_root = app_root.resolve()
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    os.environ.setdefault("JARVIS_APP_ROOT", str(app_root))
    os.environ.setdefault("JARVIS_WINDOWS_OVERLAY", "1")


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def cmd_roster(app_root: Path) -> int:
    bootstrap(app_root)
    import session_watch
    entries = session_watch.read_roster()
    emit({
        "entries": [{
            "pid": e.pid,
            "session_id": e.session_id,
            "cwd": e.cwd,
            "version": e.version,
            "socket_path": e.socket_path,
            "transport": transport.classify_socket_path(e.socket_path),
            "alive": session_watch.pid_alive(e.pid),
            "steerable": e.steerable,
        } for e in entries],
        "note": "Spike A: classify every real socket_path; do not claim steering works until a test message is received.",
    })
    return 0


def cmd_claude(app_root: Path) -> int:
    bootstrap(app_root)
    import claude_env
    native = claude_launcher.resolve_claude()
    result: dict[str, Any] = {
        "native_claude": native,
        "npm_shim_rejected": native is None,
        "credential_candidates": [
            {"path": str(p), "exists": p.exists()}
            for p in credential_candidates(Path.home() / ".claude")
        ],
    }
    if not native:
        result["status"] = "fail"
        emit(result)
        return 1
    try:
        version = subprocess.run([native, "--version"], capture_output=True,
                                 text=True, timeout=8, check=False)
        auth = subprocess.run([native, "auth", "status"], capture_output=True,
                              text=True, timeout=8, check=False,
                              env=claude_env.child_env())
        result["version"] = (version.stdout or version.stderr).strip()
        try:
            data = json.loads(auth.stdout)
            result["auth"] = {
                "loggedIn": bool(data.get("loggedIn")),
                "authMethod": data.get("authMethod"),
                "email": data.get("email"),
            }
        except (ValueError, TypeError):
            result["auth"] = {"parse_error": True}
        result["status"] = "ok" if version.returncode == 0 and auth.returncode == 0 else "fail"
    except (OSError, subprocess.SubprocessError) as e:
        result["status"] = "fail"
        result["error"] = str(e)
    emit(result)
    return 0 if result.get("status") == "ok" else 1


def cmd_windows(app_root: Path, pid: int | None) -> int:
    bootstrap(app_root)
    if pid is not None:
        emit({"pids": [win32.probe_session_window(pid)], "sends_input": False})
        return 0
    import session_watch
    pids = sorted({e.pid for e in session_watch.read_roster()})
    emit({"pids": [win32.probe_session_window(value) for value in pids],
          "sends_input": False,
          "note": "Spike C: only one exact HWND per pid is acceptable; ambiguity stays not_found."})
    return 0


def cmd_transport(app_root: Path, path: str | None, send_test: bool,
                  acknowledge: bool) -> int:
    bootstrap(app_root)
    result: dict[str, Any] = {
        "socket_path": path,
        "transport": transport.classify_socket_path(path),
        "sent_test": False,
    }
    if send_test:
        if not acknowledge:
            result["error"] = "Add --acknowledge to send a real diagnostic message to a live session."
            emit(result)
            return 2
        import session_steer
        result["outcome"] = session_steer.post_to_session(
            path, "JARVIS Windows transport check: please ignore this diagnostic message.",
            timeout=5.0)
        result["sent_test"] = True
    emit(result)
    return 0


def cmd_baseline(app_root: Path, run: bool) -> int:
    bootstrap(app_root)
    command = [sys.executable, "-m", "pytest", "-q", "tests"]
    if not run:
        emit({"command": command, "cwd": str(app_root),
              "note": "Spike D: run this in the installed venv and catalogue every failure."})
        return 0
    result = subprocess.run(command, cwd=str(app_root), capture_output=True,
                            text=True, timeout=1800, check=False)
    log = app_root / "logs" / "spike-baseline.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
    emit({"exit_code": result.returncode, "log": str(log),
          "tail": (result.stdout or result.stderr or "").splitlines()[-20:]})
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS Windows Phase 0 spikes")
    parser.add_argument("--app-root", default=os.getenv("JARVIS_APP_ROOT", "."))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("roster")
    sub.add_parser("claude")
    windows = sub.add_parser("windows")
    windows.add_argument("--pid", type=int)
    pipe = sub.add_parser("transport")
    pipe.add_argument("--path")
    pipe.add_argument("--send-test", action="store_true")
    pipe.add_argument("--acknowledge", action="store_true")
    baseline = sub.add_parser("baseline")
    baseline.add_argument("--run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_root = Path(args.app_root).resolve()
    if args.command == "roster":
        return cmd_roster(app_root)
    if args.command == "claude":
        return cmd_claude(app_root)
    if args.command == "windows":
        return cmd_windows(app_root, args.pid)
    if args.command == "transport":
        return cmd_transport(app_root, args.path, args.send_test, args.acknowledge)
    if args.command == "baseline":
        return cmd_baseline(app_root, args.run)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
