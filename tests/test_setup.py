"""새 기기 설치 회귀 시험. 호스트 설정/서비스/계정은 수정하지 않는다."""
import os
from pathlib import Path
import signal
import plistlib
import json
import tarfile
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.box = self.base / "box"
        self.env = dict(os.environ, ILSON_HOME=str(self.box), ILSON_CHECK_TIMEOUT="1")

    def shell(self, script, timeout=5):
        # 기존 v0 함수도 직접 시험하도록 명령 디스패치 이전까지만 읽는다.
        functions = (ROOT / "ilson").read_text().split('cmd="${1:-}"')[0]
        harness = self.base / "harness.sh"
        harness.write_text(functions + "\n" + script)
        proc = subprocess.Popen(["bash", str(harness)], cwd=ROOT, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            self.fail("외부 명령의 시간 제한이 없어 점검이 멈췄다")
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def fake(self, name, body):
        path = self.base / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o700)
        return path

    def test_tailscale_오류문자열을_연결성공으로_세지않는다(self):
        tool = self.fake("tailscale", "echo 'Tailscale is not running'; exit 1")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$PASS" -eq 0 ] && [ "$WARN" -gt 0 ] && [ "$FAIL" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_tailscale_무응답도_시간제한뒤_조회불가로_끝난다(self):
        tool = self.fake("tailscale", "exec sleep 30")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$WARN" -gt 0 ] && [ "$FAIL" -eq 0 ]', timeout=4)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_재설치가_기존_볼트의_자리표시자도_수정하지않는다(self):
        (self.box / "vault").mkdir(parents=True)
        context = self.box / "vault/CONTEXT.md"
        original = "기존 노트 __TODAY__ 그대로 보존\n"
        context.write_text(original)
        r = self.shell(f'TEMPLATE="{ROOT}/template"; SANDBOX=1; init_step_box')
        self.assertEqual(context.read_text(), original, r.stdout + r.stderr)

    def test_정상주소여도_명령실패면_연결성공이_아니다(self):
        tool = self.fake("tailscale", "echo 100.64.1.2; exit 1")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$PASS" -eq 0 ] && [ "$WARN" -eq 1 ] && [ "$FAIL" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_정상주소와_성공종료를_함께_확인한다(self):
        tool = self.fake("tailscale", "echo '{\"BackendState\":\"Running\",\"Self\":{\"Online\":true},\"TailscaleIPs\":[\"100.64.1.2\"]}'")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$PASS" -eq 1 ] && [ "$FAIL" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def install(self):
        bin_dir = self.base / "bin"
        bin_dir.mkdir(exist_ok=True)
        env = dict(self.env, ILSON_SRC=str(ROOT),
                   ILSON_CLI_DIR=str(self.base / "cli"), ILSON_BIN_DIR=str(bin_dir),
                   PATH=str(bin_dir) + ":" + os.environ["PATH"])
        result = subprocess.run(["sh", str(ROOT / "install.sh"), "--sandbox"], env=env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return bin_dir, env

    def test_첫설치가_코드없이_볼트와_예약파일까지_만들되_실행은_안한다(self):
        self.install()
        self.assertTrue((self.box / "vault/CONTEXT.md").is_file())
        self.assertTrue((self.box / "state/setup-pending").is_file())
        self.assertFalse((self.box / "state/pairing.json").exists())
        self.assertEqual(list((self.box / "state").glob("enabled.*")), [])
        rendered = self.box / "launchd/rendered"
        self.assertEqual(len(list(rendered.glob("*.plist"))), 6)
        briefing = plistlib.loads((rendered / "com.ilson.briefing.plist").read_bytes())
        self.assertEqual(briefing["StartCalendarInterval"], {"Hour": 8, "Minute": 0})
        self.assertEqual(briefing["ProgramArguments"][1], str(self.box / "lib/run-job.sh"))
        self.assertFalse(briefing["RunAtLoad"])

    def test_PATH의_심볼릭링크로_재실행해도_템플릿을_찾고_노트와_연결을_보존한다(self):
        bin_dir, env = self.install()
        context = self.box / "vault/CONTEXT.md"
        context.write_text("- 회사명: 시험 회사\n__TODAY__ 기록 보존\n")
        pairing = self.box / "state/pairing.json"
        pairing.write_text(json.dumps({"source": "test-local", "code": "TEST-ONLY"}))
        saved = (context.read_bytes(), pairing.read_bytes())
        r = subprocess.run([str(bin_dir / "ilson"), "setup", "--sandbox"], env=env,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((context.read_bytes(), pairing.read_bytes()), saved)

    def test_샌드박스에서는_start도_실제서비스를_켜지않는다(self):
        bin_dir, env = self.install()
        r = subprocess.run([str(bin_dir / "ilson"), "start"], env=env,
                           capture_output=True, text=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("샌드박스", r.stdout + r.stderr)
        self.assertFalse((self.box / "state/setup-complete").exists())

    def test_로그인실패면_예약업무_시작을_거절한다(self):
        self.box.mkdir()
        (self.box / "CLAUDE.md").write_text("test")
        r = self.shell('claude_logged_in() { return 1; }; start_jobs')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Claude 로그인 확인 실패", r.stdout + r.stderr)
        self.assertFalse((self.box / "state/setup-complete").exists())

    def test_회사정보없으면_인증성공해도_예약업무를_시작하지않는다(self):
        (self.box / "vault").mkdir(parents=True)
        (self.box / "CLAUDE.md").write_text("test")
        (self.box / "vault/CONTEXT.md").write_text("- 회사명: (인터뷰에서 채움)\n")
        r = self.shell('claude_logged_in() { return 0; }; has() { return 0; }; jq() { return 0; }; start_jobs')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("회사 정보가 비어", r.stdout + r.stderr)

    def test_필수도구_설치실패를_완료로_삼키지않는다(self):
        r = self.shell('has() { [ "$1" = brew ]; }; brew() { return 42; }; setup_tools')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("설치 실패", r.stdout)
        self.assertNotIn("도구 설치 확인", r.stdout)

    def test_스냅샷_커밋실패에_성공시각을_찍지않는다(self):
        self.install()
        stamp = self.box / "state/last-run.snapshot"
        stamp.write_text("12345\n")
        fakebin = self.base / "fail-bin"
        fakebin.mkdir()
        git = fakebin / "git"
        git.write_text('#!/bin/sh\ncase " $* " in *" commit "*) exit 42 ;; *" diff "*) exit 1 ;; esac\nexit 0\n')
        git.chmod(0o700)
        env = dict(self.env, PATH=str(fakebin) + ":" + os.environ["PATH"])
        r = subprocess.run(["bash", str(self.box / "lib/snapshot.sh")], env=env,
                           capture_output=True, text=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(stamp.read_text(), "12345\n")

    def prepare_start(self):
        self.install()
        (self.box / "state/sandbox").unlink()
        (self.box / "vault/CONTEXT.md").write_text("- 회사명: 시험 회사\n")
        return (f'TEMPLATE="{ROOT}/template"; LAUNCH_AGENTS="{self.base}/launchagents"; '
                'claude_logged_in() { return 0; }; has() { return 0; }; jq() { return 0; }; ')

    def test_준비확인후_6개_서비스_등록성공때만_가동완료로_기록한다(self):
        prefix = self.prepare_start()
        r = self.shell(prefix + 'launchctl() { [ "$1" != print ]; }; start_jobs')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.box / "state/setup-complete").exists())
        self.assertFalse((self.box / "state/setup-pending").exists())
        self.assertEqual(len(list((self.box / "state").glob("enabled.*"))), 6)

    def test_서비스등록_중간실패는_완료가_아니며_실패업무를_enabled로_기록하지않는다(self):
        prefix = self.prepare_start()
        r = self.shell(prefix + '''launchctl() {
            [ "$1" != print ] || return 1
            case "$*" in *weekly*) return 42 ;; esac
            return 0
        }; start_jobs''')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.box / "state/setup-complete").exists())
        self.assertTrue((self.box / "state/setup-pending").exists())
        self.assertFalse((self.box / "state/enabled.weekly").exists())

    def test_공개소스_다운로드에서_기본구성까지_하나의_설치명령으로_이어진다(self):
        archive = self.base / "source.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in ("ilson", "template", "README.md", "docs"):
                tar.add(ROOT / name, arcname="ilson-box-main/" + name)
        fakebin = self.base / "bin"
        fakebin.mkdir()
        curl = fakebin / "curl"
        log = self.base / "download-url"
        curl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > ' + shlex.quote(str(log)) + '\n'
                        'while [ "$#" -gt 0 ]; do\n'
                        'if [ "$1" = -o ]; then cp ' + shlex.quote(str(archive)) + ' "$2"; exit $?; fi\n'
                        'shift\ndone\nexit 2\n')
        curl.chmod(0o700)
        env = dict(self.env, ILSON_SRC="", ILSON_DIST_BASE="",
                   ILSON_CLI_DIR=str(self.base / "cli"), ILSON_BIN_DIR=str(fakebin),
                   PATH=str(fakebin) + ":" + os.environ["PATH"])
        r = subprocess.run(["sh", str(ROOT / "install.sh"), "--sandbox"], env=env,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("https://codeload.github.com/jakeparkcolde/ilson-box/tar.gz/main", log.read_text())
        self.assertTrue((self.box / "state/setup-pending").exists())
        self.assertTrue((self.box / "vault/CONTEXT.md").exists())


    def test_첫설치_로그인대기는_기본설치를_실패로_종료하지않는다(self):
        tool = self.fake("tailscale", "echo '{\"BackendState\":\"NeedsLogin\"}'")
        r = self.shell(f'TEMPLATE="{ROOT}/template"; TS_BIN="{tool}"; '
                       'setup_tools() { return 0; }; claude_logged_in() { return 1; }; setup')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("로그인 대기", r.stdout)
        self.assertTrue((self.box / "state/setup-pending").exists())

    def test_설정읽기오류_종료0은_미로그인이_아닌_조회불가다(self):
        tool = self.fake("tailscale", "echo 'The Tailscale CLI failed to start: Failed to load preferences.'; exit 0")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 1 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("상태 확인 불가", r.stdout)
        self.assertNotIn("로그인 대기", r.stdout)

    def test_상태별로_다른_안내를_주며_연결변경_명령은_호출하지않는다(self):
        for backend, expected in [("NeedsLogin", "login_pending"),
                                  ("NoState", "initializing"),
                                  ("Starting", "initializing"),
                                  ("NeedsMachineAuth", "approval_pending"),
                                  ("Stopped", "stopped"),
                                  ("FutureState", "unknown")]:
            with self.subTest(backend=backend):
                tool = self.fake("tailscale", '[ "$*" = "status --json" ] || exit 42\n'
                                 + 'printf "%s\\n" ' + shlex.quote(json.dumps({"BackendState": backend})))
                r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$REMOTE_STATE" = {expected} ] && '
                               '[ "$FAIL" -eq 0 ] && [ "$PASS" -eq 0 ] && [ "$WARN" -eq 1 ]')
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_앱동작중이어도_온라인확인전에는_연결성공으로_세지않는다(self):
        for online, addresses in [(False, ["100.64.1.2"]), (True, []), (True, [None]),
                                  (True, ["not-an-ip"]), (True, ["100.999.1.2"])]:
            with self.subTest(online=online, addresses=addresses):
                data = {"BackendState": "Running", "Self": {"Online": online}, "TailscaleIPs": addresses}
                tool = self.fake("tailscale", 'printf "%s\\n" ' + shlex.quote(json.dumps(data)))
                r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$REMOTE_STATE" = connecting ] && [ "$PASS" -eq 0 ]')
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_조회불가여도_기본설치완료와_업무대기는_분리한다(self):
        tool = self.fake("tailscale", "echo 'Failed to load preferences.'; exit 0")
        r = self.shell(f'TEMPLATE="{ROOT}/template"; TS_BIN="{tool}"; '
                       'setup_tools() { return 0; }; claude_logged_in() { return 1; }; setup')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("상태 확인 불가", r.stdout)
        self.assertTrue((self.box / "state/setup-pending").exists())
        self.assertEqual(list((self.box / "state").glob("enabled.*")), [])

    def test_로그인후_재점검은_실제현재상태로_바뀐다(self):
        tool = self.fake("tailscale", "echo '{\"BackendState\":\"NeedsLogin\"}'")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$REMOTE_STATE" = login_pending ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.fake("tailscale", "echo '{\"BackendState\":\"Running\",\"Self\":{\"Online\":true},\"TailscaleIPs\":[\"100.64.1.2\"]}'")
        r = self.shell(f'TS_BIN="{tool}"; check_remote; [ "$REMOTE_STATE" = connected ] && [ "$WARN" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
