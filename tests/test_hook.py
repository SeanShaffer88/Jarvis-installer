import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import hook


class HookTests(unittest.TestCase):
    def tearDown(self):
        hook.reset_for_tests()

    def test_finder_wraps_real_loader_and_patches_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fake_target.py").write_text("value = 1\n", encoding="utf-8")
            patches = {"fake_target": ("jarvis_win.session_steer_win", "apply")}
            finder = hook.JarvisImportHook(root, "win32", patches)
            spec = finder.find_spec("fake_target")
            self.assertIsNotNone(spec)
            self.assertIsInstance(spec.loader, hook.PatchingLoader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.value, 1)
            self.assertTrue(module._JARVIS_WINDOWS_PATCHED)
            self.assertTrue(callable(module.post_to_session))
            self.assertEqual(module.classify_socket_path(None), "missing")

    def test_non_windows_platform_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            finder = hook.JarvisImportHook(tmp, "linux", {})
            self.assertIsNone(finder.find_spec("dialog"))

    def test_install_is_once_and_respects_disable_env(self):
        hook.reset_for_tests()
        meta_path = []
        with patch.dict(os.environ, {"JARVIS_WINDOWS_OVERLAY": "1"}):
            first = hook.install(app_root="/tmp/jarvis", platform="win32",
                                 meta_path=meta_path, modules={})
            second = hook.install(app_root="/tmp/jarvis", platform="win32",
                                  meta_path=meta_path, modules={})
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(len(meta_path), 2)  # caller-owned list is test-isolated
        hook.uninstall(meta_path=meta_path)
        self.assertEqual(meta_path, [])
        with patch.dict(os.environ, {"JARVIS_WINDOWS_OVERLAY": "0"}):
            self.assertIsNone(hook.install(app_root="/tmp/jarvis",
                                           platform="win32", meta_path=[]))

    def test_patch_table_covers_all_nine_modules(self):
        self.assertEqual(set(hook.PATCHES), {
            "dialog", "notifier", "actions", "screen", "preflight",
            "session_watch", "session_steer", "brain", "run_executor"})


if __name__ == "__main__":
    unittest.main()
