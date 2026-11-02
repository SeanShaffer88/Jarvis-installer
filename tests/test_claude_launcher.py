import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import claude_launcher


class ClaudeLauncherTests(unittest.TestCase):
    def test_command_first_arg_is_native_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "claude.exe"
            native.write_bytes(b"MZ")
            with patch.object(claude_launcher, "resolve_claude",
                              return_value=str(native)):
                command = claude_launcher.ensure_native_claude(
                    ["claude", "-p", "--model", "sonnet"])
            self.assertEqual(command[0], str(native))
            self.assertEqual(command[1:], ["-p", "--model", "sonnet"])

    def test_missing_native_binary_raises_clear_error(self):
        with patch.object(claude_launcher, "resolve_claude", return_value=None):
            with self.assertRaises(claude_launcher.ClaudeLaunchError):
                claude_launcher.ensure_native_claude(["claude.cmd", "-p"])

    def test_environment_pins_native_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "claude.exe"
            native.write_bytes(b"MZ")
            with patch.object(claude_launcher, "resolve_claude",
                              return_value=str(native)):
                env = claude_launcher.environment(env={"PATH": "x"})
            self.assertEqual(env["JARVIS_CLAUDE_PATH"], str(native))


if __name__ == "__main__":
    unittest.main()
