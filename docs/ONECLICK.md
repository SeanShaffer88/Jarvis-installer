# One-click `JarvisOneClick.exe`

This document describes the **single-file, GUI-only** path. It is an alternative
to the Inno Setup wizard in [`installer/JarvisSetup.iss`](../installer/JarvisSetup.iss).
The goal is that SEAN double-clicks one `.exe`, enters one Fish Audio API key,
and never opens Terminal, PowerShell, VS Code, Git Bash, Inno Setup, or a
command line. Hidden helper processes may still run with no visible window.

> **Status:** source and Windows build tooling are implemented; no compiled
> `.exe`, Windows VM install, or field test has happened in this Linux sandbox.
> One-click Windows behaviour is **Unverified**. See [`STATUS.md`](STATUS.md).

## What the user sees

First run on a clean Windows PC:

1. Double-click `JarvisOneClick.exe`.
2. A small window asks for the **Fish Audio API key** in a masked field.
3. Click **Set up JARVIS**.
4. If Claude Code is not already signed in, a browser window opens. Sign in,
   then click **I've signed in** in the JARVIS window.
5. Chrome opens `https://localhost:8340/`. Accept the one-time localhost
   certificate exception and allow the microphone.
6. The JARVIS window closes. JARVIS is running.

Subsequent runs:

- Double-click the same `.exe` (or use the per-user Startup shortcut) and JARVIS
  starts with **no settings prompt at all**.
- Chrome opens the voice page on the same fixed origin.
- Replacing the `.exe` with a newer build is the update path; `%LOCALAPPDATA%\Programs\Jarvis`
  keeps `.env`, `data\`, memory, certificates, logs, and the runtime file.

There are no optional name/model/voice fields, no install-location page, no
Start-with-Windows checkbox, no update prompt, no terminal page, and no editor
choice. The safe defaults are used.

## What the .exe silently does

The frozen app contains its own Python runtime, upstream Python dependencies,
the private upstream JARVIS payload, `frontend/dist`, the Windows overlay, a
Windows `openssl.exe`, and Playwright Chromium. The target PC therefore needs
**no Python, no pip, no venv, no Node, no Vite, no Git, no Inno Setup, and no
VS Code**.

Hidden, argument-list-only helpers:

| Step | Hidden helper | Visible window |
|---|---|---|
| Install Chrome if missing | `winget install --scope user … Google.Chrome` | none |
| Install native Claude Code if missing | `winget install --scope user … Anthropic.ClaudeCode` | none |
| Save `.env` with a verified user-only DACL | native Windows file handles | none |
| Tighten `key.pem` ACLs | `icacls …` | none |
| Generate localhost cert | bundled `openssl.exe req -x509 …` | none |
| Claude sign-in | `claude.exe auth login` + browser | browser only |
| Toast notifications | fixed `ShowToast.ps1` | toast only |
| Startup shortcut | hidden PowerShell COM call | none |
| Start server | same `.exe --server` | none |
| Open UI | `chrome.exe https://localhost:8340/` | Chrome |

No shell strings, no `cmd.exe`, no `wt.exe`, no `Code.exe`, no `bash.exe`, no
`claude.cmd`, and no `0.0.0.0` binding are used.

## What still has to be accepted manually

Two browser/security steps cannot be removed by an installer:

- Claude Code's first launch uses a browser OAuth sign-in unless the user is
  already signed in. The GUI starts `claude auth login` hidden and sends the
  single Enter that the CLI asks for after the browser flow. This is one button
  in the GUI, not a terminal.
- Chrome requires a one-time self-signed certificate exception and microphone
  permission for exactly `https://localhost:8340`.

A Fish Audio key is the only secret the GUI asks for. It is not an Anthropic API
key. Claude Code uses the user's subscription/browser login.

Settings persistence requires local NTFS and trusted, stable ancestor directories.
An empty, exclusively created sibling file receives a protected DACL with exactly
one explicit full-control grant to the process user SID before content is written.
The owner must match that SID. Publication uses the retained file handle; failures
before publication preserve the previous `.env` bytes and ACL. Reusing an existing
key verifies and replaces its DACL through the same handle used to read it, without
changing its bytes. Reuse permission changes are not rolled back on later failure.
The internal ACL callback receives the empty temporary file and must return `None`.
This policy does not protect against privileged access, same-user compromise,
previously opened handles, or arbitrary concurrent ancestor substitution.

## Build machine vs target PC

| | Build machine | Target PC |
|---|---|---|
| Windows 10 1809+ / 11 | Required | Required |
| Python 3.11+ with tkinter | Required | Not required |
| PyInstaller | Required | Not required |
| Playwright + Chromium | Required | Not required; browsers are embedded |
| Node.js + npm | Required for `npm run build` | Not required |
| Windows `openssl.exe` | Required, usually from Git for Windows | Embedded |
| Private JARVIS fork | Required | Embedded inside the `.exe` |
| Google Chrome | Not required | Installed silently if missing |
| Native Claude Code | Not required | Installed silently if missing |
| Administrator rights | Not required | Not required |

Node, PyInstaller, Python, and Playwright are **build-time only**. The target PC
receives one `.exe`.

## Build it without a command line

1. On a Windows build machine, install Python 3.11+ (with tkinter), Node.js,
   Git for Windows, and Inno Setup is **not** needed for this path.
2. Place the private JARVIS fork somewhere local, for example
   `C:\src\jarvis-win`.
