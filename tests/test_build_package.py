import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_package


class BuildPackageTests(unittest.TestCase):
    @staticmethod
    def fake_upstream(root: Path) -> Path:
        source = root / "upstream"
        (source / "frontend").mkdir(parents=True)
        (source / "data").mkdir()
        (source / "node_modules").mkdir()
        (source / "server.py").write_text("# upstream\n", encoding="utf-8")
        (source / "requirements.txt").write_text("fastapi>=0.115.0\n", encoding="utf-8")
        (source / "LICENSE").write_text("personal non-commercial\n", encoding="utf-8")
        (source / "frontend" / "package.json").write_text("{}", encoding="utf-8")
        (source / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")
        (source / ".env").write_text("FISH_API_KEY=SECRET\n", encoding="utf-8")
        (source / "data" / "jarvis.db").write_text("private", encoding="utf-8")
        (source / "node_modules" / "x").write_text("private", encoding="utf-8")
        return source

    def test_stage_private_payload_without_secrets_or_upstream_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fake_upstream(root)
            out = root / "staging"
            build_package.main([
                "--upstream", str(source), "--out", str(out), "--skip-frontend"])
            payload = out / "payload"
            self.assertTrue((out / "JarvisSetup.iss").is_file())
            self.assertTrue((out / "scripts" / "prereqs.json").is_file())
            self.assertTrue((payload / "sitecustomize.py").is_file())
            self.assertTrue((payload / "jarvis_win" / "hook.py").is_file())
            self.assertTrue((payload / "jarvis_win" / "ShowToast.ps1").is_file())
            self.assertTrue((payload / "UPSTREAM_LICENSE.txt").is_file())
            self.assertTrue((payload / "INSTALLER_LICENSE.txt").is_file())
            self.assertTrue((payload / "THIRD_PARTY_NOTICES.txt").is_file())
            self.assertTrue((payload / "frontend" / "dist" / "PLACEHOLDER.txt").is_file())
            requirements = (payload / "requirements-windows.txt").read_text()
            self.assertIn("fastapi>=0.115.0", requirements)
            self.assertIn("Pillow>=10.0.0", requirements)
            self.assertFalse((payload / ".env").exists())
            self.assertFalse((payload / "data" / "jarvis.db").exists())
            self.assertFalse((payload / "node_modules").exists())
            self.assertTrue((payload / "data" / ".gitkeep").exists())
            manifest = json.loads((payload / "INSTALL_MANIFEST.json").read_text())
            self.assertFalse(manifest["frontend_prebuilt"])
            self.assertTrue(manifest["native_claude_only"])
            self.assertFalse(manifest["node_needed"])
            build_manifest = json.loads((out / "build-manifest.json").read_text())
            self.assertGreater(build_manifest["file_count"], 10)
            self.assertFalse(any(entry["path"] == ".env"
                                 for entry in build_manifest["files"]))


    def test_npm_build_does_not_ship_node_modules_on_target_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fake_upstream(root)
            out = root / "staging"

            def fake_npm(args, cwd):
                if args[0] == "ci":
                    package = cwd / "node_modules" / "build-only"
                    package.mkdir(parents=True)
                    (package / "index.js").write_text("module.exports = {};", encoding="utf-8")
                else:
                    dist = cwd / "dist"
                    dist.mkdir(parents=True, exist_ok=True)
                    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
                    (dist / "dashboard.html").write_text("<html></html>", encoding="utf-8")

            with patch.object(build_package, "run_npm", fake_npm):
                build_package.main(["--upstream", str(source), "--out", str(out)])
            payload = out / "payload"
            self.assertFalse((payload / "frontend" / "node_modules").exists())
            self.assertTrue((payload / "frontend" / "dist" / "index.html").is_file())
            manifest = json.loads((payload / "INSTALL_MANIFEST.json").read_text())
            self.assertTrue(manifest["frontend_prebuilt"])
            build_manifest = json.loads((out / "build-manifest.json").read_text())
            self.assertFalse(any("node_modules/" in entry["path"]
                                 for entry in build_manifest["files"]))


if __name__ == "__main__":
    unittest.main()
