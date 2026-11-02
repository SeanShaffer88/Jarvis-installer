import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DocumentationTests(unittest.TestCase):
    def test_all_promised_docs_exist(self):
        required = (
            "ORIGINAL_PLAN.md", "DECISIONS.md", "STATUS.md", "ARCHITECTURE.md",
            "WINDOWS_PORT.md", "INSTALLER.md", "SPIKES.md", "SECURITY.md",
            "BUILDING.md", "TESTING.md", "ONECLICK.md",
        )
        for name in required:
            self.assertTrue((ROOT / "docs" / name).is_file(), name)

    def test_status_keeps_windows_verdict_unverified(self):
        status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("Unverified", status)
        self.assertIn("No Phase 0 spike", status)
        self.assertIn("field test", status.lower())

    def test_readme_states_source_only_repo_and_staged_build(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("no copy of the", readme.lower())
        self.assertIn("personal/non-commercial", readme.lower())
        self.assertIn(r".build\installer", readme)

    def test_notice_preserves_upstream_license_note(self):
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("personal", notice.lower())
        self.assertIn("non-commercial", notice.lower())

    def test_readme_documents_oneclick_exe(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("JarvisOneClick.exe", readme)
        self.assertIn("docs/ONECLICK.md", readme)
        self.assertIn("Unverified", readme)

    def test_oneclick_doc_keeps_windows_verdict_unverified(self):
        doc = (ROOT / "docs" / "ONECLICK.md").read_text(encoding="utf-8")
        self.assertIn("Unverified", doc)
        self.assertIn("private/local", doc.lower())
        self.assertIn("field test", doc.lower())


if __name__ == "__main__":
    unittest.main()
