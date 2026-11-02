"""Cancellable, secret-safe setup run called by the Inno Setup wizard.

The Fish Audio key enters through a tightly ACL'd JSON job file, never through
a command line, and is scrubbed from every log/progress line. Long commands are
watched for a cancel sentinel so the wizard's Cancel button is prompt.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:  # Package import or direct ``python setup_runtime.py`` from the payload.
    from . import claude_launcher, win_paths
except ImportError:  # pragma: no cover - exercised when run by the wizard
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from jarvis_win import claude_launcher, win_paths

CREATE_NO_WINDOW = 0x08000000
MIN_PYTHON = (3, 11)
DEFAULT_PORT = 8340
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_APP_ID = "SeanShaffer.Jarvis.Windows"
JOB_KEYS = ("fish_api_key", "user_name", "brain_model", "voice_id")

_POPEN: Callable[..., Any] = subprocess.Popen


class SetupError(RuntimeError):
    """A plain-words setup failure."""


class SetupCancelled(RuntimeError):
    pass


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()):
        self.secrets = [str(s) for s in secrets if s]

    def add(self, value: str | None) -> None:
        if value and value not in self.secrets:
            self.secrets.append(str(value))

    def redact(self, text: str) -> str:
        value = str(text or "")
        for secret in self.secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(FISH_API_KEY\s*=\s*)([^\r\n]+)",
                       r"\1[REDACTED]", value)
        value = re.sub(r'(?i)("fish_api_key"\s*:\s*")([^"]*)(")',
                       r"\1[REDACTED]\3", value)
        return value


class SetupLogger:
    def __init__(self, log_file: Path, progress_file: Path | None,
                 redactor: Redactor | None = None):
        self.log_file = Path(log_file)
        self.progress_file = Path(progress_file) if progress_file else None
        self.redactor = redactor or Redactor()

    def log(self, message: str, percent: int | None = None) -> None:
        safe = self.redactor.redact(message)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {safe.rstrip()}\n")
        if self.progress_file is not None:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            value = max(0, min(100, int(percent if percent is not None else 0)))
            self.progress_file.write_text(f"{value}|{safe.rstrip()}\n",
                                          encoding="utf-8")
        print(safe, flush=True)


def read_job(path: str | os.PathLike[str]) -> dict[str, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SetupError("The setup input file is not valid.")
    return {key: str(data.get(key, "") or "").strip() for key in JOB_KEYS}


def secure_delete(path: str | os.PathLike[str] | None) -> None:
    """Best-effort overwrite-then-unlink of the temporary secret job file."""
    if not path:
        return
    target = Path(path)
    try:
        if not target.exists():
            return
        length = target.stat().st_size
        with target.open("r+b") as handle:
            handle.write(b"0" * length)
            handle.flush()
            os.fsync(handle.fileno())
        target.unlink()
    except OSError:
        pass


def secure_file(path: str | os.PathLike[str]) -> None:
    """Remove inheritance and grant the current user alone (Windows)."""
    target = Path(path)
    if os.name != "nt":
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return
    subprocess.run(
        ["icacls", str(target), "/inheritance:r", "/grant:r", f"{user}:(F)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        creationflags=CREATE_NO_WINDOW,
    )


def has_fish_key(env_path: Path) -> bool:
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "FISH_API_KEY" and value.strip() \
                    and "your-fish-audio-api-key-here" not in value:
                return True
    except OSError:
        pass
    return False


def update_env(env_path: Path, updates: Mapping[str, str]) -> None:
    """Preserve comments, order, and unlisted keys; write atomically."""
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["# JARVIS Windows settings", ""]
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            out.append(f"{key}={updates[key]}" if updates[key] else line)
        else:
            out.append(line)
    for key, value in updates.items():
        if value and key not in seen:
            out.append(f"{key}={value}")
    temp = env_path.with_name(env_path.name + ".tmp")
    temp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    os.replace(temp, env_path)
    secure_file(env_path)


def venv_paths(app_root: Path) -> tuple[Path, Path, Path]:
    venv = app_root / ".venv"
    if os.name == "nt":
        return venv, venv / "Scripts" / "python.exe", venv / "Scripts" / "pythonw.exe"
    return venv, venv / "bin" / "python", venv / "bin" / "python"


def child_environment(app_root: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    old_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(app_root) + (os.pathsep + old_path if old_path else "")
    env["JARVIS_APP_ROOT"] = str(app_root)
    env["JARVIS_WINDOWS_OVERLAY"] = "1"
    env.setdefault("JARVIS_TOAST_APP_ID", DEFAULT_APP_ID)
    env.setdefault("JARVIS_PORT", str(DEFAULT_PORT))
    env.setdefault("JARVIS_BIND_HOST", DEFAULT_BIND_HOST)
    env.setdefault("JARVIS_SCHEME", "https")
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def cancel_requested(cancel_file: Path | None) -> bool:
    try:
        return bool(cancel_file and Path(cancel_file).exists())
    except OSError:
        return False


def run_command(argv: list[str], *, cwd: Path, logger: SetupLogger,
                cancel_file: Path | None, label: str, percent: int,
                done_percent: int | None = None,
                env: Mapping[str, str] | None = None,
                allow_failure: bool = False,
                popen: Callable[..., Any] | None = None) -> int:
    """Run one argument-list command, hidden, cancellable, and redacted."""
    logger.log(f"Starting {label}", percent)
    if cancel_requested(cancel_file):
        raise SetupCancelled("Setup was cancelled.")
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": dict(env) if env is not None else None,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    runner = popen or _POPEN
    proc = runner(argv, **kwargs)
    output = ""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(proc.communicate)
        while not future.done():
            if cancel_requested(cancel_file):
                try:
                    proc.terminate()
                except Exception:
                    pass
                future.cancel()
                raise SetupCancelled("Setup was cancelled.")
            future.wait(0.25)
        try:
            result = future.result()
            output = result[0] if isinstance(result, tuple) else str(result or "")
        except Exception as e:
            output = str(e)
    for line in output.splitlines()[-40:]:
        logger.log(f"{label}: {line}", percent)
    code = int(proc.returncode if proc.returncode is not None else proc.wait())
    logger.log(f"Finished {label} with exit code {code}",
               done_percent if done_percent is not None else percent)
    if code != 0 and not allow_failure:
        raise SetupError(f"{label} failed with exit code {code}. See the install log.")
    return code


def ensure_venv(base_python: str, app_root: Path, *, logger: SetupLogger,
                cancel_file: Path | None,
                popen: Callable[..., Any] | None = None) -> tuple[Path, Path]:
    venv_dir, venv_python, pythonw = venv_paths(app_root)
    if not venv_python.exists():
        run_command([base_python, "-m", "venv", str(venv_dir)], cwd=app_root,
                    logger=logger, cancel_file=cancel_file,
                    label="creating the private Python environment",
                    percent=15, done_percent=25, popen=popen)
    if not venv_python.exists():
        raise SetupError("The private Python environment was not created.")
    return venv_python, pythonw


def ensure_certificates(app_root: Path, *, openssl: str | None,
                        logger: SetupLogger, cancel_file: Path | None,
                        popen: Callable[..., Any] | None = None) -> str | None:
    cert = app_root / "cert.pem"
    key = app_root / "key.pem"
    if cert.exists() and key.exists():
        logger.log("Keeping the existing localhost certificate", 75)
        return openssl
    resolved = openssl or win_paths.find_openssl(app_root=app_root)
    if not resolved:
        raise SetupError("OpenSSL was not found; install Git for Windows or supply openssl.exe.")
    common = [resolved, "req", "-x509", "-newkey", "rsa:2048",
              "-keyout", str(key), "-out", str(cert), "-days", "365",
              "-nodes", "-subj", "/CN=localhost"]
    extended = common + ["-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"]
    # Older OpenSSL builds lack -addext. Retry with the portable command only
    # when the first attempt did not produce a complete pair.
    code = run_command(extended, cwd=app_root, logger=logger,
                       cancel_file=cancel_file, label="generating the localhost certificate",
                       percent=75, done_percent=80, allow_failure=True,
                       popen=popen)
    if code != 0 or not (cert.exists() and key.exists()):
        run_command(common, cwd=app_root, logger=logger,
                    cancel_file=cancel_file, label="generating the localhost certificate",
                    percent=76, done_percent=80, popen=popen)
    if not (cert.exists() and key.exists()):
        raise SetupError("The localhost certificate was not generated.")
    secure_file(key)
    return resolved


def write_runtime(app_root: Path, *, venv_python: Path, pythonw: Path,
                  openssl: str | None, app_id: str = DEFAULT_APP_ID) -> None:
    manifest = app_root / "INSTALL_MANIFEST.json"
    upstream_ref = ""
    try:
        upstream_ref = str(json.loads(manifest.read_text(encoding="utf-8")).get("upstream_ref", ""))
    except (OSError, ValueError, TypeError):
        pass
    runtime = {
        "version": 1,
        "app_root": str(app_root),
        "venv_python": str(venv_python),
        "pythonw": str(pythonw),
        "claude": claude_launcher.resolve_claude(),
        "openssl": openssl,
        "app_user_model_id": app_id,
        "scheme": "https",
        "port": DEFAULT_PORT,
        "bind_host": DEFAULT_BIND_HOST,
        "origin": f"https://localhost:{DEFAULT_PORT}",
        "upstream_ref": upstream_ref,
        "overlay": "jarvis_win.hook",
    }
    (app_root / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS Windows runtime setup")
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--job-file", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--openssl")
    parser.add_argument("--progress-file")
    parser.add_argument("--cancel-file")
    parser.add_argument("--exit-file")
    parser.add_argument("--log-file")
    parser.add_argument("--skip-preflight", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_root = Path(args.app_root).resolve()
    log_file = Path(args.log_file or app_root / "logs" / "setup.log")
    progress_file = Path(args.progress_file or app_root / "logs" / "setup.progress")
    exit_file = Path(args.exit_file or app_root / "logs" / "setup.exitcode")
    cancel_file = Path(args.cancel_file) if args.cancel_file else None
    logger = SetupLogger(log_file, progress_file)
    job_path = Path(args.job_file)
    exit_code = 1
    try:
        (app_root / "data").mkdir(parents=True, exist_ok=True)
        (app_root / "logs").mkdir(parents=True, exist_ok=True)
        logger.log("Starting JARVIS runtime setup", 2)
        job = read_job(job_path)
        logger.redactor.add(job.get("fish_api_key"))
        secure_file(job_path)

        env_path = app_root / ".env"
        fish_key = job.get("fish_api_key", "")
        if not fish_key and not has_fish_key(env_path):
            raise SetupError("A Fish Audio API key is required; there is no voice without it.")
        updates: dict[str, str] = {}
        if fish_key:
            updates["FISH_API_KEY"] = fish_key
        if job.get("user_name"):
            updates["USER_NAME"] = job["user_name"]
        if job.get("brain_model"):
            updates["JARVIS_BRAIN_MODEL"] = job["brain_model"]
        if job.get("voice_id"):
            updates["FISH_VOICE_ID"] = job["voice_id"]
        update_env(env_path, updates)
        logger.log("Saved settings with a user-only access rule", 10)

        if sys.version_info < MIN_PYTHON and args.python == sys.executable:
            raise SetupError("Python 3.11 or newer is required.")
        venv_python, pythonw = ensure_venv(args.python, app_root, logger=logger,
                                           cancel_file=cancel_file)
        requirements = app_root / "requirements-windows.txt"
        if not requirements.exists():
            raise SetupError("requirements-windows.txt is missing from the installer payload.")
        run_command([str(venv_python), "-m", "pip", "install",
                     "--disable-pip-version-check", "-r", str(requirements)],
                    cwd=app_root, logger=logger, cancel_file=cancel_file,
                    label="installing Python packages", percent=30, done_percent=55)
        run_command([str(venv_python), "-m", "playwright", "install", "chromium"],
                    cwd=app_root, logger=logger, cancel_file=cancel_file,
                    label="installing Chromium for page sight", percent=60, done_percent=72)
        found_openssl = ensure_certificates(app_root, openssl=args.openssl,
                                            logger=logger, cancel_file=cancel_file)
        write_runtime(app_root, venv_python=venv_python, pythonw=pythonw,
                      openssl=found_openssl)
        logger.log("Runtime configuration written", 85)

        if not args.skip_preflight:
            preflight_script = Path(__file__).with_name("preflight_cli.py")
            run_command([str(venv_python), str(preflight_script),
                         "--app-root", str(app_root),
                         "--output", str(app_root / "logs" / "preflight.json"),
                         "--text-output", str(app_root / "logs" / "preflight.txt")],
                        cwd=app_root, logger=logger, cancel_file=cancel_file,
                        label="running first-run checks", percent=88, done_percent=96,
                        env=child_environment(app_root), allow_failure=True)
        logger.log("JARVIS setup is complete", 100)
        exit_code = 0
    except SetupCancelled as e:
        logger.log(str(e), 0)
        exit_code = 125
    except Exception as e:
        logger.log(f"Setup failed: {e}", 0)
        exit_code = 1
    finally:
        secure_delete(job_path)
        try:
            if cancel_file:
                Path(cancel_file).unlink(missing_ok=True)
        except OSError:
            pass
        exit_file.parent.mkdir(parents=True, exist_ok=True)
        exit_file.write_text(f"{exit_code}\n", encoding="ascii")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
