import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import notifier_win
from tests._stubs import FakeAsyncProcess, notifier_module


class NotifierWindowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_untrusted_text_is_a_separate_arg_to_fixed_script(self):
        payload = 'evil"; do shell script "rm -rf /'
        calls = []

        async def fake_spawn(*argv, **kwargs):
            calls.append((list(argv), kwargs))
            return FakeAsyncProcess(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ShowToast.ps1"
            script.write_text("# fixed\n", encoding="utf-8")
            with patch.object(notifier_win.sys, "platform", "win32"), \
                 patch.object(notifier_win.win_paths, "find_powershell",
                              return_value="C:\\Windows\\System32\\powershell.exe"), \
                 patch.object(notifier_win, "TOAST_SCRIPT", script), \
                 patch.object(notifier_win, "_SPAWN", fake_spawn):
                module = notifier_module()
                notifier_win.apply(module)
                self.assertTrue(module.available())
                self.assertTrue(await module.notify(payload, payload, subtitle=payload))

        self.assertEqual(len(calls), 1)
        argv, _kwargs = calls[0]
        self.assertIn("-File", argv)
        self.assertNotIn("-Command", argv)
        self.assertNotIn("osascript", " ".join(argv))
        self.assertEqual(argv[argv.index("-File") + 1], str(script))
        self.assertEqual(argv[argv.index("-Title") + 1], payload)
        self.assertEqual(argv[argv.index("-Message") + 1], payload)
        self.assertEqual(argv[argv.index("-Subtitle") + 1], payload)

    async def test_unavailable_and_spawn_failure_never_raise(self):
        with patch.object(notifier_win.sys, "platform", "linux"):
            self.assertFalse(await notifier_win.notify("title", "message"))

        async def failing_spawn(*_argv, **_kwargs):
            raise OSError("no PowerShell")

        with patch.object(notifier_win.sys, "platform", "win32"), \
             patch.object(notifier_win.win_paths, "find_powershell",
                          return_value="powershell.exe"), \
             patch.object(notifier_win, "_SPAWN", failing_spawn):
            self.assertFalse(await notifier_win.notify("title", "message"))

    def test_truncation_matches_upstream_limits(self):
        self.assertEqual(len(notifier_win._truncate("x" * 500, 300)), 300)
        self.assertTrue(notifier_win._truncate("x" * 500, 300).endswith("…"))


if __name__ == "__main__":
    unittest.main()
