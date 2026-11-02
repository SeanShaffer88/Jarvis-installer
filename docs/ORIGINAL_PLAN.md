# JARVIS on Windows — Option 2 Plan (installer + Windows port)

Status: **PLAN ONLY — not built.** Prepared 2026-11-01 from a full read of
`ethanplusai/jarvis` @ main (27 commits). SEAN's call pending on §9 decisions.

Goal in one line: a single per-user Windows installer that sets JARVIS up end
to end on SEAN's PC, plus a Windows port of its macOS-only parts so it
actually works — not just installs.

---

## 1. What I verified in the source

JARVIS = Python/FastAPI backend (`server.py`, ~7,000 lines) + Vite/TypeScript
frontend + one long-lived `claude -p` "brain" on the user's Claude
subscription. Voice in = Chrome Web Speech API (Chrome only, no fallback).
Voice out = Fish Audio (API key required, no fallback).

The macOS surface is smaller than the README makes it sound. Everything
mac-specific lives in 5 files; the rest is already cross-platform in
structure (paths via `Path.expanduser()`, subprocesses via argument lists):

| File | Lines | macOS dependency |
|---|---|---|
| `dialog.py` | 392 | Terminal.app tabs by tty over AppleScript; sends one keystroke (Return/Escape/1-9, closed set) to answer a Claude Code permission prompt |
| `notifier.py` | 130 | `osascript display notification` when no browser tab is listening |
| `screen.py` | 409 | `screencapture` + `sips` for screenshots, AppleScript window list, CoreGraphics permission probe via ctypes |
| `actions.py` | 275 | AppleScript: open Terminal.app + run command, open Chrome, read active Chrome tab; macOS `open` for editor fallback |
| `preflight.py` | 726 | 2 of ~7 checks are mac-only: Accessibility (osascript) and Screen Recording; Keychain read for OAuth expiry (`security find-generic-password`) |

Already fine on Windows in principle: `brain.py`, `run_executor.py`,
`builds.py`, `specs.py`, `run_store.py` (SQLite), `jarvis_memory.py`,
`tts.py`, `speech.py`, `browser.py` (Playwright), `usage_*`, dashboard,
Fish/Claude env scrubbing (`claude_env.py`).

Two hidden Windows traps found while reading, not in the README:

1. **npm `claude.cmd` shim.** `brain.py`/`run_executor.py` spawn `claude`
   with `asyncio.create_subprocess_exec`, which cannot execute the `.cmd`
   shim npm installs on Windows (WinError 193). Fix: install Claude Code's
   **native Windows `.exe`** build instead of the npm package, or resolve
   and wrap the shim explicitly. The installer must do the native route.
2. **`os.kill(pid, 0)` liveness check** in `session_watch.py`. That idiom
   is Unix; on Windows it does not have the same "check only" meaning.
   Needs a ctypes `OpenProcess`/`GetExitCodeProcess` replacement.

Plus one open question code alone cannot answer (§2, Spike A).

## 2. Phase 0 — Spikes first (gate: no port code until these pass)

Four short hands-on checks on SEAN's PC (or a clean Windows VM with his
Claude login). Each either clears a Phase or kills/changes it honestly.

- **Spike A — Cross-session steering transport (BIGGEST RISK).**
  `session_steer.py` posts to another Claude Code session over a Unix
  socket (`socket.AF_UNIX`). Does the Windows build of Claude Code
  (2.1.224+) create the same roster under `~/.claude/sessions`, and what
  is `socket_path` there — Unix socket (supported on Win10 1803+),
  a named pipe (`\\.\pipe\...`), or nothing? Outcome decides: keep,
  rewrite to named-pipe client, or degrade "steer a session" to
  display-only on Windows v1.
- **Spike B — Claude spawn.** Native `claude.exe` installed, logged in;
  prove `create_subprocess_exec` can spawn the brain and a run, and that
  `claude auth status` parses the same JSON as on Mac. Also confirm where
  Windows Claude Code stores credentials (expected
  `%USERPROFILE%\.claude\.credentials.json`, vs Mac Keychain) so the
  preflight login check reads the right place.
- **Spike C — Session roster + pid liveness.** Run 2-3 real Claude Code
  sessions in SEAN's normal terminal; confirm `session_watch.py` lists
  them correctly with the Windows pid-liveness replacement sketched.
