import json
import tempfile
import unittest
from pathlib import Path

from oneclick import core
from tools import build_oneclick as builder


def _mz(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * 32)


def _required_payload(payload: Path) -> None:
    files = (
        "server.py", "jarvis_mcp.py", "jarvis_win/hook.py",
        "jarvis_win/ShowToast.ps1", "frontend/dist/index.html",
        "frontend/dist/dashboard.html", "requirements-windows.txt",
        "UPSTREAM_LICENSE.txt", "INSTALLER_LICENSE.txt",
    )
    for name in files:
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub", encoding="utf-8")


class BuildTests(unittest.TestCase):
    def test_render_spec_is_onefile_windowed_and_no_admin(self):
        spec = builder.render_spec(
            entry=Path("oneclick/main.py"), app_dir=Path("app"),
            browsers=Path("browsers"), hidden_imports=["server", "jarvis_mcp"])
        self.assertIn("console=False", spec)
        self.assertIn("uac_admin=False", spec)
        self.assertIn("name='JarvisOneClick'", spec)
        self.assertIn("'app'", spec)
        self.assertIn("'ms-playwright'", spec)
        self.assertIn("collect_all", spec)
        self.assertNotIn("COLLECT(", spec)

    def test_stage_app_removes_installer_and_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "payload"
            out = root / "out"
            _required_payload(payload)
            (payload / "installer" / "scripts").mkdir(parents=True)
            (payload / "installer" / "JarvisSetup.iss").write_text("iss", encoding="utf-8")
            (payload / "installer" / "scripts" / "helper.ps1").write_text("ps", encoding="utf-8")
            (payload / "frontend" / "node_modules" / "x").mkdir(parents=True)
            (payload / "frontend" / "node_modules" / "x" / "a.js").write_text("x", encoding="utf-8")
            (payload / "data").mkdir()
            (payload / "data" / "jarvis.db").write_text("db", encoding="utf-8")
            (payload / ".env").write_text("FISH_API_KEY=x", encoding="utf-8")
            (payload / "cert.pem").write_text("cert", encoding="utf-8")
            (payload / "random.exe").write_text("exe", encoding="utf-8")
            (payload / "setup.log").write_text("log", encoding="utf-8")

            app_dir = builder.stage_app(out, payload)
            _mz(app_dir / "tools" / "openssl.exe")
            builder.assert_payload_complete(app_dir)
            self.assertFalse((app_dir / "installer").exists())
            self.assertFalse((app_dir / "frontend" / "node_modules").exists())
            self.assertFalse((app_dir / ".env").exists())
            self.assertFalse((app_dir / "cert.pem").exists())
            self.assertFalse((app_dir / "random.exe").exists())
            self.assertFalse((app_dir / "setup.log").exists())
            self.assertFalse((app_dir / "data" / "jarvis.db").exists())
            self.assertTrue((app_dir / "data" / ".gitkeep").exists())

    def test_scan_payload_flags_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "installer" / "scripts").mkdir(parents=True)
            (root / "tools").mkdir()
            (root / "jarvis_win").mkdir()
            _mz(root / "tools" / "openssl.exe")
            (root / "jarvis_win" / "ShowToast.ps1").write_text("fixed", encoding="utf-8")
            (root / ".env").write_text("secret", encoding="utf-8")
            (root / "cert.pem").write_text("cert", encoding="utf-8")
            (root / "installer" / "scripts" / "bad.ps1").write_text("ps", encoding="utf-8")
            (root / "random.exe").write_text("exe", encoding="utf-8")
            problems = core.scan_payload(root)
            self.assertIn(".env", problems)
            self.assertIn("cert.pem", problems)
            self.assertIn("installer/scripts/bad.ps1", problems)
            self.assertIn("random.exe", problems)
            self.assertNotIn("tools/openssl.exe", problems)
            self.assertNotIn("jarvis_win/ShowToast.ps1", problems)

    def test_payload_hidden_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "jarvis_win").mkdir()
            for name in ("server.py", "brain.py", "jarvis_win/hook.py",
                         "jarvis_win/win32.py"):
                (root / name).write_text("", encoding="utf-8")
            names = builder.payload_hidden_imports(root)
            self.assertIn("server", names)
            self.assertIn("brain", names)
            self.assertIn("jarvis_win.hook", names)
            self.assertIn("jarvis_win.win32", names)

    def test_write_manifest_hashes_bundle_and_records_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / "app"
            browsers = root / "browsers"
            out = root / "out"
            app_dir.mkdir()
            browsers.mkdir()
            out.mkdir()
            (app_dir / "server.py").write_text("stub", encoding="utf-8")
            _mz(app_dir / "tools" / "openssl.exe")
            _mz(browsers / "chromium-1" / "chrome.exe")
            manifest = builder.write_manifest(
                out, app_dir, browsers, upstream_ref="abc",
                openssl=root / "openssl.exe", playwright=browsers,
                frontend_prebuilt=True)
            self.assertFalse(manifest["secrets_embedded"])
            self.assertFalse(manifest["node_runtime"])
            self.assertFalse(manifest["inno_setup"])
            self.assertGreater(manifest["file_count"], 0)
            self.assertTrue(all(len(item["sha256"]) == 64
                                for item in manifest["files"]))
            written = json.loads((out / "ONCLICK_MANIFEST.json")
                                 .read_text(encoding="utf-8"))
            self.assertEqual(written["upstream_ref"], "abc")
            self.assertTrue((app_dir / "ONCLICK_MANIFEST.json").exists())

    def test_compile_refuses_placeholder_frontend(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                builder.main(["--compile", "--skip-frontend",
                              "--out", str(Path(tmp) / "out")])


if __name__ == "__main__":
    unittest.main()
