# JARVIS for Windows — installer + compatibility overlay

> Source-only per-user Windows installer and compatibility overlay for JARVIS;
> builds a private local payload from pinned upstream.

This repository builds a **per-user Windows installer** for the macOS-oriented
[JARVIS](https://github.com/ethanplusai/jarvis) project and supplies the
Windows platform layer it needs to actually run. It contains no copy of the
upstream application: a local build step creates the installer payload from a
private fork, adds this repo's overlay, and pre-builds the frontend.

> **Status:** implementation files are present; Linux unit/static checks and a
> pinned frontend build pass, but **Windows-unverified**. Phase 0 spikes, an
> Inno Setup compile, a clean Windows VM install, and SEAN's field test are
> still required. See [`docs/STATUS.md`](docs/STATUS.md).

## What is here

- `installer/JarvisSetup.iss` — Inno Setup wizard: PC checks, per-user
  prerequisites, masked Fish Audio key, cancellable/logged setup, Claude login
  hand-off, Start-menu shortcuts, and data-preserving uninstall.
- `jarvis_win/` — a non-invasive import hook plus Windows implementations for
  notifications, actions, preflight, screen sight, dialog identity, pid
  liveness, cross-session transport, native Claude spawning, launcher, setup,
  preflight CLI, and Phase 0 spike probes.
- `installer/scripts/` — fixed PowerShell helpers for system checks,
  prerequisites, secret ACLs, login hand-off, startup, and shutdown. The fixed
  toast script lives beside its Python caller in `jarvis_win/ShowToast.ps1`.
- `tools/build_package.py` — clones or copies the private fork, builds
  `frontend/dist`, writes Windows requirements, vendors an OpenSSL binary when
  available, and stages a payload for Inno Setup.
- `tests/` — stdlib `unittest` suite that runs on Linux; it tests safety
  properties and logic without a Windows desktop.
- `docs/` — the original plan, decisions, architecture, spikes, security
  model, build/install instructions, and honest verification status.

## Design in one paragraph

At install time the wizard installs Python 3.11+, Git for Windows, and the
**native** `claude.exe` through per-user WinGet packages; Node and the npm
`claude.cmd` shim are never used. It writes user settings into a tightly ACL'd
`.env`, creates a venv, installs Python requirements plus Pillow, installs
Playwright Chromium, generates a localhost certificate, and serves the
pre-built frontend from `https://localhost:8340` on loopback only. A
`sitecustomize` import hook patches nine upstream modules in memory so
`server.py` keeps its existing function signatures and outcome strings.

## Build

On a Windows build machine with Python 3.11+, Node (build-time only), Git, and
Inno Setup 6.4+:

```powershell
py -3 tools\build_package.py --upstream C:\src\jarvis-win
iscc .build\installer\JarvisSetup.iss
```

`--upstream` should point at a **private local fork**. If omitted, the build
script clones the public upstream at the pinned ref in `upstream.json` into
`.build/upstream`; do not publish that generated payload. The build script
also accepts `--openssl PATH\TO\openssl.exe`; Git for Windows ships one at
`Git\usr\bin\openssl.exe`. If no binary is provided, setup locates Git's
OpenSSL at runtime.

## Install

Double-click the generated `dist\JarvisSetup.exe`. No administrator rights are
needed; files go to `%LOCALAPPDATA%\Programs\Jarvis`. Chrome and a Fish Audio
API key are required. The final wizard page can open Claude Code for a one-time
login, start JARVIS, and add it to Startup. Updating means re-running the
installer over the top; `.env`, `data\`, memory, and certificates are kept.

## Test

```bash
python tools/run_tests.py
```

This runs 69 standard-library unit tests on any OS. The Windows VM and
field-test checklists are in [`docs/TESTING.md`](docs/TESTING.md).

## Licence

Installer/overlay code in this repository is MIT; see [`LICENSE`](LICENSE).
Upstream JARVIS is **personal/non-commercial use only**. The build script
copies its licence into the local payload as `UPSTREAM_LICENSE.txt`. Keep the
fork, payload, and compiled installer private/local unless the upstream author
grants a commercial licence. See [`NOTICE.md`](NOTICE.md).
