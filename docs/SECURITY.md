# Security and safety properties

## Loopback and origin

JARVIS spawns Claude with broad permissions and reads local sessions. The
installer therefore preserves the upstream trust model: bind `127.0.0.1`,
serve one pre-built origin at `https://localhost:8340`, add no CORS or LAN
exposure, and keep the self-signed certificate's name pinned to localhost.
The launcher never passes `--host 0.0.0.0`.

## Secrets

- Fish Audio key is captured in a masked field, written to an ACL'd temp job
  file, then written to `.env` with a user-only ACL.
- The key is never an executable argument, never in the install log, and never
  in a progress line. `setup_runtime.Redactor` scrubs exact values, `.env`
  lines, and JSON values from child output.
- The temp job file is overwritten and deleted in `finally`, on success,
  failure, and cancel.
- `key.pem` also receives a user-only ACL.
- Uninstall keeps `.env` and user data rather than copying them elsewhere.

## Toast argv boundary

Session titles and transcript text are untrusted. `ShowToast.ps1` is fixed;
Python passes `-File` and separate `-Title`/`-Message`/`-Subtitle` argv values.
PowerShell assigns them with `XmlDocument.InnerText`. There is no `-Command`,
no XML string interpolation, and no shell string. Failures log only the process
exit code, not stderr that might echo untrusted text.

## Action argument lists

`open_browser` passes a URL as one Chrome argv entry. `open_terminal` passes a
command as one PowerShell argv entry after `wt.exe ... --`, never as a
Python-composed shell line. `open_in_editor` rejects `code.cmd` and uses a real
`Code.exe` or `os.startfile`.

## Dialog closed vocabulary

`dialog.normalize_key` is untouched. Only Return, Escape, and digits 1–9 are
accepted; free text returns `bad_key` before any identity lookup. Windows v1
proves a pid/HWND chain and then returns `not_found` with an audit log. No
`SendInput`, no keystroke script, no focus fallback. A stale identity token is
re-proved and discarded.

## Native Claude only

`brain_win` and `preflight_win` resolve a real `claude.exe`. A `.cmd`/`.bat`
npm shim is refused with a clear error rather than failing as WinError 193 or
running through an accidental shell. WinGet installs `Anthropic.ClaudeCode`;
Node is not installed.

## Screen sight

Screenshots are user-initiated only, held in memory, capped at 1280 edge and
4 MB, blank-frame checked, and never fed into ambient context. Window titles
are treated as untrusted tool results. No screenshot is saved by the Windows
implementation.

## Installer integrity and scope

Prerequisites come from signed WinGet packages in user scope; no `irm | iex`,
no admin, no npm global install. The build payload is local/private and
includes a SHA-256 manifest. Generated installers, secrets, certs, data, and
the venv are gitignored.

## Residual risks

- A self-signed localhost certificate still requires a one-time Chrome
  exception.
- `https://localhost:8340` is trusted by origin guards; any local process can
  speak to loopback. This is the upstream design and is not widened here.
- Cross-session steering transport and HWND mapping are unverified until
  Spikes A/C run on a real Windows machine.


## One-click frozen exe

The one-click path keeps the same loopback/origin trust model and adds a
frozen-exe secret scan that refuses `.env`, certificates, private databases,
logs, runtime state, `node_modules`, `.iss` files, and unexpected executables or
PowerShell scripts. The Fish key stays in an external user-only `.env`; the
frozen process scrubs inherited `ANTHROPIC_*` and `CLAUDE_CODE_*` variables.
The compiled exe embeds upstream source and must remain private/local. Hidden
helpers never place the key on a command line or in a log.
