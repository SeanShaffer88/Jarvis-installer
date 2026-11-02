# Licence and distribution notice

The installer, Windows overlay, build tooling, tests, and documentation in
this repository are © 2026 Sean Shaffer and are offered under the MIT licence
in `LICENSE`.

JARVIS itself is © 2026 Ethan Rogers. Its licence permits personal,
educational, and non-commercial use and requires attribution on substantial
copies. Commercial use of JARVIS or a derivative work requires a separate
licence from the author. The original plan therefore requires the modified
fork, the generated installer payload, and the compiled installer to stay
private/local to SEAN's PC.

This repository intentionally contains **no upstream source files**.
`tools/build_package.py` creates a local payload from a private fork (or a
pinned public clone) and includes a copy of the upstream licence as
`UPSTREAM_LICENSE.txt` in that payload. `.gitignore` excludes `.build`,
`dist`, payloads, executables, certificates, secrets, and runtime data.

Do not attach the built installer or payload to a public GitHub release
without the upstream author's permission.
