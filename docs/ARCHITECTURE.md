# Architecture

```text
Jarvis-installer (public, MIT: installer + overlay only)
  ├─ tools/build_package.py
  │    ├─ private local upstream fork / pinned public clone
  │    ├─ npm ci && npm run build  (build machine only)
  │    ├─ Windows requirements = upstream requirements + Pillow
  │    ├─ optional bundled openssl.exe
  │    └─ .build/installer/payload  (gitignored, local/private)
  ├─ installer/JarvisSetup.iss
  └─ jarvis_win  ───────────────── copied into payload root

Generated app root on SEAN's PC (%LOCALAPPDATA%\Programs\Jarvis)
  ├─ server.py, frontend/dist, requirements-windows.txt, .env, certs, data/
  ├─ sitecustomize.py
  └─ jarvis_win/
       ├─ hook.py               import-time platform dispatch
       ├─ *_win.py              nine in-memory module patches
       ├─ win32.py / transport.py / win_paths.py
       ├─ setup_runtime.py      install-time venv, pip, Chromium, certs
       ├─ launcher.py           hidden server + health check + Chrome
       ├─ preflight_cli.py      plain-words checks
       ├─ spikes.py             Phase 0 probes
       └─ ShowToast.ps1         fixed argv-only toast script
```

## Import hook

`sitecustomize.py` calls `jarvis_win.hook.install()` on Windows. The hook is a
`sys.meta_path` finder that wraps the loader for nine top-level modules:

| Module | Patch |
|---|---|
| `dialog` | safe 4a identity probe, closed vocabulary, no key sending |
| `notifier` | Windows toast with argv-only untrusted text |
| `actions` | wt.exe, Chrome argv, `{}` Chrome tab info, VS Code/startfile |
| `screen` | Pillow ImageGrab + ctypes EnumWindows |
| `preflight` | native Claude, Windows credentials file, neutral grants |
| `session_watch` | OpenProcess pid liveness, pipe-aware `steerable` |
| `session_steer` | AF_UNIX or named-pipe transport |
| `brain` | native `claude.exe` command patch |
| `run_executor` | native `claude.exe` command patch |

The upstream module is loaded normally, then patched in place. Function names,
argument shapes, dataclasses, and outcome strings are preserved, so `server.py`
never learns which OS it is on. On macOS the hook is inert.

## Why an overlay rather than a committed fork

Upstream JARVIS is personal/non-commercial only, and a substantial copy in this
public repository would be both a licence problem and a maintenance burden.
The overlay is small, independently tested, and can be re-applied after the
pinned upstream ref changes. The generated payload includes the upstream
licence and stays local.

## One origin, one port

`frontend/dist` is served by `server.py` at `https://localhost:8340` on
`127.0.0.1`. There is no Vite dev server at runtime, no Node on the PC, and no
5173→5174 microphone-origin trap. Self-signed certs include a localhost SAN.
The launcher waits for `/api/health` before opening Chrome.


## One-click frozen path

`oneclick/` plus `tools/build_oneclick.py` produce a separate one-file
`JarvisOneClick.exe`. It embeds the private payload, Python runtime,
`frontend/dist`, Windows overlay, `openssl.exe`, and Playwright Chromium. The
persistent `%LOCALAPPDATA%\Programs\Jarvis` root keeps `.env`, `data\`, certs,
logs, and `runtime.json`. The same exe runs four modes: default GUI,
`--launch`, hidden `--server`, and hidden `--mcp`. One-click patches disable
visible terminals/editors, hide helper windows, rewrite MCP/restart commands,
and keep loopback/origin behaviour unchanged. See [`ONECLICK.md`](ONECLICK.md).
