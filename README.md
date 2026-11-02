# JARVIS for Windows — installer + compatibility overlay

> Source-only per-user Windows installer and compatibility overlay for JARVIS;
> builds a private local payload from pinned upstream.

**JARVIS for Windows** is a source-only installer and Windows compatibility
layer for the macOS-oriented [JARVIS](https://github.com/ethanplusai/jarvis)
voice assistant. It sets up a complete per-user installation on Windows and
patches the macOS-only system integrations in memory, so JARVIS can actually
run on Windows rather than merely install.

This repository contains **no copy of the upstream application**. A local build
step stages a private payload from a pinned upstream checkout, builds the
frontend, adds this repository's overlay, and writes the files Inno Setup needs.
Upstream JARVIS remains licensed for personal, educational, and non-commercial
use only; the generated payload and compiled installer should stay private and
local unless its author grants a commercial licence.

> **Status:** implementation files are present; Linux unit/static checks and a
> pinned frontend build pass, but **Windows-unverified**. Phase 0 spikes, an
> Inno Setup compile, a clean Windows VM install, and SEAN's field test are
> still required. The one-click `JarvisOneClick.exe` path is also **Unverified**
> and has not been compiled in this Linux sandbox. See
> [Verification status](#verification-status), [`docs/STATUS.md`](docs/STATUS.md),
> and [`docs/ONECLICK.md`](docs/ONECLICK.md).

---

## Table of contents

- [What this repository is](#what-this-repository-is)
- [What it costs](#what-it-costs)
- [What it does](#what-it-does)
- [What it deliberately does not do](#what-it-deliberately-does-not-do)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [One-click .exe (end-user path)](#one-click-exe-end-user-path)
- [Build the installer](#build-the-installer)
- [Install on Windows](#install-on-windows)
- [Configuration](#configuration)
- [Runtime layout](#runtime-layout)
- [Connections: bring your own](#connections-bring-your-own)
- [Make it yours](#make-it-yours)
- [How it works](#how-it-works)
- [Windows port map](#windows-port-map)
- [Security and trust decisions](#security-and-trust-decisions)
- [Testing and verification](#testing-and-verification)
- [Phase 0 spikes](#phase-0-spikes)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Repository layout](#repository-layout)
- [Documentation index](#documentation-index)
- [Frequently asked questions](#frequently-asked-questions)
- [Verification status](#verification-status)
- [Licence, credits, and disclaimer](#licence-credits-and-disclaimer)

---

## What this repository is

The upstream project is a voice assistant that sits on top of Claude Code. It
was designed for macOS: Terminal control, notifications, screenshots, and
window listing all go through AppleScript, and Claude Code is assumed to be a
Unix-friendly CLI. This repository solves two separate problems:

1. **Distribution.** It builds a single per-user Windows installer that checks
   the PC, installs missing prerequisites, writes the Fish Audio key safely,
   creates a venv, installs Python packages and Playwright Chromium, generates
   a localhost certificate, sets up shortcuts, and hands off Claude login.
2. **Compatibility.** It provides a `jarvis_win` overlay that patches nine
   upstream modules in memory on Windows. The upstream source files are not
   edited, the macOS implementations remain untouched, and `server.py` keeps
   its existing function signatures, dataclasses, and outcome strings.

The result is intended for one person — SEAN — on his own Windows PC. It is not
a general-purpose public distribution of JARVIS, and it does not include the
upstream application in Git.

The original plan is preserved in [`docs/ORIGINAL_PLAN.md`](docs/ORIGINAL_PLAN.md).
The four decisions confirmed before implementation are recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md): full scope, Windows Terminal,
Pillow for screenshots, and safe 4a permission-prompt alerts.

---

## What it costs

**No Anthropic API key is used on the voice path.** JARVIS's brain still runs
as a Claude Code process on the user's Claude subscription. This installer does
not add an Anthropic API key, does not ask for one, and does not change the
upstream environment-scrubbing behaviour that removes `ANTHROPIC_*` variables
from spawned Claude processes. A leftover Anthropic key is treated as a
preflight warning, not a hidden billing route.

**One paid service is required: [Fish Audio](https://fish.audio).** JARVIS uses
it for speech. There is no fallback voice. The installer asks for
`FISH_API_KEY` in a masked field and writes it to an ACL'd `.env`. Without it,
JARVIS can install and start, but spoken replies become text in the browser.

The rest of the runtime is local:

| Cost | Who pays | Notes |
|---|---|---|
| Claude Code subscription | User | The brain and builds use the user's existing login, not an API key. |
| Fish Audio | User | One required key gives JARVIS his voice. |
| Python 3.11+ | Free | Installed per-user through WinGet only if missing. |
| Git for Windows | Free | Installed per-user for project work and for `openssl.exe`. |
| Native Claude Code | Included with subscription | Installed through `Anthropic.ClaudeCode`; Node is not used. |
| Google Chrome | Free | Hard requirement for microphone input. |
| Node.js + npm | Build machine only | Used to build `frontend/dist`; never installed on the target PC. |
| Inno Setup 6.4+ | Build machine only | Used to compile `JarvisSetup.exe`; not needed on the target PC. |

The installer is per-user and uses signed WinGet packages. It does not install
a background updater, telemetry service, scheduled task, or system-wide
service.

---

## What it does

### Installer flow

1. Checks Windows 10 version 1809 / build 17763 or newer, Chrome, and about
   1 GB of free space on the `%LOCALAPPDATA%` drive.
2. Installs only missing prerequisites with per-user WinGet packages:
   Python 3.11+, Git for Windows, and native Claude Code 2.1.224+.
3. Rejects `claude.cmd` / `claude.bat` npm shims. `asyncio.create_subprocess_exec`
   cannot spawn those directly, and silently substituting a shell would widen
   the trust boundary.
4. Collects a masked Fish Audio key and optional name, brain model, and voice
   ID. On reinstall, leaving the key blank preserves the existing `.env`.
5. Writes settings through a tightly ACL'd temporary job file. The key is never
   a command-line argument and never appears in a progress line or log.
6. Stops a verified running JARVIS instance before an over-the-top update.
7. Copies the pre-built application payload to
   `%LOCALAPPDATA%\Programs\Jarvis`.
8. Creates `.venv`, installs `requirements-windows.txt` (upstream requirements
   plus Pillow), installs Playwright Chromium, generates `cert.pem` and
   `key.pem`, creates `data/`, writes `runtime.json`, and runs plain-words
   preflight.
9. Shows a Claude login hand-off page with **Open Claude Code to sign in** and
   **Check again** buttons. A not-logged-in state does not trap the user.
10. Offers **Start JARVIS now** and **Start with Windows**, then creates three
    Start-menu shortcuts with an explicit AppUserModelID for toasts.

### Runtime flow

The hidden launcher starts `server.py --host 127.0.0.1`, waits for
`GET /api/health` on `https://localhost:8340`, and opens Chrome at the voice
page. The dashboard is on the same origin at `/dashboard`, which avoids the
Vite dev-server port trap where Chrome's microphone grant is scoped to a
changing `localhost:5173` / `5174` origin.

### Windows compatibility flow

On Windows, root `sitecustomize.py` installs a `sys.meta_path` finder. When one
of nine upstream modules is imported, the real loader runs first and the
Windows patch is applied in place:

| Upstream module | Windows patch |
|---|---|
| `dialog` | safe 4a identity probe, closed vocabulary, no keystrokes |
| `notifier` | fixed-script WinRT toast with argv-only untrusted text |
| `actions` | `wt.exe`, PowerShell, Chrome, Firefox, VS Code argument lists |
| `screen` | Pillow `ImageGrab`, blank-frame refusal, `EnumWindows` listing |
| `preflight` | native Claude detection, Windows credentials file, neutral grants |
| `session_watch` | `OpenProcess` / `GetExitCodeProcess` liveness |
| `session_steer` | AF_UNIX or named-pipe transport with the same outcome strings |
| `brain` | native `claude.exe` command rewriting |
| `run_executor` | native `claude.exe` command rewriting |

The hook is inert on macOS and Linux. No upstream file is modified.

---

## What it deliberately does not do

- **Does not commit upstream source.** This repository is public; upstream
  JARVIS is personal/non-commercial only. The payload is generated locally and
  gitignored.
- **Does not install Node on the target PC.** Node and Vite are build-time
  tools. Runtime serves static `frontend/dist` from `server.py`.
- **Does not use `claude.cmd`.** The npm shim is rejected, not wrapped in
  `cmd.exe`.
- **Does not ask for administrator rights.** Files and shortcuts live in the
  user's profile.
- **Does not bind to `0.0.0.0`.** The server stays on `127.0.0.1`, preserving
  the upstream loopback trust model.
- **Does not send keystrokes.** Phase 4b `SendInput` automation is not built.
  Safe 4a displays the session and key aloud; the human presses the key.
- **Does not fake Chrome tab information.** `get_chrome_tab_info()` returns
  `{}` on Windows v1 rather than scraping UI.
- **Does not guess a cross-session transport.** Named pipes and AF_UNIX paths
  are supported, but Spike A must prove what Windows Claude Code publishes.
- **Does not auto-update or nag.** Updating means rerunning a newly built
  installer over the top.
- **Does not claim Windows support is verified.** Linux unit tests and a real
  frontend build are not a Windows VM or field-test verdict.

---

## Requirements

### Target PC

| Requirement | Minimum | Why |
|---|---:|---|
| Windows | 10 version 1809, build 17763 | Inno Setup `MinVersion` and native Claude Code support. |
| Architecture | x64-compatible | Inno Setup `ArchitecturesAllowed=x64compatible`. |
| Google Chrome | Current stable | Web Speech API microphone input; no fallback browser. |
| Disk | ~1 GB free on `%LOCALAPPDATA%` drive | Venv, Chromium, frontend, certificates, and data. |
| Claude Code | Native 2.1.224+ | Brain and builds spawn `claude.exe`. |
| Claude login | One-time manual sign-in | JARVIS uses the user's subscription. |
| Fish Audio | API key | Required for spoken replies. |
| WinGet / App Installer | Present | Used for signed per-user prerequisite packages. |
| Administrator rights | Not required | The install is per-user. |
| Node.js | Not required | No Vite dev server at runtime. |

### Build machine

| Requirement | Purpose |
|---|---|
| Windows 10 1809+ or Windows 11 | Match the target and use Windows `openssl.exe`. |
| Python 3.11+ with tkinter | Run the builders, the GUI builder, and unit suite. |
| Git | Fetch a pinned upstream ref or read a private fork. |
| Node.js + npm | `npm ci` and `npm run build` produce `frontend/dist`. |
| Inno Setup 6.4+ | Compile `JarvisSetup.iss` into `JarvisSetup.exe`; not needed for the one-click path. |
| PyInstaller | Compile the one-file `JarvisOneClick.exe` on Windows. |
| Playwright + Chromium | Embed browser binaries for screen/page tools. |
| Private local JARVIS fork | Preferred source for the local payload. |
| Windows `openssl.exe` | Required for the one-click exe; Git for Windows supplies one. |

`installer/prereqs.json` pins the WinGet strategy and package IDs.
`upstream.json` pins the upstream ref inspected for the plan:
`16e37bd801eb797798e02540665f8b3804b0fe14`.
`version.json` records installer version `0.1.0`, overlay protocol `1`,
AppUserModelID `SeanShaffer.Jarvis.Windows`, port `8340`, and bind host
`127.0.0.1`.

---

## Quick start

### Build and compile on a Windows build machine

```powershell
git clone https://github.com/SeanShaffer88/Jarvis-installer.git
cd Jarvis-installer
py -3 tools\build_package.py --upstream C:\src\jarvis-win --openssl "C:\Program Files\Git\usr\bin\openssl.exe"
iscc .build\installer\JarvisSetup.iss
```

The compiled installer is written to `.build\installer\dist\JarvisSetup.exe`.

### Install on SEAN's PC

```powershell
.\dist\JarvisSetup.exe
```

Double-clicking works too. No elevation is needed. Chrome and a Fish Audio key
are required. The final page opens Claude Code for login and can start JARVIS.

### Run tests on any OS

```bash
python tools/run_tests.py
python tools/lint_iss.py
```

The 100-test suite uses only the Python standard library and runs on Linux,
macOS, or Windows.

---

## One-click .exe (end-user path)

The Inno Setup wizard below is the original full-control path. The new
end-user path is a **single private `JarvisOneClick.exe`** built from this
source on a Windows machine. It is described in detail in
[`docs/ONECLICK.md`](docs/ONECLICK.md).

What SEAN does on the target PC:

1. Double-click `JarvisOneClick.exe`.
2. Enter the Fish Audio API key in a masked field.
3. If Claude Code is not already signed in, sign in through the browser window
   and click **I've signed in**.
4. Accept Chrome's one-time localhost certificate and microphone prompts.
5. Use JARVIS at `https://localhost:8340/`.

There is no Terminal, PowerShell, VS Code, Git Bash, Inno Setup, Node runtime,
Python install, pip command, or command line to use. Hidden helpers run with no
console window. Subsequent launches show no settings prompt at all. Chrome and
native Claude Code are installed silently through per-user WinGet only if
missing. The `.exe` embeds the private upstream payload, Python runtime,
`frontend/dist`, Windows overlay, `openssl.exe`, and Playwright Chromium.

Build it on a Windows build machine by double-clicking
[`tools/build_oneclick_gui.pyw`](tools/build_oneclick_gui.pyw) and selecting
the private JARVIS fork. The output is
`.build\oneclick\dist\JarvisOneClick.exe`. The builder silently installs
PyInstaller/Playwright if missing, prepares Chromium, stages the payload, and
compiles the one-file windowed app. A development-only command exists at
`python -m tools.build_oneclick --upstream C:\src\jarvis-win --compile`, but
the GUI builder is the intended no-console route.

This Linux sandbox contains no PyInstaller, tkinter, Windows toolchain, or
compiled binary, so **no runnable `.exe` is produced here**. The source,
Windows build script, GUI builder, tests, and docs are complete; Windows
behaviour remains **Unverified**. The compiled one-click exe contains upstream
JARVIS source and must stay private/local under the upstream
personal/non-commercial licence.

---

## Build the installer

The build script is the boundary between this public repository and the private
upstream application. It never copies upstream source into Git.

```powershell
py -3 tools\build_package.py --upstream C:\src\jarvis-win
```

Common options:

| Option | Meaning |
|---|---|
| `--upstream PATH` | Use a private local JARVIS fork. Recommended. |
| `--ref SHA` | Override the pinned ref in `upstream.json`. |
| `--frontend-dist PATH` | Use an already-built `frontend/dist`. |
| `--skip-frontend` | Test staging only; writes a placeholder `dist`. Do not compile for release. |
| `--openssl PATH` | Bundle a Windows PE `openssl.exe` into `payload\tools`. |
| `--out PATH` | Change the staging directory. Default: `.build\installer`. |

Without `--upstream`, the script fetches exactly one pinned commit into
`.build/upstream` using `git init` + shallow `fetch` + detached checkout. It
does not create a branch in this repository.

The staging tree is:

```text
.build\installer\
  JarvisSetup.iss
  scripts\                 extracted PowerShell helpers + prereqs.json
  payload\                 generated app root
    server.py              upstream server, local payload only
    frontend\dist\         pre-built voice page + dashboard
    jarvis_win\            Windows overlay
    sitecustomize.py       installs the Windows import hook
    requirements-windows.txt
    tools\openssl.exe      optional bundled OpenSSL
    UPSTREAM_LICENSE.txt
    INSTALLER_LICENSE.txt
    THIRD_PARTY_NOTICES.txt
    INSTALL_MANIFEST.json
  build-manifest.json      SHA-256 of every payload file
  dist\                    ISCC output directory
```

The build script:

1. Copies the upstream tree while ignoring `.git`, `node_modules`, `dist`,
   `.env`, certificates, databases, logs, caches, and private runtime data.
2. Replaces the payload's `data/` with an empty directory and `.gitkeep`.
3. Copies the upstream licence as `UPSTREAM_LICENSE.txt` and this repository's
   MIT licence as `INSTALLER_LICENSE.txt`.
4. Copies `jarvis_win/` and installs `jarvis_win/sitecustomize.py` at the
   payload root.
5. Writes `requirements-windows.txt` from upstream `requirements.txt` plus
   `Pillow>=10.0.0`.
6. Runs `npm ci` and `npm run build` in `frontend/`, then removes
   `frontend/node_modules`. Only `frontend/dist` ships.
7. Bundles a Windows `openssl.exe` when one is supplied or found.
8. Copies the Inno Setup script and PowerShell helpers.
9. Writes `INSTALL_MANIFEST.json` and `build-manifest.json`.

`npm ci` may report advisories in upstream build-only dev dependencies. Review
them against the pinned upstream ref; do not run `npm audit fix` blindly. No
Node or Vite runtime reaches the target PC.

Compile with Inno Setup 6.4 or newer:

```powershell
cd .build\installer
iscc JarvisSetup.iss
```

Do not attach the generated payload or `JarvisSetup.exe` to a public GitHub
release without the upstream author's permission. See
[`docs/BUILDING.md`](docs/BUILDING.md).

---

## Install on Windows

The wizard is intentionally linear and plain-spoken.

### 1. Checking your PC

`Check-System.ps1` writes `Status=OK|FAIL` and plain words. Windows version,
Chrome, and disk space are checked before Next is enabled. Chrome is a hard
requirement because the microphone uses Chrome's Web Speech API.

### 2. Prerequisites

`InstallPrereqs.ps1` checks first, then installs only missing per-user WinGet
packages:

```text
Python.Python.3.12
Git.Git
Anthropic.ClaudeCode
```

It refreshes the user PATH, verifies Python 3.11+ and Claude Code 2.1.224+,
and rejects `.cmd` shims. No `irm | iex`, no npm global install, no WSL, and
no elevation.

### 3. Voice settings

The masked fields are:

| Field | Required | Written as |
|---|---|---|
| Fish Audio API key | First install only | `FISH_API_KEY` |
| Your name | Optional | `USER_NAME` |
| Brain model | Optional, default `sonnet` | `JARVIS_BRAIN_MODEL` |
| Fish voice ID | Optional | `FISH_VOICE_ID` |

`SetSecretAcl.ps1` creates an empty temporary JSON job file with inheritance
removed before the wizard writes the key. `setup_runtime.py` reads, overwrites,
and deletes that file in `finally`.

### 4. File install and cancellable setup

The payload goes to `%LOCALAPPDATA%\Programs\Jarvis`. A verified running server
is stopped first. A hidden setup process then:

- creates `.venv`;
- pip-installs Windows requirements plus Pillow;
- installs Playwright Chromium;
- generates a self-signed localhost certificate;
- writes `runtime.json`;
- runs plain-words preflight.

Progress and cancel sentinels keep the wizard responsive. Cancel terminates the
current child and deletes the temporary key file. Every child-output line goes
through a redactor that scrubs exact secret values, `FISH_API_KEY=...` lines,
and JSON `fish_api_key` values.

### 5. Claude login hand-off

JARVIS cannot sign in for you. The wizard opens native Claude Code in Windows
Terminal — or a console if `wt.exe` is missing — and provides **Check again**
to rerun preflight live. A not-logged-in state does not block finishing the
install.

### 6. Finish and shortcuts

| Shortcut | Action |
|---|---|
| JARVIS | Hidden server, health wait, opens the voice page. |
| JARVIS Dashboard | Starts/uses the server and opens `/dashboard`. |
| Stop JARVIS | Verifies PID command line before `taskkill /T`. |

Each shortcut carries `AppUserModelID: SeanShaffer.Jarvis.Windows`, which a
non-packaged application needs for toast notifications. **Start with Windows**
creates a per-user Startup shortcut, not a scheduled task.

Open Chrome at:

```text
https://localhost:8340/
```

The dashboard is at:

```text
https://localhost:8340/dashboard
```

Accept the self-signed certificate once, click the page to allow audio, and
grant microphone permission for exactly `https://localhost:8340`. Chrome's
microphone grant is origin- and port-scoped; this design keeps the origin fixed.

### Update and uninstall

Update = rerun `JarvisSetup.exe` over the top. There is no auto-update prompt.

Preserved:

```text
.env
data\
runtime.json
cert.pem
key.pem
logs\
.venv\
memory
```

Uninstall stops the verified server, removes the Startup shortcut, and removes
only transient setup markers from `[UninstallDelete]`. It deliberately does not
delete user data, secrets, certificates, memory, or the venv.

See [`docs/INSTALLER.md`](docs/INSTALLER.md) for the exact wizard contract.

---

## Configuration

### `.env`

The installed `.env` sits beside `server.py`. `setup_runtime.update_env()`
preserves comments, ordering, and unlisted keys. Blank optional values do not
erase existing settings.

| Key | Required | Default | Purpose |
|---|---|---|---|
| `FISH_API_KEY` | Yes | none | Fish Audio voice key; no fallback voice. |
| `USER_NAME` | No | upstream default | Name JARVIS uses for the user. |
| `JARVIS_BRAIN_MODEL` | No | `sonnet` | Brain model passed to Claude Code. |
| `FISH_VOICE_ID` | No | upstream default | Fish Audio voice ID. |

The installer never asks for or writes `ANTHROPIC_API_KEY`. Upstream JARVIS
strips `ANTHROPIC_*` variables from spawned Claude processes; this overlay does
not weaken that behaviour.

### `runtime.json`

Generated by `jarvis_win/setup_runtime.py` and read by
`jarvis_win/launcher.py`:

| Field | Value |
|---|---|
| `version` | `1` |
| `app_root` | Installed application root |
| `venv_python` | `.venv\Scripts\python.exe` |
| `pythonw` | `.venv\Scripts\pythonw.exe` |
| `claude` | Resolved native `claude.exe` or `null` |
| `openssl` | Resolved OpenSSL or `null` |
| `app_user_model_id` | `SeanShaffer.Jarvis.Windows` |
| `scheme` | `https` |
| `port` | `8340` |
| `bind_host` | `127.0.0.1` |
| `origin` | `https://localhost:8340` |
| `upstream_ref` | Pinned ref from `INSTALL_MANIFEST.json` |
| `overlay` | `jarvis_win.hook` |

### Certificates

`cert.pem` and `key.pem` are generated once. The certificate uses
`CN=localhost` and, where OpenSSL supports `-addext`,
`SAN=DNS:localhost,IP:127.0.0.1`. Older OpenSSL builds fall back to the
portable command. `key.pem` receives a user-only ACL. Existing pairs are kept
on update.

### Generated files and directories

Everything generated on the target PC is ignored by Git:

```text
.build\
dist\
out\
payload\
*.exe
.env
cert.pem
key.pem
runtime.json
logs\
data\
.venv\
frontend\dist\
node_modules\
__pycache__\
```

---

## Runtime layout

```text
%LOCALAPPDATA%\Programs\Jarvis\
  server.py                    upstream server, local payload only
  frontend\dist\               pre-built static voice page + dashboard
  sitecustomize.py             installs jarvis_win.hook on Windows
  requirements-windows.txt
  jarvis_win\
    hook.py                    sys.meta_path finder
    *_win.py                   nine in-memory module patches
    win32.py                   ctypes pid/HWND/monitor helpers
    win_paths.py               native executable discovery
    transport.py               AF_UNIX + named-pipe transport
    setup_runtime.py           install-time venv/pip/Chromium/certs
    launcher.py                hidden server + health + Chrome
    preflight_cli.py           plain-words checks
    spikes.py                  Phase 0 probes
    ShowToast.ps1              fixed argv-only toast script
  installer\scripts\           installed PowerShell helpers
  tools\openssl.exe            optional bundled OpenSSL
  .env                         user settings, preserved
  cert.pem / key.pem           localhost certificate, preserved
  runtime.json                 launcher configuration
  data\                        SQLite, memory, tool token, preserved
  logs\                        install/preflight logs, preserved
  .venv\                       private Python environment, preserved
```

`server.py` serves `frontend/dist`, `/api`, and `/ws` from one origin. The
launcher does not start a Vite dev server and does not pass `--host 0.0.0.0`.

---

## Connections: bring your own

This installer does not change upstream JARVIS's connection model. JARVIS still
ships connected to nothing; the useful part is the door you choose to open, not
a bundle of integrations someone else guessed at. MCP servers belong in the
installed data directory, not in this public repository:

```text
%LOCALAPPDATA%\Programs\Jarvis\data\jarvis\connections.json
```

The shape is an `mcpServers` block, copied from the server's own documentation:

```json
{
  "mcpServers": {
    "project-notes": {
      "command": "C:\\Tools\\notes-mcp.exe",
      "args": ["--read-only"]
    }
  }
}
```

That is an example shape, not a bundled server. A user-supplied MCP server may
have its own runtime; the JARVIS installer itself never installs Node for the
target PC. Upstream runs with strict MCP configuration, so servers inherited
from `~/.claude.json` or Claude Desktop do not silently appear. Restart JARVIS
and ask what it is connected to: the answer comes from what actually started.

Tool results are treated as untrusted data. A connected server's code is
something you installed; the tickets, pages, emails, and transcripts it returns
are not instructions. This is upstream behaviour and is not widened by the
Windows overlay.

---

## Make it yours

This repository is source-only, so the upstream application files are not here
to edit directly. Personalize JARVIS in the **private fork** or local payload,
then rebuild the installer. Editing the installed app root alone works until
the next update replaces the payload.

| Seam | Where it lives | Notes |
|---|---|---|
| Personality | `jarvis_home/CLAUDE.md` | Copied into the data directory on first run; edit the installed copy for one PC or the template for fresh installs. |
| Voice | `tts.py` | One provider call; replace it for a different TTS engine without touching the installer. |
| Tools | `TOOL_HANDLERS` in `server.py` and the allowlist in `brain.py` | Add a handler and name it in the brain allowlist. |
| Dashboard look | `frontend/src/dashboard/theme/` | CSS tokens first; rebuild `frontend/dist` afterwards. |
| Orb | `frontend/src/orb.ts` | Self-contained Three.js voice visualization. |
| Windows behaviour | `jarvis_win/*_win.py` and `jarvis_win/hook.py` | Add a patch here, not to an upstream file in this repo. |
| Installer flow | `installer/JarvisSetup.iss`, `installer/scripts/`, `jarvis_win/setup_runtime.py` | Change wizard pages, helper scripts, or setup steps. |

Useful contributions are the limits this design has not crossed yet: verified
Windows session transport, real Windows test-baseline fixes, alternative TTS,
and a compile/VM report. Open an issue before a large PR. Always rerun
`python tools/run_tests.py` and update [`docs/STATUS.md`](docs/STATUS.md)
honestly.

---

## How it works

```text
Private fork / pinned upstream ref
            │
            ▼
tools/build_package.py
  ├─ copy upstream source into ignored payload
  ├─ npm ci && npm run build  (build machine only)
  ├─ requirements-windows.txt = upstream + Pillow
  ├─ copy jarvis_win\ + root sitecustomize.py
  └─ optional openssl.exe + manifests
            │
            ▼
.build\installer\JarvisSetup.iss ── iscc ──> dist\JarvisSetup.exe
            │
            ▼
Per-user Inno Setup wizard
  ├─ Check-System.ps1
  ├─ InstallPrereqs.ps1
  ├─ SetSecretAcl.ps1 + masked key page
  ├─ payload copy
  ├─ setup_runtime.py
  └─ login hand-off + finish options
            │
            ▼
%LOCALAPPDATA%\Programs\Jarvis
            │
            ▼
launcher.py start
  ├─ pythonw server.py --host 127.0.0.1 --port 8340
  ├─ wait for https://localhost:8340/api/health
  └─ open Chrome at https://localhost:8340/
```

At import time on Windows:

```text
sitecustomize.py
  └─ jarvis_win.hook.install()
       └─ sys.meta_path finder
            └─ real upstream loader
                 └─ apply one of nine Windows patches in place
```

The patch table is in [`jarvis_win/hook.py`](jarvis_win/hook.py). Each patch
module exposes an `apply(module)` or `apply_brain` / `apply_run_executor`
function. The upstream module is loaded normally first, so constants, classes,
function signatures, and outcome strings survive. macOS keeps the original
implementations.

### Why one origin and one port

Chrome scopes microphone permission to an origin including the port. Upstream's
Vite dev server can move from `5173` to `5174`, leaving the microphone silently
denied. This installer ships `frontend/dist` and serves it from
`https://localhost:8340` directly. The voice page and dashboard are the same
origin, so there is no cross-origin API/WebSocket path and no moving port.

### Why an overlay

A committed upstream fork would put a substantial personal/non-commercial
codebase into this public repository and create a permanent merge burden. The
overlay is small, independently testable, and re-applied after the pinned
upstream ref changes. Upstream source is only copied into a local payload at
build time, together with `UPSTREAM_LICENSE.txt`.

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Windows port map

Every operation is a plain function first; the installer and launcher only call
those functions.

| Upstream surface | Windows behaviour | Outcome compatibility |
|---|---|---|
| `notifier.available/notify` | Fixed `ShowToast.ps1` with WinRT toast; PowerShell argv only. | `bool`; never raises. |
| `actions.open_terminal` | `wt.exe new-tab ... -- powershell.exe`; console fallback. | `{"success", "confirmation"}`. |
| `actions.open_browser/open_chrome` | Chrome/Firefox spawned with URL as one argv entry. | Same dict. |
| `actions.get_chrome_tab_info` | `{}` on Windows v1; no UI scraping. | `{}`. |
| `actions.open_in_editor` | Real `Code.exe` or `os.startfile`; `code.cmd` rejected. | Same dict plus `editor`. |
| `preflight` accessibility/screen recording | Explicit OK; blank-frame check still guards capture. | `ok` Check. |
| `preflight` Claude | Proves native `.exe`; version/login via that path. | `claude_cli`, `claude_login`. |
| `preflight` OAuth expiry | Reads only `claudeAiOauth.refreshTokenExpiresAt`; unknown is non-fatal. | Same login wording. |
| `screen.screen_recording_granted` | `None` (neutral). | Proceed to blank-frame check. |
| `screen.capture_screen` | `PIL.ImageGrab`, Pillow resize, in-memory PNG, blank-frame refusal. | `Shot` or spoken `ScreenError`. |
| `screen.list_windows` | ctypes `EnumWindows` + process names; foreground first. | `list[Window]`. |
| `dialog.normalize_key` | Unchanged closed vocabulary: Return, Escape, 1–9. | Identical. |
| `dialog.tty_for_pid*` | Proves pid → console/host → HWND; emits `/dev/ttywin<hwnd>` token. | String or `None`. |
| `dialog.find_terminal_tab` | Re-proves HWND ownership; stale/moved window is `None`. | `TerminalTab` or `None`. |
| `dialog.answer` | Re-checks identity, logs human hand-off, returns `not_found`; never sends input. | `bad_key`, `no_tty`, `not_found`, `failed`. |
| `session_watch.pid_alive` | `OpenProcess` / `GetExitCodeProcess`. | `bool`. |
| `session_watch.RosterEntry.steerable` | AF_UNIX path existence or `WaitNamedPipeW`. | `bool`. |
| `session_steer.post_to_session` | AF_UNIX or `\\.\pipe\...` with same JSON lines. | `sent`, `not_live`, `refused`, `failed`. |
| `brain.command` | Plain `claude` token during `shlex.split`, then native argv[0]. | `list[str]`. |
| `run_executor._command` | Same native-path substitution. | `list[str]`. |

### Phase 4 boundary

No `SendInput`, `PostMessageW`, keystroke script, or front-window fallback
exists in this repository. The exact HWND probe is present for Spike C and
future gated work, but safe 4a is the final v1 behaviour: JARVIS names the
session and key aloud; the human presses the key.

### Cross-session steering caveat

Spike A is unresolved. Windows Claude Code may publish an AF_UNIX path, a
named pipe, or no `messagingSocketPath` at all. The transport supports the first
two and degrades to `not_live` for the third. No code claims a real steer has
been received until `spikes transport --send-test --acknowledge` works on a
live Windows session.

More detail: [`docs/WINDOWS_PORT.md`](docs/WINDOWS_PORT.md).

---

## Security and trust decisions

These are deliberate trade-offs, not bugs waiting for a fix.

1. **Loopback is trusted, LAN is not.** `server.py` binds `127.0.0.1`; the
   launcher never passes `--host 0.0.0.0`. No CORS or LAN exposure is added.
   Anything on the local machine that can speak to loopback is inside the
   upstream trust model. A self-signed cert still needs one Chrome exception.
2. **The Fish key is a file secret, not a command-line secret.** It enters
   through a masked field, goes into an ACL'd temp job file, then into `.env`
   with a user-only ACL. `setup_runtime.Redactor` scrubs exact values, `.env`
   lines, and JSON values from child output before any log or progress write.
3. **The temp job file is deleted on every path.** Success, setup failure, and
   wizard cancel all overwrite-then-unlink it in `finally` or the wizard's
   cancel handler.
4. **Native Claude only.** `brain_win`, `preflight_win`, and
   `claude_launcher` resolve a real Windows PE `.exe`. A `.cmd` / `.bat` npm
   shim is refused with a clear error rather than failing as WinError 193 or
   being wrapped in a shell.
5. **Toast text is untrusted argv, never source.** `ShowToast.ps1` is fixed;
   Python passes `-File` and separate `-Title`, `-Message`, `-Subtitle`
   arguments. PowerShell assigns them with `XmlDocument.InnerText`. There is no
   `-Command`, no XML string interpolation, and no shell string.
6. **Action argument lists, not command strings.** Browser URLs and terminal
   commands are separate argv entries. `open_in_editor` rejects `code.cmd`.
7. **Dialog keys are a closed vocabulary.** `normalize_key` is untouched. Free
   text returns `bad_key` before any identity lookup. Windows v1 proves a
   pid/HWND chain and then returns `not_found`; it never sends input.
8. **Screenshots are bounded.** User-initiated only, held in memory, capped at
   1280 edge and 4 MB, blank-frame checked, and never fed into ambient context.
   Window titles are untrusted tool results.
9. **Prerequisite integrity comes from WinGet.** Signed packages in user scope;
   no `irm | iex`, no npm global install, no elevation. The generated payload
   has a SHA-256 manifest.
10. **Uninstall preserves secrets and data.** It does not copy `.env` or memory
    elsewhere and does not delete `data/`.

Residual risks:

- A self-signed localhost certificate requires a one-time browser exception.
- Any local process can speak to loopback; this is upstream's design and is not
  widened here.
- Cross-session steering and HWND mapping are unverified until Spikes A/C run
  on a real Windows machine.
- `npm ci` advisories in upstream build-only dev dependencies remain a build
  supply-chain review item.

More detail: [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Testing and verification

### Linux unit suite

```bash
python -m compileall -q jarvis_win tools tests
python tools/lint_iss.py
python tools/run_tests.py
```

The 100-test standard-library suite covers:

- native Claude resolution and `.cmd` rejection;
- named-pipe/AF_UNIX classification and JSON payloads;
- pid/HWND identity proof with ambiguity refusal;
- dialog closed vocabulary and the no-send 4a boundary;
- toast argv safety and truncation;
- action argument lists and `{}` Chrome tab info;
- Pillow capture/blank-frame logic with fake images;
- Windows preflight and credential-file expiry;
- brain/run-executor command rewriting around `shlex.split`;
- import-hook wrapping and platform gating;
- setup log redaction, `.env` preservation, job-file deletion, cancellation;
- launcher environment and stop verification;
- payload staging and licence/manifest generation;
- Inno Setup and PowerShell static safety checks.

These tests do **not** prove a real Windows desktop works.

### Windows gates

1. Compile `JarvisSetup.iss` with Inno Setup 6.4+; fix compiler errors and
   rerun `tools/lint_iss.py`.
2. Install on a clean Windows VM with no Python, no Git, no Claude Code, and an
   existing Chrome. Confirm no elevation prompt and no Node install.
3. Walk every wizard page. Confirm the log contains no Fish key and the `.env`
   ACL grants only the current user.
4. Finish without signing in; verify the installer still completes, then sign
   in and use Check again.
5. Start JARVIS. Confirm hidden `server.py`, `https://localhost:8340`, the
   one-time certificate exception, Chrome microphone permission, and dashboard
   on the same origin.
6. Uninstall. Confirm `.env`, `data\`, memory, certs, logs, and `.venv\`
   remain; confirm Startup shortcut and verified server process are gone.
7. Reinstall over the top. Confirm no duplicate key page requirement, no
   regenerated cert, no lost memory, and no second server on port 8340.
8. Run `spikes baseline --run` and write the failure catalogue.

### Field test — the verdict

Label **Unverified** until SEAN completes this on his own PC:

1. Speak to JARVIS; he answers aloud.
2. Brainstorm a project by voice.
3. Approve a spec by voice; a real build runs.
4. A second Claude Code session blocks on a permission prompt.
5. JARVIS posts a toast and speaks an alert naming the session.
6. SEAN presses the key himself — 4a; JARVIS must not press it.
7. Ask “what am I looking at?” and receive a correct screen-sight answer.
8. Stop JARVIS from the shortcut; no orphan server remains.

Record failures as spike/port/installer bugs with logs, not as caveats in a
“passed” claim. More detail: [`docs/TESTING.md`](docs/TESTING.md).

---

## Phase 0 spikes

Run these on SEAN's PC or a clean Windows VM with his Claude login and Windows
Terminal. Use the installed venv:

```powershell
cd %LOCALAPPDATA%\Programs\Jarvis
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . roster
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . claude
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . windows
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . baseline --run
```

| Spike | Question | Gate |
|---|---|---|
| A | What is `messagingSocketPath` on Windows: AF_UNIX, named pipe, or absent? | A real benign message must be received before steering is called working. |
| B | Does native `claude.exe` spawn, report version, and parse `auth status`? | `claude.cmd` only is a stop condition. |
| C | Can pid → console/host → HWND be proven for 2–3 Windows Terminal sessions? | Ambiguity stays `not_found`; no input is sent. |
| D | What does the upstream suite do on Windows? | Catalogue mac-only, Windows-port, and upstream failures separately. |

Spike A is still unresolved in source: the transport supports both AF_UNIX and
named pipes but does not pretend the answer is known. Spike C's probe exists,
but 4a ships regardless because no keystrokes are sent.

More detail: [`docs/SPIKES.md`](docs/SPIKES.md).

---

## Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| Checks page blocks Next | Windows too old, Chrome missing, or <1 GB free | Install Chrome, free space, or use Windows 10 1809+. |
| WinGet prerequisite failure | App Installer missing or package source unavailable | Install App Installer from Microsoft Store, open a new terminal, rerun. |
| `claude.cmd` is the only Claude binary | npm shim installed instead of native Claude Code | Install `Anthropic.ClaudeCode`; do not wrap the shim in `cmd.exe`. |
| Python is 3.10 or older | Existing PATH entry wins | Install Python 3.11+ or let WinGet install `Python.Python.3.12`. |
| OpenSSL not found during setup | No bundled `openssl.exe` and Git is absent | Install Git for Windows or rebuild with `--openssl PATH`. |
| Chrome shows a certificate warning | Self-signed localhost cert | Accept the exception for `https://localhost:8340` once. |
| Microphone silently denied | Permission granted for a different origin/port | Use exactly `https://localhost:8340`, not `http` or port 5173/5174. |
| Dashboard returns 404 | `frontend/dist` was not built or staged | Build without `--skip-frontend` or pass `--frontend-dist`. |
| Port 8340 already in use | Stale server or PID reuse | Use Stop JARVIS; the launcher verifies command line before `taskkill`. |
| Toast does not appear | Missing AppUserModelID shortcut or PowerShell unavailable | Recreate Start-menu shortcuts and check `powershell.exe`. |
| Setup log contains `[REDACTED]` | Expected | Secrets are scrubbed; do not paste raw child output into logs. |
| Update asks for Fish key again | Existing `.env` was not preserved | Check that `.env` still exists; blank key field should keep old value. |
| JARVIS goes silent but browser shows text | Missing or invalid `FISH_API_KEY` | Add a valid Fish Audio key to `.env` and rerun preflight. |
| Cross-session steering returns `not_live` | Spike A unresolved, no published socket path | Run `spikes roster`; do not fake UI scraping. |
| Screen sight says the frame is blank | Capture did not reach the desktop | Check monitor/capture context; blank frames are refused on purpose. |
| Permission prompt is not answered automatically | Safe 4a by design | JARVIS names the session and key aloud; the human presses the key. |

For a deeper check from an installed app root:

```powershell
.\.venv\Scripts\python.exe .\jarvis_win\launcher.py --app-root . status
.\.venv\Scripts\python.exe .\jarvis_win\launcher.py --app-root . preflight
.\.venv\Scripts\python.exe .\jarvis_win\launcher.py --app-root . stop
```

---

## Development

### Commands

```bash
python tools/run_tests.py
python tools/lint_iss.py
python tools/build_package.py --upstream /path/to/private/fork --skip-frontend
python tools/build_package.py --upstream /path/to/private/fork --frontend-dist /path/to/dist
```

`--skip-frontend` creates a placeholder `frontend/dist` for staging tests only.
It is not a release build.

### Adding a Windows patch

1. Add or update a `jarvis_win/*_win.py` module with an `apply(module)`
   function.
2. Preserve upstream names, argument shapes, dataclasses, and outcome strings.
3. Register the module in `jarvis_win/hook.py` only when it is a top-level
   upstream module.
4. Add a Linux unit test with a small stand-in module from `tests/_stubs.py`.
5. Never edit upstream source in this repository.
6. Update [`docs/WINDOWS_PORT.md`](docs/WINDOWS_PORT.md) and
   [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
7. Rerun `python tools/run_tests.py`.

### Changing the pinned upstream ref

1. Update `upstream.json`.
2. Re-read the five macOS modules and the two hidden Windows traps.
3. Rerun all Linux tests and the real frontend build.
4. Rerun every Phase 0 spike.
5. Update [`docs/STATUS.md`](docs/STATUS.md) honestly.

### Conventions

- Plain functions first; UI/installer code only calls them.
- No upstream source, secrets, certs, databases, logs, generated payloads, or
  executables in Git.
- No shell strings for untrusted text; use argument lists.
- No `SendInput`, no focus fallback, no free-text keystrokes.
- No `0.0.0.0`, no runtime Node, no `claude.cmd`.
- Tests are standard-library `unittest`, not a new dependency.
- Windows behaviour stays **Unverified** until a real VM and SEAN's field test
  say otherwise.

---

## Repository layout

| Path | Purpose |
|---|---|
| [`README.md`](README.md) | This guide. |
| [`LICENSE`](LICENSE) | MIT licence for installer/overlay code. |
| [`NOTICE.md`](NOTICE.md) | Upstream licence and distribution notice. |
| [`version.json`](version.json) | Installer version, overlay protocol, AUMID, port, bind host. |
| [`upstream.json`](upstream.json) | Pinned upstream repository/ref and licence note. |
| [`installer/JarvisSetup.iss`](installer/JarvisSetup.iss) | Inno Setup wizard. |
| [`installer/prereqs.json`](installer/prereqs.json) | WinGet package IDs and native-Claude-only policy. |
| `installer/scripts/` | Fixed PowerShell helpers. See [`installer/scripts/README.md`](installer/scripts/README.md). |
| `jarvis_win/` | Windows overlay, launcher, setup runtime, preflight CLI, spikes, toast script. |
| `oneclick/` | Frozen one-click GUI, hidden setup helpers, server/MCP bootstrap, runtime patches. |
| `jarvis_win/hook.py` | Nine-module import hook. |
| `jarvis_win/setup_runtime.py` | Cancellable install-time environment setup. |
| `jarvis_win/launcher.py` | Hidden server, health check, browser opener, stop switch. |
| `jarvis_win/spikes.py` | Phase 0 probes. |
| `tools/build_package.py` | Local payload staging and frontend build. |
| `tools/build_oneclick.py` | Stage and compile the one-file frozen exe. |
| `tools/build_oneclick_gui.pyw` | Double-click, no-console Windows builder GUI. |
| `tools/lint_iss.py` | Static Inno Setup safety checks. |
| `tools/run_tests.py` | Standard-library test runner. |
| `tests/` | 100 unit/static tests with upstream API stand-ins. |
| `docs/` | Plan, decisions, architecture, port map, installer, security, spikes, building, testing, one-click, status. |

---

## Documentation index

| Document | Read it for |
|---|---|
| [`docs/ORIGINAL_PLAN.md`](docs/ORIGINAL_PLAN.md) | The original Option 2 plan and acceptance gates. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Confirmed choices: scope, terminal, Pillow, 4a, private fork. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Payload, app root, import hook, one-origin design. |
| [`docs/WINDOWS_PORT.md`](docs/WINDOWS_PORT.md) | Per-module Windows behaviour and outcome compatibility. |
| [`docs/INSTALLER.md`](docs/INSTALLER.md) | Wizard pages, shortcuts, preservation, certificates. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Secrets, loopback, argv boundary, 4a boundary, residual risks. |
| [`docs/BUILDING.md`](docs/BUILDING.md) | Build machine setup, staging, compile, pinning. |
| [`docs/SPIKES.md`](docs/SPIKES.md) | Phase 0 spike commands and gates. |
| [`docs/TESTING.md`](docs/TESTING.md) | Linux tests, Windows gates, field-test verdict. |
| [`docs/ONECLICK.md`](docs/ONECLICK.md) | Single-file GUI exe, frozen runtime, build steps, gates. |
| [`docs/STATUS.md`](docs/STATUS.md) | Honest verification status. |

---

## Frequently asked questions

### Why not just commit a patched upstream fork?

Upstream JARVIS is personal/non-commercial only, and this target repository is
public. A substantial copy would be a licence problem and a maintenance burden.
The overlay is small, source-only, and re-applied to a local payload.

### Why Windows Terminal?

SEAN chose `wt.exe` as the terminal host. `actions.open_terminal` uses it with
a PowerShell console fallback. The identity probe exists for Spike C, but v1
does not send keys.

### Why Pillow?

Pillow was accepted for Windows screenshots. `ImageGrab` captures the screen,
Pillow resizes and PNG-encodes it in memory, and the blank-frame check refuses
a capture that did not reach the desktop. macOS keeps its original `sips` path.

### Why is Node on the build machine but not the PC?

Vite builds `frontend/dist`; `server.py` serves that static directory. A
runtime dev server would reintroduce changing ports and Chrome microphone
permission problems. `npm ci` is build-time only, and `node_modules` is removed
before the payload manifest is written.

### Why port 8340?

It is upstream JARVIS's default API port. Serving the built frontend from the
same process gives one fixed origin for the voice page, dashboard, `/api`, and
`/ws`.

### Why safe 4a instead of automatic key pressing?

Automatic 4b `SendInput` was explicitly held back. The closed vocabulary and
exact HWND identity proof are implemented, but v1 returns `not_found` after a
display-only hand-off. The user presses the key. There is no focus fallback.

### Can I use Firefox?

Chrome is a hard requirement for voice input because upstream uses the Web
Speech API. Firefox is supported only by `open_browser` when JARVIS explicitly
asks for it; it is not a microphone fallback.

### Does the installer need an Anthropic API key?

No. Upstream JARVIS uses Claude Code on the user's subscription and scrubs
`ANTHROPIC_*` variables from spawned processes. The installer does not ask for
or write an Anthropic key.

### Does uninstall delete my data?

No. `.env`, `data\`, memory, certificates, logs, and `.venv\` are preserved.
The Startup shortcut and verified server process are removed.

### Is Windows support verified?

No. Linux unit tests, static checks, and a real frontend build pass, but Inno
Setup compilation, PowerShell execution, clean-VM install, Phase 0 spikes,
upstream Windows suite, and SEAN's field test are **Unverified**.

### Can I get one `.exe` that does everything?

Yes — build the private `JarvisOneClick.exe` described above and in
[`docs/ONECLICK.md`](docs/ONECLICK.md). The target user enters only the Fish
Audio key and, if needed, completes browser sign-in. No Terminal, PowerShell,
VS Code, Git Bash, or command line is used. It is source-only here and remains
**Unverified** until compiled and field-tested on Windows.

### May I publish `JarvisSetup.exe` or `JarvisOneClick.exe`?

Not without the upstream author's permission. Both generated payloads include
upstream source and its personal/non-commercial licence. Keep them
private/local.

---

## Verification status

**Overall: implementation files are present; Linux unit/static checks and a
pinned frontend build pass; Windows behaviour is Unverified.**

Verified in this session:

- `python -m compileall -q jarvis_win tools tests` — pass.
- `python tools/lint_iss.py` — pass.
- `python tools/run_tests.py` — 100 tests pass.
- `python tools/build_package.py --upstream /home/user/_upstream_jarvis --out .build/installer` —
  staged 215 payload files and built `frontend/dist` from the pinned upstream
  ref. No `.env`, private database, or `frontend/node_modules` is shipped.
- `npm ci` reported two high-severity advisories in upstream build-only dev
  dependencies. The lockfile was not changed and no Node/Vite runtime is
  shipped.
- One-click source, hidden setup helpers, frozen server/MCP patches, PyInstaller
  spec generation, GUI builder, payload secret scan, and one-click docs pass
  Linux unit/static tests. No compiled `JarvisOneClick.exe` exists here.

Hard gates still open:

1. Spike A: prove the Windows cross-session transport with a real benign
   message.
2. Spike B: prove native `claude.exe`, version, login JSON, and credentials.
3. Spike C: prove pid → console/host → HWND with 2–3 real sessions.
4. Spike D: run and catalogue the upstream Windows suite.
5. Compile Inno Setup, install on a clean VM, log in, uninstall, confirm data
   survives, reinstall, resume.
6. Compile and clean-VM test `JarvisOneClick.exe`: confirm no console windows,
   only the Fish key prompt, browser login, Chrome mic, relaunch without a key
   prompt, and update preserving data.
7. SEAN's field test: speak → brainstorm → approve a spec → build → blocked
   session → toast/spoken alert → user presses key → screen sight → stop.

Never describe the field-test verdict as passed until step 7 actually happens.
See [`docs/STATUS.md`](docs/STATUS.md).

---

## Licence, credits, and disclaimer

Installer, Windows overlay, build tooling, tests, and documentation in this
repository are © 2026 Sean Shaffer and are offered under the MIT licence in
[`LICENSE`](LICENSE).

Upstream JARVIS is © 2026 Ethan Rogers and is licensed for personal,
educational, and non-commercial use with attribution required. Commercial use
requires a separate licence from the author; see
[`NOTICE.md`](NOTICE.md) and the upstream
[LICENSE](https://github.com/ethanplusai/jarvis/blob/main/LICENSE).
The build script copies that licence into the local payload as
`UPSTREAM_LICENSE.txt`. The single-file `JarvisOneClick.exe` embeds the same
upstream source and is subject to the same private/local restriction.

Built on [JARVIS](https://github.com/ethanplusai/jarvis),
[Claude Code](https://claude.com/claude-code), and
[Fish Audio](https://fish.audio). Thanks to Ethan for the original project.

> **Disclaimer:** This is an independent, source-only installer/overlay project
> and is not affiliated with, endorsed by, or connected to Ethan Rogers,
> upstream JARVIS, Anthropic, Marvel Entertainment, The Walt Disney Company, or
> any related entities. The JARVIS name and character are property of Marvel
> Entertainment. Do not publish the generated installer or payload without the
> upstream author's permission.
