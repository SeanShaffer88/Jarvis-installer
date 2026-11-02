import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import launcher


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class LauncherTests(unittest.TestCase):
    def test_health_check_uses_one_loopback_origin(self):
        runtime = {"origin": "http://localhost:8340"}
        with patch.object(launcher.urllib.request, "urlopen",
                          return_value=FakeResponse()) as opened:
            self.assertTrue(launcher.health_ok(runtime))
        self.assertEqual(opened.call_args.args[0], "http://localhost:8340/api/health")

    def test_child_environment_turns_on_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = launcher.child_env(Path(tmp), {"claude": "C:\\native\\claude.exe"})
        self.assertEqual(env["JARVIS_WINDOWS_OVERLAY"], "1")
        self.assertEqual(env["JARVIS_BIND_HOST"], "127.0.0.1")
        self.assertEqual(env["JARVIS_CLAUDE_PATH"], "C:\\native\\claude.exe")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_open_dashboard_uses_chrome_argv(self):
        calls = []
        with patch.object(launcher.win_paths, "find_chrome",
                          return_value="C:\\Chrome\\chrome.exe"), \
             patch.object(launcher.subprocess, "Popen",
                          side_effect=lambda argv, **kwargs: calls.append(argv)):
            self.assertEqual(launcher.open_page({}, "dashboard"), 0)
        self.assertEqual(calls, [["C:\\Chrome\\chrome.exe",
                                 "https://localhost:8340/dashboard"]])
        self.assertEqual(launcher.open_page({}, "none"), 0)

    def test_stop_refuses_unverified_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = launcher.pid_file(root)
            pid_path.parent.mkdir(parents=True)
            pid_path.write_text("4242\n", encoding="ascii")
            with patch.object(launcher.win32, "pid_alive", return_value=True), \
                 patch.object(launcher, "command_line",
                              return_value="C:\\Windows\\notepad.exe"):
                self.assertEqual(launcher.stop(root, {}), 2)
            self.assertTrue(pid_path.exists())


if __name__ == "__main__":
    unittest.main()
