import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from jarvis_win import notifier_win
from oneclick import patches, win

ROOT = Path(__file__).resolve().parent.parent


class PatchTests(unittest.TestCase):
    def test_apply_actions_disables_terminal_and_editor(self):
        module = SimpleNamespace()
        spawned: list[list[str]] = []
        patches.apply_actions(
            module, find_chrome=lambda: "C:/chrome.exe",
            spawn=lambda argv, **kwargs: spawned.append(argv))
        terminal = asyncio.run(module.open_terminal("echo hi"))
        editor = asyncio.run(module.open_in_editor("file.txt"))
        browser = asyncio.run(module.open_browser("https://localhost:8340/"))
        self.assertFalse(terminal["success"])
        self.assertFalse(editor["success"])
        self.assertTrue(browser["success"])
        self.assertEqual(spawned, [["C:/chrome.exe", "https://localhost:8340/"]])
        self.assertTrue(module._ONECLICK_NO_TERMINAL)

    def test_apply_preflight_rewrites_terminal_words(self):
        @dataclass(frozen=True)
        class Check:
            message: str
            remedy: str

        async def original():
            return Check("Open a terminal",
                         "Run `claude` in a terminal and log in.")
        module = SimpleNamespace(_ASYNC_CHECKS=(original,))
        patches.apply_preflight(module)
        result = asyncio.run(module._ASYNC_CHECKS[0]())
        self.assertNotIn("terminal", result.message.lower())
        self.assertNotIn("terminal", result.remedy.lower())
        self.assertTrue(module._ONECLICK_PLAIN_WORDS)

    def test_apply_server_rewrites_mcp_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            def original(home: Path) -> Path:
                path = home / "mcp.json"
                path.write_text(json.dumps({"mcpServers": {"jarvis": {
                    "command": "python", "args": ["jarvis_mcp.py"]}}}),
                    encoding="utf-8")
                return path

            module = SimpleNamespace(_write_mcp_config=original,
                                     RESERVED_SERVER_NAME="jarvis",
                                     api_restart=lambda: None)
            patches.apply_server(module, exe="C:/JarvisOneClick.exe",
                                 spawn=lambda *a, **k: None)
            path = module._write_mcp_config(home)
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = data["mcpServers"]["jarvis"]
            self.assertEqual(entry["command"], "C:/JarvisOneClick.exe")
            self.assertEqual(entry["args"], ["--mcp"])
            self.assertNotIn("python", entry.values())
            self.assertTrue(module._ONECLICK_FROZEN_SERVER)

    def test_apply_notifier_uses_hidden_argv_only_spawn(self):
        original_available = notifier_win.available
        original_command = notifier_win.command
        captured: dict[str, object] = {}

        class FakeProc:
            returncode = 0
            async def communicate(self):
                return (b"", b"")
            def kill(self):
                return None

        async def fake_spawn(*argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakeProc()

        try:
            notifier_win.available = lambda: True
            notifier_win.command = lambda *a: [
                "powershell.exe", "-File", "fixed.ps1", "-Title", "t"]
            module = SimpleNamespace()
            patches.apply_notifier(module, spawn=fake_spawn)
            self.assertTrue(asyncio.run(module.notify("title", "message")))
        finally:
            notifier_win.available = original_available
            notifier_win.command = original_command

        argv = captured["argv"]
        kwargs = captured["kwargs"]
        self.assertNotIn("-Command", argv)
        self.assertNotIn("shell", kwargs)
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], win.hidden_creationflags())
            self.assertEqual(kwargs["startupinfo"], win.hidden_startupinfo())
        else:
            self.assertNotIn("creationflags", kwargs)
            self.assertNotIn("startupinfo", kwargs)

    def test_apply_all_patches_fake_modules(self):
        server = SimpleNamespace(
            _write_mcp_config=lambda home: home / "mcp.json",
            RESERVED_SERVER_NAME="jarvis", api_restart=lambda: None)
        modules = {
            "actions": SimpleNamespace(),
            "notifier": SimpleNamespace(),
            "preflight": SimpleNamespace(_ASYNC_CHECKS=()),
            "server": server,
        }
        patches.apply_all(modules=modules, exe="C:/JarvisOneClick.exe",
                          spawn=lambda *a, **k: None)
        self.assertTrue(modules["actions"]._ONECLICK_NO_TERMINAL)
        self.assertTrue(modules["notifier"]._ONECLICK_HIDDEN_TOAST)
        self.assertTrue(modules["preflight"]._ONECLICK_PLAIN_WORDS)
        self.assertTrue(server._ONECLICK_FROZEN_SERVER)

    def test_oneclick_source_has_no_user_visible_shell_hosts(self):
        paths = list((ROOT / "oneclick").glob("*.py"))
        paths += [ROOT / "tools" / "build_oneclick.py",
                  ROOT / "tools" / "build_oneclick_gui.pyw"]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for forbidden in ("wt.exe", "Code.exe", "bash.exe", "cmd.exe",
                          "0.0.0.0", "ANTHROPIC_API_KEY", "claude.cmd", "iscc"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
