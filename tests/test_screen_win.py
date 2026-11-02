import io
import types
import unittest
from unittest.mock import patch

from jarvis_win import screen_win, win32
from tests._stubs import screen_module


class FakeImage:
    def __init__(self, width, height, varied=True):
        self.width = width
        self.height = height
        self.size = (width, height)
        self.varied = varied

    def convert(self, mode):
        return self

    def thumbnail(self, size, resample=None):
        edge = size[0]
        scale = min(1.0, edge / max(self.width, self.height))
        self.width = max(1, int(self.width * scale))
        self.height = max(1, int(self.height * scale))
        self.size = (self.width, self.height)

    def resize(self, size, resample=None):
        return FakeImage(size[0], size[1], self.varied)

    def getdata(self):
        if self.varied:
            return [(0, 0, 0) if index % 2 else (255, 255, 255)
                    for index in range(self.width * self.height)]
        return [(10, 10, 10)] * (self.width * self.height)

    def save(self, buffer, format=None, optimize=False):
        buffer.write(b"\x89PNG\r\n\x1a\n" + b"fake frame")


class FakeImageModule:
    Resampling = types.SimpleNamespace(LANCZOS=1)

    @staticmethod
    def open(path):
        return FakeImage(32, 32, True)


class FakeImageGrab:
    varied = True

    @classmethod
    def grab(cls, **kwargs):
        return FakeImage(1920, 1080, cls.varied)


class ScreenWindowsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = screen_module()
        self.factory = patch.object(screen_win, "_PIL_FACTORY",
                                    lambda: (FakeImageModule, FakeImageGrab))
        self.factory.start()
        screen_win.apply(self.module)
        FakeImageGrab.varied = True

    def tearDown(self):
        self.factory.stop()

    async def test_capture_is_resized_png_in_memory(self):
        shot = await self.module.capture_screen()
        self.assertTrue(shot.png.startswith(b"\x89PNG"))
        self.assertLessEqual(max(shot.width, shot.height), 1280)
        self.assertEqual((shot.width, shot.height), (1280, 720))
        self.assertIsNone(self.module.screen_recording_granted())

    async def test_blank_frame_is_refused(self):
        FakeImageGrab.varied = False
        with self.assertRaises(self.module.ScreenError):
            await self.module.capture_screen()

    async def test_list_windows_maps_ctypes_infos_and_foreground_first(self):
        infos = [
            win32.WindowInfo(1, 1, "Background", "notepad.exe", True, False),
            win32.WindowInfo(2, 2, "Active", "WindowsTerminal.exe", True, True),
            win32.WindowInfo(3, 3, "Program Manager", "explorer.exe", True, False),
            win32.WindowInfo(4, 4, "", "chrome.exe", True, False),
        ]
        with patch.object(screen_win.win32, "list_windows", return_value=infos), \
             patch.object(screen_win, "_MONITOR_RECTS",
                          lambda: [(0, 0, 1920, 1080)]):
            windows = await self.module.list_windows()
        self.assertEqual([w.app for w in windows],
                         ["WindowsTerminal", "notepad"])
        self.assertTrue(windows[0].frontmost)

    async def test_invalid_display_is_refused(self):
        with patch.object(screen_win, "_MONITOR_RECTS",
                          lambda: [(0, 0, 1920, 1080)]):
            with self.assertRaises(self.module.ScreenError):
                await self.module.capture_screen(display=2)


if __name__ == "__main__":
    unittest.main()
