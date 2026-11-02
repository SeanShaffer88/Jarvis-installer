import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import dialog_win, win32
from tests._stubs import dialog_module


class DialogWindowsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        dialog_win.reset_state()
        self.module = dialog_module()

    def tearDown(self):
        dialog_win.reset_state()

    @staticmethod
    def window(hwnd=0xABC, pid=4242):
        return win32.SessionWindow(
            hwnd=hwnd, pid=pid, title="Claude Code", process_name="claude.exe",
            confidence="direct", host_pid=pid, console_hwnd=0)

    async def test_identity_token_round_trip_and_display_only_handoff(self):
        calls = []

        def probe(pid):
            calls.append(pid)
            return self.window()

        dialog_win.apply(self.module, probe=probe)
        tty = self.module.tty_for_pid(4242)
        self.assertIsNotNone(tty)
        self.assertEqual(self.module.normalize_tty(tty), tty)
        self.assertEqual(dialog_win.hwnd_from_token(tty), 0xABC)

        with self.assertRaises(RuntimeError):
            self.module._send_script(None, "return")
        outcome = await self.module.answer(4242, "yes")
        self.assertEqual(outcome, self.module.NOT_FOUND)
        self.assertGreaterEqual(len(calls), 2)  # identity re-proved at use time
        self.assertFalse(self.module.WINDOWS_SEND_KEYS_ENABLED)

    async def test_free_text_is_rejected_before_identity_lookup(self):
        calls = []
        dialog_win.apply(self.module, probe=lambda pid: calls.append(pid) or self.window())
        self.assertEqual(await self.module.answer(4242, "rm -rf /"),
                         self.module.BAD_KEY)
        self.assertEqual(calls, [])

    async def test_no_tty_returns_no_tty(self):
        dialog_win.apply(self.module, probe=lambda pid: None)
        self.assertEqual(await self.module.answer(4242, "return"),
                         self.module.NO_TTY)

    async def test_stale_identity_is_discarded(self):
        answers = [self.window(), None]
        dialog_win.apply(self.module, probe=lambda pid: answers.pop(0) if answers else None)
        self.assertEqual(await self.module.answer(4242, "1"),
                         self.module.NOT_FOUND)
        self.assertEqual(dialog_win._TOKENS, {})

    def test_no_sendinput_call_exists(self):
        source = Path(dialog_win.__file__).read_text(encoding="utf-8")
        self.assertNotIn("SendInput(", source)
        self.assertNotIn("PostMessageW(", source)


if __name__ == "__main__":
    unittest.main()
