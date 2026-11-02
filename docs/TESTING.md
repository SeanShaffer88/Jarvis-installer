# Testing and gates

## Linux unit suite

```bash
python tools/run_tests.py
```

The 100-test suite uses only the Python standard library. It covers:

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
- Inno Setup and PowerShell static safety checks;
- one-click path/env/redaction/hidden-argv helpers and a fake full setup flow;
- frozen MCP/restart patches, no-terminal/no-editor action patches, and hidden toast argv;
- PyInstaller one-file spec generation, payload secret scan, and SHA-256 manifests.

These tests do **not** prove a real Windows desktop works.

## Windows gates

Follow [`SPIKES.md`](SPIKES.md) first. Then:

1. Compile `JarvisSetup.iss` with Inno Setup 6.4+; fix compiler errors and
   rerun `tools/lint_iss.py`.
2. Install on a clean Windows VM with no Python, no Git, no Claude Code, and
   an existing Chrome. Confirm no elevation prompt and no Node install.
3. Walk every wizard page. Confirm the log contains no Fish key and the `.env`
   ACL grants only the current user.
4. Finish without signing in; verify the installer still completes, then sign
   in and use Check again.
5. Start JARVIS. Confirm hidden `server.py`, `https://localhost:8340`, the
   one-time certificate exception, Chrome microphone permission, and dashboard
   on the same origin.
6. Uninstall. Confirm `.env`, `data/`, memory, certs, logs, and `.venv/` remain;
   confirm Startup shortcut and verified server process are gone.
7. Reinstall over the top. Confirm no duplicate key page requirement, no
   regenerated cert, no lost memory, and no second server on port 8340.
8. Run `spikes baseline --run` and write the failure catalogue.

## One-click Windows gates

Follow [`ONECLICK.md`](ONECLICK.md) before calling the one-click path working:

1. Compile `JarvisOneClick.exe` with PyInstaller on Windows.
2. Run on a clean VM with no Python, no Git, no Node, and no Claude Code.
3. Confirm no console windows appear during WinGet, certificate, sign-in,
   startup-shortcut, server, or toast helpers.
4. Confirm the first GUI asks only for the Fish Audio key and opens browser
   sign-in when needed.
5. Confirm Chrome uses exactly `https://localhost:8340`, the microphone works,
   and JARVIS speaks.
6. Relaunch without a key prompt; replace the exe and confirm data survives.

## Field test — the verdict

Label **Unverified** until SEAN completes this on his own PC:

1. Speak to JARVIS; he answers aloud.
2. Brainstorm a project by voice.
3. Approve a spec by voice; a real build runs.
4. A second Claude Code session blocks on a permission prompt.
5. JARVIS posts a toast and speaks an alert naming the session.
6. SEAN presses the key himself (4a; JARVIS must not press it).
7. Ask “what am I looking at?” and receive a correct screen-sight answer.
8. Stop JARVIS from the shortcut; no orphan server remains.

Record failures as spike/port/installer bugs with logs, not as caveats in a
“passed” claim.
