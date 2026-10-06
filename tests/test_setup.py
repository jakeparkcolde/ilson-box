"""새 기기 설치 회귀 시험. 호스트 설정/서비스/계정은 수정하지 않는다."""
import os
from pathlib import Path
import signal
import plistlib
import json
import tarfile
import shlex
import subprocess
import sys
import shutil
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

    def test_검색스킬과_실행기가_첫설치에_포함된다(self):
        self.install()
        self.assertTrue((self.box / ".claude/skills/ilson-search/SKILL.md").is_file())
        self.assertTrue((self.box / "lib/search.sh").is_file())

    def test_텔레그램_연결도구가_설치되지만_샌드박스는_연결하지않는다(self):
        bin_dir, env = self.install()
        self.assertTrue((self.box / "lib/telegram-setup.py").is_file())
        r = subprocess.run([str(bin_dir / "ilson"), "telegram", "connect"],
                           env=env, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("샌드박스", r.stdout + r.stderr)
        self.assertFalse((self.box / "state/pairing.json").exists())

    def test_텔레그램_명령이_설치된_박스와_조회옵션을_전달한다(self):
        bin_dir, env = self.install()
        module = self.box / "lib/telegram-setup.py"
        module.write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        r = subprocess.run([str(bin_dir / "ilson"), "telegram", "status", "--verify"],
                           env=env, text=True, capture_output=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout), ["status", "--verify", "--home", str(self.box)])

    def test_텔레그램_대화번호만_있으면_설정완료가_아니다(self):
        (self.box / "state").mkdir(parents=True)
        (self.box / "state/pairing.json").write_text(json.dumps({"telegram_chat_id": 123}))
        r = self.shell('telegram_configured')
        self.assertNotEqual(r.returncode, 0)

    def test_텔레그램_선택연결_오류는_기본설치_실패와_구분한다(self):
        r = self.shell('telegram_box() { return 42; }; setup_telegram')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("텔레그램 연결 대기", r.stdout)
        self.assertIn("ilson telegram connect", r.stdout)

    def test_텔레그램에_필요한_Python이_없으면_설치한다(self):
        r = self.shell('''installed=0
has() { [ "$1" != python3 ]; }
brew() { if [ "$*" = 'install python' ]; then installed=1; fi; return 0; }
setup_search_tools() { return 0; }
setup_tools && [ "$installed" = 1 ]
''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_검색도구_없으면_설치하고_있으면_재사용한다(self):
        r = self.shell('''installed=0; calls=0
has() { [ "$1" = uv ] || { [ "$1" = tvly ] && [ "$installed" = 1 ]; }; }
uv() { [ "$*" = "tool install --python 3.12 tavily-cli" ] || return 42; installed=1; calls=$((calls+1)); }
setup_search_tools && setup_search_tools && [ "$calls" = 1 ]
''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_검색도구_설치실패를_완료로_보고하지않는다(self):
        r = self.shell('has() { [ "$1" = uv ]; }; uv() { return 42; }; setup_search_tools')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("설치 실패", r.stdout)

    def search(self, body, *args):
        fakebin = self.base / "search-bin"
        fakebin.mkdir(exist_ok=True)
        tool = fakebin / "tvly"
        tool.write_text("#!/bin/bash\n" + "touch " + shlex.quote(str(self.base / "search-called")) + "\n" + body + "\n")
        tool.chmod(0o700)
        # 호스트 coreutils를 설치하지 않는다. 자식까지 종료하는 시간 제한 대역.
        timer = fakebin / "gtimeout"
        timer.write_text("#!" + sys.executable + "\n" + '''import os, signal, subprocess, sys
assert sys.argv[1:3] == ["-k", "2"]
p = subprocess.Popen(sys.argv[4:], start_new_session=True)
try:
    sys.exit(p.wait(timeout=float(sys.argv[3])))
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    sys.exit(124)
''')
        timer.chmod(0o700)
        return subprocess.run(["bash", str(ROOT / "template/lib/search.sh"), *args],
                              env=dict(self.env, PATH=str(fakebin) + ":" + os.environ["PATH"],
                                       ILSON_SEARCH_TIMEOUT="1"),
                              capture_output=True, text=True, timeout=5)

    def test_검색실패와_잘못된응답은_성공이나_빈결과가_아니다(self):
        for body in ["echo PRIVATE_ERROR >&2; exit 3", "echo 'not json'",
                     "echo '{\"error\":\"PRIVATE_ERROR\"}'", "sleep 20"]:
            with self.subTest(body=body):
                (self.base / "search-called").unlink(missing_ok=True)
                r = self.search(body, "공개 뉴스")
                self.assertTrue((self.base / "search-called").exists())
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")
                self.assertNotIn("PRIVATE_ERROR", r.stderr)

    def test_검색어를_실행하지않고_제한된_결과만_반환한다(self):
        marker = self.base / "injected"
        query = f'뉴스 $(touch {marker})'
        data = {"results": [{"title": "기사", "url": "https://example.com", "content": "본문"}],
                "extra": "PRIVATE_ERROR"}
        r = self.search('[ "$1" = search ] && [ "$2" = ' + shlex.quote(query) + ' ] || exit 42\n'
                        + 'printf "%s\\n" ' + shlex.quote(json.dumps(data)), query)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(r.stdout), {"results": data["results"]})

    def test_검색0건은_유효응답이며_추가옵션은_허용하지않는다(self):
        r = self.search("echo '{\"results\":[]}'", "뉴스")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"results": []})
        (self.base / "search-called").unlink()
        r = self.search("exit 0", "--help")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.base / "search-called").exists())

    def test_일반검색점검은_외부검색을_호출하지않는다(self):
        self.install()
        r = self.shell('has() { return 0; }; check_search; [ "$WARN" -eq 1 ] && [ "$FAIL" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("실제 검색 미확인", r.stdout)

    def test_실제검색점검은_유효한_검색결과가_있어야_통과한다(self):
        self.install()
        (self.box / "state/sandbox").unlink()
        for data, expected in [('{"results":[]}', 1),
                               ('{"results":[{"title":"test"}]}', 0)]:
            with self.subTest(data=data):
                (self.box / "lib/search.sh").write_text('printf "%s\\n" ' + shlex.quote(data))
                r = self.shell('has() { return 0; }; PROBE_SEARCH=1; check_search; '
                               + f'[ "$FAIL" -eq {expected} ]')
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_샌드박스_검색은_외부명령을_실행하지않는다(self):
        (self.box / "state").mkdir(parents=True)
        (self.box / "state/sandbox").touch()
        marker = self.base / "called"
        r = self.search('touch ' + shlex.quote(str(marker)), "뉴스")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(marker.exists())

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

    def test_관리대화는_박스에서_auto로_시작하고_권한우회하지않는다(self):
        self.install()
        (self.box / "state/sandbox").unlink()
        r = self.shell('''claude() {
            [ "$PWD" = "$ILSON_HOME" ] || return 41
            [ "$*" = "--permission-mode auto" ] || return 42
        }; chat_box''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_재설치가_사용자_예약설정을_덮어쓰지않는다(self):
        self.install()
        config = self.box / "launchd/jobs.conf"
        custom = config.read_text() + '\nresearch | run-job.sh | research | daily 07:30\n'
        config.write_text(custom)
        r = self.shell(f'TEMPLATE="{ROOT}/template"; SANDBOX=1; init_step_box')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(config.read_text(), custom)

    def run_job(self, missing_policy=False, denied=False):
        shutil.copytree(ROOT / "template", self.box)
        (self.box / "claude").rename(self.box / ".claude")
        if missing_policy:
            (self.box / "lib/job-settings.json").unlink(missing_ok=True)
        # 알림과 LLM 호출은 모두 가짜 실행기로 대체한다.
        (self.box / "lib/notify.sh").write_text('#!/bin/sh\ncat >/dev/null\n')
        (self.box / "lib/notify.sh").chmod(0o700)
        fakebin = self.base / "job-bin"
        fakebin.mkdir()
        capture = self.base / "claude-call.json"
        claude = fakebin / "claude"
        result = {"is_error": False, "result": "시험 보고서", "permission_denials": []}
        if denied:
            result["permission_denials"] = [{"tool_name": "Bash"}]
        claude.write_text('#!' + sys.executable + '\nimport json,sys\n'
                          + 'from pathlib import Path\nPath(' + repr(str(capture))
                          + ').write_text(json.dumps(sys.argv[1:]))\nprint(' + repr(json.dumps(result)) + ')\n')
        claude.chmod(0o700)
        timer = fakebin / "gtimeout"
        timer.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
        timer.chmod(0o700)
        r = subprocess.run(['bash', str(self.box / 'lib/run-job.sh'), 'briefing'],
                           env=dict(self.env, PATH=str(fakebin) + ':' + os.environ['PATH']),
                           capture_output=True, text=True, timeout=5)
        return r, capture

    def test_예약업무는_사용자와_프로젝트권한을_상속하지않는다(self):
        r, capture = self.run_job()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        args = json.loads(capture.read_text())
        self.assertEqual(args[args.index('--setting-sources') + 1], '')
        self.assertEqual(args[args.index('--permission-mode') + 1], 'dontAsk')
        self.assertEqual(args[args.index('--settings') + 1], str(self.box / 'lib/job-settings.json'))
        self.assertIn('--strict-mcp-config', args)
        self.assertIn('--safe-mode', args)
        self.assertIn('--disable-slash-commands', args)
        self.assertNotIn('--bare', args)  # 구독 로그인 보존
        self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertNotIn('Agent', args[args.index('--tools') + 1].split(','))
        self.assertTrue((self.box / 'state/last-run.briefing').exists())

    def test_예약권한파일_없으면_관리권한으로_대체실행하지않는다(self):
        r, capture = self.run_job(missing_policy=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(capture.exists())
        self.assertFalse((self.box / 'state/last-run.briefing').exists())

    def test_예약도구거절은_종료0이어도_성공으로_기록하지않는다(self):
        r, capture = self.run_job(denied=True)
        self.assertTrue(capture.exists())
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.box / 'state/last-run.briefing').exists())

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
        self.assertIn("ilson telegram connect", r.stdout)
        self.assertFalse((self.box / "state/pairing.json").exists())
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
