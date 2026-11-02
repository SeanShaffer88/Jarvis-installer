# Verification status

**Overall: implementation files are present; Linux unit/static checks and a
pinned frontend build pass; Windows behaviour is Unverified.**
No Phase 0 spike, Inno Setup compilation, clean-VM install/uninstall/reinstall,
upstream Windows suite, real toast, real screenshot, or SEAN field test has been
run in this session. Linux unit tests exercise safety invariants with fakes;
they are not a Windows verdict.

Verified in this session:

- `python -m compileall -q jarvis_win tools tests` — pass.
- `python tools/lint_iss.py` — pass.
- `python tools/run_tests.py` — 69 tests pass.
- `python tools/build_package.py --upstream /home/user/_upstream_jarvis --out .build/installer` —
  staged 215 payload files and built `frontend/dist` from the pinned upstream
  ref. No `.env`, private database, or `frontend/node_modules` is shipped.
- `npm ci` reported two high-severity advisories in upstream build-only dev
  dependencies. The lockfile was not changed and the target PC receives no
  Node or Vite runtime.

| Plan phase | Implementation | Verification |
|---|---|---|
| 0 Spikes A–D | `jarvis_win/spikes.py`, `docs/SPIKES.md` | **Unverified** — must run on SEAN's PC / clean VM with his Claude login. |
| 1 Platform layer | `jarvis_win/hook.py`, `sitecustomize.py`, nine patch modules | Linux unit tests for hook/application; real Windows import untested. |
| 2 Notifier / actions / preflight | `notifier_win.py`, `actions_win.py`, `preflight_win.py`, `ShowToast.ps1` | Linux unit tests with fakes; real toast, Chrome, and wt.exe untested. |
| 3 Screen sight | `screen_win.py`, `win32.py`, Pillow | Logic and blank-frame tests with fake images; real multi-monitor GDI capture untested. |
| 4 Dialog 4a | `dialog_win.py`, `console_probe.py`, identity probe | Linux unit tests for closed vocabulary / no-send; HWND identity chain unverified. **4b deliberately absent.** |
| 5 Installer + launcher | `JarvisSetup.iss`, PowerShell helpers, `setup_runtime.py`, `launcher.py` | Static checks and Python unit tests; Inno Setup compile, clean-VM install, uninstall/reinstall untested. |
| 6 Gates + field test | `tools/run_tests.py`, `docs/TESTING.md` | 69 Linux unit tests, static lint, and frontend build pass in sandbox; upstream Windows suite, VM lifecycle, and field test outstanding. |

## Hard gates still open

1. **Spike A:** what does `messagingSocketPath` look like in Windows Claude
   Code 2.1.224+? Until a real benign steer is received, steering is
   transport-ready but not feature-verified.
2. **Spike B:** confirm `%USERPROFILE%\.claude\.credentials.json` and that
   `claude auth status` returns the same JSON under native `claude.exe`.
3. **Spike C:** prove pid → console/host → HWND for Windows Terminal with 2–3
   real sessions. Ambiguity must stay `not_found`.
4. **Spike D:** run the upstream suite on Windows and catalogue failures.
5. **Installer:** compile with Inno Setup 6.4, install on a clean VM, log in,
   uninstall, confirm data survives, reinstall, and resume.
6. **Field test:** speak → brainstorm → approve a spec by voice → build →
   blocked session → toast/spoken alert → user presses key → screen sight.

Never describe the field-test verdict as passed until step 6 actually happens.