- **Spike D — Test baseline.** Run the upstream suite (~1,640 tests, 89
  files) on Windows unmodified; catalogue failures as (a) mac-only by
  design, (b) port bugs to fix, (c) upstream Windows bugs. This list is
  the port's real scope — no guessing after this.

**Which terminal does SEAN run Claude Code in?** (Windows Terminal /
PowerShell window / VS Code terminal / other) — Spike C + Phase 4 depend
on it. Asked in §9.

## 3. Phase 1 — Fork + platform layer (foundation, no behaviour change)

- Private fork/copy `jarvis-win` (see §8 licence note — local/private only).
- Introduce a thin platform dispatch in the 5 mac files only: keep the Mac
  implementation untouched, add a `_win` implementation behind
  `sys.platform == "win32"`, same function signatures and same outcome
  strings (`sent` / `not_found` / `not_permitted` / `failed` …) so
  `server.py` and the brain never learn which OS they're on.
- Everything-is-an-operation rule applies: each ported capability is a
  plain function first; UI/installer call it, never the reverse.

## 4. Phase 2 — Easy ports (each independently shippable)

1. **Notifier → Windows toast.** Fixed PowerShell/WinRT toast script,
   text passed as argv only — preserving the original's key safety
   property (untrusted session titles never enter script source).
   Installer registers an AppUserModelID + Start-menu shortcut, which
   Windows requires for toasts from a non-packaged app.
