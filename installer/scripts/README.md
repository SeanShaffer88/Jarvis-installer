# Installer helper scripts

These are fixed scripts copied into the payload and also marked `dontcopy` in
Inno Setup so they can run before the payload is installed.

| Script | Purpose | Security property |
|---|---|---|
| `Check-System.ps1` | Windows 10 1809+, Chrome, and ~1 GB disk checks. | Writes plain words, no secrets. |
| `InstallPrereqs.ps1` | Per-user WinGet install of Python 3.11+, Git, and native Claude Code only when missing. | Rejects `claude.cmd`; no Node/npm; no admin. |
| `SetSecretAcl.ps1` | Creates an empty job file with inheritance removed before the key is written. | Key never enters a command line or log. |
| `OpenClaudeLogin.ps1` | Opens native Claude Code in Windows Terminal or a console for one-time login. | Path only; no `-Command` interpolation. |
| `Set-Startup.ps1` | Creates/removes a per-user Startup shortcut. | No scheduled task or elevation. |
| `Stop-Jarvis.ps1` | Stops the hidden server before update/uninstall. | PID command line is verified by `launcher.py stop`. |

`jarvis_win/ShowToast.ps1` is the fixed toast script installed with the Python
overlay; untrusted transcript text arrives only as `-Title`, `-Message`, and
`-Subtitle` argv values and is assigned with `InnerText`.
