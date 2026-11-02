"""Double-click builder for JarvisOneClick.exe — no console window.

Run this file with Windows ``pythonw.exe`` (the normal .pyw association). It
selects a private JARVIS fork, installs build-only Python packages silently,
and invokes tools/build_oneclick.py with hidden child processes.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oneclick.win import run_hidden  # noqa: E402


def default_fork() -> Path:
    profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    return profile / "src" / "jarvis-win"


def ensure_module(module: str, pip_name: str, progress) -> None:
    if importlib.util.find_spec(module):
        return
    progress("Installing build helper: " + pip_name)
    result = run_hidden([sys.executable, "-m", "pip", "install", pip_name],
                        cwd=ROOT, timeout=900.0)
    if result.returncode != 0:
        raise RuntimeError("Could not install " + pip_name + ":\n"
                           + result.stdout[-1000:])


def build(fork: Path, progress, done, failed) -> None:
    def worker() -> None:
        try:
            if not fork.is_dir():
                raise RuntimeError("Choose the folder containing your private JARVIS fork.")
            progress("Checking build tools…")
            ensure_module("PyInstaller", "pyinstaller", progress)
            ensure_module("playwright", "playwright", progress)
            progress("Preparing Chromium for the bundle…")
            result = run_hidden([sys.executable, "-m", "playwright",
                                 "install", "chromium"], cwd=ROOT, timeout=900.0)
            if result.returncode != 0:
                raise RuntimeError("Chromium preparation failed:\n"
                                   + result.stdout[-1000:])
            progress("Building JarvisOneClick.exe…")
            result = run_hidden(
                [sys.executable, "-m", "tools.build_oneclick",
                 "--upstream", str(fork), "--compile",
                 "--out", str(ROOT / ".build" / "oneclick")],
                cwd=ROOT, timeout=1800.0)
            if result.returncode != 0:
                raise RuntimeError("Build failed:\n" + result.stdout[-2000:])
            progress(result.stdout.strip())
            done(ROOT / ".build" / "oneclick" / "dist" / "JarvisOneClick.exe")
        except Exception as exc:
            failed(str(exc))
    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    root = tk.Tk()
    root.title("Build JARVIS One-Click")
    root.geometry("640x420")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Build JARVIS One-Click",
              font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(frame, wraplength=580,
              text=("Choose your private JARVIS folder. The output is one "
                    "JarvisOneClick.exe. Keep it private; it contains "
                    "upstream source.")).pack(anchor="w", pady=(6, 14))

    path_var = tk.StringVar(value=str(default_fork()))
    row = ttk.Frame(frame)
    row.pack(fill="x")
    ttk.Entry(row, textvariable=path_var, width=64).pack(side="left", fill="x", expand=True)

    def choose() -> None:
        chosen = filedialog.askdirectory(title="Private JARVIS folder")
        if chosen:
            path_var.set(chosen)
    ttk.Button(row, text="Browse", command=choose).pack(side="left", padx=(8, 0))

    log = tk.Text(frame, height=10, wrap="word")
    log.configure(state="disabled")
    log.pack(fill="both", expand=True, pady=(16, 10))

    def progress(message: str) -> None:
        def append() -> None:
            log.configure(state="normal")
            log.insert("end", message + "\n")
            log.see("end")
            log.configure(state="disabled")
        root.after(0, append)

    def done(exe: Path) -> None:
        def show() -> None:
            messagebox.showinfo("JARVIS", "Built:\n" + str(exe))
        root.after(0, show)

    def failed(message: str) -> None:
        def show() -> None:
            progress(message)
            messagebox.showerror("JARVIS", message)
        root.after(0, show)

    button = ttk.Button(frame, text="Build",
                        command=lambda: build(Path(path_var.get()), progress,
                                              done, failed))
    button.pack(anchor="e")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
