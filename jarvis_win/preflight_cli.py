"""Plain-language preflight CLI for the installer's login/check-again page."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PLAIN_NAMES = {
    "claude_cli": "Claude Code",
    "claude_login": "Claude Code sign-in",
    "accessibility": "permission-prompt hand-off",
    "screen_recording": "screen sight",
    "fish_api_key": "Fish Audio voice key",
    "anthropic_key_leftover": "old Anthropic API key setting",
    "cross_session_inbound": "cross-session messages",
}


def load_env_file(path: Path) -> None:
    """Mirror server.py's conservative .env loading; never print values."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip())


def plain_line(check: Any) -> str:
    name = PLAIN_NAMES.get(getattr(check, "name", ""), getattr(check, "name", "check"))
    status = getattr(check, "status", "warn")
    remedy = getattr(check, "remedy", None) or getattr(check, "message", "")
    if status == "ok":
        return f"OK — {name}: {getattr(check, 'message', '')}"
    if status == "warn":
        return f"Worth knowing — {name}: {remedy}"
    return f"Needs attention — {name}: {remedy}"


def summary(checks: list[Any]) -> str:
    issues = [c for c in checks if getattr(c, "status", "") != "ok"]
    if not issues:
        return "Everything JARVIS needs looks ready."
    count = len(issues)
    noun = "thing needs" if count == 1 else "things need"
    return f"{count} {noun} attention. JARVIS will still install, but voice may not work until they are fixed."


def as_dict(check: Any) -> dict[str, Any]:
    return {
        "name": getattr(check, "name", ""),
        "status": getattr(check, "status", ""),
        "message": getattr(check, "message", ""),
        "remedy": getattr(check, "remedy", None),
    }


async def collect() -> list[Any]:
    import preflight  # sitecustomize patches it when JARVIS_WINDOWS_OVERLAY=1
    return await preflight.run_checks()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS Windows preflight")
    parser.add_argument("--app-root", default=os.getenv("JARVIS_APP_ROOT", "."))
    parser.add_argument("--output", help="JSON result path")
    parser.add_argument("--text-output", help="Plain-words result path")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero when any check fails")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_root = Path(args.app_root).resolve()
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    load_env_file(app_root / ".env")
    checks = asyncio.run(collect())
    payload = {
        "all_ok": all(getattr(c, "status", "") == "ok" for c in checks),
        "summary": summary(checks),
        "checks": [as_dict(c) for c in checks],
    }
    text = payload["summary"] + "\n" + "\n".join(plain_line(c) for c in checks) + "\n"
    data = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(data, encoding="utf-8")
    if args.text_output:
        Path(args.text_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.text_output).write_text(text, encoding="utf-8")
    print(text, end="")
    if args.strict and any(getattr(c, "status", "") == "fail" for c in checks):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
