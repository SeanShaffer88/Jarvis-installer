import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PowerShellScriptTests(unittest.TestCase):
    def test_toast_script_uses_fixed_source_and_argv_innertext(self):
        text = (ROOT / "jarvis_win" / "ShowToast.ps1").read_text(encoding="utf-8")
        self.assertIn("param(", text)
        self.assertIn("-Title", text)
        self.assertIn("$textNodes.Item(0).InnerText = $Title", text)
        self.assertIn("$textNodes.Item(1).InnerText = $Message", text)
        self.assertNotIn("-Command", text)
        self.assertNotIn("<toast", text)
        self.assertNotIn("$($Title)", text)

    def test_prereq_helper_is_user_scope_native_only(self):
        text = (ROOT / "installer" / "scripts" /
                "InstallPrereqs.ps1").read_text(encoding="utf-8")
        self.assertIn("winget.exe install", text)
        self.assertIn("--scope user", text)
        self.assertIn("Anthropic.ClaudeCode", text)
        self.assertNotIn("npm install -g", text)
        self.assertNotIn("irm https://claude.ai/install.ps1 | iex", text)
        self.assertNotIn("$claude.cmd", text)
        self.assertIn("[System.IO.Path]::GetExtension($source) -ieq '.exe'", text)

    def test_secret_helper_never_takes_a_key(self):
        text = (ROOT / "installer" / "scripts" /
                "SetSecretAcl.ps1").read_text(encoding="utf-8")
        self.assertIn("icacls.exe", text)
        self.assertIn("/inheritance:r", text)
        self.assertNotIn("fish_api_key", text.lower())
        self.assertNotIn("FISH_API_KEY", text)

    def test_login_and_startup_helpers_are_fixed_and_per_user(self):
        login = (ROOT / "installer" / "scripts" /
                 "OpenClaudeLogin.ps1").read_text(encoding="utf-8")
        startup = (ROOT / "installer" / "scripts" /
                   "Set-Startup.ps1").read_text(encoding="utf-8")
        self.assertIn("Start-Process", login)
        # Get-Command is a cmdlet name, not a PowerShell -Command argument.
        self.assertIsNone(re.search(r"(?<!\w)-Command\b", login))
        self.assertIn("[Environment]::GetFolderPath('Startup')", startup)
        self.assertNotIn("schtasks", startup.lower())

    def test_system_check_writes_status_without_secrets(self):
        text = (ROOT / "installer" / "scripts" /
                "Check-System.ps1").read_text(encoding="utf-8")
        self.assertIn("Status=", text)
        self.assertIn("BuildNumber", text)
        self.assertIn("chrome.exe", text)
        self.assertNotIn("FISH_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
