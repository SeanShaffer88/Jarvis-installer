import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oneclick import core, gui, win


class CoreTests(unittest.TestCase):
    def test_app_root_uses_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"LOCALAPPDATA": tmp}
            self.assertEqual(core.app_root(env), Path(tmp) / "Programs" / "Jarvis")

    def test_paths_from_env_keeps_bundle_and_data_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {"LOCALAPPDATA": str(root / "local"),
                   "APPDATA": str(root / "roaming"),
                   "USERPROFILE": str(root / "home")}
            paths = core.Paths.from_env(env, bundle=root / "bundle")
            self.assertEqual(paths.app_root, root / "local" / "Programs" / "Jarvis")
            self.assertEqual(paths.bundle, root / "bundle")
            self.assertEqual(paths.env_file, paths.app_root / ".env")
            self.assertEqual(paths.playwright, root / "ms-playwright")
            self.assertEqual(paths.frontend, root / "bundle" / "frontend" / "dist")

    def test_parse_env_and_redactor(self):
        self.assertEqual(core.parse_env("# c\nA=1\nB='two'\n"),
                         [("A", "1"), ("B", "two")])
        redactor = core.Redactor(["s3cr3t"])
        text = redactor.redact("FISH_API_KEY=s3cr3t\n{\"fish_api_key\": \"s3cr3t\"}\n")
        self.assertNotIn("s3cr3t", text)
        self.assertIn("[REDACTED]", text)

    def test_update_env_preserves_comments_and_calls_acl(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("# keep\nUSER_NAME=Tony\n", encoding="utf-8")
            seen = []
            core.update_env(env_path, {"FISH_API_KEY": "abc"},
                            acl=seen.append)
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("# keep", text)
            self.assertIn("USER_NAME=Tony", text)
            self.assertIn("FISH_API_KEY=abc", text)
            self.assertEqual(seen, [env_path])

    def test_apply_env_file_and_scrub(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FISH_API_KEY=voice\nANTHROPIC_API_KEY=nope\n",
                                encoding="utf-8")
            environ = {"CLAUDE_CODE_X": "bad", "CLAUDECODE": "bad"}
            core.apply_env_file(env_path, environ)
            core.scrub_anthropic(environ)
            self.assertEqual(environ["FISH_API_KEY"], "voice")
            self.assertNotIn("ANTHROPIC_API_KEY", environ)
            self.assertNotIn("CLAUDECODE", environ)
            self.assertNotIn("CLAUDE_CODE_X", environ)

    def test_is_native_exe_rejects_shim_and_elf(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "claude.exe"
            shim = Path(tmp) / "claude.cmd"
            elf = Path(tmp) / "elf.exe"
            good.write_bytes(b"MZ" + b"\0" * 64)
            shim.write_bytes(b"MZ" + b"\0" * 64)
            elf.write_bytes(b"\x7fELF" + b"\0" * 64)
            self.assertTrue(core.is_native_exe(good))
            self.assertFalse(core.is_native_exe(shim))
            self.assertFalse(core.is_native_exe(elf))

    def test_scan_payload_flags_secrets_and_allows_openssl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "jarvis_win").mkdir()
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "tools" / "openssl.exe").write_bytes(b"MZ" + b"\0" * 10)
            (root / "jarvis_win" / "ShowToast.ps1").write_text("fixed", encoding="utf-8")
            (root / ".env").write_text("FISH_API_KEY=x", encoding="utf-8")
            (root / "cert.pem").write_text("x", encoding="utf-8")
            (root / "node_modules" / "x" / "a.js").write_text("x", encoding="utf-8")
            problems = core.scan_payload(root)
            self.assertIn(".env", problems)
            self.assertIn("cert.pem", problems)
            self.assertTrue(any("node_modules" in p for p in problems))
            self.assertNotIn("tools/openssl.exe", problems)
            self.assertNotIn("jarvis_win/ShowToast.ps1", problems)

    def test_winget_argv_is_user_scope(self):
        argv = core.winget_argv("Anthropic.ClaudeCode")
        self.assertEqual(argv[argv.index("--scope") + 1], "user")
        self.assertIn("--silent", argv)
        self.assertNotIn("--scope machine", " ".join(argv))

    def test_certificate_argv_has_localhost_san(self):
        argv = core.certificate_argv("openssl.exe", "cert.pem", "key.pem")
        self.assertIn("-addext", argv)
        self.assertIn("subjectAltName=DNS:localhost,IP:127.0.0.1", argv)
        self.assertNotIn("0.0.0.0", " ".join(argv))

    def test_runtime_document_has_no_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.Paths.from_env({"LOCALAPPDATA": str(root / "local"),
                                         "APPDATA": str(root / "roaming")},
                                        bundle=root / "bundle")
            doc = core.runtime_document(paths, "claude.exe", "openssl.exe", "abc")
            self.assertEqual(doc["bind_host"], "127.0.0.1")
            self.assertFalse(doc["node_runtime"])
            self.assertFalse(doc["venv"])
            self.assertFalse(doc["inno_setup"])


