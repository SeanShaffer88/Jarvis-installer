# Phase 0 spikes — run before declaring Windows support

Run these on SEAN's PC or a clean Windows VM with his Claude login and the
terminal host he actually uses (Windows Terminal). Use the installed venv and
the overlay:

```powershell
cd %LOCALAPPDATA%\Programs\Jarvis
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . roster
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . claude
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . windows
.\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . baseline --run
```

## Spike A — cross-session steering transport

1. Start 2–3 real Claude Code sessions in Windows Terminal.
2. Run `spikes roster`. Record `socket_path`, `transport`, `alive`, and
   `steerable` for every entry.
3. If a named pipe or AF_UNIX path is present, deliberately send one benign
   message to a session you control:

   ```powershell
   .\.venv\Scripts\python.exe -m jarvis_win.spikes --app-root . transport `
     --path "<socket_path>" --send-test --acknowledge
   ```

4. Confirm the target session actually received the text. `sent` alone only
   means bytes left this process.

**Gate:** if no usable path exists, steering is display-only on Windows v1 and
the docs must say so. Do not fake a transport with UI scraping.

## Spike B — native Claude spawn and credentials

1. `spikes claude` must report a native `.exe`, version ≥ 2.1.224, parseable
   `auth status`, and which credential-file candidates exist.
2. In a fresh terminal, confirm `claude --version` and `claude auth status`.
3. Start a JARVIS brain/run and prove `asyncio.create_subprocess_exec` spawned
   it without WinError 193.

**Gate:** if `claude.cmd` is the only binary, stop; reinstall native Claude
Code. The overlay refuses silently substituting the shim.

## Spike C — roster and window identity

1. With 2–3 live sessions, run `spikes windows` (or `windows --pid <pid>`).
2. For each pid, record: process chain, console HWND, candidate HWNDs, and
   whether `verified` is true.
3. A verified result must be one exact HWND owned by the target or a trusted
   terminal host. More than one candidate must stay unverified.

**Gate:** 4a ships regardless — no input is sent. A reliable mapping is only a
prerequisite for considering future 4b, which is not built here.

## Spike D — test baseline

`spikes baseline --run` executes the upstream `tests/` suite under the
installed venv and writes `logs/spike-baseline.txt`. Catalogue every failure as:

- (a) mac-only by design — record the reason for exclusion;
- (b) Windows port bug — fix in `jarvis_win/` and add a test;
- (c) upstream Windows bug — report upstream, do not silently patch here.

The resulting written catalogue is the real port scope; Linux unit tests are
not a substitute.

## Do not do during spikes

- Do not send keystrokes, free text, or focus-stealing input.
- Do not log token values, Fish keys, or transcript contents.
- Do not mark the field test passed from a lab-only probe.
