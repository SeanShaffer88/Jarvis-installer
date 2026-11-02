# Windows port map

The five macOS files named in the original plan plus the two hidden Windows
traps are covered. Every operation is a plain function first; the wizard and
launcher only call them.

| Upstream surface | Windows behaviour | Outcome compatibility |
|---|---|---|
| `notifier.available/notify` | Fixed `ShowToast.ps1` with WinRT toast; PowerShell argv only; installer sets AppUserModelID on Start-menu shortcuts. | `bool`; never raises. |
| `actions.open_terminal` | `wt.exe new-tab ... -- powershell.exe` with a PowerShell console fallback. Ocean theme marker is a no-op. | `{"success", "confirmation"}`. |
| `actions.open_browser/open_chrome` | Directly spawns Chrome/Firefox with URL as one argv entry. No command-string interpolation. | Same dict. |
| `actions.get_chrome_tab_info` | `{}` on Windows v1; no unsupported UI scraping. | `{}`. |
| `actions.open_in_editor` | Real VS Code `Code.exe` if present, else `os.startfile`. `code.cmd` is rejected. | Same dict plus `editor`. |
| `preflight` accessibility/screen recording | Explicit OK: no Windows grant exists; blank-frame check still guards capture. | `ok` Check. |
| `preflight` Claude | `resolve_claude()` proves native `.exe`; version/login via that path. | `claude_cli`, `claude_login`. |
| `preflight` OAuth expiry | Reads only `claudeAiOauth.refreshTokenExpiresAt` from credential-file candidates; unknown stays non-fatal. | Same login wording. |
| `screen.screen_recording_granted` | `None` (neutral). | `None` means proceed to blank-frame check. |
| `screen.capture_screen` | `PIL.ImageGrab` one display; Pillow resize to 1280 edge; PNG in memory; blank-frame refusal. | `Shot(png,width,height)` or spoken `ScreenError`. |
| `screen.list_windows` | ctypes `EnumWindows`/process names via `QueryFullProcessImageNameW`; foreground first. | `list[Window]`, `ScreenError` on enumeration failure. |
| `dialog.normalize_key` | Unchanged closed vocabulary: Return, Escape, 1–9. | Identical. |
| `dialog.tty_for_pid*` | Proves pid → console/host → HWND; emits a short-lived synthetic `/dev/ttywin<hwnd>` token. | String or None. |
| `dialog.find_terminal_tab` | Re-proves HWND ownership at use time; stale/moved window is None. | `TerminalTab`-shaped or None. |
| `dialog.answer` | Re-checks identity, logs a human hand-off, returns `not_found`; **never sends input**. | `bad_key`, `no_tty`, `not_found`, `failed`. |
| `session_watch.pid_alive` | `OpenProcess`/`GetExitCodeProcess`; access denied is treated as alive/unknown rather than gone. | `bool`. |
| `session_watch.RosterEntry.steerable` | AF_UNIX path existence or `WaitNamedPipeW`. | `bool`. |
| `session_steer.post_to_session` | AF_UNIX or `\\.\pipe\...` with the same JSON lines and outcome strings. | `sent`/`not_live`/`refused`/`failed`. |
| `brain.command` | Temporarily substitutes a plain `claude` token before upstream `shlex.split`, then replaces argv[0] with native `.exe`. | `list[str]`. |
| `run_executor._command` | Same native-path substitution. | `list[str]`. |

## Phase 4 boundary

No `SendInput`, no `PostMessage`, no keystroke script, and no front-window
fallback exists in this repository. The exact HWND probe is present for Spike C
and future gated 4b work, but safe 4a is the final v1 behaviour: JARVIS names
the session and key aloud, the human presses it.

## Cross-session steering caveat

Spike A is unresolved. Windows builds of Claude Code may publish an AF_UNIX
path, a named pipe, or no `messagingSocketPath` at all. The transport supports
the first two and degrades to `not_live` for the third. No code claims a real
steer has been received until `spikes transport --send-test --acknowledge`
works on a live Windows session.
