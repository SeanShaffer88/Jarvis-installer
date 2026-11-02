"""Frozen-runtime bootstrap: same .exe acts as GUI, server, and MCP child."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import core, patches, win
from .core import Paths

_LOG_HANDLE: Any = None


def configure_environment(paths: Paths, claude: str | None = None,
                          openssl: str | None = None,
                          ref: str = "") -> dict[str, str]:
    """Point upstream code at external data/.env and the frozen bundle."""
    env = dict(os.environ)
    core.apply_env_file(paths.env_file, env)
    core.scrub_anthropic(env)
    env.update({
        "JARVIS_ONECLICK": "1",
        "JARVIS_ONECLICK_APP_ROOT": str(paths.app_root),
        "JARVIS_APP_ROOT": str(paths.bundle),
        "JARVIS_ENV_FILE": str(paths.env_file),
        "JARVIS_DATA_DIR": str(paths.data_dir),
        "JARVIS_CLAUDE_PATH": claude or "",
        "JARVIS_OPENSSL": openssl or "",
        "JARVIS_UPSTREAM_REF": ref,
        "JARVIS_PORT": str(core.PORT),
        "JARVIS_SCHEME": "https",
        "JARVIS_BIND_HOST": core.BIND_HOST,
        "JARVIS_TOAST_APP_ID": core.APP_USER_MODEL_ID,
        "JARVIS_WINDOWS_OVERLAY": "1",
        "JARVIS_SKIP_PERMISSIONS": "true",
        "JARVIS_DEFAULT_BROWSER": "chrome",
        "JARVIS_BROWSER": "chrome",
        "PLAYWRIGHT_BROWSERS_PATH": str(paths.playwright),
        "PYTHONIOENCODING": "utf-8",
    })
    os.environ.clear()
    os.environ.update(env)
    return env


def copy_certificates(paths: Paths) -> None:
    """server.py expects certs beside its own file in the extracted bundle."""
    paths.bundle.mkdir(parents=True, exist_ok=True)
    if not (paths.cert.exists() and paths.key.exists()):
        raise RuntimeError("Localhost certificate is missing from the app root.")
    shutil.copy2(paths.cert, paths.bundle / "cert.pem")
    shutil.copy2(paths.key, paths.bundle / "key.pem")


def install_hidden_subprocess_patch() -> None:
    """Ensure every spawned helper inherits hidden-window creation flags."""
    if os.name != "nt" or getattr(asyncio, "_jarvis_oneclick_hidden", False):
        return
    original_exec = asyncio.create_subprocess_exec

    async def hidden_exec(*args: Any, **kwargs: Any):
        kwargs.setdefault("creationflags", win.hidden_creationflags())
        kwargs.setdefault("startupinfo", win.hidden_startupinfo())
        return await original_exec(*args, **kwargs)

    asyncio.create_subprocess_exec = hidden_exec
    asyncio._jarvis_oneclick_hidden = True

    if not getattr(subprocess, "_jarvis_oneclick_hidden", False):
        original_popen = subprocess.Popen

        class HiddenPopen(original_popen):  # type: ignore[valid-type,misc]
            def __init__(self, *a: Any, **kw: Any):
                kw.setdefault("creationflags", win.hidden_creationflags())
                kw.setdefault("startupinfo", win.hidden_startupinfo())
                super().__init__(*a, **kw)

        subprocess.Popen = HiddenPopen
        subprocess._jarvis_oneclick_hidden = True


def _redirect_stdio(log_path: Path) -> None:
    global _LOG_HANDLE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_HANDLE = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _LOG_HANDLE
    sys.stderr = _LOG_HANDLE


def run_server() -> int:
    """Hidden ``--server`` mode used by the GUI and Startup shortcut."""
    paths = Paths.from_env()
    claude = win.find_claude()
    openssl = win.find_openssl(paths)
    ref = ""
    if paths.manifest.exists():
        try:
            import json
            ref = str(json.loads(paths.manifest.read_text(encoding="utf-8"))
                      .get("upstream_ref", ""))
        except (OSError, ValueError, TypeError):
            ref = ""
    configure_environment(paths, claude, openssl, ref)
    copy_certificates(paths)
    install_hidden_subprocess_patch()
    _redirect_stdio(paths.logs_dir / "server.log")

    bundle = str(paths.bundle)
    if bundle not in sys.path:
        sys.path.insert(0, bundle)

    from jarvis_win import hook
    hook.install(app_root=paths.bundle, platform="win32")

    import server  # noqa: F401  (import applies the Windows overlay)
    patches.apply_all(exe=sys.executable)

    import uvicorn
    cert = paths.bundle / "cert.pem"
    key = paths.bundle / "key.pem"
    if not (cert.exists() and key.exists()):
        raise RuntimeError("Certificates were not staged beside server.py.")
    uvicorn.run("server:app", host=core.BIND_HOST, port=core.PORT,
                reload=False, log_level="info",
                ssl_certfile=str(cert), ssl_keyfile=str(key))
    return 0


def run_mcp() -> int:
    """Hidden ``--mcp`` mode; stdin/stdout remain the JSON-RPC channel."""
    paths = Paths.from_env()
    claude = win.find_claude()
    openssl = win.find_openssl(paths)
    configure_environment(paths, claude, openssl)
    bundle = str(paths.bundle)
    if bundle not in sys.path:
        sys.path.insert(0, bundle)
    import jarvis_mcp
    jarvis_mcp.main()
    return 0
