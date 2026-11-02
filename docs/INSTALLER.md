# Installer behaviour

`installer/JarvisSetup.iss` targets Inno Setup 6.4+ and compiles against the
staging directory produced by `tools/build_package.py`.

## Wizard flow

1. **Checks page.** `Check-System.ps1` verifies Windows 10 build 17763+,
   Chrome, and at least 1 GB free on the `%LOCALAPPDATA%` drive. Chrome failure
   blocks Next with plain words.
2. **Prerequisites page.** `InstallPrereqs.ps1` checks first, then installs
   only missing per-user WinGet packages: Python 3.12, Git for Windows, and
   `Anthropic.ClaudeCode` (native binary). It rejects `claude.cmd`, never
   installs Node/npm, and needs no elevation. WinGet is the package-integrity
   boundary.
3. **Keys page.** Masked Fish Audio key plus optional name, brain model, and
   voice ID. On a first install the key is required; on reinstall blank keeps
   the existing `.env` value. `SetSecretAcl.ps1` creates a user-only temp job
   file before the wizard writes it. The key is never on a command line nor in
   a log.
4. **File install.** Payload files go to `%LOCALAPPDATA%\Programs\Jarvis`.
   `Stop-Jarvis.ps1` stops an existing instance first. `.env`, `data\`,
   memory, and certificates are not part of the payload.
5. **Cancellable setup.** `setup_runtime.py` runs hidden with a progress file
   and a cancel sentinel. It creates `.venv`, pip-installs Windows requirements
   (upstream + Pillow), installs Playwright Chromium, generates `cert.pem`/
   `key.pem`, writes `runtime.json`, and runs plain-words preflight. Every log
   line passes through a secret redactor. Cancel terminates the current child
   and the wizard aborts; the temp key file is deleted.
6. **Claude login hand-off.** A button opens native Claude Code in Windows
   Terminal (or a console) for the one manual login. **Check again** reruns
   preflight live and shows plain words. A not-logged-in state does not trap
   the user on the page.
7. **Finish options.** Start JARVIS now and/or create a per-user Startup
   shortcut. No scheduled task, no auto-update, no nagging.

## Shortcuts

| Shortcut | Action |
|---|---|
| JARVIS | `launcher.py start` — hidden server, health wait, opens the voice page. |
| JARVIS Dashboard | `launcher.py start --open dashboard`. |
| Stop JARVIS | `launcher.py stop` — verifies PID command line before `taskkill /T`. |

Each shortcut carries `AppUserModelID: SeanShaffer.Jarvis.Windows`, which a
non-packaged app needs for toast notifications. The launcher opens the voice
page by default rather than the dashboard because Chrome's microphone is the
primary input; the dashboard is one shortcut away on the same origin.

## Runtime layout and preservation

- `server.py`, `frontend/dist`, `jarvis_win/`, `sitecustomize.py` — replaced on
  update.
- `.env`, `data/`, `runtime.json`, `cert.pem`, `key.pem`, `logs/`, `.venv/` —
  kept. `[UninstallDelete]` removes only transient setup markers.
- Uninstall stops the verified server, removes the Startup shortcut, and keeps
  user data.
- Update = re-run `JarvisSetup.exe` over the top. There is no background
  updater and no update prompt.

## Certificate and OpenSSL

The build script bundles a Windows `openssl.exe` when one is supplied or found
in a Git for Windows installation. Otherwise `setup_runtime.py` locates Git's
copy after prerequisites are installed. The certificate uses `CN=localhost`
and, where supported, `SAN=DNS:localhost,IP:127.0.0.1`; old OpenSSL builds
fall back to the portable command. `key.pem` gets a user-only ACL.
