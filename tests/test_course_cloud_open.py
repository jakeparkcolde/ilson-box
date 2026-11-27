"""Course cloud bridge, ilson.work default open, and Windows compatibility tests."""
import contextlib
import datetime as dt
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "template" / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

import cloud_bridge as cb  # noqa: E402
from course_bundle import sources, target_path  # noqa: E402
from test_cloud_bridge import FakeCloud, NOW, SAMPLE_COMPANY_ID, SAMPLE_RAW_CODE, SAMPLE_RUNNER_ID  # noqa: E402


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _os_proxy_nt():
    proxy = SimpleNamespace(
        **{name: getattr(os, name) for name in dir(os) if not name.startswith("__")}
    )
    proxy.name = "nt"
    return proxy


class CourseOpenCommandTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "state-home"
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.cli = _load_module("course_ilson_open_test", ROOT / "course/ilson.py")

    def tearDown(self):
        self._td.cleanup()

    def _base_env(self, **extra):
        env = {
            "ILSON_COURSE_STATE": str(self.home),
            "ILSON_COURSE_VAULT": str(self.vault),
        }
        env.update(extra)
        return env

    def test_open_defaults_to_ilson_work_on_macos_and_shows_hint_only_when_unpaired(self):
        out = io.StringIO()
        env = self._base_env(ILSON_CLOUD_URL="https://custom.supabase.co")
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(os, "environ", dict(os.environ, **env)), \
             mock.patch.object(self.cli.sys, "platform", "darwin"), \
             mock.patch.object(self.cli.os, "name", "posix"), \
             mock.patch.object(self.cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as m_run, \
             contextlib.redirect_stdout(out):
            os.environ.pop("ILSON_WORKSPACE_URL", None)
            rc = self.cli.main(["open"])
        self.assertEqual(rc, 0)
        m_run.assert_called_once_with(["/usr/bin/open", "https://ilson.work/"], check=False)
        text = out.getvalue()
        self.assertIn("일손 워크스페이스(https://ilson.work/)를 브라우저에서 열었습니다.", text)
        self.assertIn("이 PC를 ilson.work에 연결하려면: ilson cloud pair --code <사무소코드>", text)
        self.assertIn("로컬 간이 화면이 필요하면: ilson open --local", text)

        # Once cloud-runner.json exists, pairing hint is suppressed
        cfg_path = self.home / "state" / "cloud-runner.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text('{"runner_id": "r-1"}\n', encoding="utf-8")

        out2 = io.StringIO()
        with mock.patch.object(os, "environ", dict(os.environ, **env)), \
             mock.patch.object(self.cli.sys, "platform", "darwin"), \
             mock.patch.object(self.cli.os, "name", "posix"), \
             mock.patch.object(self.cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as m_run2, \
             contextlib.redirect_stdout(out2):
            os.environ.pop("ILSON_WORKSPACE_URL", None)
            rc2 = self.cli.main(["open"])
        self.assertEqual(rc2, 0)
        m_run2.assert_called_once_with(["/usr/bin/open", "https://ilson.work/"], check=False)
        text2 = out2.getvalue()
        self.assertIn("일손 워크스페이스(https://ilson.work/)를 브라우저에서 열었습니다.", text2)
        self.assertNotIn("ilson cloud pair --code", text2)
        self.assertIn("로컬 간이 화면이 필요하면: ilson open --local", text2)

    def test_open_uses_os_startfile_on_windows_and_respects_custom_https_url(self):
        out = io.StringIO()
        proxy = _os_proxy_nt()
        proxy.startfile = mock.Mock()
        proxy.environ = dict(
            os.environ,
            ILSON_COURSE_STATE=str(self.home),
            ILSON_COURSE_VAULT=str(self.vault),
            ILSON_WORKSPACE_URL="https://app.ilson.work/workspace",
        )
        with mock.patch.object(self.cli, "os", proxy), \
             contextlib.redirect_stdout(out):
            rc = self.cli.main(["open"])
        self.assertEqual(rc, 0)
        proxy.startfile.assert_called_once_with("https://app.ilson.work/workspace")
        self.assertIn("일손 워크스페이스(https://app.ilson.work/workspace)를 브라우저에서 열었습니다.", out.getvalue())

    def test_open_rejects_non_https_and_malformed_cloud_urls(self):
        bad_urls = (
            "",
            "http://ilson.work/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://",
            "https://user:pass@ilson.work/",
            "https://user@ilson.work/",
            "https://ilson.work:99999/",
            "https://ilson.work:abc/",
            "https://ilson.work/ path",
            'https://ilson.work/"injected',
            "https://ilson.work/'injected",
            "https://ilson.work/`id`",
            "https://ilson.work/<tag>",
            "https://ilson.work/|pipe",
            "https://ilson.work/\x85c1",
            "https://ilson.work/\nnewline",
            "https://ilson.work/\\backslash",
        )
        for bad in bad_urls:
            with self.subTest(bad=bad):
                err = io.StringIO()
                env = dict(os.environ, **self._base_env(ILSON_WORKSPACE_URL=bad))
                with mock.patch.object(os, "environ", env), \
                     mock.patch.object(self.cli.subprocess, "run") as m_run, \
                     mock.patch.object(self.cli.webbrowser, "open") as m_wb, \
                     contextlib.redirect_stderr(err):
                    rc = self.cli.main(["open"])
                self.assertEqual(rc, 2)
                self.assertIn("오류:", err.getvalue())
                m_run.assert_not_called()
                m_wb.assert_not_called()

    def test_open_local_dispatches_to_web_admin_course_profile(self):
        observed = []
        env = dict(os.environ, **self._base_env())
        with mock.patch.object(os, "environ", env), \
             mock.patch.object(self.cli.subprocess, "call", side_effect=lambda cmd: observed.append(cmd) or 0), \
             mock.patch.object(self.cli.subprocess, "run") as m_run:
            rc = self.cli.main(["open", "--local"])
        self.assertEqual(rc, 0)
        m_run.assert_not_called()
        self.assertEqual(len(observed), 1)
        cmd = observed[0]
        self.assertTrue(cmd[3].endswith("web-admin.py"))
        self.assertEqual(cmd[4:], ["open", "--home", str(self.home), "--vault", str(self.vault), "--profile", "course"])

        # Unknown extra flag fails with usage
        out = io.StringIO()
        with mock.patch.object(os, "environ", env), \
             mock.patch.object(self.cli.subprocess, "call") as m_call, \
             contextlib.redirect_stdout(out):
            rc_bad = self.cli.main(["open", "--bogus"])
        self.assertEqual(rc_bad, 2)
        self.assertIn("ilson open [--local]", out.getvalue())
        m_call.assert_not_called()

    def test_admin_status_and_stop_unchanged(self):
        observed = []
        env = dict(os.environ, **self._base_env())
        with mock.patch.object(os, "environ", env), \
             mock.patch.object(self.cli.subprocess, "call", side_effect=lambda cmd: observed.append(cmd) or 0):
            self.assertEqual(self.cli.main(["admin", "status"]), 0)
            self.assertEqual(self.cli.main(["admin", "stop", "--force"]), 0)
        self.assertEqual(observed[0][4:], ["status", "--home", str(self.home), "--vault", str(self.vault), "--profile", "course"])
        self.assertEqual(observed[1][4:], ["stop", "--home", str(self.home), "--vault", str(self.vault), "--profile", "course", "--force"])


class CourseCloudCommandTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        self.home = self.root / "state-home"
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.lib = self.root / "lib"
        self.lib.mkdir()
        (self.lib / "ilson.py").write_text((ROOT / "course/ilson.py").read_text(encoding="utf-8"), encoding="utf-8")
        (self.lib / "cloud_bridge.py").write_text((ROOT / "template/lib/cloud_bridge.py").read_text(encoding="utf-8"), encoding="utf-8")
        self.cli = _load_module("course_ilson_cloud_test", self.lib / "ilson.py")

    def tearDown(self):
        self._td.cleanup()

    def test_cloud_status_and_help_skip_license_check(self):
        # License denies everything, yet status and --help still work!
        (self.lib / "license.py").write_text("import sys; print('NO_LICENSE'); sys.exit(1)\n", encoding="utf-8")
        env = dict(os.environ, ILSON_COURSE_STATE=str(self.home), ILSON_COURSE_VAULT=str(self.vault))

        res_status = subprocess.run(
            [sys.executable, "-X", "utf8", str(self.lib / "ilson.py"), "cloud", "status", "--json"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_status.returncode, 0, res_status.stdout + res_status.stderr)
        data = json.loads(res_status.stdout)
        self.assertFalse(data["paired"])
        self.assertEqual(data["published_count"], 0)

        for flag in ("--help", "-h"):
            res_help = subprocess.run(
                [sys.executable, "-X", "utf8", str(self.lib / "ilson.py"), "cloud", flag],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_help.returncode, 0, res_help.stdout + res_help.stderr)
            self.assertIn("pair", res_help.stdout)
            self.assertIn("heartbeat", res_help.stdout)
            self.assertIn("publish", res_help.stdout)

    def test_cloud_mutating_actions_and_pair_alias_require_license_and_dispatch(self):
        env = dict(os.environ, ILSON_COURSE_STATE=str(self.home), ILSON_COURSE_VAULT=str(self.vault))

        # 1. Failing license blocks all mutating cloud actions
        for action_args in (
            ["cloud", "pair", "--code", SAMPLE_RAW_CODE],
            ["cloud", "sync"],
            ["cloud", "submit-draft", "--source-key", "k", "--platform", "threads", "--account", "a", "--body", "b"],
            ["cloud", "heartbeat"],
            ["cloud", "publish", "--dry-run"],
            ["pair", "--code", SAMPLE_RAW_CODE],
            ["pair", "--cloud", "--code", SAMPLE_RAW_CODE],
        ):
            with self.subTest(blocked=action_args):
                observed = []
                with mock.patch.object(os, "environ", env), \
                     mock.patch.object(self.cli.subprocess, "call", side_effect=lambda cmd: observed.append(cmd) or 1):
                    rc = self.cli.main(action_args)
                self.assertEqual(rc, 1)
                self.assertEqual(len(observed), 1)
                self.assertTrue(observed[0][3].endswith("license.py"))
                self.assertEqual(observed[0][4:], ["--home", str(self.home), "check"])

        # 2. Passing license dispatches to cloud_bridge.py --home <state> ...
        observed = []
        with mock.patch.object(os, "environ", env), \
             mock.patch.object(self.cli.subprocess, "call", side_effect=lambda cmd: observed.append(cmd) or 0):
            rc1 = self.cli.main(["cloud", "pair", "--code", SAMPLE_RAW_CODE])
            rc2 = self.cli.main(["pair", "--cloud", "--code", SAMPLE_RAW_CODE])
            rc3 = self.cli.main(["cloud", "heartbeat", "--json"])
            rc4 = self.cli.main(["cloud", "publish", "--dry-run"])
        self.assertEqual((rc1, rc2, rc3, rc4), (0, 0, 0, 0))
        self.assertEqual(len(observed), 8)
        # Check cloud_bridge dispatches (indices 1, 3, 5, 7)
        self.assertEqual(observed[1][3:], [str(self.lib / "cloud_bridge.py"), "--home", str(self.home), "pair", "--code", SAMPLE_RAW_CODE])
        self.assertEqual(observed[3][3:], [str(self.lib / "cloud_bridge.py"), "--home", str(self.home), "pair", "--code", SAMPLE_RAW_CODE])
        self.assertEqual(observed[5][3:], [str(self.lib / "cloud_bridge.py"), "--home", str(self.home), "heartbeat", "--json"])
        self.assertEqual(observed[7][3:], [str(self.lib / "cloud_bridge.py"), "--home", str(self.home), "publish", "--dry-run"])

    def test_cloud_bridge_cli_all_subcommands_with_leading_and_trailing_home(self):
        cloud = FakeCloud()
        # 1. pair with --home BEFORE subcommand
        buf_pair = io.StringIO()
        with contextlib.redirect_stdout(buf_pair):
            rc_pair = cb.main(
                ["--home", str(self.home), "pair", "--code", SAMPLE_RAW_CODE, "--json"],
                http_send=cloud.send,
            )
        self.assertEqual(rc_pair, 0)
        self.assertEqual(json.loads(buf_pair.getvalue())["company_id"], SAMPLE_COMPANY_ID)
        self.assertTrue((self.home / "state" / "cloud-runner.json").is_file())

        # 2. status with --home BEFORE subcommand sees paired=True
        buf_st = io.StringIO()
        with contextlib.redirect_stdout(buf_st):
            rc_st = cb.main(["--home", str(self.home), "status", "--json"])
        self.assertEqual(rc_st, 0)
        self.assertTrue(json.loads(buf_st.getvalue())["paired"])

        # 3. heartbeat with --home BEFORE subcommand
        cloud.calls.clear()
        buf_hb = io.StringIO()
        with contextlib.redirect_stdout(buf_hb):
            rc_hb = cb.main(["--home", str(self.home), "heartbeat", "--json"], http_send=cloud.send)
        self.assertEqual(rc_hb, 0)
        hb_data = json.loads(buf_hb.getvalue())
        self.assertTrue(hb_data["ok"])
        self.assertIn("last_beat_at", hb_data)

        # 4. submit-draft with --home BEFORE subcommand
        cloud.calls.clear()
        buf_draft = io.StringIO()
        with contextlib.redirect_stdout(buf_draft):
            rc_draft = cb.main(
                [
                    "--home", str(self.home), "submit-draft",
                    "--source-key", "k-cli-1", "--platform", "threads",
                    "--account", "student_alpha", "--body", "hello", "--json",
                ],
                http_send=cloud.send,
            )
        self.assertEqual(rc_draft, 0)
        self.assertEqual(json.loads(buf_draft.getvalue())["status"], "pending")

        # 5. sync --dry-run with --home BEFORE subcommand
        cloud.calls.clear()
        buf_sync = io.StringIO()
        with contextlib.redirect_stdout(buf_sync):
            rc_sync = cb.main(["--home", str(self.home), "sync", "--dry-run", "--json"], http_send=cloud.send)
        self.assertEqual(rc_sync, 0)
        self.assertTrue(json.loads(buf_sync.getvalue())["ok"])

        # 6. publish --dry-run with both leading and trailing --home
        for argv in (
            ["--home", str(self.home), "publish", "--dry-run", "--json"],
            ["publish", "--home", str(self.home), "--dry-run", "--json"],
        ):
            cloud.calls.clear()
            buf_pub = io.StringIO()
            with contextlib.redirect_stdout(buf_pub):
                rc_pub = cb.main(argv, http_send=cloud.send)
            self.assertEqual(rc_pub, 0)
            pub_data = json.loads(buf_pub.getvalue())
            self.assertTrue(pub_data["dry_run"])
            self.assertEqual(pub_data["published"], [])


class CloudBridgeWindowsCompatTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name).resolve()
        self.cloud = FakeCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_windows_nonblocking_lock_writes_byte_locks_unlocks_and_handles_contention(self):
        fake_msvcrt = SimpleNamespace(LK_NBLCK=11, LK_UNLCK=0, locking=mock.Mock())
        fake_acl = mock.Mock()
        proxy = _os_proxy_nt()

        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(cb, "_load_windows_acl", return_value=fake_acl), \
             mock.patch.dict(sys.modules, msvcrt=fake_msvcrt):
            res = cb.dispatch_approved_publishes(
                self.home, self.cfg, "jwt-1", http_send=self.cloud.send, now=NOW
            )
            self.assertFalse(res["locked"])
            self.assertEqual(fake_msvcrt.locking.call_count, 2)
            # First call acquires 1-byte non-blocking lock, second releases it
            self.assertEqual(fake_msvcrt.locking.call_args_list[0].args[1:], (11, 1))
            self.assertEqual(fake_msvcrt.locking.call_args_list[1].args[1:], (0, 1))
            # Lock file has at least 1 byte
            lock_path = self.home / "state" / "cloud-publish.lock"
            self.assertGreaterEqual(lock_path.stat().st_size, 1)

            # Lock contention via EACCES, EDEADLK, and BlockingIOError returns locked=True without unlocking
            for exc in (
                PermissionError(errno.EACCES, "locked"),
                OSError(errno.EDEADLK, "deadlock"),
                BlockingIOError("busy"),
            ):
                with self.subTest(exc=type(exc).__name__):
                    fake_msvcrt.locking.reset_mock()
                    fake_msvcrt.locking.side_effect = exc
                    self.cloud.calls.clear()
                    locked_res = cb.dispatch_approved_publishes(
                        self.home, self.cfg, "jwt-1", http_send=self.cloud.send, now=NOW
                    )
                    self.assertTrue(locked_res["locked"])
                    self.assertEqual(self.cloud.calls, [])
                    # Must NOT call LK_UNLCK when lock was not acquired
                    self.assertEqual(fake_msvcrt.locking.call_count, 1)

            # Non-lock OSError (e.g. EIO) must propagate
            fake_msvcrt.locking.side_effect = OSError(errno.EIO, "disk failure")
            with self.assertRaises(OSError):
                cb.dispatch_approved_publishes(
                    self.home, self.cfg, "jwt-1", http_send=self.cloud.send, now=NOW
                )

    def test_windows_reparse_point_refused_for_read_write_and_lock(self):
        proxy = _os_proxy_nt()
        target = self.home / "state" / "cloud-runner.json"
        real_lstat = Path.lstat

        def fake_lstat(path_obj):
            real_info = real_lstat(path_obj)
            if Path(path_obj) == target:
                return SimpleNamespace(
                    st_mode=real_info.st_mode,
                    st_file_attributes=0x400,
                    st_nlink=1,
                )
            return real_info

        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(Path, "lstat", fake_lstat):
            with self.assertRaises(cb.CloudBridgeError) as ctx_r:
                cb._read_private_json(target)
            self.assertIn("리파스 포인트", str(ctx_r.exception))

            with self.assertRaises(cb.CloudBridgeError) as ctx_w:
                cb._write_private_json(target, {"x": 1})
            self.assertIn("리파스 포인트", str(ctx_w.exception))

        # Reparse point on state directory must also fail
        state_dir = self.home / "state"

        def fake_lstat_dir(path_obj):
            real_info = real_lstat(path_obj)
            if Path(path_obj) == state_dir:
                return SimpleNamespace(
                    st_mode=real_info.st_mode,
                    st_file_attributes=0x400,
                    st_nlink=1,
                )
            return real_info

        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(Path, "lstat", fake_lstat_dir):
            with self.assertRaises(cb.CloudBridgeError):
                cb._open_lock_file(state_dir / "cloud-publish.lock")

    def test_windows_acl_invoked_on_private_files_and_fails_closed_without_helper(self):
        proxy = _os_proxy_nt()
        calls = []

        def fake_acl(path, create=False):
            calls.append((Path(path), create))

        fresh_home = self.home / "win-fresh"
        fresh_home.mkdir()
        target = fresh_home / "state" / "cloud-runner.json"

        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(cb, "_load_windows_acl", return_value=fake_acl):
            cb._write_private_json(target, {"runner_id": "r-win"})
            # Must NOT touch shared state/ dir DACL; enforces ACL on temp file (create=True)
            self.assertFalse(any(p == fresh_home / "state" for p, _ in calls))
            self.assertTrue(any(p.parent == fresh_home / "state" and p.name.startswith(".cloud-runner.json.") and c is True for p, c in calls))

            calls.clear()
            loaded = cb._read_private_json(target)
            self.assertEqual(loaded, {"runner_id": "r-win"})
            self.assertIn((target, False), calls)

        # P1 regression: missing license.windows_acl on Windows must FAIL CLOSED
        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(cb, "_load_windows_acl", return_value=None):
            with self.assertRaises(cb.CloudBridgeError):
                cb._read_private_json(target)

        # ACL verification failure must also fail closed with CloudBridgeError
        with mock.patch.object(cb, "os", proxy), \
             mock.patch.object(cb, "_load_windows_acl", return_value=mock.Mock(side_effect=ValueError("STORAGE_ERROR"))):
            with self.assertRaises(cb.CloudBridgeError):
                cb._read_private_json(target)

    def test_course_payload_bundles_social_meta_publish_and_rejects_non_loopback_http(self):
        # P0 regression: extracted course payload must import social.meta_publish in isolated python -I
        import base64, gzip, re
        ps1 = (ROOT / "course/install-windows.ps1").read_text(encoding="ascii")
        m = re.search(r"\$CoursePayload='([^']+)'", ps1)
        self.assertIsNotNone(m)
        bundle = json.loads(gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8"))
        for needed in ("cloud_bridge.py", "social/__init__.py", "social/http.py", "social/meta_publish.py"):
            self.assertIn(needed, bundle)
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "lib"
            for name, content in bundle.items():
                dest = (lib.parent / name) if name.startswith("web/") else (lib / name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-I", "-c",
                 f"import sys; sys.path.insert(0, {str(lib)!r}); import cloud_bridge; from social import meta_publish; print('SOCIAL_OK')"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("SOCIAL_OK", proc.stdout)

        # P2 regression: non-loopback http:// rejected, loopback http:// allowed
        with self.assertRaises(cb.CloudBridgeError):
            cb._resolve_endpoints(supabase_url="http://evil.example.com", anon_key="k")
        url_ok, _ = cb._resolve_endpoints(supabase_url="http://127.0.0.1:54321", anon_key="k")
        self.assertEqual(url_ok, "http://127.0.0.1:54321")

        # P2 regression: bogus cloud subcommand with --help returns exit 2
        cli = _load_module("course_ilson_bogus_help", ROOT / "course/ilson.py")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["cloud", "bogus", "--help"])
        self.assertEqual(rc, 2)


class CourseOriginMainUpgradeWithCloudTests(unittest.TestCase):
    def test_42bbfef_install_upgrades_with_cloud_bridge_and_rolls_back_cleanly(self):
        payload = _load_module("course_payload_42bbfef", ROOT / "course/install_payload.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve() / "lib"
            root.mkdir()
            current = sources()
            new_files = ("cloud_bridge.py", "social/__init__.py", "social/http.py", "social/meta_publish.py")
            for nf in new_files:
                self.assertIn(nf, current)
            for name, text in current.items():
                if name in new_files:
                    continue  # did not exist in 42bbfef
                dest = target_path(root, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if name == "ilson.py":
                    dest.write_bytes(subprocess.check_output(["git", "show", "42bbfef:course/ilson.py"], cwd=ROOT))
                elif name == "install_payload.py":
                    dest.write_bytes(subprocess.check_output(["git", "show", "42bbfef:course/install_payload.py"], cwd=ROOT))
                elif name == "license.py":
                    dest.write_bytes(subprocess.check_output(["git", "show", "42bbfef:course/lib/license.py"], cwd=ROOT))
                else:
                    dest.write_text(text, encoding="utf-8")

            old_ilson = (root / "ilson.py").read_bytes()
            backup = payload.install(root, current)
            self.assertIsNotNone(backup)
            for nf in new_files:
                self.assertTrue((root / nf).is_file())
                self.assertEqual((root / nf).read_text(encoding="utf-8"), current[nf])
            self.assertEqual((root / "ilson.py").read_text(encoding="utf-8"), current["ilson.py"])

            payload.rollback(root, backup)
            for nf in new_files:
                self.assertFalse((root / nf).exists())
            self.assertEqual((root / "ilson.py").read_bytes(), old_ilson)


if __name__ == "__main__":
    unittest.main()
