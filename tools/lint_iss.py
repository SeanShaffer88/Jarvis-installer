#!/usr/bin/env python3
"""Static safety/structure checks for the Inno Setup script.

This is not a compiler check (ISCC is Windows-only), but it catches the
configuration mistakes that would silently break the plan's guarantees.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "installer" / "JarvisSetup.iss"


def section(text: str, name: str) -> str:
    match = re.search(rf"^\[{re.escape(name)}\]\s*$([\s\S]*?)(?=^\[|\Z)",
                      text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def lint(text: str) -> list[str]:
    errors: list[str] = []
    for name in ("Setup", "Languages", "Dirs", "Files", "Icons", "UninstallRun",
                 "UninstallDelete", "Code"):
        if not section(text, name):
            errors.append(f"missing [{name}] section")
    required = (
        "PrivilegesRequired=lowest",
        r"DefaultDirName={localappdata}\Programs\Jarvis",
        "SetupLogging=yes",
        "MinVersion=10.0.17763",
        "ArchitecturesAllowed=x64compatible",
        r'Source: "payload\*"',
        "uninsneveruninstall",
        "CreateInputQueryPage",
        "CreateOutputProgressPage",
        "CancelButtonClick",
        "NextButtonClick",
        "ssPostInstall",
        "AppUserModelID:",
        "SetSecretAcl.ps1",
        "InstallPrereqs.ps1",
        "setup_runtime.py",
    )
    for value in required:
        if value not in text:
            errors.append(f"missing required directive: {value}")
    if text.count("AppUserModelID:") < 3:
        errors.append("all three JARVIS shortcuts need AppUserModelID")
    forbidden = (
        "PrivilegesRequired=admin",
        "npm install -g",
        "irm https://claude.ai/install.ps1 | iex",
        "0.0.0.0",
        "--host 0.0.0.0",
    )
    for value in forbidden:
        if value in text:
            errors.append(f"forbidden installer directive: {value}")
    uninstall = section(text, "UninstallDelete")
    for value in (r"{app}\.env", r"{app}\data", "cert.pem", "key.pem", r"{app}\*"):
        if value in uninstall:
            errors.append(f"uninstall must preserve: {value}")
    if re.search(r"Log(?:Setup)?\([^)]*KeysPage\.Values\[0\]", text):
        errors.append("Fish key is logged")
    if "BuildJobJson" not in text or "SaveStringToFile(JobPath, BuildJobJson, False)" not in text:
        errors.append("secret job file write is missing")
    # A rough Pascal block sanity check; ISCC remains the real compiler gate.
    # try/finally/except blocks open without a 'begin' but still close with 'end'.
    opens = len(re.findall(r"\b(?:begin|try)\b", text, flags=re.IGNORECASE))
    closes = len(re.findall(r"\bend\b", text, flags=re.IGNORECASE))
    if opens != closes:
        errors.append(f"unbalanced begin/try/end blocks: {opens} vs {closes}")
    return errors


def main() -> int:
    errors = lint(ISS.read_text(encoding="utf-8"))
    if errors:
        for error in errors:
            print("ISS lint:", error, file=sys.stderr)
        return 1
    print(f"ISS static checks passed: {ISS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
