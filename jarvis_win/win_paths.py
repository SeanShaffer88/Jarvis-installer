"""Locate Windows executables without shelling out or trusting a shim.

Every function is importable on Linux for unit tests. Windows paths are
expanded from a supplied environment mapping where possible, so tests do not
need a Windows registry or filesystem layout.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable, Mapping

_VAR_RE = re.compile(r"%([A-Za-z0-9_()]+)%")
_SHIM_SUFFIXES = frozenset({".cmd", ".bat", ".ps1", ".vbs", ".js", ".py"})
_NATIVE_SUFFIXES = frozenset({".exe", ""})


def expand(value: str, env: Mapping[str, str] | None = None) -> str:
    """Expand ``%NAME%`` and ``~`` while preserving Windows-style separators."""
    if not value:
        return ""
    source = dict(os.environ)
    if env:
        source.update({str(k): str(v) for k, v in env.items()})

    def replace(match: re.Match[str]) -> str:
        return source.get(match.group(1), match.group(0))

    expanded = _VAR_RE.sub(replace, value)
    try:
        return os.path.expanduser(expanded)
    except Exception:
        return expanded


def _fs_path(value: str | os.PathLike[str]) -> str:
    """Translate Windows separators for filesystem checks on a POSIX test host."""
    text = str(value)
    return text.replace("\\", os.sep) if os.name != "nt" else text


def _resolved(value: str | os.PathLike[str]) -> str:
    return str(Path(_fs_path(value)).resolve())


def exists(path: str | os.PathLike[str] | None) -> bool:
    if not path:
        return False
    try:
        return Path(_fs_path(path)).is_file()
    except OSError:
        return False


def is_native_executable(path: str | os.PathLike[str] | None) -> bool:
    """True for a real ``.exe`` (or extensionless POSIX test binary).

    ``.cmd``/``.bat``/script shims are always rejected. This is the guard that
    keeps ``asyncio.create_subprocess_exec`` away from WinError 193.
    """
    if not exists(path):
        return False
    suffix = Path(_fs_path(path)).suffix.lower()
    if suffix in _SHIM_SUFFIXES:
        return False
    return suffix in _NATIVE_SUFFIXES


def is_windows_pe(path: str | os.PathLike[str] | None) -> bool:
    """Require a real Windows PE ``.exe``, not a script or POSIX ELF binary."""
    if not exists(path):
        return False
    candidate = Path(_fs_path(path))
    if candidate.suffix.lower() != ".exe":
        return False
    try:
        with candidate.open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def _candidates(values: Iterable[str | None], env: Mapping[str, str] | None) -> list[str]:
    out: list[str] = []
    for value in values:
        if value:
            candidate = expand(str(value), env)
            if candidate and candidate not in out:
                out.append(candidate)
    return out


def _program_files(env: Mapping[str, str] | None) -> list[str]:
    return _candidates(
        (
            "%ProgramFiles%",
            "%ProgramW6432%",
            "%ProgramFiles(x86)%",
            "%LOCALAPPDATA%",
            "%USERPROFILE%",
        ),
        env,
    )


def _registry_app_path(name: str) -> str | None:
    """Read the per-user or machine App Paths value when on Windows."""
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except Exception:
        return None
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "")
                if value and exists(value):
                    return str(value)
        except OSError:
            continue
    return None


def find_powershell(env: Mapping[str, str] | None = None,
                    which: Callable[[str], str | None] = shutil.which) -> str | None:
    for name in ("powershell.exe", "powershell", "pwsh.exe"):
        found = which(name)
        if found and is_native_executable(found):
            return _resolved(found)
    for candidate in _candidates(
            (r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe",
             r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"), env):
        if is_native_executable(candidate):
            return _resolved(candidate)
    return None


def find_windows_terminal(env: Mapping[str, str] | None = None,
                          which: Callable[[str], str | None] = shutil.which) -> str | None:
    found = which("wt.exe") or which("wt")
    if found and is_native_executable(found):
        return _resolved(found)
    for candidate in _candidates((r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe",), env):
        if is_native_executable(candidate):
            return _resolved(candidate)
    return None


def find_chrome(env: Mapping[str, str] | None = None,
                which: Callable[[str], str | None] = shutil.which) -> str | None:
    registry = _registry_app_path("chrome.exe")
    if registry:
        return registry
    for name in ("chrome.exe", "chrome"):
        found = which(name)
        if found and is_native_executable(found):
            return _resolved(found)
    roots = _program_files(env)
    paths = [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ]
    if roots:
        paths.extend(str(Path(_fs_path(root)) / "Google" / "Chrome" /
                         "Application" / "chrome.exe") for root in roots)
    for candidate in _candidates(paths, env):
        if is_native_executable(candidate):
            return _resolved(candidate)
    return None


def find_firefox(env: Mapping[str, str] | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> str | None:
    registry = _registry_app_path("firefox.exe")
    if registry:
        return registry
    for name in ("firefox.exe", "firefox"):
        found = which(name)
        if found and is_native_executable(found):
            return _resolved(found)
    paths = [r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
             r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"]
    for candidate in _candidates(paths, env):
        if is_native_executable(candidate):
            return _resolved(candidate)
    return None


def find_code(env: Mapping[str, str] | None = None,
              which: Callable[[str], str | None] = shutil.which) -> str | None:
    """Return a real VS Code ``.exe``; ``code.cmd`` is unusable here."""
    for name in ("Code.exe", "code.exe", "code"):
        found = which(name)
        if found and is_native_executable(found):
            return _resolved(found)
    paths = [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
        r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
    ]
    for candidate in _candidates(paths, env):
        if is_native_executable(candidate):
            return _resolved(candidate)
    return None


def find_claude(explicit: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None,
                which: Callable[[str], str | None] = shutil.which) -> str | None:
    """Return the native ``claude.exe`` path, or None. Never return a shim."""
    source = dict(os.environ)
    if env:
        source.update({str(k): str(v) for k, v in env.items()})

    if explicit:
        candidate = Path(_fs_path(expand(str(explicit), source)))
        if is_windows_pe(candidate):
            return str(candidate.resolve())

    configured = source.get("JARVIS_CLAUDE_PATH")
    if configured:
        candidate = Path(_fs_path(expand(str(configured), source)))
        if is_windows_pe(candidate):
            return str(candidate.resolve())

    found = which("claude.exe") or which("claude")
    if found:
        path = Path(_fs_path(found))
        if is_windows_pe(path):
            return str(path.resolve())
        # npm installs claude.cmd beside a potential native claude.exe.
        sibling = path.with_suffix(".exe")
        if is_windows_pe(sibling):
            return str(sibling.resolve())

    paths = [
        r"%USERPROFILE%\.local\bin\claude.exe",
        r"%LOCALAPPDATA%\Programs\Claude Code\claude.exe",
        r"%LOCALAPPDATA%\AnthropicClaudeCode\claude.exe",
        r"%APPDATA%\npm\claude.exe",
    ]
    for candidate in _candidates(paths, source):
        candidate_path = Path(_fs_path(candidate))
        if is_windows_pe(candidate_path):
            return str(candidate_path.resolve())
    return None


def find_openssl(app_root: str | os.PathLike[str] | None = None,
                 explicit: str | os.PathLike[str] | None = None,
                 env: Mapping[str, str] | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> str | None:
    """Locate openssl.exe: bundled copy first, then PATH, then Git for Windows."""
    source = dict(os.environ)
    if env:
        source.update({str(k): str(v) for k, v in env.items()})
    if explicit:
        candidate = Path(_fs_path(expand(str(explicit), source)))
        if is_windows_pe(candidate):
            return str(candidate.resolve())
    if app_root:
        bundled = Path(app_root) / "tools" / "openssl.exe"
        if is_windows_pe(bundled):
            return str(bundled.resolve())
    found = which("openssl.exe") or which("openssl")
    if found:
        path = Path(_fs_path(found))
        if is_windows_pe(path):
            return str(path.resolve())
    paths = [
        r"%ProgramFiles%\Git\usr\bin\openssl.exe",
        r"%ProgramFiles(x86)%\Git\usr\bin\openssl.exe",
        r"%LOCALAPPDATA%\Programs\Git\usr\bin\openssl.exe",
    ]
    for candidate in _candidates(paths, source):
        candidate_path = Path(_fs_path(candidate))
        if is_windows_pe(candidate_path):
            return str(candidate_path.resolve())
    return None
