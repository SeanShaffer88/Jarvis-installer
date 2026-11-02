"""PyInstaller entry point for JarvisOneClick.exe.

One binary has four modes. The default is the GUI; ``--launch`` is used by the
Startup shortcut; ``--server`` and ``--mcp`` are hidden child modes.
"""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--server" in args:
        from . import frozen
        return frozen.run_server()
    if "--mcp" in args:
        from . import frozen
        return frozen.run_mcp()
    if "--launch" in args:
        from . import gui
        if gui.Controller().quick_launch():
            return 0
        return gui.run()
    from . import gui
    return gui.run()


if __name__ == "__main__":
    raise SystemExit(main())
