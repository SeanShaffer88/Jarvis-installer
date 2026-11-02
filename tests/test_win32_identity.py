import unittest

from jarvis_win import win32


class FakeAPI:
    def __init__(self, *, alive=True, windows=(), chain=(), console_hwnd=0):
        self.alive = alive
        self._windows = list(windows)
        self._chain = list(chain)
        self.console_hwnd_value = console_hwnd

    def pid_alive(self, pid):
        return self.alive

    def windows(self):
        return list(self._windows)

    def window_by_hwnd(self, hwnd):
        for item in self._windows:
            if item.hwnd == hwnd:
                return item
        return None

    def process_chain(self, pid, max_hops=6):
        return list(self._chain)

    def console_hwnd(self, pid, timeout=1.0):
        return self.console_hwnd_value

    def monitor_rects(self):
        return [(0, 0, 1920, 1080)]


class Win32IdentityTests(unittest.TestCase):
    def test_direct_window_is_exact_identity(self):
        window = win32.WindowInfo(100, 4242, "Claude Code", "claude.exe", True, False)
        api = FakeAPI(windows=[window])
        result = win32.find_session_window(4242, api)
        self.assertIsNotNone(result)
        self.assertEqual(result.hwnd, 100)
        self.assertEqual(result.confidence, "direct")

    def test_ambiguous_host_windows_are_not_guessed(self):
        first = win32.WindowInfo(200, 900, "Terminal one", "WindowsTerminal.exe", True, False)
        second = win32.WindowInfo(201, 900, "Terminal two", "WindowsTerminal.exe", True, True)
        chain = [win32.ProcessInfo(4242, 900, "claude.exe"),
                 win32.ProcessInfo(900, 1, "WindowsTerminal.exe")]
        api = FakeAPI(windows=[first, second], chain=chain)
        self.assertIsNone(win32.find_session_window(4242, api))
        report = win32.probe_session_window(4242, api)
        self.assertFalse(report["verified"])
        self.assertFalse(report["sends_input"])

    def test_console_hwnd_disambiguates_multiple_candidates(self):
        first = win32.WindowInfo(200, 900, "Terminal one", "WindowsTerminal.exe", True, False)
        second = win32.WindowInfo(201, 900, "Terminal two", "WindowsTerminal.exe", True, True)
        chain = [win32.ProcessInfo(4242, 900, "claude.exe"),
                 win32.ProcessInfo(900, 1, "WindowsTerminal.exe")]
        api = FakeAPI(windows=[first, second], chain=chain, console_hwnd=201)
        result = win32.find_session_window(4242, api)
        self.assertIsNotNone(result)
        self.assertEqual(result.hwnd, 201)
        self.assertIn(result.confidence, {"console", "console-lineage"})

    def test_dead_pid_never_maps_to_window(self):
        window = win32.WindowInfo(100, 4242, "Claude", "claude.exe", True, False)
        self.assertIsNone(win32.find_session_window(
            4242, FakeAPI(alive=False, windows=[window])))

    def test_pid_alive_uses_injected_windows_api(self):
        self.assertTrue(win32.pid_alive(4242, FakeAPI()))
        self.assertFalse(win32.pid_alive(4242, FakeAPI(alive=False)))
        self.assertEqual(win32.monitor_rects(FakeAPI()), [(0, 0, 1920, 1080)])


if __name__ == "__main__":
    unittest.main()
