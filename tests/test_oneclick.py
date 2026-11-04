import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from oneclick import core, gui, win


class FakeStore(core._EnvStore):
    """Portable fixture store: no Windows API or real ACL calls."""

    def secure_temp(self, path):
        if path.read_bytes() != b"":
            raise AssertionError("ACL callback received content")

    def reuse(self, path):
        return path.read_text(encoding="utf-8")


class CoreTests(unittest.TestCase):
    def test_transaction_order_and_failure_stages(self):
        for failure in (None, "begin", "acl", "identity", "write", "flush", "publish", "close"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_bytes(b"# original\nFISH_API_KEY=old\n")
                events = []
                transaction = Mock(original="# original\nFISH_API_KEY=old\n",
                                   temp_path=path.with_suffix(".tmp"))
                def step(name):
                    def invoke(*args):
                        events.append(name)
                        if name == failure:
                            raise OSError("inert-secret")
                    return invoke
                for method, stage in (("check_identity", "identity"), ("write_all", "write"),
                                      ("flush", "flush"), ("publish", "publish"),
                                      ("close", "close"), ("abort", "abort")):
                    getattr(transaction, method).side_effect = step(stage)
                store = Mock()
                def begin(p):
                    step("begin")()
                    return transaction
                store.begin.side_effect = begin
                if failure:
                    with self.assertRaises(core.EnvPersistenceError) as caught:
                        core._update_env_with_store(path, {"FISH_API_KEY": "inert-secret"},
                                                    acl=step("acl"), store=store)
                    self.assertEqual(caught.exception.stage, failure)
                    self.assertNotIn("inert-secret", str(caught.exception))
                    self.assertEqual(path.read_bytes(), b"# original\nFISH_API_KEY=old\n")
                    if failure != "begin":
                        transaction.abort.assert_called_once()
                else:
                    self.assertEqual(core._update_env_with_store(path, {"FISH_API_KEY": "new"},
                                     acl=step("acl"), store=store), path)
                    self.assertEqual(events, ["begin", "acl", "identity", "write", "flush", "publish", "close"])

    def test_callback_failure_keeps_old_file_and_foreign_temp(self):
        for result in (False, True, 0, win.CommandResult(0, "inert-secret")):
            with self.subTest(result=type(result)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_bytes(b"# keep\nFISH_API_KEY=old\n")
                foreign = path.with_name(".env.tmp")
                foreign.write_bytes(b"foreign")
                def acl(temp):
                    self.assertEqual(temp.read_bytes(), b"")
                    return result
                with self.assertRaises(core.EnvPersistenceError):
                    core.update_env(path, {"FISH_API_KEY": "new"}, acl=acl)
                self.assertEqual(path.read_bytes(), b"# keep\nFISH_API_KEY=old\n")
                self.assertEqual(foreign.read_bytes(), b"foreign")
                self.assertEqual(set(Path(tmp).iterdir()), {path, foreign})

    def test_cleanup_failure_preserves_primary_error(self):
        primary = OSError("inert-secret")
        transaction = Mock(original="", temp_path=Path("unused"))
        transaction.flush.side_effect = primary
        transaction.abort.side_effect = OSError("cleanup")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(core.EnvPersistenceError) as caught:
            core._update_env_with_store(Path(tmp) / ".env", {}, acl=None,
                                        store=Mock(begin=Mock(return_value=transaction)))
        self.assertIs(caught.exception.primary, primary)
        self.assertTrue(caught.exception.cleanup_failed)
        self.assertNotIn("inert-secret", str(caught.exception))

    def test_blank_updates_unknown_keys_and_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# café\nUNKNOWN=é\nFISH_API_KEY=keep\n", encoding="utf-8")
            core.update_env(path, {"FISH_API_KEY": "", "EMPTY": ""})
            self.assertEqual(path.read_text(encoding="utf-8"), "# café\nUNKNOWN=é\nFISH_API_KEY=keep\n")
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
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].parent, env_path.parent)
            self.assertNotEqual(seen[0], env_path)

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
    def test_persistence_failure_stops_setup_and_sanitizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = core.Paths.from_env({"LOCALAPPDATA": tmp}, bundle=Path(tmp) / "bundle")
            progress, run, spawn = [], Mock(), Mock()
            with patch("oneclick.win.WindowsStore", side_effect=OSError("inert-secret")), \
                    patch("oneclick.win.ensure_chrome") as chrome, \
                    patch("oneclick.win.write_runtime") as runtime:
                with self.assertRaises(win.SetupError) as caught:
                    win.setup_all("inert-secret", paths, progress=progress.append, run=run, spawn=spawn)
            self.assertNotIn("inert-secret", str(caught.exception))
            self.assertNotIn("inert-secret", " ".join(progress))
            self.assertNotIn("JARVIS is ready.", progress)
            chrome.assert_not_called()
            runtime.assert_not_called()
            run.assert_not_called()
            spawn.assert_not_called()

    def test_existing_key_reuse_and_blank_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch("oneclick.win.WindowsStore", FakeStore):
            paths = core.Paths.from_env({"JARVIS_ONECLICK_APP_ROOT": tmp}, bundle=Path(tmp))
            paths.env_file.parent.mkdir(parents=True, exist_ok=True)
            paths.env_file.write_bytes(b"# unchanged\nFISH_API_KEY=inert\n")
            original = paths.env_file.read_bytes()
            run = Mock()
            win.write_env_and_acl(paths, "", run=run)
            self.assertEqual(paths.env_file.read_bytes(), original)
            paths.env_file.write_bytes(b"FISH_API_KEY=\n")
            with self.assertRaisesRegex(win.SetupError, "required"):
                win.write_env_and_acl(paths, "", run=run)
            run.assert_not_called()
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

            with patch("oneclick.win.health_ok", side_effect=[False, True]), \
                    patch("oneclick.win.WindowsStore", FakeStore):
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


