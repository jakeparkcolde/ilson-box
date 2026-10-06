"""관리 웹 실행기 회귀 시험. 실제 launchd·브라우저·계정은 변경하지 않는다."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("web_admin_launcher", ROOT / "template/lib/web-admin.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)
REAL_AWAIT_HEALTH = admin.await_health
REAL_HEALTH = admin.health


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ilson-admin-launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "box"
        self.user = self.base / "user"
        (self.home / "lib").mkdir(parents=True)
        (self.home / "state").mkdir()
        (self.home / "web").mkdir()
        (self.home / ".git").mkdir()
        (self.home / "lib/web-admin-server.py").write_text("# mock server\n")
        (self.home / "web/index.html").write_text("mock screen")
        self.is_loaded = False
        self.healthy = False
        self.calls = []
        self.foreign = None
        self.boot_fail = False
        self.ready_fail = False
        for patcher in (patch.object(admin.sys, "platform", "darwin"),
                        patch.object(admin.Path, "home", return_value=self.user),
                        patch.object(admin, "run", side_effect=self.run_command),
                        patch.object(admin, "health", side_effect=self.health),
                        patch.object(admin, "await_health", side_effect=self.wait_health)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def result(self, args, code=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args, code, stdout, stderr)

    def run_command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "git":
            return self.result(args)
        if args[:2] == ["/usr/bin/osascript", "-"]:
            return self.result(args)
        if args[:2] == ["/bin/launchctl", "print"]:
            if not self.is_loaded:
                return self.result(args, 113, stderr='Could not find service "com.ilson.admin"')
            arguments = admin.build_plist(self.foreign or self.home, 18794)["ProgramArguments"]
            return self.result(args, stdout="service = {\n\targuments = {\n" +
                               "\n".join("\t\t" + value for value in arguments) + "\n\t}\n}")
        if args[:2] == ["/bin/launchctl", "bootstrap"]:
            if self.boot_fail:
                return self.result(args, 5)
            self.is_loaded = True
            self.healthy = not self.ready_fail
            return self.result(args)
        if args[:2] == ["/bin/launchctl", "bootout"]:
            self.is_loaded = False
            self.healthy = False
            return self.result(args)
        if args[:2] == ["/bin/launchctl", "kickstart"]:
            self.healthy = not self.ready_fail
            return self.result(args)
        self.fail("허용하지 않은 명령: " + repr(args))

    def health(self, port):
        if not self.healthy:
            return None
        return {"service": admin.SERVICE, "instance": admin.identity(self.home)}

    def wait_health(self, port, instance, **kwargs):
        if not admin.ours(self.health(port), instance):
            raise admin.AdminError("모의 서버 응답 없음")

    def main(self, command, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = admin.main([command, "--home", str(self.home), *args])
        token_path = self.home / "state/web-admin/token"
        if token_path.exists():
            self.assertNotIn(token_path.read_text(), output.getvalue())
        return code, output.getvalue()

    def actions(self):
        return [args[1] for args, _ in self.calls if args[0] == "/bin/launchctl" and args[1] != "print"]

    def test_설치와브라우저열기는_건강확인후_토큰을인자에넣지않는다(self):
        code, output = self.main("open")
        self.assertEqual(code, 0, output)
        private = self.home / "state/web-admin"
        token = (private / "token").read_text()
        instance = (private / "instance").read_text()
        self.assertEqual(len(token), 43)
        self.assertEqual(len(instance), 32)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
        for name in ("token", "instance", "config.json", "enabled", "stdout.log", "stderr.log", "launcher.lock"):
            self.assertEqual(stat.S_IMODE((private / name).stat().st_mode), 0o600)
        plist = plistlib.loads(admin.plist_path().read_bytes())
        self.assertNotIn(token, repr(plist))
        self.assertEqual(plist["ProgramArguments"][2:], ["--home", str(self.home), "--port", "18794"])
        browser = [(args, kwargs) for args, kwargs in self.calls if args[0] == "/usr/bin/osascript"]
        self.assertEqual(len(browser), 1)
        self.assertIn("#token=" + token, browser[0][1]["input"])
        for args, _ in self.calls:
            self.assertNotIn(token, repr(args))
        self.assertEqual(self.actions(), ["bootstrap"])

    def test_같은설치재실행은_재시작없이기존토큰과고객설정을보존한다(self):
        self.assertEqual(self.main("install")[0], 0)
        private = self.home / "state/web-admin"
        old = {name: (private / name).read_bytes() for name in ("token", "instance")}
        config = json.loads((private / "config.json").read_text())
        config["customer_note"] = "keep"
        (private / "config.json").write_text(json.dumps(config))
        self.calls.clear()
        self.assertEqual(self.main("install")[0], 0)
        self.assertEqual(self.actions(), [])
        for name, value in old.items():
            self.assertEqual((private / name).read_bytes(), value)
        self.assertEqual(json.loads((private / "config.json").read_text())["customer_note"], "keep")

    def test_UI또는서버파일변경시만_같은Box서비스를재시작한다(self):
        self.assertEqual(self.main("install")[0], 0)
        for file in (self.home / "web/index.html", self.home / "lib/web-admin-server.py"):
            file.write_text(file.read_text() + "changed")
            self.calls.clear()
            self.assertEqual(self.main("install")[0], 0)
            self.assertEqual(self.actions(), ["bootout", "bootstrap"])

    def test_서버가죽었으면_같은구성은kickstart로복구한다(self):
        self.assertEqual(self.main("install")[0], 0)
        self.healthy = False
        self.calls.clear()
        self.assertEqual(self.main("open")[0], 0)
        self.assertEqual(self.actions(), ["kickstart"])

    def test_토큰파일분실로다시생성하면_실행중서버도새토큰을읽게한다(self):
        self.assertEqual(self.main("install")[0], 0)
        (self.home / "state/web-admin/token").unlink()
        self.calls.clear()
        self.assertEqual(self.main("open")[0], 0)
        self.assertEqual(self.actions(), ["bootout", "bootstrap"])

    def test_새포트는저장되고_옵션없는재실행에서도유지된다(self):
        self.assertEqual(self.main("install", "--port", "18795")[0], 0)
        self.calls.clear()
        self.assertEqual(self.main("install")[0], 0)
        self.assertEqual(json.loads((self.home / "state/web-admin/config.json").read_text())["port"], 18795)
        self.assertEqual(self.actions(), [])

    def test_다른home의launchd는수정하거나중지하지않는다(self):
        self.is_loaded = True
        self.foreign = self.base / "another-box"
        for command in ("install", "open", "stop"):
            code, output = self.main(command)
            self.assertEqual(code, 1, output)
        self.assertEqual(self.actions(), [])
        self.assertFalse((self.home / "state/web-admin/token").exists())

    def test_다른instance의포트는강제종료하지않는다(self):
        with patch.object(admin, "health", return_value={"service": admin.SERVICE, "instance": "other"}):
            code, output = self.main("open")
        self.assertEqual(code, 1, output)
        self.assertEqual(self.actions(), [])
        self.assertFalse((self.home / "state/web-admin/token").exists())

    def test_포트의다른HTTP앱도성공으로간주하지않는다(self):
        with patch.object(admin, "health", return_value={"service": "other-app", "instance": "other"}):
            self.assertEqual(self.main("install")[0], 1)
        self.assertEqual(self.actions(), [])

    def test_launchctl상태조회실패면_미등록으로추정하지않는다(self):
        original = self.run_command
        def denied(args, **kwargs):
            if args[:2] == ["/bin/launchctl", "print"]:
                return self.result(args, 1, stderr="permission denied")
            return original(args, **kwargs)
        with patch.object(admin, "run", side_effect=denied):
            self.assertEqual(self.main("install")[0], 1)
        self.assertEqual(self.actions(), [])

    def test_bootstrap실패와응답없는서버는_완료나브라우저열기를보고하지않는다(self):
        for failure in ("boot_fail", "ready_fail"):
            with self.subTest(failure=failure):
                setattr(self, failure, True)
                code, output = self.main("open")
                self.assertEqual(code, 1, output)
                self.assertNotIn("열었습니다", output)
                self.assertNotIn("준비하고", output)
                self.assertFalse(any(args[0] == "/usr/bin/osascript" for args, _ in self.calls))
                self.assertFalse((self.home / "state/web-admin/enabled").exists())
                setattr(self, failure, False)

    def test_부팅중일시적인포트타임아웃은_기한안에다시확인한다(self):
        calls = 0
        def transient(port):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            if calls == 2:
                raise admin.HealthPending("fixture timeout")
            return self.health(port)
        with patch.object(admin, "await_health", side_effect=REAL_AWAIT_HEALTH), \
             patch.object(admin, "health", side_effect=transient), \
             patch.object(admin.time, "sleep"):
            code, output = self.main("install")
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / "state/web-admin/config.json").exists())
        self.assertTrue((self.home / "state/web-admin/enabled").exists())
        self.assertEqual(self.actions(), ["bootstrap"])

    def test_계속타임아웃이면_기한후실패하고_설치완료표시를남기지않는다(self):
        calls = 0
        def transient(port):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            raise admin.HealthPending("fixture timeout")
        with patch.object(admin, "await_health", side_effect=REAL_AWAIT_HEALTH), \
             patch.object(admin, "health", side_effect=transient), \
             patch.object(admin.time, "monotonic", side_effect=[0, 4, 8, 12]), \
             patch.object(admin.time, "sleep"):
            code, output = self.main("install")
        self.assertEqual(code, 1, output)
        self.assertFalse((self.home / "state/web-admin/config.json").exists())
        self.assertFalse((self.home / "state/web-admin/enabled").exists())
        self.assertNotIn("준비하고", output)

    def test_실제접속계층의socket타임아웃만_재시도가능상태로분리한다(self):
        opener = Mock()
        opener.open.side_effect = URLError("fixture timeout")
        with patch.object(admin, "build_opener", return_value=opener), \
             patch.object(admin.socket, "create_connection", side_effect=TimeoutError()):
            with self.assertRaises(admin.HealthPending):
                REAL_HEALTH(18794)

    def test_부팅대기중다른instance응답은_재시도하거나성공으로넘기지않는다(self):
        with patch.object(admin, "await_health", side_effect=REAL_AWAIT_HEALTH), \
             patch.object(admin, "health", side_effect=[None, {"service": admin.SERVICE, "instance": "other"}]) as probe, \
             patch.object(admin.time, "sleep") as sleep:
            self.assertEqual(self.main("install")[0], 1)
        self.assertEqual(probe.call_count, 2)
        sleep.assert_not_called()
        self.assertFalse((self.home / "state/web-admin/enabled").exists())

    def test_sandbox는설치열기중지전에호스트변경을거부한다(self):
        (self.home / "state/sandbox").touch()
        for command in ("install", "open", "stop", "status"):
            self.assertEqual(self.main(command)[0], 1)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.home / "state/web-admin").exists())

    def test_status는파일과launchd를수정하지않는다(self):
        self.assertEqual(self.main("install")[0], 0)
        private = self.home / "state/web-admin"
        before = {p.name: p.read_bytes() for p in private.iterdir()}
        self.calls.clear()
        self.assertEqual(self.main("status")[0], 0)
        self.assertEqual(self.calls, [])
        self.assertEqual({p.name: p.read_bytes() for p in private.iterdir()}, before)

    def test_stop은관리웹만해제하고예약업무와자격정보를남긴다(self):
        self.assertEqual(self.main("install")[0], 0)
        token = (self.home / "state/web-admin/token").read_bytes()
        self.calls.clear()
        self.assertEqual(self.main("stop")[0], 0)
        self.assertEqual(self.actions(), ["bootout"])
        self.assertFalse(admin.plist_path().exists())
        self.assertFalse((self.home / "state/web-admin/enabled").exists())
        self.assertEqual((self.home / "state/web-admin/token").read_bytes(), token)
        self.assertTrue(all("com.ilson.briefing" not in repr(args) for args, _ in self.calls))
        self.assertEqual(self.main("open")[0], 0)

    def test_이미중지한서비스도_enabled표시는지워서업데이트재가동을막는다(self):
        self.assertEqual(self.main("install")[0], 0)
        marker = self.home / "state/web-admin/enabled"
        self.assertTrue(marker.exists())
        self.is_loaded = False
        self.healthy = False
        self.assertEqual(self.main("stop")[0], 0)
        self.assertFalse(marker.exists())
        self.assertTrue((self.home / "state/web-admin/config.json").exists())

    def test_중지실패는_enabled와기존설정을그대로보존한다(self):
        self.assertEqual(self.main("install")[0], 0)
        marker = self.home / "state/web-admin/enabled"
        self.assertTrue(marker.exists())
        original = self.run_command
        def fail_stop(args, **kwargs):
            if args[:2] == ["/bin/launchctl", "bootout"]:
                return self.result(args, 5)
            return original(args, **kwargs)
        with patch.object(admin, "run", side_effect=fail_stop):
            self.assertEqual(self.main("stop")[0], 1)
        self.assertTrue(marker.exists())
        self.assertTrue(admin.plist_path().exists())

    def test_자동실행밖에서관리웹이실행중이면_중지성공으로표시하지않는다(self):
        self.assertEqual(self.main("install")[0], 0)
        self.is_loaded = False
        self.healthy = True
        self.calls.clear()
        code, output = self.main("stop")
        self.assertEqual(code, 1, output)
        self.assertNotIn("중지했습니다", output)
        self.assertEqual(self.actions(), [])

    def test_snapshot제외미확인과기존추적파일은토큰생성전에거부한다(self):
        original = self.run_command
        for defect in ("tracked", "not_ignored"):
            def git_failure(args, **kwargs):
                if args[0] == "git" and args[3] == "ls-files" and defect == "tracked":
                    return self.result(args, stdout="state/web-admin/token\n")
                if args[0] == "git" and args[3] == "check-ignore" and defect == "not_ignored":
                    return self.result(args, 1)
                return original(args, **kwargs)
            with patch.object(admin, "run", side_effect=git_failure):
                self.assertEqual(self.main("install")[0], 1)
            self.assertFalse((self.home / "state/web-admin/token").exists())
        self.assertEqual(self.actions(), [])

    def test_token심볼릭링크와하드링크는대상파일을변경하지않는다(self):
        private = self.home / "state/web-admin"
        private.mkdir()
        victim = self.base / "victim"
        victim.write_text("keep")
        token = private / "token"
        for kind in ("symlink", "hardlink"):
            if kind == "symlink":
                token.symlink_to(victim)
            else:
                os.link(victim, token)
            self.assertEqual(self.main("install")[0], 1)
            self.assertEqual(victim.read_text(), "keep")
            token.unlink()
        self.assertEqual(self.actions(), [])

    def test_관리폴더심볼릭링크는토큰생성전에거부한다(self):
        victim = self.base / "victim-dir"
        victim.mkdir()
        (self.home / "state/web-admin").symlink_to(victim, target_is_directory=True)
        self.assertEqual(self.main("install")[0], 1)
        self.assertEqual(list(victim.iterdir()), [])

    def test_기존다른Boxplist는실행중이아니어도덮어쓰지않는다(self):
        path = admin.plist_path()
        path.parent.mkdir(parents=True)
        original = plistlib.dumps(admin.build_plist(self.base / "other", 18794))
        path.write_bytes(original)
        self.assertEqual(self.main("install")[0], 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.actions(), [])


if __name__ == "__main__":
    unittest.main()
