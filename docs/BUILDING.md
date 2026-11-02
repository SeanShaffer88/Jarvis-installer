# Build a local installer

## Requirements on the build machine

- Windows 10 1809+ or Windows 11, x64.
- Python 3.11+ with tkinter, Git, Node.js + npm (**build time only**), and
  Inno Setup 6.4+ for the original wizard.
- PyInstaller and Playwright + Chromium for the one-click `.exe` path.
- A **private local** JARVIS fork, or outbound access to the pinned public
  upstream commit.
- A Windows `openssl.exe` (Git for Windows supplies one); required by the
  one-click build.

Node is used only to produce `frontend/dist`; the target PC never runs Vite or
Node.

## Stage the payload

```powershell
git clone <this-repo-url> Jarvis-installer
cd Jarvis-installer
py -3 tools\build_package.py --upstream C:\src\jarvis-win --openssl "C:\Program Files\Git\usr\bin\openssl.exe"
```

Without `--upstream`, the script fetches the pinned ref from `upstream.json`
into `.build/upstream`. With `--skip-frontend`, it creates a test placeholder
instead of a release-capable `dist`; do not compile that. `--frontend-dist`
accepts a pre-built `frontend/dist` directory.

The staging output is:

```text
.build\installer\
  JarvisSetup.iss
  scripts\                 extracted helpers + prereqs.json
  payload\                 app root, overlay, frontend/dist, notices, manifest
  build-manifest.json      SHA-256 of every payload file
  dist\                    ISCC output directory
```

`.build/`, `dist/`, payloads, executables, certs, secrets, logs, and runtime
data are gitignored. The payload includes `UPSTREAM_LICENSE.txt`,
`INSTALLER_LICENSE.txt`, `THIRD_PARTY_NOTICES.txt`, and
`INSTALL_MANIFEST.json`. The build script removes `frontend/node_modules`
after `npm run build`; only `frontend/dist` ships. `npm ci` may report
advisories in upstream build-only dev dependencies — review them against the
pinned upstream ref rather than running `npm audit fix` blindly. No Node or
Vite runtime is installed on the target PC.

## Compile

```powershell
cd .build\installer
iscc JarvisSetup.iss
```

The compiled `dist\JarvisSetup.exe` is a per-user installer. Do not publish it
or the payload without the upstream author's commercial licence.

## One-click `JarvisOneClick.exe`

The no-console end-user path is built by double-clicking
[`tools/build_oneclick_gui.pyw`](../tools/build_oneclick_gui.pyw) and choosing
the private JARVIS fork. The GUI silently installs PyInstaller/Playwright if
missing, prepares Chromium, stages the private payload, and invokes
[`tools/build_oneclick.py`](../tools/build_oneclick.py). Output:

```text
.build\oneclick\dist\JarvisOneClick.exe
```

The generated PyInstaller spec is one-file and windowed, with no admin request,
no Node runtime, no venv, no Inno Setup, and a SHA-256 manifest. The compiled
exe embeds upstream source and must stay private/local. See
[`ONECLICK.md`](ONECLICK.md). No compiled exe is produced in this Linux
sandbox; the one-click path is **Unverified**.

## Pinning and updates

`upstream.json` pins the source revision read for the plan. Changing it
requires:

1. re-reading the five macOS files and the two Windows traps;
2. rerunning `python tools/run_tests.py`;
3. rerunning all Phase 0 spikes;
4. updating `docs/STATUS.md` honestly.

The installer itself has no auto-update: SEAN reruns a newly built installer
over the top.
