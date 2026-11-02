import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import win_paths


class WinPathsTests(unittest.TestCase):
    def test_shims_are_rejected_and_exe_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native = root / "claude.exe"
            shim = root / "claude.cmd"
            native.write_bytes(b"MZ")
            shim.write_text("@echo off\n", encoding="ascii")
            self.assertTrue(win_paths.is_native_executable(native))
            self.assertFalse(win_paths.is_native_executable(shim))

    def test_find_claude_prefers_explicit_native_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native = root / "claude.exe"
            shim = root / "claude.cmd"
            native.write_bytes(b"MZ")
            shim.write_text("@echo off\n", encoding="ascii")
            found = win_paths.find_claude(explicit=native,
                                          which=lambda _name: str(shim))
            self.assertEqual(found, str(native.resolve()))

    def test_find_claude_uses_userprofile_native_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native = root / ".local" / "bin" / "claude.exe"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"MZ")
            found = win_paths.find_claude(env={"USERPROFILE": str(root)},
                                          which=lambda _name: None)
            self.assertEqual(found, str(native.resolve()))

    def test_find_claude_rejects_only_cmd_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shim = root / "claude.cmd"
            shim.write_text("@echo off\n", encoding="ascii")
            self.assertIsNone(win_paths.find_claude(which=lambda _name: str(shim)))

    def test_percent_vars_expand_from_supplied_environment(self):
        self.assertEqual(win_paths.expand(r"%USERPROFILE%\.local\bin",
                                           {"USERPROFILE": "C:\\Users\\Sean"}),
                         r"C:\Users\Sean\.local\bin")

    def test_find_openssl_requires_windows_pe_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows_binary = root / "openssl.exe"
            windows_binary.write_bytes(b"MZ..." )
            linux_binary = root / "openssl"
            linux_binary.write_bytes(b"\x7fELF")
            self.assertEqual(win_paths.find_openssl(explicit=windows_binary),
                             str(windows_binary.resolve()))
            self.assertIsNone(win_paths.find_openssl(explicit=linux_binary))


if __name__ == "__main__":
    unittest.main()