3. Double-click [`tools/build_oneclick_gui.pyw`](../tools/build_oneclick_gui.pyw).
   Windows associates `.pyw` with `pythonw.exe`, so no console appears.
4. Choose the private fork folder and click **Build**.
5. The builder silently installs `pyinstaller` and `playwright` if missing,
   prepares Chromium, stages the private payload, compiles the one-file exe,
   and reports the output path:
   `.build\oneclick\dist\JarvisOneClick.exe`.

The builder uses [`tools/build_oneclick.py`](../tools/build_oneclick.py), which:

1. calls `tools/build_package.py` to stage the pinned private payload and build
   `frontend/dist`;
2. removes Inno Setup scripts, `.iss` files, secrets, certs, databases, logs,
   `node_modules`, and generated executables;
3. embeds a proven Windows PE `openssl.exe`;
4. copies Playwright Chromium into the bundle;
5. writes a generated PyInstaller spec with `console=False`, `uac_admin=False`,
   one-file output, hidden imports, and SHA-256 manifests;
6. optionally runs PyInstaller;
7. writes `ONCLICK_MANIFEST.json` with every embedded file hash.

For development only, the underlying command is:

```powershell
py -3 -m tools.build_oneclick --upstream C:\src\jarvis-win --compile
```

The GUI builder is the intended no-console route.

## Frozen runtime architecture

```text
JarvisOneClick.exe (PyInstaller --onefile --windowed)
  ├─ oneclick/main.py            GUI / --launch / --server / --mcp
  ├─ app/                       private upstream payload, no secrets
  │    ├─ server.py
  │    ├─ frontend/dist/
  │    ├─ jarvis_win/
  │    ├─ tools/openssl.exe
  │    └─ ONCLICK_MANIFEST.json
  ├─ ms-playwright/             Chromium, no runtime download
  └─ embedded Python + wheels
```

The persistent app root is separate:

```text
%LOCALAPPDATA%\Programs\Jarvis\
  .env                  Fish key, user-only ACL
  cert.pem / key.pem    preserved across updates
  data\                 SQLite, memory, MCP connections, tool token
  logs\
  runtime.json
```

`--server` mode sets `JARVIS_ENV_FILE`, `JARVIS_DATA_DIR`,
`JARVIS_APP_ROOT`, `JARVIS_CLAUDE_PATH`, `PLAYWRIGHT_BROWSERS_PATH`, and the
loopback/origin variables before importing upstream `server.py`. It copies the
persistent cert pair beside the extracted `server.py`, installs the Windows
import hook, applies one-click patches, and runs Uvicorn on `127.0.0.1:8340`.

### One-click patches

The existing nine-module Windows overlay is still installed. Extra in-memory
patches then:

- make `actions.open_terminal` and `actions.open_in_editor` fail closed — no
  Terminal and no VS Code;
- keep Chrome as the only visible browser/action path;
- hide the fixed toast helper's PowerShell window;
- rewrite preflight remedies so they never tell the user to open a terminal;
- rewrite the brain's MCP config to spawn `JarvisOneClick.exe --mcp` instead of
  `python jarvis_mcp.py`;
- rewrite `/api/restart` to spawn `JarvisOneClick.exe --server` hidden instead
  of `os.execv(sys.executable, __file__)`;
- add `CREATE_NO_WINDOW` / hidden `STARTUPINFO` to every spawned subprocess.

Safe 4a remains: no `SendInput`, no focus fallback, no automatic key pressing.

## Security properties

- The Fish key is masked in the GUI, written atomically to `.env`, and never
  placed on a command line or in a log. A user-only ACL is applied to `.env` and
  `key.pem`.
- `ANTHROPIC_*` and `CLAUDE_CODE_*` variables are scrubbed from the frozen
  process. No Anthropic API key is requested or used.
- Native `claude.exe` is required; `.cmd`/`.bat` shims are rejected by PE header.
- WinGet packages are installed in user scope only. No `irm | iex`, no admin,
  no npm global install.
- The server stays on `127.0.0.1` with one pre-built origin. No CORS, no LAN
  exposure, no Vite dev server, and no moving `5173`/`5174` microphone origin.
- The payload scan refuses `.env`, certificates, private databases, logs,
  runtime state, `node_modules`, `.iss` files, and unexpected executables or
  PowerShell scripts.
- The one-click `.exe` contains upstream JARVIS source. It must stay
  private/local under the upstream personal/non-commercial licence. Do not
  attach it to a public release without the author's permission.

## Verification gates still open

The one-click path does not bypass the original plan's gates. Before claiming
it works:

1. Compile with PyInstaller on Windows.
2. Run on a clean VM with no Python, no Git, no Node, no Claude Code.
3. Confirm no console windows appear during WinGet, certificate, sign-in,
   startup-shortcut, server, or toast helpers.
4. Confirm the first GUI asks only for the Fish key and opens browser sign-in
   when needed.
5. Confirm Chrome uses exactly `https://localhost:8340`, the mic works, and
   JARVIS speaks.
6. Close and relaunch; confirm no key prompt and no second server on 8340.
7. Replace the `.exe` with a newer build; confirm `.env`, `data\`, memory,
   certs, and logs survive.
8. Run all Phase 0 spikes and SEAN's field test. Record failures as bugs, not
   caveats in a “passed” claim.

Linux unit tests, static checks, and a frontend build are not a Windows verdict.
See [`TESTING.md`](TESTING.md) and [`SPIKES.md`](SPIKES.md).
