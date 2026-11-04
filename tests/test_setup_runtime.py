import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_win import setup_runtime
from tests._stubs import FakeSyncProcess


class SetupRuntimeTests(unittest.TestCase):
    def test_redactor_covers_bare_env_and_json_values(self):
        redactor = setup_runtime.Redactor(["SUPERSECRET"])
        text = "FISH_API_KEY=OTHER_SECRET\n{\"fish_api_key\": \"ANOTHER_SECRET\"}\nSUPERSECRET"
        safe = redactor.redact(text)
        for secret in ("SUPERSECRET", "OTHER_SECRET", "ANOTHER_SECRET"):
            self.assertNotIn(secret, safe)
        self.assertIn("[REDACTED]", safe)

    def test_update_env_preserves_comments_and_other_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("# keep me\nUSER_NAME=Old\nOTHER=Keep\n", encoding="utf-8")
            setup_runtime.update_env(env, {"FISH_API_KEY": "NEWSECRET",
                                           "USER_NAME": "Sean"})
            text = env.read_text(encoding="utf-8")
            self.assertIn("# keep me", text)
            self.assertIn("USER_NAME=Sean", text)
            self.assertIn("OTHER=Keep", text)
            self.assertIn("FISH_API_KEY=NEWSECRET", text)
            self.assertTrue(setup_runtime.has_fish_key(env))

    def test_secure_delete_removes_job_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job.json"
            job.write_text('{"fish_api_key": "SUPERSECRET"}', encoding="utf-8")
            setup_runtime.secure_delete(job)
            self.assertFalse(job.exists())
            setup_runtime.secure_delete(job)  # idempotent

    def test_run_command_redacts_output_and_never_puts_key_in_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_file = root / "setup.log"
            progress_file = root / "setup.progress"
            logger = setup_runtime.SetupLogger(log_file, progress_file,
                                               setup_runtime.Redactor(["SUPERSECRET"]))
            calls = []
            process = FakeSyncProcess("pip says SUPERSECRET", 0)

            def fake_popen(argv, **kwargs):
                calls.append((list(argv), kwargs))
                return process

            code = setup_runtime.run_command(
                ["python", "-m", "pip", "install"], cwd=root, logger=logger,
                cancel_file=None, label="installing", percent=30, done_percent=40,
                popen=fake_popen)
            self.assertEqual(code, 0)
            text = log_file.read_text(encoding="utf-8")
            progress = progress_file.read_text(encoding="utf-8")
            self.assertNotIn("SUPERSECRET", text)
            self.assertNotIn("SUPERSECRET", progress)
            self.assertTrue(progress.startswith("40|"))
            self.assertNotIn("SUPERSECRET", " ".join(calls[0][0]))

    def test_cancel_sentinel_stops_before_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel = root / "cancel"
            cancel.write_text("cancel", encoding="ascii")
            logger = setup_runtime.SetupLogger(root / "setup.log", None)

            def forbidden_popen(*_args, **_kwargs):
                raise AssertionError("must not spawn after cancellation")

            with self.assertRaises(setup_runtime.SetupCancelled):
                setup_runtime.run_command(
                    ["python", "-m", "pip"], cwd=root, logger=logger,
                    cancel_file=cancel, label="installing", percent=30,
                    popen=forbidden_popen)

    def test_skip_preflight_main_is_end_to_end_secret_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_python, pythonw = setup_runtime.venv_paths(root)[1:]
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("#!/bin/sh\n", encoding="ascii")
            (root / "requirements-windows.txt").write_text("fastapi\n", encoding="ascii")
            (root / "cert.pem").write_text("existing cert", encoding="ascii")
            (root / "key.pem").write_text("existing key", encoding="ascii")
            job = root / "job.json"
            job.write_text(json.dumps({"fish_api_key": "SUPERSECRET",
                                       "user_name": "Sean",
                                       "brain_model": "sonnet",
                                       "voice_id": "jarvis"}), encoding="utf-8")
            calls = []

            def fake_popen(argv, **kwargs):
                calls.append(list(argv))
                return FakeSyncProcess("child saw SUPERSECRET", 0)

            with patch.object(setup_runtime, "_POPEN", fake_popen), \
                 patch.object(setup_runtime.claude_launcher, "resolve_claude",
                              return_value=None):
                code = setup_runtime.main([
                    "--app-root", str(root), "--job-file", str(job),
                    "--python", "/usr/bin/python3",
                    "--progress-file", str(root / "logs" / "setup.progress"),
                    "--exit-file", str(root / "logs" / "setup.exitcode"),
                    "--log-file", str(root / "logs" / "setup.log"),
                    "--cancel-file", str(root / "logs" / "setup.cancel"),
                    "--skip-preflight",
                ])
            self.assertEqual(code, 0)
            self.assertFalse(job.exists())
            self.assertEqual((root / "logs" / "setup.exitcode").read_text().strip(), "0")
            self.assertIn("FISH_API_KEY=SUPERSECRET", (root / ".env").read_text())
            self.assertNotIn("SUPERSECRET", (root / "logs" / "setup.log").read_text())
            self.assertNotIn("SUPERSECRET", (root / "logs" / "setup.progress").read_text())
            self.assertNotIn("SUPERSECRET", " ".join(" ".join(a) for a in calls))
            runtime = json.loads((root / "runtime.json").read_text())
            self.assertEqual(runtime["bind_host"], "127.0.0.1")
            self.assertEqual(runtime["origin"], "https://localhost:8340")
            self.assertEqual(Path(runtime["pythonw"]).resolve(), pythonw.resolve())


if __name__ == "__main__":
    unittest.main()
