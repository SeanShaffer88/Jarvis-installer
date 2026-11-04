"""Pure, cross-platform helpers for the one-click Windows bootstrapper.

This module deliberately has no ``tkinter``, ``PyInstaller``, ``win32``, or
``ctypes`` import. That lets the whole safety layer be unit-tested on Linux.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from . import (APP_USER_MODEL_ID, BIND_HOST, DASHBOARD_URL, HEALTH_URL,
               ONCLICK_ENV_VAR, ORIGIN, PORT, VOICE_URL)


def local_appdata(env: Mapping[str, str] | None = None, *,
                  platform: str | None = None) -> Path:
    """Return the per-user LocalAppData directory without expanding %Vars%."""
    source = dict(os.environ if env is None else env)
    raw = source.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    profile = source.get("USERPROFILE")
    if profile:
        return Path(profile) / "AppData" / "Local"
    active = platform or sys.platform
    if active == "win32":
        return Path.home() / "AppData" / "Local"
    return Path.home() / ".local" / "share"


def app_root(env: Mapping[str, str] | None = None, *,
             platform: str | None = None) -> Path:
    """Fixed per-user install root; no install-location prompt."""
    override = (dict(os.environ if env is None else env)
                .get(ONCLICK_ENV_VAR, "").strip())
    if override:
        return Path(override)
    return local_appdata(env, platform=platform) / "Programs" / "Jarvis"


def bundle_root() -> Path:
    """Directory containing the frozen upstream app inside the .exe."""
    override = os.getenv("JARVIS_ONECLICK_BUNDLE", "").strip()
    if override:
        return Path(override)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "app"
    return Path(__file__).resolve().parent.parent / ".build" / "oneclick" / "app"


def appdata_roaming(env: Mapping[str, str] | None = None) -> Path:
    source = dict(os.environ if env is None else env)
    raw = source.get("APPDATA")
    if raw:
        return Path(raw)
    return local_appdata(env).parent / "Roaming"


@dataclass(frozen=True)
class Paths:
    """Every path the one-click app reads or writes."""

    app_root: Path
    bundle: Path
    env_file: Path
    data_dir: Path
    logs_dir: Path
    cert: Path
    key: Path
    runtime: Path
    pid: Path
    startup: Path
    openssl: Path
    playwright: Path
    frontend: Path
    server: Path
    mcp: Path
    manifest: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *,
                 bundle: str | os.PathLike[str] | None = None,
                 platform: str | None = None) -> "Paths":
        root = app_root(env, platform=platform)
        b = Path(bundle) if bundle else bundle_root()
        return cls(
            app_root=root,
            bundle=b,
            env_file=root / ".env",
            data_dir=root / "data",
            logs_dir=root / "logs",
            cert=root / "cert.pem",
            key=root / "key.pem",
            runtime=root / "runtime.json",
            pid=root / "jarvis.pid",
            startup=(appdata_roaming(env) / "Microsoft" / "Windows"
                     / "Start Menu" / "Programs" / "Startup" / "JARVIS.lnk"),
            openssl=b / "tools" / "openssl.exe",
            playwright=b.parent / "ms-playwright",
            frontend=b / "frontend" / "dist",
            server=b / "server.py",
            mcp=b / "jarvis_mcp.py",
            manifest=b / "ONCLICK_MANIFEST.json",
        )


def parse_env(text: str) -> list[tuple[str, str]]:
    """The same conservative .env grammar as upstream server.py."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.append((key.strip(), value.strip().strip('"').strip("'")))
    return out


