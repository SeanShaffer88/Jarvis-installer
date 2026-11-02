# Decisions — 2026-11-01

The four open choices in §9 of the [original plan](ORIGINAL_PLAN.md) were
confirmed before implementation.

| Decision | Choice | Consequence |
|---|---|---|
| Scope | Full implementation in this repository | Installer, overlay, launcher, helpers, tests, and docs are all here. |
| Terminal host | **Windows Terminal** | `open_terminal` targets `wt.exe` with a PowerShell fallback. A gated identity probe exists, but automated key sending is not implemented. |
| Pillow | **Accepted** | Windows screenshots use `PIL.ImageGrab` and Pillow resize/PNG encode; macOS keeps `sips`. No PowerShell image plumbing. |
| Permission prompts | **Safe 4a** | Closed vocabulary is preserved; exact pid → console/host → HWND proof is audited, but v1 never calls `SendInput`. The user presses the key. |
| Fork location | **Private/local** | No upstream source is committed here. The build script creates a local payload and copies the upstream licence into it. |
| One-click distribution | **Single private `JarvisOneClick.exe` built from source** | GUI-only first run, hidden helpers, embedded private payload, and browser Claude sign-in if needed. No visible Terminal, PowerShell, VS Code, or Git Bash. |

## Additional implementation decisions

- **Overlay instead of a patched fork in this repo.** A `sitecustomize`
  import hook wraps target modules as they load, so upstream source remains
  untouched and no substantial upstream copy enters this public repository.
- **Native Claude only.** `brain.py` and `run_executor.py` are patched to
  resolve an `.exe`; `.cmd`/`.bat` shims are rejected with a clear error.
- **WinGet user scope.** The wizard installs missing prerequisites with
  per-user WinGet packages. No Node.js and no npm global install.
- **Pre-built frontend.** Node is a build-machine-only dependency. Runtime is
  Python + the static `frontend/dist` served by `server.py` on one origin.
- **Self-signed HTTPS on loopback.** `localhost:8340` keeps Chrome's microphone
  permission pinned and avoids the 5173→5174 Vite port trap.
- **Named pipes are supported defensively.** Spike A still decides whether
  Claude Code actually uses AF_UNIX, a named pipe, or neither on Windows.
  The transport code does not pretend that question is answered.

## Explicitly not decided or not built

- Phase 4b `SendInput` automation is **not** built; no focus fallback exists.
- Cross-session steering is not declared working until Spike A verifies the
  Windows roster's `messagingSocketPath` and a real benign message is received.
- The Windows test baseline, clean-VM install, and SEAN's field test are
  **Unverified**. Code review and Linux unit tests are not substitutes.
