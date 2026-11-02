import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import brain_win
from tests._stubs import brain_module


class BrainWindowsTests(unittest.TestCase):
    def test_windows_path_with_spaces_survives_shlex(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "Program Files" / "claude.exe"
            native.parent.mkdir(parents=True, exist_ok=True)
            native.write_bytes(b"MZ")
            module = brain_module()
            with patch.object(brain_win.claude_launcher, "resolve_claude",
                              return_value=str(native)):
                brain_win.apply_brain(module)
                brain_win.apply_run_executor(module)
                brain = module.Brain(module.BrainConfig(claude_path="claude.cmd"))
                executor = module.RunExecutor(claude_path="claude.cmd")
                brain_argv = brain.command()
                executor_argv = executor._command("session-1")
            self.assertEqual(brain_argv[0], str(native))
            self.assertEqual(brain_argv[1:], ["-p", "--model", "sonnet"])
            self.assertEqual(executor_argv[0], str(native))
            self.assertEqual(executor_argv[1:], ["-p", "--session-id", "session-1"])

    def test_missing_native_binary_raises_instead_of_spawning_shim(self):
        module = brain_module()
        with patch.object(brain_win.claude_launcher, "resolve_claude",
                          return_value=None):
            brain_win.apply_brain(module)
            brain = module.Brain(module.BrainConfig())
            with self.assertRaises(module.ClaudeLaunchError):
                brain.command()


if __name__ == "__main__":
    unittest.main()
