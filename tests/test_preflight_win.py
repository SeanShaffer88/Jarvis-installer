import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import preflight_win
from tests._stubs import preflight_module


class PreflightWindowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_claude_and_neutral_grants(self):
        module = preflight_module()

        async def fake_run(*args, timeout=5.0, env=None):
            if args[-1] == "--version":
                return 0, "2.1.259 (Claude Code)", ""
            if "auth" in args:
                return 0, json.dumps({"loggedIn": True,
                                      "authMethod": "claude.ai",
                                      "email": "sean@example.com"}), ""
            return 1, "", "unexpected command"

        module._run_subprocess = fake_run
        with patch.object(preflight_win.claude_launcher, "resolve_claude",
                          return_value="C:\\native\\claude.exe"):
            preflight_win.apply(module)
            cli = await module._check_claude_cli()
            login = await module._check_claude_login()
            accessibility = await module._check_accessibility()

        self.assertEqual(cli.status, module.STATUS_OK)
        self.assertIn("Native", cli.message)
        self.assertEqual(login.status, module.STATUS_OK)
        self.assertIn("Could not independently verify", login.message)
        self.assertEqual(accessibility.status, module.STATUS_OK)
        self.assertIn("not applicable", accessibility.message.lower())
        screen = module._SYNC_CHECKS[0]()
        self.assertEqual(screen.status, module.STATUS_OK)
        self.assertIn("blank-frame", screen.message)

    async def test_native_shim_is_a_failure_not_a_spawn(self):
        module = preflight_module()
        with patch.object(preflight_win.claude_launcher, "resolve_claude",
                          return_value=None):
            preflight_win.apply(module)
            result = await module._check_claude_cli()
        self.assertEqual(result.status, module.STATUS_FAIL)
        self.assertIn("claude.cmd", result.message)
        self.assertIn("winget", result.remedy)

    def test_credential_expiry_never_exposes_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".credentials.json").write_text(json.dumps({
                "claudeAiOauth": {
                    "accessToken": "DO-NOT-LOG",
                    "refreshToken": "DO-NOT-LOG",
                    "refreshTokenExpiresAt": 1_800_000_000_000,
                }
            }), encoding="utf-8")
            self.assertEqual(preflight_win._read_expiry([root / ".credentials.json"]),
                             1_800_000_000.0)
            candidates = preflight_win.credential_candidates(
                root, env={"USERPROFILE": str(root), "APPDATA": str(root)})
            self.assertTrue(candidates)
            self.assertTrue(any(p.is_file() for p in candidates))


if __name__ == "__main__":
    unittest.main()