class NativeContractMockTests(unittest.TestCase):
    def setUp(self):
        self.last_error = patch("ctypes.get_last_error", return_value=5, create=True)
        self.last_error.start()
        self.addCleanup(self.last_error.stop)

    def test_token_user_queries_and_handle_lifetime(self):
        import ctypes as C
        from oneclick._env_windows import _Native, P, H, D, NativeError
        for failure in (None, "impersonation", "thread-query", "process-token",
                        "token-size", "token-user", "user-sid", "copy-sid", "close"):
            with self.subTest(failure=failure):
                native = _Native.__new__(_Native)
                native.a, native.k = Mock(), Mock()
                error = [1008]
                user = C.create_string_buffer(12)
                def thread(thread, access, self_token, output):
                    C.cast(output, C.POINTER(H))[0] = 20
                    error[0] = 5 if failure == "thread-query" else 1008
                    return failure == "impersonation"
                native.a.OpenThreadToken.side_effect = thread
                def process(process, access, output):
                    C.cast(output, C.POINTER(H))[0] = 30
                    return failure != "process-token"
                native.a.OpenProcessToken.side_effect = process
                def information(token, kind, data, size, needed):
                    C.cast(needed, C.POINTER(D))[0] = C.sizeof(P) + 8
                    if data is None:
                        error[0] = 5 if failure == "token-size" else 122
                        return False
                    C.cast(data, C.POINTER(P))[0] = C.addressof(user)
                    return failure != "token-user"
                native.a.GetTokenInformation.side_effect = information
                native.a.IsValidSid.return_value = failure != "user-sid"
                native.a.GetLengthSid.return_value = 12
                native.a.CopySid.return_value = failure != "copy-sid"
                native.k.CloseHandle.return_value = failure != "close"
                with patch("ctypes.get_last_error", side_effect=lambda: error[0], create=True):
                    if failure:
                        with self.assertRaises(NativeError): native._user_sid()
                    else:
                        self.assertEqual(C.sizeof(native._user_sid()), 12)
                if failure in ("thread-query", "process-token"):
                    native.k.CloseHandle.assert_not_called()
                else:
                    native.k.CloseHandle.assert_called_once()

    def test_regular_file_identity_rejects_reparse_directory_and_hardlinks(self):
        import ctypes as C
        from oneclick._env_windows import _Native, _FileInfo, NativeError
        for case in ("regular", "query", "pipe", "reparse", "directory", "hardlinks"):
            with self.subTest(case=case):
                native = _Native.__new__(_Native)
                native.k = Mock()
                def information(handle, output):
                    info = C.cast(output, C.POINTER(_FileInfo)).contents
                    info.attributes = {"reparse": 0x400, "directory": 0x10}.get(case, 0)
                    info.links = 2 if case == "hardlinks" else 1
                    info.volume, info.index_high, info.index_low = 1, 2, 3
                    return case != "query"
                native.k.GetFileInformationByHandle.side_effect = information
                native.k.GetFileType.return_value = 3 if case == "pipe" else 1
                if case == "regular": self.assertEqual(native.info(10), (1, 2, 3))
                else:
                    with self.assertRaises(NativeError): native.info(10)

    def test_constructor_collisions_and_foreign_objects_are_never_aborted(self):
        from oneclick._env_windows import _Transaction, NativeError
        path = Path("C:/fixture/.env")
        for case in ("success", "collision", "owner", "ancestor", "identity"):
            with self.subTest(case=case):
                native = Mock()
                def open_file(candidate, access, creation=3, share=0):
                    if creation == 1:
                        if case == "collision": raise NativeError("open", 80)
                        return 30
                    return 20 if candidate == path else 10
                native.open.side_effect = open_file
                native.info.return_value = (1, 2, 3)
                native.read.return_value = "# inert\nFISH_API_KEY=old\n"
                if case == "owner": native.descriptor.side_effect = NativeError("owner")
                if case == "ancestor": native.local_ntfs.side_effect = NativeError("ancestor")
                if case == "identity":
                    native.info.side_effect = lambda handle, **kw: (
                        (_ for _ in ()).throw(NativeError("identity")) if handle == 30 else (1, 2, 3))
                if case != "success":
                    with self.assertRaises(core.EnvPersistenceError): _Transaction(path, native)
                    if case == "identity":
                        self.assertEqual(native.k.SetFileInformationByHandle.call_args.args[:2], (30, 4))
                    else:
                        native.k.SetFileInformationByHandle.assert_not_called()
                    if case == "collision":
                        self.assertEqual(sum(call.kwargs.get("creation") == 1 for call in native.open.call_args_list), 16)
                else:
                    transaction = _Transaction(path, native)
                    self.assertEqual(transaction.original, "# inert\nFISH_API_KEY=old\n")
                    transaction.abort()
                    transaction.close()
                    self.assertEqual(native.k.SetFileInformationByHandle.call_args.args[:2], (30, 4))

    def test_descriptor_rejects_each_policy_deviation_and_frees(self):
        import ctypes as C
        from oneclick._env_windows import _Native, _Acl, _Ace, P, FILE_ALL_ACCESS, NativeError
        for invalid in (None, "descriptor", "owner", "protection", "absent", "null", "acl",
                        "count", "revision", "type", "flags", "mask", "sid", "size", "query", "get-ace"):
            with self.subTest(invalid=invalid):
                native = _Native.__new__(_Native)
                native.a, native.k, native.sid = Mock(), Mock(), C.create_string_buffer(12)
                acl = _Acl(2, 0, 28, 1, 0)
                ace = _Ace(0, 0, 20, FILE_ALL_ACCESS, 0)
                native.a.IsValidSecurityDescriptor.return_value = invalid != "descriptor"
                native.a.IsValidSid.return_value = True
                native.a.EqualSid.side_effect = [invalid != "owner", invalid != "sid"]
                native.a.IsValidAcl.return_value = invalid != "acl"
                native.a.GetLengthSid.return_value = 12
                native.k.LocalFree.return_value = None
                def security(handle, kind, flags, owner, group, dacl, sacl, descriptor):
                    C.cast(owner, C.POINTER(P))[0] = 0x1234
                    C.cast(dacl, C.POINTER(P))[0] = C.addressof(acl)
                    C.cast(descriptor, C.POINTER(P))[0] = 0x5678
                    return 5 if invalid == "query" else 0
                native.a.GetSecurityInfo.side_effect = security
                def control(sd, flags, revision):
                    C.cast(flags, C.POINTER(C.c_ushort))[0] = 0 if invalid == "protection" else 0x1000
                    return True
                native.a.GetSecurityDescriptorControl.side_effect = control
                def dacl(sd, present, actual, defaulted):
                    C.cast(present, C.POINTER(C.c_long))[0] = invalid != "absent"
                    C.cast(actual, C.POINTER(P))[0] = None if invalid == "null" else C.addressof(acl)
                    return True
                native.a.GetSecurityDescriptorDacl.side_effect = dacl
                def get_ace(a, index, output):
                    C.cast(output, C.POINTER(P))[0] = C.addressof(ace)
                    return invalid != "get-ace"
                native.a.GetAce.side_effect = get_ace
                if invalid == "count": acl.count = 2
                if invalid == "revision": acl.revision = 4
                if invalid == "type": ace.type = 1
                if invalid == "flags": ace.flags = 0x10
                if invalid == "mask": ace.mask = 0x120089
                if invalid == "size": ace.size = 24
                if invalid is None:
                    native.descriptor(10, exact=True)
                else:
                    with self.assertRaises(NativeError):
                        native.descriptor(10, exact=True)
                if invalid != "query":
                    native.k.LocalFree.assert_called_once()

    def test_exact_replacement_checked_dword_and_owner_refusal(self):
        import ctypes as C
        from oneclick._env_windows import _Native, NativeError, FILE_ALL_ACCESS
        for fail in (None, "owner", "initialize", "add", "set", "readback"):
            with self.subTest(fail=fail):
                native = _Native.__new__(_Native)
                native.a, native.sid = Mock(), C.create_string_buffer(12)
                native.descriptor = Mock()
                native.a.GetLengthSid.return_value = 12
                native.a.InitializeAcl.return_value = fail != "initialize"
                native.a.AddAccessAllowedAceEx.return_value = fail != "add"
                native.a.SetSecurityInfo.return_value = 5 if fail == "set" else 0
                if fail == "owner": native.descriptor.side_effect = NativeError("owner")
                if fail == "readback": native.descriptor.side_effect = [None, NativeError("readback")]
                if fail:
                    with self.assertRaises(NativeError): native.secure(10)
                else:
                    native.secure(10)
                    native.descriptor.assert_any_call(10, exact=False)
                    native.descriptor.assert_any_call(10, exact=True)
                    args = native.a.SetSecurityInfo.call_args.args
                    self.assertEqual(args[:5], (10, 1, 0x80000004, None, None))
                    self.assertIsNotNone(args[5])
                    self.assertIsNone(args[6])
                    self.assertEqual(native.a.AddAccessAllowedAceEx.call_args.args[1:4],
                                     (2, 0, FILE_ALL_ACCESS))
                if fail == "owner": native.a.SetSecurityInfo.assert_not_called()

    def test_handle_partial_writes_zero_write_flush_rename_and_abort_failures(self):
        import ctypes as C
        from oneclick._env_windows import _Native, _Transaction, NativeError, D
        for failure in (None, "write", "zero", "flush", "rename", "abort", "close"):
            with self.subTest(failure=failure):
                native = Mock()
                native.check.side_effect = lambda result, stage: _Native.check(native, result, stage)
                native.info.return_value = (1, 2, 3)
                transaction = _Transaction.__new__(_Transaction)
                transaction.native, transaction.path = native, Path("C:/fixture/.env")
                transaction.handle, transaction.existing, transaction.directories = 10, None, []
                transaction.secured, transaction.committed = True, False
                transaction.identity = (1, 2, 3)
                counts = []
                def write(handle, buffer, size, count, overlapped):
                    counts.append(size)
                    C.cast(count, C.POINTER(D))[0] = 0 if failure == "zero" else min(2, size)
                    return failure != "write"
                native.k.WriteFile.side_effect = write
                native.k.FlushFileBuffers.return_value = failure != "flush"
                native.k.SetFileInformationByHandle.side_effect = lambda h, kind, *a: not (
                    (failure == "rename" and kind == 3) or (failure == "abort" and kind == 4))
                if failure == "close": native.close.side_effect = NativeError("close")
                if failure in ("write", "zero"):
                    with self.assertRaises(NativeError): transaction.write_all(b"inert")
                    continue
                transaction.write_all(b"inert")
                self.assertEqual(counts, [5, 3, 1])
                if failure == "flush":
                    with self.assertRaises(NativeError): transaction.flush()
                    continue
                transaction.flush()
                if failure == "rename":
                    with self.assertRaises(NativeError): transaction.publish()
                    self.assertFalse(transaction.committed)
                    transaction.abort()
                elif failure == "abort":
                    with self.assertRaises(NativeError): transaction.abort()
                else:
                    transaction.publish()
                    self.assertTrue(transaction.committed)
                    native.k.SetFileInformationByHandle.reset_mock()
                    transaction.abort()
                    native.k.SetFileInformationByHandle.assert_not_called()
                    if failure == "close":
                        with self.assertRaises(NativeError): transaction.close()
                        self.assertTrue(transaction.committed)


