import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class IssStructureTests(unittest.TestCase):
    def test_static_safety_lint_passes(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "lint_iss.py")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_secret_in_command_lines_or_logs(self):
        text = (ROOT / "installer" / "JarvisSetup.iss").read_text(encoding="utf-8")
        self.assertNotIn("--fish-key", text)
        self.assertNotIn("--fish-api-key", text)
        self.assertNotIn("LogSetup('Fish", text)
        self.assertIn("SaveStringToFile(JobPath, BuildJobJson, False)", text)
        self.assertIn("DeleteFile(JobPath)", text)


if __name__ == "__main__":
    unittest.main()