2. **Actions.** `open_terminal` → Windows Terminal (`wt.exe`) with
   PowerShell fallback; drop the Mac "Ocean theme" marker (or map to a
   named WT profile — SEAN's call, cosmetic). `open_browser` →
   `Start-Process` Chrome. `get_chrome_tab_info` → returns `{}` on
   Windows v1 (callers already tolerate empty); reading Chrome's active
   tab has no supported Windows API — do not fake it with UI scraping.
   `open_in_editor` → `code` on PATH, fallback `os.startfile`.
3. **Preflight.** Accessibility + Screen Recording checks → "not
   applicable on Windows" = OK (Windows has no equivalent grants).
   OAuth expiry probe → read the Windows credentials file from Spike B,
   or return "unknown" (the Mac code already treats unknown ≠ failed).
4. **Screen permission probe** → neutral (no Windows grant exists).

## 5. Phase 3 — Screen sight

- Window list: `EnumWindows` + `GetWindowText` via ctypes `user32`
  (no new dependency, mirrors the ctypes approach the Mac code uses).
- Capture: ctypes GDI `BitBlt` from the desktop DC, or PowerShell
  `System.Drawing.CopyFromScreen` — decide in Phase 3 by prototype
  speed; both are stdlib/OS-only. One display per call, same as Mac.
- Resize from 1920→1280 edge: replace `sips`. Cleanest is one new
  dependency, **Pillow** (also gives PNG encode for free); the
  dependency-free path (PowerShell Drawing) is uglier. Decision in §9 —
  my recommendation: accept Pillow, it's the standard, maintained tool
  for exactly this and the Mac path keeps using `sips`.

## 6. Phase 4 — Answering permission prompts (the hard, dangerous one)

`dialog.py` is deliberately the most careful file in the project: target
found by exact tty identity, never by focus; closed key vocabulary;
`not_found` (press nothing) is the expected common case.

Windows has no tty. Equivalent identity chain to prove in Spike C:
session pid → console/host process → window handle (HWND) via
`GetConsoleWindow` / window enumeration matched on owning pid.

- **4a (v1, safe):** if the exact HWND cannot be proven, return
  `not_found` exactly like the Mac code does for non-Terminal hosts.
  JARVIS tells SEAN out loud which session needs him; SEAN presses the
  key. This ships.
- **4b (only if 4a's mapping proves reliable for SEAN's terminal):**
  `SendInput` of the same closed set (Return/Escape/1-9 only) to the
  verified HWND after re-checking ownership at press time — same
  re-check the Mac send script does. No free text, ever. No
  "front window" fallback, ever.

If SEAN runs Claude Code inside VS Code's terminal, 4b may be
impossible to make safe (no per-tab identity) — then 4a is the final
answer, stated plainly, not worked around.

## 7. Phase 5 — The installer (Inno Setup, per-user, SEAN's pattern)

Shape follows SEAN's proven installers (HushRun/ytTrayDL): Inno Setup,
per-user, no admin, `%LOCALAPPDATA%\Programs\Jarvis`, Start-menu entry,
uninstaller keeps user data, install log kept.

Wizard flow:
1. **Checks page:** Windows 10/11, Chrome present (hard requirement,
   explained in plain words), disk space (~1 GB with Chromium + venv).
2. **Prerequisites, installed only if missing:** Python 3.11+ (official
   python.org installer, silent), Git (needed to clone projects JARVIS
   builds), Claude Code **native .exe** (never the npm shim, per §1).
   Node is **not** needed on the PC — see next point.
3. **Frontend pre-built:** the installer package ships `frontend/dist`
   built beforehand. `server.py` already serves `dist` itself
   (`StaticFiles` mount), so at runtime only Python runs, on
   https://localhost:8340 — no Vite dev server, no Node, and the Chrome
   mic permission stays pinned to one origin/port (the Mac README's
   5173→5174 mic trap disappears).
4. **Keys page:** Fish Audio key (masked field, required — plain-words
   note that there's no voice without it), optional name / brain model /
   voice ID. Written to `.env` with a tight ACL; the key is never put in
   the install log or any command line.
5. **Setup run (progress page, cancellable, logged):** create venv →
   `pip install -r requirements.txt` (+ Pillow if §5 decision passes) →
   `playwright install chromium` → generate self-signed `cert.pem`/
   `key.pem` (bundled OpenSSL binary shipped in the installer — Windows
   has none by default) → create `data/` → first-run preflight, results
   shown in plain words.
6. **Claude login hand-off (last page):** installer cannot log in for
   him — a button opens a terminal running `claude` so SEAN logs in
   once, then a "Check again" re-runs preflight live.
7. **Finish:** optional "Start JARVIS now" + "Start with Windows".
   Shortcuts: *JARVIS* (launcher), *JARVIS Dashboard*, *Stop JARVIS*.

Launcher: a small script that starts `server.py --host 127.0.0.1`
hidden, waits for the 8340 health check, then opens Chrome to the
dashboard. Loopback-only binding kept — JARVIS runs Claude with full
permissions, the upstream design trusts loopback, that stays.

Update story: "Check for updates" = re-run installer over the top
(`data/`, `.env`, certs, memory all preserved). No auto-update, no
nagging — per SEAN's every-program rules.

## 8. Phase 6 — Gates + field test

- Upstream test suite green on Windows (minus the Phase 0 catalogue's
  mac-only set, each exclusion written down with its reason), plus new
  Windows tests mirroring the Mac ones per ported file (toast argv
  safety, dialog closed-vocabulary, screen blank-frame, preflight).
- Installer tested on a clean Windows VM: install → login hand-off →
  uninstall keeps data → reinstall resumes.
- **SEAN's field test is the verdict** (labelled Unverified until then):
  speak → brainstorm → approve a spec by voice → a build runs → a second
  session blocks → toast + spoken alert → (4b if built) JARVIS answers
  the prompt → screen sight answers "what am I looking at".
- Licence: upstream is personal/non-commercial use only, commercial use
  needs the author's licence. So: installer and fork stay **private /
  local to SEAN's PC** — no public GitHub release of the fork or the
  installer without the author's permission. Fine for personal use.

## 9. Decisions needed from SEAN before building

1. **Terminal host** — where do you run Claude Code? (Windows Terminal /
   VS Code / other) — decides whether Phase 4b is even possible.
2. **Pillow** — accept one new Python dependency for screenshots
   (recommended), or stay dependency-free with the clunkier route?
3. **Answering prompts v1** — ship safe 4a first (JARVIS alerts, you
   press the key) and add 4b later if it proves safe (recommended),
   or hold v1 until 4b works?
4. **Install location of record** — a private local folder/repo for the
   fork (recommended, per licence), confirm not a public repo.

## 10. Rough effort (estimates, not promises)

| Phase | Effort |
|---|---|
| 0 Spikes | Half a day, incl. SEAN's login/terminal time |
| 1 Platform layer | A few hours |
| 2 Easy ports | Half a day |
| 3 Screen | Half a day |
| 4 Dialog (4a; 4b extra) | Half a day; 4b +half a day if viable |
| 5 Installer + launcher | A day, incl. clean-VM test |
| 6 Gates + fixes | Half a day + SEAN's field test |

Total ≈ 3–4 working days end to end, with Phase 0 able to shrink it:
if Spike A kills cross-session steering on Windows, Phases 4/steer
shrink and the honest v1 scope is voice + builds + watching.