class WinTests(unittest.TestCase):
    def test_hidden_creationflags(self):
        if os.name == "nt":
            self.assertTrue(win.hidden_creationflags()
                            & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        else:
            self.assertEqual(win.hidden_creationflags(), 0)

    def test_run_hidden_uses_no_shell_and_captures_output(self):
        with patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(["tool"], 0, stdout="ok")
            result = win.run_hidden(["tool", "arg"])
            self.assertEqual(result.stdout, "ok")
            kwargs = run.call_args.kwargs
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
            self.assertTrue(kwargs["text"])

    def test_login_status_parses_json(self):
        result = win.CommandResult(0, '{"loggedIn": true, "email": "a@b.c"}')
        self.assertTrue(win.login_status("claude.exe", run=lambda *a, **k: result))

    def test_finish_login_sends_enter(self):
        class FakeProcess:
            def __init__(self):
                self.stdin = io.StringIO()
                self.waited = False
            def wait(self, timeout=None):
                self.waited = True
                return 0
        process = FakeProcess()
        win.finish_login(process)
        self.assertEqual(process.stdin.getvalue(), "\n")
        self.assertTrue(process.waited)

    def test_startup_shortcut_argv_has_no_shell_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.Paths.from_env({"LOCALAPPDATA": str(root / "local"),
                                         "APPDATA": str(root / "roaming")},
                                        bundle=root / "bundle")
            argv = win.startup_shortcut_argv(paths, "C:/JarvisOneClick.exe")
            joined = " ".join(argv)
            for forbidden in ("wt.exe", "Code.exe", "bash.exe", "cmd.exe", "0.0.0.0"):
                self.assertNotIn(forbidden, joined)
            self.assertIn("-WindowStyle", argv)
            self.assertIn("Hidden", argv)
            self.assertIn("--launch", joined)

    def test_setup_all_first_run_with_fakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = root / "local"
            home = root / "home"
            pf = root / "pf"
            bundle = root / "bundle"
            for path in (local, home, pf, bundle / "tools"):
                path.mkdir(parents=True, exist_ok=True)
            chrome = pf / "Google" / "Chrome" / "Application" / "chrome.exe"
            claude = home / ".local" / "bin" / "claude.exe"
            openssl = bundle / "tools" / "openssl.exe"
            chrome.parent.mkdir(parents=True, exist_ok=True)
            claude.parent.mkdir(parents=True, exist_ok=True)
            for path in (chrome, claude, openssl):
                path.write_bytes(b"MZ" + b"\0" * 64)
            env = {
                "LOCALAPPDATA": str(local), "APPDATA": str(root / "roaming"),
                "USERPROFILE": str(home), "ProgramFiles": str(pf),
                "USERNAME": "SEAN", "USERDOMAIN": "PC",
            }
            paths = core.Paths.from_env(env, bundle=bundle)
            calls: list[list[str]] = []
            spawns: list[list[str]] = []
            progress: list[str] = []

            def fake_run(argv, **kwargs):
                calls.append([str(x) for x in argv])
                if len(argv) > 2 and argv[1] == "auth" and argv[2] == "status":
                    return win.CommandResult(0, '{"loggedIn": true}')
                if "openssl.exe" in str(argv[0]):
                    paths.cert.write_text("cert", encoding="utf-8")
                    paths.key.write_text("key", encoding="utf-8")
                return win.CommandResult(0, "")

            def fake_spawn(argv, **kwargs):
                spawns.append([str(x) for x in argv])
                return object()

            with patch("oneclick.win.health_ok", side_effect=[False, True]):
                result = win.setup_all(
                    "fish-secret", paths, progress=progress.append,
                    run=fake_run, spawn=fake_spawn, env=env,
                    login_prompt=lambda proc: None, ref="abc",
                    exe=str(root / "JarvisOneClick.exe"), start=True)

            self.assertTrue(result.started)
            self.assertTrue(result.logged_in)
            self.assertEqual(result.claude, str(claude))
            self.assertEqual(result.chrome, str(chrome))
            self.assertEqual(result.openssl, str(openssl))
            self.assertIn("FISH_API_KEY=fish-secret",
                          paths.env_file.read_text(encoding="utf-8"))
            self.assertTrue(paths.cert.exists())
            self.assertTrue(paths.runtime.exists())
            self.assertNotIn("fish-secret", " ".join(progress))
            for argv in calls + spawns:
                self.assertNotIn("fish-secret", " ".join(argv))
                self.assertNotIn("0.0.0.0", " ".join(argv))
                self.assertNotIn("claude.cmd", " ".join(argv))
                self.assertNotIn("wt.exe", " ".join(argv))
                self.assertNotIn("Code.exe", " ".join(argv))

    def test_controller_quick_launch_without_key_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = core.Paths.from_env({"LOCALAPPDATA": str(root / "local"),
                                         "APPDATA": str(root / "roaming")},
                                        bundle=root / "bundle")
            controller = gui.Controller(paths=paths,
                                        run=lambda *a, **k: win.CommandResult(0, ""),
                                        spawn=lambda *a, **k: object(),
                                        exe="JarvisOneClick.exe")
            self.assertFalse(controller.quick_launch())


if __name__ == "__main__":
    unittest.main()