def read_env(path: str | os.PathLike[str]) -> dict[str, str]:
    try:
        return dict(parse_env(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeError):
        return {}


def apply_env_file(path: str | os.PathLike[str],
                   environ: dict[str, str] | None = None) -> dict[str, str]:
    """Load the external .env into the process before importing server.py."""
    target = os.environ if environ is None else environ
    env_path = Path(path)
    pairs = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else []
    for key, value in pairs:
        target.setdefault(key, value)
    return target


def scrub_anthropic(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Remove inherited API keys; Claude Code must use the browser sign-in."""
    target = os.environ if environ is None else environ
    for key in [k for k in target
                if k.startswith("ANTHROPIC_") or k in ("CLAUDECODE",)
                or k.startswith("CLAUDE_CODE_")]:
        target.pop(key, None)
    return target


def update_env(path: str | os.PathLike[str], updates: Mapping[str, str], *,
               acl: Callable[[Path], None] | None = None) -> Path:
    """Update settings; acl receives an empty temporary file and must return None."""
    return _update_env_with_store(path, updates, acl=acl, store=_EnvStore())


class EnvPersistenceError(RuntimeError):
    """Sanitized failure with internal primary-error and cleanup evidence."""

    def __init__(self, stage, primary, cleanup_failed=False):
        super().__init__("The voice settings could not be saved securely.")
        self.stage = stage
        self.primary = primary
        self.cleanup_failed = cleanup_failed or getattr(primary, "cleanup_failed", False)


class _EnvStore:
    def begin(self, path):
        return _EnvTransaction(path)


class _EnvTransaction:
    def __init__(self, path):
        self.path = path
        self.committed = False
        self.original = path.read_text(encoding="utf-8") if path.exists() else None
        fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        self.temp_path = Path(name)
        self.fd = fd
        self.identity = os.fstat(fd)

    def check_identity(self):
        current = self.temp_path.lstat()
        if not os.path.samestat(self.identity, current):
            raise OSError("Temporary file identity changed")

    def write_all(self, content):
        view = memoryview(content)
        while view:
            count = os.write(self.fd, view)
            if count == 0:
                raise OSError("Incomplete settings write")
            view = view[count:]

    def flush(self):
        os.fsync(self.fd)

    def publish(self):
        self.check_identity()
        self.close()
        os.replace(self.temp_path, self.path)
        self.committed = True

    def abort(self):
        if not self.committed:
            self.check_identity()
            self.close()
            self.temp_path.unlink()

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)


def _update_env_with_store(path, updates, *, acl, store) -> Path:
    env_path = Path(path)
    transaction = None
    stage = "begin"
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        transaction = store.begin(env_path)
        stage = "acl"
        if acl is not None and acl(transaction.temp_path) is not None:
            raise TypeError("ACL callback must return None")
        stage = "identity"
        transaction.check_identity()
        lines = (transaction.original.splitlines() if transaction.original is not None
                 else ["# JARVIS one-click settings", ""])
        content = _render_env(lines, updates)
        stage = "write"
        transaction.write_all(content)
        stage = "flush"
        transaction.flush()
        stage = "publish"
        transaction.publish()
        stage = "close"
        transaction.close()
    except Exception as primary:
        cleanup_failed = False
        if transaction is not None:
            try:
                transaction.abort()
            except Exception:
                cleanup_failed = True
            try:
                transaction.close()
            except Exception:
                cleanup_failed = True
        raise EnvPersistenceError(stage, primary, cleanup_failed) from None
    return env_path


def _render_env(lines, updates):
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
    return ("\n".join(out).rstrip() + "\n").encode("utf-8")


class Redactor:
    """Scrub exact secrets, .env lines, and JSON values before any log write."""

    def __init__(self, secrets: Iterable[str] = ()):
        self.secrets = [str(s) for s in secrets if s]

    def redact(self, text: str) -> str:
        result = str(text)
        for secret in self.secrets:
            result = result.replace(secret, "[REDACTED]")
        result = re.sub(r"(?im)^(FISH_API_KEY\s*=\s*).*$",
                        r"\1[REDACTED]", result)
        result = re.sub(r'(?i)("fish_api_key"\s*:\s*")[^"]*(")',
                        r"\1[REDACTED]\2", result)
        return result


def acl_argv(path: str | os.PathLike[str],
             env: Mapping[str, str] | None = None) -> list[str]:
    """User-only ACL argv; the secret itself is never on a command line."""
    source = dict(os.environ if env is None else env)
    user = source.get("USERNAME") or "USER"
    domain = source.get("USERDOMAIN")
    principal = f"{domain}\\{user}" if domain else user
    return ["icacls", str(Path(path)), "/inheritance:r",
            "/grant:r", f"{principal}:(F)"]


def certificate_argv(openssl: str | os.PathLike[str],
                     cert: str | os.PathLike[str],
                     key: str | os.PathLike[str], *, san: bool = True) -> list[str]:
    argv = [str(openssl), "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key), "-out", str(cert), "-days", "365",
            "-nodes", "-subj", "/CN=localhost"]
    if san:
        argv += ["-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"]
    return argv


def winget_argv(package_id: str) -> list[str]:
    return ["winget", "install", "--id", package_id, "--exact",
            "--scope", "user", "--silent",
            "--accept-package-agreements", "--accept-source-agreements"]


def chrome_candidates(env: Mapping[str, str] | None = None) -> list[Path]:
    source = dict(os.environ if env is None else env)
    found = shutil.which("chrome.exe") or shutil.which("chrome")
    roots = [source.get("ProgramFiles"), source.get("ProgramFiles(x86)"),
             source.get("LOCALAPPDATA")]
    out: list[Path] = []
    if found:
        out.append(Path(found))
    for root in roots:
        if not root:
            continue
        out += [Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    return out


def claude_candidates(env: Mapping[str, str] | None = None) -> list[Path]:
    source = dict(os.environ if env is None else env)
    home = Path(source["USERPROFILE"]) if source.get("USERPROFILE") else Path.home()
    local = Path(source["LOCALAPPDATA"]) if source.get("LOCALAPPDATA") else home / "AppData" / "Local"
    found = shutil.which("claude.exe")
    out: list[Path] = []
    if found:
        out.append(Path(found))
    out += [home / ".local" / "bin" / "claude.exe",
            local / "Programs" / "Claude Code" / "claude.exe",
            local / "Anthropic" / "claude.exe",
            local / "Microsoft" / "WinGet" / "Links" / "claude.exe"]
    return out


def is_native_exe(path: str | os.PathLike[str] | None) -> bool:
    """A real Windows PE .exe, not a .cmd/.bat/.ps1 shim or a Unix ELF."""
    if not path:
        return False
    candidate = Path(path)
    if candidate.suffix.lower() != ".exe" or not candidate.is_file():
        return False
    try:
        with candidate.open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def runtime_document(paths: Paths, claude: str | None,
                     openssl: str | None, ref: str) -> dict[str, object]:
    return {
        "version": 2,
        "mode": "one-click-frozen",
        "app_root": str(paths.app_root),
        "bundle": str(paths.bundle),
        "app_user_model_id": APP_USER_MODEL_ID,
        "scheme": "https",
        "port": PORT,
        "bind_host": BIND_HOST,
        "origin": ORIGIN,
        "health_url": HEALTH_URL,
        "voice_url": VOICE_URL,
        "dashboard_url": DASHBOARD_URL,
        "claude": claude,
        "openssl": openssl,
        "playwright_browsers": str(paths.playwright),
        "upstream_ref": ref,
        "python_runtime": "embedded",
        "node_runtime": False,
        "venv": False,
        "inno_setup": False,
    }


FORBIDDEN_PAYLOAD_NAMES = {
    ".env", "cert.pem", "key.pem", "runtime.json", "jarvis.pid",
    "setup.cancel", "setup.exitcode", "setup.progress", "jarvis.db",
    "JarvisSetup.iss", "JarvisSetup.exe",
}
FORBIDDEN_PAYLOAD_SUFFIXES = {".pem", ".pfx", ".p12", ".db", ".log"}
FORBIDDEN_PAYLOAD_PARTS = {"node_modules", "__pycache__", ".git", ".venv", "venv"}


def scan_payload(root: str | os.PathLike[str]) -> list[str]:
    """Return paths that must never be embedded in a public .exe payload."""
    base = Path(root)
    problems: list[str] = []
    for path in base.rglob("*"):
        rel = path.relative_to(base)
        parts = {part.lower() for part in rel.parts}
        name = path.name
        lower = name.lower()
        if parts & FORBIDDEN_PAYLOAD_PARTS:
            problems.append(str(rel))
            continue
        if lower in FORBIDDEN_PAYLOAD_NAMES:
            problems.append(str(rel))
            continue
        if path.is_file() and (path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES
                               or lower.endswith(".iss")):
            problems.append(str(rel))
            continue
        if path.is_file() and lower.endswith(".exe") and rel.as_posix() != "tools/openssl.exe":
            problems.append(str(rel))
        if path.is_file() and lower.endswith(".ps1") and rel.as_posix() != "jarvis_win/ShowToast.ps1":
            problems.append(str(rel))
    return sorted(set(problems))


def sha256_manifest(root: str | os.PathLike[str]) -> list[dict[str, str]]:
    base = Path(root)
    out: list[dict[str, str]] = []
    for path in sorted(base.rglob("*"), key=lambda p: p.relative_to(base).as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append({"path": path.relative_to(base).as_posix(), "sha256": digest})
    return out


def json_dumps(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"
