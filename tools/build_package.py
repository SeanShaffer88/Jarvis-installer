#!/usr/bin/env python3
"""Stage a private Inno Setup payload from upstream JARVIS plus this overlay.

The generated payload contains upstream source, its licence, and a pre-built
frontend. It is deliberately gitignored: keep the fork/payload/installer local
unless the upstream author grants a commercial licence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / ".build" / "installer"
DEFAULT_UPSTREAM_CHECKOUT = ROOT / ".build" / "upstream"

IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "node_modules", "dist", "build",
    ".env", ".env.local", "*.pem", "*.db", "*.db-shm", "*.db-wal", "*.log",
    ".agents", ".claude", ".arch", "context", "*.exe", "*.msi",
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(argv: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=str(cwd) if cwd else None, check=True)


def clone_upstream(repository: str, ref: str, destination: Path) -> Path:
    """Fetch exactly one local pinned commit, without creating a branch."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "init", str(destination)])
    run(["git", "-C", str(destination), "remote", "add", "origin", repository])
    run(["git", "-C", str(destination), "fetch", "--depth", "1", "origin", ref])
    run(["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"])
    return destination


def validate_upstream(source: Path) -> None:
    required = ["server.py", "requirements.txt", "LICENSE", "frontend/package.json"]
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise SystemExit("Upstream source is missing: " + ", ".join(missing))


def copy_upstream(source: Path, payload: Path) -> None:
    shutil.copytree(source, payload, ignore=IGNORE, dirs_exist_ok=True)
    # User data is never shipped; keep an empty data directory only.
    shutil.rmtree(payload / "data", ignore_errors=True)
    (payload / "data").mkdir(parents=True, exist_ok=True)
    (payload / "data" / ".gitkeep").write_text("", encoding="utf-8")
    shutil.copy2(source / "LICENSE", payload / "UPSTREAM_LICENSE.txt")
    shutil.copy2(ROOT / "LICENSE", payload / "INSTALLER_LICENSE.txt")
    (payload / "THIRD_PARTY_NOTICES.txt").write_text(
        "JARVIS upstream is (c) 2026 Ethan Rogers and is licensed for personal,\n"
        "educational, and non-commercial use only. See UPSTREAM_LICENSE.txt.\n"
        "Commercial use requires the upstream author's permission.\n\n"
        "The Windows installer and overlay are (c) 2026 Sean Shaffer, MIT.\n"
        "See INSTALLER_LICENSE.txt. This payload is local/private.\n",
        encoding="utf-8")


def copy_overlay(payload: Path) -> None:
    target = payload / "jarvis_win"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "jarvis_win", target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "jarvis_win" / "sitecustomize.py", payload / "sitecustomize.py")


