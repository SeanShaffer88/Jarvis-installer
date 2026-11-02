# Build a local installer

## Requirements on the build machine

- Windows 10 1809+ or Windows 11, x64.
- Python 3.11+, Git, Node.js + npm (**build time only**), Inno Setup 6.4+.
- A **private local** JARVIS fork, or outbound access to the pinned public
  upstream commit.
- Optional: a Windows `openssl.exe` (Git for Windows supplies one).

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

## Pinning and updates

`upstream.json` pins the source revision read for the plan. Changing it
requires:

1. re-reading the five macOS files and the two Windows traps;
2. rerunning `python tools/run_tests.py`;
3. rerunning all Phase 0 spikes;
4. updating `docs/STATUS.md` honestly.

The installer itself has no auto-update: SEAN reruns a newly built installer
over the top.