@unittest.skipUnless(os.name == "nt" and os.getenv("JARVIS_TEST_NATIVE_ENV") == "1",
                     "Explicit fresh-fixture native gate only")
class NativeEnvTests(unittest.TestCase):
    def test_native_transaction_precommit_preserves_old_bytes_and_acl(self):
        from oneclick._env_windows import _Native, _Transaction, FILE_ALL_ACCESS
        native = _Native()
        with tempfile.TemporaryDirectory(prefix="jarvis-native-env-") as tmp:
            path = Path(tmp) / ".env"
            path.write_bytes(b"# inert original\nFISH_API_KEY=inert-old\n")
            original, descriptor = path.read_bytes(), self._descriptor_bytes(path, native)
            # Inject only fixture acquisition: full ancestor validation has its own gate.
            class FixtureStore:
                def begin(self, target):
                    transaction = _Transaction.__new__(_Transaction)
                    transaction.native, transaction.path = native, target
                    transaction.temp_path = target.with_name("owned.tmp")
                    transaction.handle = native.open(transaction.temp_path, FILE_ALL_ACCESS, creation=1)
                    transaction.existing, transaction.directories = None, []
                    transaction.committed, transaction.secured = False, False
                    transaction.original = original.decode("utf-8")
                    transaction.identity = native.info(transaction.handle)
                    self.transaction = transaction
                    return transaction

                def secure_temp(self, temporary):
                    native.secure(self.transaction.handle)
                    self.transaction.secured = True

            for failure in ("acl", "write_all", "flush", "publish", "close"):
                with self.subTest(failure=failure):
                    store = FixtureStore()
                    real_begin = store.begin
                    def begin(target):
                        transaction = real_begin(target)
                        if failure not in ("acl", "close"):
                            setattr(transaction, failure, Mock(side_effect=OSError("inert-failure")))
                        if failure == "close":
                            real_close = transaction.close
                            def close():
                                real_close()
                                raise OSError("inert-close-failure")
                            transaction.close = close
                        return transaction
                    store.begin = begin
                    callback = (Mock(side_effect=OSError("inert-acl-failure"))
                                if failure == "acl" else store.secure_temp)
                    with self.assertRaises(core.EnvPersistenceError):
                        core._update_env_with_store(path, {"FISH_API_KEY": "inert-new"},
                                                    acl=callback, store=store)
                    if failure == "close":
                        self.assertTrue(store.transaction.committed)
                        self.assertIn(b"FISH_API_KEY=inert-new", path.read_bytes())
                        handle = native.open(path, 0x80000000 | 0x60000)
                        try:
                            native.secure(handle)
                            self.assertIn("inert-new", native.read(handle))
                        finally:
                            native.close(handle)
                    else:
                        self.assertEqual(path.read_bytes(), original)
                        self.assertEqual(self._descriptor_bytes(path, native), descriptor)
                    self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_native_acl_write_flush_rename_and_lifetime(self):
        from oneclick._env_windows import _Native, _Transaction, FILE_ALL_ACCESS
        with tempfile.TemporaryDirectory(prefix="jarvis-native-env-") as tmp:
            native = _Native()
            path = Path(tmp) / ".env"
            # This API gate does not claim ancestor-validation coverage.
            transaction = _Transaction.__new__(_Transaction)
            transaction.native, transaction.path = native, path
            transaction.temp_path = Path(tmp) / "owned.tmp"
            transaction.handle = native.open(transaction.temp_path, FILE_ALL_ACCESS, creation=1)
            transaction.existing, transaction.directories = None, []
            transaction.committed, transaction.secured = False, False
            try:
                transaction.identity = native.info(transaction.handle)
                native.local_ntfs(transaction.handle)
                native.secure(transaction.handle)
                transaction.secured = True
                transaction.check_identity()
                transaction.write_all(b"FISH_API_KEY=inert-native\n")
                transaction.flush()
                transaction.publish()
                native.descriptor(transaction.handle, exact=True)
                self.assertTrue(transaction.committed)
                transaction.abort()  # A committed object must survive cleanup.
            finally:
                if not transaction.committed:
                    transaction.abort()
                transaction.close()
            self.assertEqual(path.read_bytes(), b"FISH_API_KEY=inert-native\n")

    def test_local_ntfs_write_replace_reuse_and_precommit_preservation(self):
        from oneclick._env_windows import WindowsStore
        with tempfile.TemporaryDirectory(prefix="jarvis-native-env-") as tmp:
            path = Path(tmp) / ".env"
            try:
                for value in ("inert-first", "inert-replacement"):
                    store = WindowsStore()
                    result = core._update_env_with_store(path, {"FISH_API_KEY": value},
                                                        acl=store.secure_temp, store=store)
                    self.assertEqual(result, path)
                    self.assertIn(value, path.read_text())
                    self.assertIn(value, WindowsStore().reuse(path))
                original = path.read_bytes()
                for failure in ("acl", "write_all", "flush", "publish"):
                    store = WindowsStore()
                    native = store.native
                    with self.subTest(failure=failure):
                        real_begin = store.begin
                        def begin(p):
                            transaction = real_begin(p)
                            if failure != "acl":
                                setattr(transaction, failure, Mock(side_effect=OSError("inert-failure")))
                            return transaction
                        store.begin = begin
                        # Capture exact descriptor bytes before each failed transaction.
                        before = self._descriptor_bytes(path, native)
                        callback = (Mock(side_effect=OSError("inert-acl-failure"))
                                    if failure == "acl" else store.secure_temp)
                        with self.assertRaises(core.EnvPersistenceError):
                            core._update_env_with_store(path, {"FISH_API_KEY": "inert-new"},
                                                        acl=callback, store=store)
                        self.assertEqual(path.read_bytes(), original)
                        self.assertEqual(self._descriptor_bytes(path, native), before)
                        self.assertEqual(list(Path(tmp).iterdir()), [path])
            except Exception as error:
                current = error
                stages = []
                while current is not None:
                    stages.append((type(current).__name__, getattr(current, "stage", None),
                                   getattr(current, "errno", None)))
                    current = getattr(current, "primary", None)
                print("Native stage evidence:", stages)
                raise

    @staticmethod
    def _descriptor_bytes(path, native):
        import ctypes as C
        from oneclick._env_windows import P
        handle = native.open(path, 0x20000)
        descriptor = P()
        try:
            code = native.a.GetSecurityInfo(handle, 1, 5, None, None, None, None, C.byref(descriptor))
            if code:
                raise OSError(code, "Fixture descriptor query failed")
            fn = native.a.GetSecurityDescriptorLength
            fn.argtypes, fn.restype = [P], C.c_uint32
            return C.string_at(descriptor, fn(descriptor))
        finally:
            if descriptor:
                native.k.LocalFree(descriptor)
            native.close(handle)


if __name__ == "__main__":
    unittest.main()