def windows_requirements(source: Path, payload: Path) -> None:
    lines = (source / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if not any(line.strip().lower().startswith("pillow") for line in lines):
        lines.append("")
        lines.append("# Windows screen sight: ImageGrab, resize, and PNG encode.")
        lines.append("Pillow>=10.0.0")
    (payload / "requirements-windows.txt").write_text(
        "\n".join(line.rstrip() for line in lines).rstrip() + "\n", encoding="utf-8")


def run_npm(args: list[str], cwd: Path) -> None:
    if os.name == "nt":
        # npm is a .cmd shim on Windows; cmd.exe is the reliable build-time route.
        run(["cmd.exe", "/c", "npm", *args], cwd)
    else:
        run(["npm", *args], cwd)


def build_frontend(payload: Path, *, frontend_dist: Path | None,
                   skip_frontend: bool) -> bool:
    target = payload / "frontend" / "dist"
    shutil.rmtree(target, ignore_errors=True)
    if frontend_dist:
        dist = frontend_dist.resolve()
        if not (dist / "index.html").is_file() or not (dist / "dashboard.html").is_file():
            raise SystemExit("--frontend-dist must contain index.html and dashboard.html")
        shutil.copytree(dist, target)
        return True
    if skip_frontend:
        target.mkdir(parents=True, exist_ok=True)
        (target / "PLACEHOLDER.txt").write_text(
            "Test staging only: run build_package.py without --skip-frontend "
            "(or pass --frontend-dist) before compiling a real installer.\n",
            encoding="utf-8")
        return False
    frontend = payload / "frontend"
    if not (frontend / "package-lock.json").is_file():
        raise SystemExit("frontend/package-lock.json is missing; cannot run npm ci")
    run_npm(["ci"], frontend)
    run_npm(["run", "build"], frontend)
    return target.is_dir() and (target / "index.html").is_file()


def is_windows_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def openssl_candidates(explicit: Path | None) -> list[Path]:
    if explicit:
        return [explicit]
    candidates = [os.getenv("JARVIS_OPENSSL"), shutil.which("openssl.exe")]
    roots = [os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"),
             os.getenv("LOCALAPPDATA")]
    for root in roots:
        if root:
            candidates.append(str(Path(root) / "Git" / "usr" / "bin" / "openssl.exe"))
            candidates.append(str(Path(root) / "Programs" / "Git" / "usr" / "bin" / "openssl.exe"))
    return [Path(value) for value in candidates if value]


def vendor_openssl(payload: Path, explicit: Path | None) -> bool:
    tools = payload / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for candidate in openssl_candidates(explicit):
        if candidate.is_file() and is_windows_binary(candidate):
            shutil.copy2(candidate, tools / "openssl.exe")
            return True
    (tools / "README.txt").write_text(
        "No Windows openssl.exe was bundled at build time. setup_runtime.py will\n"
        "locate the openssl.exe installed with Git for Windows. For an offline\n"
        "package, rerun with --openssl C:\\Path\\To\\Git\\usr\\bin\\openssl.exe.\n",
        encoding="utf-8")
    return False


def stage_scripts(out: Path) -> None:
    scripts = out / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "installer" / "scripts").glob("*.ps1"):
        shutil.copy2(path, scripts / path.name)
    shutil.copy2(ROOT / "installer" / "scripts" / "README.md", scripts / "README.md")
    shutil.copy2(ROOT / "installer" / "prereqs.json", scripts / "prereqs.json")
    shutil.copy2(ROOT / "installer" / "JarvisSetup.iss", out / "JarvisSetup.iss")
    (out / "dist").mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifests(out: Path, payload: Path, *, version: dict, upstream: dict,
                    ref: str, frontend_prebuilt: bool, openssl_bundled: bool) -> None:
    install_manifest = {
        "installer_version": version["installer_version"],
        "overlay_protocol": version["overlay_protocol"],
        "app_user_model_id": version["app_user_model_id"],
        "api_port": version["api_port"],
        "bind_host": version["bind_host"],
        "upstream_repository": upstream["repository"],
        "upstream_ref": ref,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "frontend_prebuilt": frontend_prebuilt,
        "openssl_bundled": openssl_bundled,
        "prerequisite_strategy": "winget-user",
        "python_min_version": "3.11",
        "claude_min_version": "2.1.224",
        "native_claude_only": True,
        "node_needed": False,
        "license": "upstream personal/non-commercial; installer/overlay MIT",
    }
    (payload / "INSTALL_MANIFEST.json").write_text(
        json.dumps(install_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = []
    for path in sorted(p for p in payload.rglob("*") if p.is_file()):
        files.append({
            "path": path.relative_to(payload).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    build_manifest = {
        "installer_version": version["installer_version"],
        "upstream_ref": ref,
        "frontend_prebuilt": frontend_prebuilt,
        "openssl_bundled": openssl_bundled,
        "file_count": len(files),
        "files": files,
    }
    (out / "build-manifest.json").write_text(
        json.dumps(build_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--upstream", help="Path to a private local JARVIS fork")
    parser.add_argument("--ref", help="Override the pinned upstream ref")
    parser.add_argument("--frontend-dist", help="Use an already-built frontend/dist")
    parser.add_argument("--skip-frontend", action="store_true",
                        help="Test staging only; do not run npm and do not ship a real dist")
    parser.add_argument("--openssl", help="Path to a Windows openssl.exe to bundle")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    version = read_json(ROOT / "version.json")
    upstream = read_json(ROOT / "upstream.json")
    ref = args.ref or upstream["pinned_ref"]
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    payload = out / "payload"
    payload.mkdir(parents=True)

    source = (Path(args.upstream).resolve() if args.upstream
              else clone_upstream(upstream["repository"], ref, DEFAULT_UPSTREAM_CHECKOUT))
    validate_upstream(source)
    copy_upstream(source, payload)
    copy_overlay(payload)
    windows_requirements(source, payload)
    frontend_prebuilt = build_frontend(
        payload,
        frontend_dist=Path(args.frontend_dist) if args.frontend_dist else None,
        skip_frontend=args.skip_frontend)
    # npm ci creates node_modules on the build machine. The target PC must not
    # receive Node or Vite; only frontend/dist is shipped.
    shutil.rmtree(payload / "frontend" / "node_modules", ignore_errors=True)
    openssl_bundled = vendor_openssl(
        payload, Path(args.openssl) if args.openssl else None)
    stage_scripts(out)
    write_manifests(out, payload, version=version, upstream=upstream, ref=ref,
                    frontend_prebuilt=frontend_prebuilt,
                    openssl_bundled=openssl_bundled)
    print(f"Staged installer source: {out}")
    print(f"Frontend pre-built: {frontend_prebuilt}")
    print(f"Windows OpenSSL bundled: {openssl_bundled}")
    if not frontend_prebuilt:
        print("WARNING: --skip-frontend staging is not a release build.")
    print(f"Compile on Windows with: iscc {out / 'JarvisSetup.iss'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
