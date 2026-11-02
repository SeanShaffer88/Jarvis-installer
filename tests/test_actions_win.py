import unittest
from unittest.mock import patch

from jarvis_win import actions_win
from tests._stubs import FakeAsyncProcess


class ActionWindowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_url_is_one_argv_entry(self):
        calls = []

        async def fake_spawn(*argv, **kwargs):
            calls.append(list(argv))
            return FakeAsyncProcess(returncode=0)

        with patch.object(actions_win, "_SPAWN", fake_spawn), \
             patch.object(actions_win.win_paths, "find_chrome",
                          return_value="C:\\Chrome\\chrome.exe"):
            result = await actions_win.open_browser(
                'https://localhost:8340/?q=";evil&x=1')

        self.assertTrue(result["success"])
        self.assertEqual(calls, [["C:\\Chrome\\chrome.exe",
                                 'https://localhost:8340/?q=";evil&x=1']])
        self.assertEqual(await actions_win.get_chrome_tab_info(), {})

    async def test_windows_terminal_uses_argument_list(self):
        calls = []
        command = "cd 'C:\\temp'; Get-ChildItem"

        async def fake_spawn(*argv, **kwargs):
            calls.append(list(argv))
            return FakeAsyncProcess(returncode=0)

        with patch.object(actions_win, "_SPAWN", fake_spawn), \
             patch.object(actions_win.win_paths, "find_windows_terminal",
                          return_value="C:\\wt\\wt.exe"), \
             patch.object(actions_win.win_paths, "find_powershell",
                          return_value="C:\\Windows\\powershell.exe"):
            result = await actions_win.open_terminal(command)

        self.assertTrue(result["success"])
        argv = calls[0]
        self.assertEqual(argv[:5], ["C:\\wt\\wt.exe", "new-tab", "--title",
                                    "JARVIS", "--"])
        self.assertNotIn("cmd.exe", argv)
        self.assertEqual(argv[-1], command)
        self.assertEqual(argv[-2], "-Command")

    async def test_editor_rejects_cmd_shim_and_uses_real_exe(self):
        calls = []

        async def fake_spawn(*argv, **kwargs):
            calls.append(list(argv))
            return FakeAsyncProcess(returncode=0)

        with patch.object(actions_win, "_SPAWN", fake_spawn), \
             patch.object(actions_win.win_paths, "find_code",
                          return_value="C:\\Code\\Code.exe"):
            result = await actions_win.open_in_editor("C:\\project\\app.py")
        self.assertTrue(result["success"])
        self.assertEqual(calls, [["C:\\Code\\Code.exe", "C:\\project\\app.py"]])
        self.assertEqual(result["editor"], "VS Code")


if __name__ == "__main__":
    unittest.main()
