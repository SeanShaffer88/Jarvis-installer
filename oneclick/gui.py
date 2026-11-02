"""The only window the end user sees: a masked Fish key and progress."""

from __future__ import annotations

import sys
import threading
from typing import Callable

from . import core, win
from .core import Paths


class Controller:
    """GUI-independent controller that can be unit-tested without tkinter."""

    def __init__(self, *, paths: Paths | None = None,
                 env: dict[str, str] | None = None,
                 run=win.run_hidden, spawn=win.spawn_hidden,
                 exe: str | None = None, ref: str = ""):
        self.paths = paths or Paths.from_env(env)
        self.env = env
        self.run = run
        self.spawn = spawn
        self.exe = exe or sys.executable
        self.ref = ref

    def has_key(self) -> bool:
        return bool(core.read_env(self.paths.env_file)
                    .get("FISH_API_KEY", "").strip())

    def quick_launch(self, *, progress: Callable[[str], None] = lambda _: None) -> bool:
        """Subsequent runs: no prompt, just start/open if everything is ready."""
        if not self.has_key():
            return False
        chrome = win.find_chrome(self.env)
        claude = win.find_claude(self.env)
        if not chrome or not claude:
            return False
        if not win.login_status(claude, run=self.run, env=self.env):
            return False
        win.start_server(self.exe, self.paths, claude,
                         spawn=self.spawn, progress=progress)
        win.open_chrome(chrome, core.VOICE_URL, spawn=self.spawn)
        return True

    def setup(self, api_key: str, *, progress: Callable[[str], None],
              login_prompt: Callable[[object], None]) -> win.SetupResult:
        return win.setup_all(api_key, self.paths, progress=progress,
                             run=self.run, spawn=self.spawn,
                             login_prompt=login_prompt, env=self.env,
                             ref=self.ref, exe=self.exe, start=True)


def run() -> int:
    """Build the one-window GUI. tkinter is imported only here."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    controller = Controller()
    root = tk.Tk()
    root.title("JARVIS")
    root.geometry("520x340")
    root.resizable(False, False)

    outer = ttk.Frame(root, padding=24)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="JARVIS", font=("Segoe UI", 22, "bold")).pack(anchor="w")
    status = tk.StringVar(value="")
    ttk.Label(outer, textvariable=status, wraplength=460).pack(anchor="w", pady=(4, 14))

    progress_box = tk.Text(outer, height=8, width=58, wrap="word")
    progress_box.configure(state="disabled")
    progress_box.pack(fill="both", expand=True)

    key_frame = ttk.Frame(outer)
    login_frame = ttk.Frame(outer)
    action_frame = ttk.Frame(outer)

    def progress(message: str) -> None:
        def append() -> None:
            progress_box.configure(state="normal")
            progress_box.insert("end", message + "\n")
            progress_box.see("end")
            progress_box.configure(state="disabled")
        root.after(0, append)

    def show_login(process: object) -> None:
        """One browser sign-in button; no command window is ever shown."""
        del process
        done = threading.Event()

        def show_ui() -> None:
            for child in login_frame.winfo_children():
                child.destroy()
            status.set("Your browser is open. Sign in to Claude, then continue.")
            login_frame.pack(fill="x", pady=(10, 0))
            ttk.Label(login_frame, text="Claude sign-in",
                      font=("Segoe UI", 10, "bold")).pack(anchor="w")

            def signed_in() -> None:
                login_frame.pack_forget()
                status.set("Checking sign-in…")
                done.set()

            ttk.Button(login_frame, text="I've signed in",
                       command=signed_in).pack(anchor="w", pady=(6, 0))

        root.after(0, show_ui)
        done.wait()

    def clear_frames() -> None:
        for frame in (key_frame, login_frame, action_frame):
            frame.pack_forget()

    def done_ok() -> None:
        clear_frames()
        status.set("JARVIS is ready.")
        ttk.Label(action_frame, text="Chrome is opening JARVIS.").pack(anchor="w")
        action_frame.pack(fill="x", pady=(10, 0))
        root.after(1800, root.destroy)

    def done_error(message: str) -> None:
        status.set("Setup could not finish.")
        progress(message)
        messagebox.showerror("JARVIS", message)

    def start_setup(api_key: str) -> None:
        clear_frames()
        status.set("Setting up JARVIS…")
        progress_box.configure(state="normal")
        progress_box.delete("1.0", "end")
        progress_box.configure(state="disabled")

        def worker() -> None:
            try:
                controller.setup(api_key, progress=progress,
                                 login_prompt=show_login)
                root.after(0, done_ok)
            except Exception as exc:
                root.after(0, done_error, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def show_key_prompt() -> None:
        clear_frames()
        status.set("Enter your Fish Audio API key. Everything else is automatic.")
        key_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(key_frame, text="Fish Audio API key").pack(anchor="w")
        entry = ttk.Entry(key_frame, show="•", width=56)
        entry.pack(fill="x", pady=(4, 10))
        ttk.Button(key_frame, text="Set up JARVIS",
                   command=lambda: start_setup(entry.get())).pack(anchor="e")
        entry.focus_set()

    def quick_start() -> None:
        status.set("Starting JARVIS…")
        def worker() -> None:
            try:
                if controller.quick_launch(progress=progress):
                    root.after(0, root.destroy)
                else:
                    root.after(0, show_key_prompt)
            except Exception as exc:
                root.after(0, done_error, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    if controller.has_key():
        quick_start()
    else:
        show_key_prompt()
    root.mainloop()
    return 0


__all__ = ["Controller", "run"]
