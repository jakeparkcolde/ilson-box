"""예약 업무 운영 회귀 시험. launchctl·Claude·텔레그램은 모두 가짜로 대체한다."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import test_setup as setup_fixtures

ROOT = Path(__file__).resolve().parents[1]
UID = os.getuid()

# 상태를 기억하는 가짜 launchctl. 호출 기록만 남기고 실제 서비스는 건드리지 않는다.
FAKE_LAUNCHCTL = r'''
calls="$ILSON_HOME/../launchctl.calls"; loaded="$ILSON_HOME/../loaded"; mkdir -p "$loaded"
launchctl() {
    printf '%s\n' "$*" >> "$calls"
    case "$1" in
        print) [ -e "$loaded/${2##*/}" ] ;;
        bootstrap) case "$3" in *"${FAIL_BOOTSTRAP:-no-failure}") return 5 ;; esac
                   touch "$loaded/$(basename "$3" .plist)" ;;
        bootout) [ -n "${STICKY_BOOTOUT:-}" ] && return 0   # 0을 돌려줘도 잠시 목록에 남는 launchd
                 [ -e "$loaded/${2##*/}" ] && rm -f "$loaded/${2##*/}" ;;
        list) printf 'PID\tStatus\tLabel\n'; for f in "$loaded"/*; do [ -e "$f" ] && printf -- '-\t0\t%s\n' "$(basename "$f")"; done; return 0 ;;
        *) return 0 ;;
    esac
}
'''


def today():
    return subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()


class PauseResumeTests(unittest.TestCase):
    def setUp(self):
        self.s = setup_fixtures.SetupTests()
        self.s.setUp()
        self.addCleanup(self.s.doCleanups)
        self.box, self.base = self.s.box, self.s.base
        self.calls = self.base / "launchctl.calls"
        self.agents = self.base / "launchagents"

    def call_log(self):
        return self.calls.read_text() if self.calls.exists() else ""

    def started(self):
        prefix = self.s.prepare_start() + FAKE_LAUNCHCTL
        r = self.s.shell(prefix + "start_jobs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.calls.unlink()
        return prefix

    def test_멈춤은_등록을_내리고_표시하며_start가_다시_등록하지않는다(self):
        prefix = self.started()
        r = self.s.shell(prefix + "pause_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.box / "state"
        self.assertTrue((state / "paused.tidy").exists())
        self.assertFalse((state / "enabled.tidy").exists())
        self.assertIn(f"bootout gui/{UID}/com.ilson.tidy", self.call_log())
        self.assertFalse((self.base / "loaded/com.ilson.tidy").exists())
        # 로그인 때 다시 적재되지 않도록 LaunchAgents 사본도 내린다.
        self.assertFalse((self.agents / "com.ilson.tidy.plist").exists())
        self.assertTrue((self.agents / "com.ilson.briefing.plist").exists())
        self.assertIn("ilson resume tidy", r.stdout)

        self.calls.unlink()
        r = self.s.shell(prefix + "start_jobs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("com.ilson.tidy", self.call_log())
        self.assertFalse((state / "enabled.tidy").exists())
        self.assertFalse((self.agents / "com.ilson.tidy.plist").exists())

    def test_재개는_표시를_지우고_현재설정으로_다시등록한다(self):
        prefix = self.started()
        r = self.s.shell(prefix + "pause_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conf = self.box / "launchd/jobs.conf"
        conf.write_text(conf.read_text().replace("daily 23:30", "daily 22:15"))
        r = self.s.shell(prefix + "resume_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        state = self.box / "state"
        self.assertFalse((state / "paused.tidy").exists())
        self.assertTrue((state / "enabled.tidy").exists())
        self.assertIn(f"bootstrap gui/{UID} {self.agents}/com.ilson.tidy.plist", self.call_log())
        registered = plistlib.loads((self.agents / "com.ilson.tidy.plist").read_bytes())
        self.assertEqual(registered["StartCalendarInterval"], {"Hour": 22, "Minute": 15})

    def test_시작전에도_멈춤을_기록하면_start가_등록하지않는다(self):
        prefix = self.s.prepare_start() + FAKE_LAUNCHCTL
        r = self.s.shell(prefix + "pause_job weekly && start_jobs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.box / "state/paused.weekly").exists())
        self.assertFalse((self.box / "state/enabled.weekly").exists())
        self.assertNotIn("bootstrap gui/" + str(UID) + " " + str(self.agents) + "/com.ilson.weekly.plist", self.call_log())
        self.assertEqual(len(list((self.box / "state").glob("enabled.*"))), 5)

    def test_기본관리업무와_모르는업무는_거절하고_launchctl을_부르지않는다(self):
        prefix = self.s.prepare_start() + FAKE_LAUNCHCTL
        for command in ("pause_job", "resume_job"):
            for job in ("watchdog", "snapshot", "update"):
                with self.subTest(command=command, job=job):
                    r = self.s.shell(prefix + f"{command} {job}")
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("멈출 수 없", r.stdout + r.stderr)
            for job in ("nope", "../state/x", ""):
                with self.subTest(command=command, job=job):
                    r = self.s.shell(prefix + f"{command} '{job}'")
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("jobs.conf", r.stdout + r.stderr)
        self.assertNotIn("bootout", self.call_log())
        self.assertNotIn("bootstrap", self.call_log())
        self.assertEqual(list((self.box / "state").glob("paused.*")), [])
        self.assertFalse((self.box / "x").exists())

    def test_샌드박스는_멈춤재개를_거절한다(self):
        self.s.install()
        for command in ("pause_job", "resume_job"):
            r = self.s.shell(FAKE_LAUNCHCTL + f"{command} tidy")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("샌드박스", r.stdout + r.stderr)
        self.assertEqual(self.call_log(), "")
        self.assertFalse((self.box / "state/paused.tidy").exists())

    def test_사용법과_명령연결에_멈춤재개가_있다(self):
        r = self.s.shell("usage")
        self.assertIn("pause <업무명>", r.stdout)
        self.assertIn("resume <업무명>", r.stdout)
        bin_dir, env = self.s.install()
        # 실제 launchctl 대신 기록용 가짜를 PATH 앞에 둔다. 샌드박스 거절이 먼저여야 한다.
        fake = self.base / "fake-launchctl"
        fake.mkdir()
        (fake / "launchctl").write_text(f'#!/bin/sh\necho "$*" >> "{self.calls}"\nexit 1\n')
        (fake / "launchctl").chmod(0o700)
        env = dict(env, HOME=str(self.base / "home"), PATH=str(fake) + ":" + env["PATH"])
        r = subprocess.run([str(bin_dir / "ilson"), "pause"], env=env, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ilson pause <업무명>", r.stdout + r.stderr)
        for command in ("pause", "resume"):
            r = subprocess.run([str(bin_dir / "ilson"), command, "tidy"], env=env, text=True, capture_output=True, timeout=5)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("샌드박스", r.stdout + r.stderr)
        self.assertEqual(self.call_log(), "")

    def test_점검의_적재기대값은_멈춘업무를_빼고_멈췄는데_적재되면_알린다(self):
        self.s.install()
        (self.box / "state/sandbox").unlink()
        (self.box / "state/setup-pending").unlink()
        (self.box / "state/paused.tidy").touch()
        agents = self.box / "launchd/rendered"
        five = "\\n".join("1 0 com.ilson." + x for x in ("briefing", "weekly", "watchdog", "snapshot", "update"))
        r = self.s.shell(f'LAUNCH_AGENTS="{agents}"; launchctl() {{ printf "{five}\\n"; }}; check_jobs; [ "$FAIL" -eq 0 ]')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("5/5", r.stdout)
        self.assertIn("tidy", r.stdout)
        six = five + "\\n1 0 com.ilson.tidy"
        r = self.s.shell(f'LAUNCH_AGENTS="{agents}"; launchctl() {{ printf "{six}\\n"; }}; check_jobs; [ "$FAIL" -eq 0 ]')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ilson pause tidy", r.stdout)
        # 업무명에 따라 틀리는 조사(을/를)를 명령 뒤에 붙이지 않는다.
        self.assertNotIn("ilson pause tidy 을", r.stdout)
        self.assertNotIn("ilson pause tidy을", r.stdout)

    def test_멈춤표시가_있는데_아직_적재된_업무도_재개하면_내린뒤_다시_등록한다(self):
        prefix = self.started()
        # 예전 멈춤의 bootout이 실패해 표시만 남고 LaunchAgents 사본은 없는 상태.
        (self.agents / "com.ilson.tidy.plist").unlink()
        (self.box / "state/paused.tidy").touch()
        conf = self.box / "launchd/jobs.conf"
        conf.write_text(conf.read_text().replace("daily 23:30", "daily 22:15"))
        r = self.s.shell(prefix + "resume_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = self.call_log()
        bootout, bootstrap = f"bootout gui/{UID}/com.ilson.tidy", f"bootstrap gui/{UID} {self.agents}/com.ilson.tidy.plist"
        self.assertIn(bootout, log)
        self.assertIn(bootstrap, log)
        self.assertLess(log.index(bootout), log.index(bootstrap))
        registered = plistlib.loads((self.agents / "com.ilson.tidy.plist").read_bytes())
        self.assertEqual(registered["StartCalendarInterval"], {"Hour": 22, "Minute": 15})
        self.assertFalse((self.box / "state/paused.tidy").exists())
        self.assertTrue((self.base / "loaded/com.ilson.tidy").exists())

    def test_bootout직후_아직_목록에_남아도_재개는_LaunchAgents_사본을_남긴다(self):
        prefix = self.started()
        (self.agents / "com.ilson.tidy.plist").unlink()
        (self.box / "state/paused.tidy").touch()
        r = self.s.shell(prefix + "STICKY_BOOTOUT=1; resume_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"bootout gui/{UID}/com.ilson.tidy", self.call_log())
        # 다음 로그인 때 다시 적재되도록 사본이 있어야 한다.
        self.assertTrue((self.agents / "com.ilson.tidy.plist").exists())
        self.assertFalse((self.box / "state/paused.tidy").exists())

    def test_등록이_실패하면_복사한_plist를_지우고_멈춤을_유지한다(self):
        prefix = self.s.prepare_start() + FAKE_LAUNCHCTL
        r = self.s.shell(prefix + "FAIL_BOOTSTRAP=com.ilson.weekly.plist; start_jobs")
        self.assertNotEqual(r.returncode, 0)
        # 로그인 때 launchd가 실패한 업무를 몰래 적재하지 않게 사본을 남기지 않는다.
        self.assertFalse((self.agents / "com.ilson.weekly.plist").exists())
        self.assertFalse((self.box / "state/enabled.weekly").exists())
        r = self.s.shell(prefix + "start_jobs && pause_job tidy && FAIL_BOOTSTRAP=com.ilson.tidy.plist && resume_job tidy")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.box / "state/paused.tidy").exists())
        self.assertFalse((self.agents / "com.ilson.tidy.plist").exists())
        self.assertFalse((self.box / "state/enabled.tidy").exists())

    def test_다시_등록한_업무는_켠시각을_새로_재고_이미_적재된_업무는_처음시각을_유지한다(self):
        prefix = self.started()
        state = self.box / "state"
        old = time.time() - 30 * 86400
        for job in ("tidy", "briefing"):
            os.utime(state / f"enabled.{job}", (old, old))
        (state / "last-run.tidy").write_text(f"{int(old)}\n")
        # 로그아웃 등으로 tidy만 내려간 상태에서 start로 다시 등록한다.
        (self.base / "loaded/com.ilson.tidy").unlink()
        r = self.s.shell(prefix + "start_jobs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater((state / "enabled.tidy").stat().st_mtime, time.time() - 120)
        self.assertLess(abs((state / "enabled.briefing").stat().st_mtime - old), 5)

    def test_켜져있는_업무를_재개하면_이미켜짐과_일정변경방법을_알린다(self):
        prefix = self.started()
        r = self.s.shell(prefix + "resume_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("이미 켜져", r.stdout)
        self.assertIn("ilson pause tidy", r.stdout)
        self.assertIn("ilson resume tidy", r.stdout)
        self.assertNotIn("bootout", self.call_log())
        self.assertNotIn("bootstrap", self.call_log())

    def test_설정에서_빠진_업무의_멈춤표시는_재개로_정리하되_이름형식은_검사한다(self):
        prefix = self.started()
        r = self.s.shell(prefix + "pause_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conf = self.box / "launchd/jobs.conf"
        conf.write_text("".join(l for l in conf.read_text().splitlines(True) if not l.startswith("tidy")))
        r = self.s.shell(prefix + "resume_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.box / "state/paused.tidy").exists())
        self.assertIn("jobs.conf", r.stdout)
        self.assertNotIn("bootstrap", self.call_log())
        (self.box / "state/paused.x").touch()
        r = self.s.shell(prefix + "resume_job '../state/paused.x'")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.box / "state/paused.x").exists())

    def test_대문자_업무명은_UTF8_로캘에서도_거절한다(self):
        prefix = self.started()
        r = self.s.shell(prefix + "pause_job tidy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # macOS 기본 파일시스템은 대소문자를 구분하지 않아 paused.Tidy 가 paused.tidy 와 같다.
        self.s.env = dict(self.s.env, LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8")
        for command in ("resume_job", "pause_job"):
            r = self.s.shell(prefix + f"{command} Tidy")
            self.assertNotEqual(r.returncode, 0, command)
            self.assertIn("jobs.conf", r.stdout + r.stderr)
        self.assertTrue((self.box / "state/paused.tidy").exists())


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-watchdog-")
        self.addCleanup(self.temp.cleanup)
        self.box = Path(self.temp.name) / "box"
        shutil.copytree(ROOT / "template/lib", self.box / "lib")
        # Existing watchdog timing tests assume a licensed box.
        (self.box / 'lib/license.py').write_text('import sys\nsys.exit(0)\n')
        (self.box / "state").mkdir()
        self.capture = Path(self.temp.name) / "notify.txt"
        notify = self.box / "lib/notify.sh"
        notify.write_text('#!/bin/bash\n{ printf "ARGS:%s\\n" "$*"; cat; printf "\\n"; } >> "$NOTIFY_CAPTURE"\n')
        notify.chmod(0o700)
        self.env = dict(os.environ, ILSON_HOME=str(self.box), NOTIFY_CAPTURE=str(self.capture))

    def enable(self, job, age=0, last_run=None):
        marker = self.box / f"state/enabled.{job}"
        marker.touch()
        then = time.time() - age
        os.utime(marker, (then, then))
        if last_run is not None:
            (self.box / f"state/last-run.{job}").write_text(f"{int(time.time() - last_run)}\n")

    def run_watchdog(self):
        r = subprocess.run(["bash", str(self.box / "lib/watchdog.sh")], env=self.env,
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.capture.read_text() if self.capture.exists() else ""

    def test_방금_켠_업무는_첫실행전에_실패로_알리지않는다(self):
        for job in ("briefing", "weekly", "tidy", "snapshot"):
            self.enable(job)
        self.assertEqual(self.run_watchdog(), "")
        self.assertEqual(list((self.box / "state").glob("alerted.*")), [])

    def test_이미_켠_박스도_첫예정시각을_놓치기전엔_알리지않고_놓치면_알린다(self):
        # 3일 전 ilson start: 주간 보고는 아직 기한 전, 브리핑은 실제로 놓쳤다.
        self.enable("weekly", age=3 * 86400)
        self.enable("briefing", age=3 * 86400)
        sent = self.run_watchdog()
        self.assertNotIn("weekly", sent)
        self.assertIn("briefing 업무가 26시간 이상", sent)
        # 9일 전에 켜고 한 번도 돌지 않은 주간 보고는 실제 누락이다.
        self.capture.unlink()
        for marker in (self.box / "state").glob("alerted.*"):
            marker.unlink()
        self.enable("weekly", age=9 * 86400)
        self.assertIn("weekly 업무가 192시간 이상", self.run_watchdog())

    def test_다시_켠_업무는_오래된_성공기록으로_바로_알리지않는다(self):
        self.enable("weekly", age=60, last_run=40 * 86400)
        self.assertEqual(self.run_watchdog(), "")

    def test_오래_멈춘_실제업무는_하루한번만_알린다(self):
        self.enable("tidy", age=30 * 86400, last_run=2 * 86400)
        self.assertIn("tidy 업무가 26시간 이상", self.run_watchdog())
        self.capture.unlink()
        self.assertEqual(self.run_watchdog(), "")

    def test_스냅샷_기한은_0시간이_아니라_분으로_알린다(self):
        self.enable("snapshot", age=7200, last_run=7200)
        sent = self.run_watchdog()
        self.assertIn("snapshot 업무가 30분 이상", sent)
        self.assertNotIn("0시간", sent)

    def test_멈춘_업무는_표시가_남아있어도_점검하지않는다(self):
        self.enable("tidy", age=30 * 86400)
        (self.box / "state/paused.tidy").touch()
        self.assertEqual(self.run_watchdog(), "")

    def test_켠표시가_미래면_이번_점검에서_그_업무를_건너뛴다(self):
        # 시계를 뒤로 돌린 직후: 켠 시각을 믿을 수 없으니 이번 회차는 알리지 않는다.
        self.enable("tidy", age=-86400, last_run=30 * 86400)
        self.enable("briefing", age=30 * 86400, last_run=30 * 86400)
        sent = self.run_watchdog()
        self.assertNotIn("tidy", sent)
        self.assertIn("briefing 업무가 26시간 이상", sent)

    def stamp(self, job, text):
        (self.box / f"state/last-run.{job}").write_text(text)

    def test_깨진_성공기록은_0으로_보고_점검을_멈추지않는다(self):
        # set -u 아래에서 'abc'를 산술식에 넣으면 워치독 전체가 멈춘다.
        self.enable("tidy", age=30 * 86400)
        self.stamp("tidy", "abc\n")
        self.enable("briefing", age=30 * 86400, last_run=60)
        sent = self.run_watchdog()
        self.assertIn("tidy 업무가 26시간 이상", sent)
        self.assertNotIn("briefing", sent)

    def test_앞자리가_0인_기록도_10진수로_읽는다(self):
        self.enable("tidy", age=30 * 86400)
        self.stamp("tidy", "0999\n")
        self.enable("briefing", age=30 * 86400)
        self.stamp("briefing", "0" + str(int(time.time()) - 60) + "\n")
        sent = self.run_watchdog()
        self.assertIn("tidy 업무가 26시간 이상", sent)
        self.assertNotIn("briefing", sent)

    def test_미래_성공기록이_알림을_영원히_막지_못한다(self):
        self.enable("tidy", age=30 * 86400)
        self.stamp("tidy", str(int(time.time()) + 10 * 365 * 86400) + "\n")
        self.assertIn("tidy 업무가 26시간 이상", self.run_watchdog())


class RunJobNotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-runjob-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.box = base / "box"
        shutil.copytree(ROOT / "template", self.box)
        # Existing execution tests assume a licensed box.
        (self.box / 'lib/license.py').write_text('import sys\nsys.exit(0)\n')
        (self.box / "claude").rename(self.box / ".claude")
        self.capture = base / "notify.txt"
        notify = self.box / "lib/notify.sh"
        notify.write_text('#!/bin/bash\n{ printf "ARGS:%s\\n" "$*"; cat; printf "\\n--END--\\n"; } >> "$NOTIFY_CAPTURE"\n')
        notify.chmod(0o700)
        self.bin = base / "bin"
        self.bin.mkdir()
        (self.bin / "gtimeout").write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
        (self.bin / "gtimeout").chmod(0o700)
        # 가짜 Claude: 지정한 보고서 파일을 Write 도구처럼 쓰고 JSON 결과만 출력한다.
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nsys.stdin.read()\n"
            "report=os.environ.get('FAKE_REPORT')\n"
            "if report:\n p=Path(report);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(os.environ['FAKE_REPORT_BODY'])\n"
            " os.environ.get('FAKE_REPORT_MODE') and p.chmod(int(os.environ['FAKE_REPORT_MODE'],8))\n"
            "pid=os.environ.get('FAKE_PID_FILE')\n"
            "if pid:\n import time;Path(pid).write_text(str(os.getpid()));time.sleep(30)\n"
            "denied=[{'tool_name':'Bash'}] if os.environ.get('FAKE_DENIED') else []\n"
            "print(json.dumps({'is_error':False,'permission_denials':denied,'result':os.environ.get('FAKE_RESULT','시험 결과')}))\n")
        (self.bin / "claude").chmod(0o700)
        self.env = dict(os.environ, ILSON_HOME=str(self.box), NOTIFY_CAPTURE=str(self.capture),
                        PATH=str(self.bin) + ":" + os.environ["PATH"])

    def run_job(self, name, **fake):
        env = dict(self.env, **fake)
        return subprocess.run(["bash", str(self.box / "lib/run-job.sh"), name], env=env,
                              capture_output=True, text=True, timeout=10)

    def sent(self):
        return self.capture.read_text() if self.capture.exists() else ""

    def test_야간정리_성공은_알리지않고_실패는_알린다(self):
        r = self.run_job("tidy", FAKE_RESULT="정리 완료, 특이사항 없음")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.box / "state/last-run.tidy").exists())
        self.assertEqual(self.sent(), "")
        r = self.run_job("tidy", FAKE_DENIED="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ARGS:tidy --fail", self.sent())

    def test_보고업무와_사용자추가업무의_성공은_계속_알린다(self):
        (self.box / ".claude/commands/custom.md").write_text("사용자 추가 보고 $ARGUMENTS\n")
        for name in ("briefing", "weekly", "custom"):
            with self.subTest(name=name):
                r = self.run_job(name, FAKE_RESULT=f"{name} 결과")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"ARGS:{name}\n{name} 결과", self.sent())

    def test_주간_예약이_정형_보고서를_만든다(self):
        r = self.run_job('weekly')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        reports = list((self.box / 'vault/reports/weekly').glob('*-ilson.md'))
        self.assertEqual(len(reports), 1)
        self.assertIn('이번 주 일손 리포트', reports[0].read_text(encoding='utf-8'))

    def test_저장된_브리핑과_주간보고에_목록용_제목을_붙이고_알림은_그대로다(self):
        date = today()
        body = f"☀️ 시험 회사 아침 브리핑 {date}\n어제 한 일: 기록 없음\n"
        r = self.run_job("briefing", FAKE_REPORT=f"vault/reports/briefing/{date}.md",
                         FAKE_REPORT_BODY=body, FAKE_RESULT=body.strip())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        saved = (self.box / f"vault/reports/briefing/{date}.md").read_text()
        self.assertEqual(saved, f"# {date} 아침 브리핑\n\n" + body)
        message = self.sent().split("ARGS:briefing\n", 1)[1].split("\n--END--", 1)[0]
        self.assertEqual(message.rstrip("\n"), body.strip())
        self.assertNotIn("#", message)

        weekly = f"📋 시험 회사 주간 보고 2026-10-15~{date}\n"
        r = self.run_job("weekly", FAKE_REPORT=f"vault/reports/weekly/{date}.md", FAKE_REPORT_BODY=weekly)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.box / f"vault/reports/weekly/{date}.md").read_text(), f"# {date} 주간 보고\n\n" + weekly)

    def test_이미_제목이있거나_파일이없으면_건드리지않는다(self):
        date = today()
        body = "# 사장님이 고친 제목\n내용\n"
        r = self.run_job("briefing", FAKE_REPORT=f"vault/reports/briefing/{date}.md", FAKE_REPORT_BODY=body)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.box / f"vault/reports/briefing/{date}.md").read_text(), body)
        r = self.run_job("weekly")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.box / f"vault/reports/weekly/{date}.md").exists())

    def test_야간정리는_이상없음_한줄일때만_조용하고_이상보고는_보낸다(self):
        quiet = "정리 완료, 특이사항 없음"
        # 실행기의 조용한 문구는 명령 파일이 지시한 문구와 정확히 같아야 한다.
        self.assertIn(f"`{quiet}`", (ROOT / "template/claude/commands/tidy.md").read_text())
        for result, silent in ((quiet, True), (f"  {quiet}\n\n", True),
                               ("머리말 2개 · 색인 10개\n중복 제목: 거래처.md, 거래처-2.md", False),
                               (f"{quiet}\n빈 파일: memo.md", False), (f"{quiet}.", False)):
            with self.subTest(result=result):
                self.capture.unlink(missing_ok=True)
                r = self.run_job("tidy", FAKE_RESULT=result)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                if silent:
                    self.assertEqual(self.sent(), "")
                else:
                    self.assertIn("ARGS:tidy\n" + result.strip(), self.sent())

    def briefing_file(self, body, mode=None):
        date = today()
        fake = {"FAKE_REPORT": f"vault/reports/briefing/{date}.md", "FAKE_REPORT_BODY": body}
        if mode:
            fake["FAKE_REPORT_MODE"] = mode
        r = self.run_job("briefing", **fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return self.box / f"vault/reports/briefing/{date}.md", date

    def test_보고서_제목은_원래권한을_지키고_웹목록과_같은규칙으로_판단한다(self):
        path, date = self.briefing_file("☀️ 본문\n", mode="640")
        self.assertEqual(path.read_text(), f"# {date} 아침 브리핑\n\n☀️ 본문\n")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        unchanged = ("---\ntitle: 아침\n---\n☀️ 본문\n",          # 머리말
                     "☀️ 본문 요약\n\n# 아침 보고\n내용\n",          # 40줄 안의 제목
                     "﻿# 사장님이 쓴 제목\n내용\n")             # BOM 뒤의 제목
        for body in unchanged:
            with self.subTest(body=body[:12]):
                path, _ = self.briefing_file(body)
                self.assertEqual(path.read_text(), body)
        late = "".join(f"줄 {i}\n" for i in range(45)) + "# 늦은 제목\n"
        path, date = self.briefing_file(late)
        self.assertEqual(path.read_text(), f"# {date} 아침 브리핑\n\n" + late)
        path, date = self.briefing_file("﻿☀️ 본문\n")
        self.assertEqual(path.read_text(), f"# {date} 아침 브리핑\n\n☀️ 본문\n")

    def test_안내한_시험명령은_다른폴더의_Box에서도_그_Box를_쓴다(self):
        rules = (ROOT / "template/CLAUDE.md").read_text()
        command = 'ILSON_HOME="$PWD" bash lib/run-job.sh <업무명>'
        self.assertIn(command, rules)
        home = Path(self.temp.name) / "home"
        home.mkdir()
        env = {k: v for k, v in self.env.items() if k != "ILSON_HOME"}
        env.update(HOME=str(home), BOX=str(self.box), FAKE_RESULT="정리 완료, 특이사항 없음")
        r = subprocess.run(["bash", "-c", 'cd "$BOX" && ' + command.replace("<업무명>", "tidy")],
                           env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.box / "state/last-run.tidy").exists())
        self.assertFalse((home / "ilson").exists())

    def test_업무가_TERM으로_끝나면_claude까지_끝내고_실패알림은_보내지않는다(self):
        import signal
        # GNU timeout처럼 자기 프로세스 묶음을 만들고 받은 신호를 실행 명령에 전달하는 가짜.
        (self.bin / "gtimeout").write_text(
            "#!" + sys.executable + "\nimport os,signal,subprocess,sys\nos.setpgid(0,0)\n"
            "child=subprocess.Popen(sys.argv[4:])\n"
            "signal.signal(signal.SIGTERM,lambda s,f:child.send_signal(s))\n"
            "sys.exit(child.wait())\n")
        pid_file = Path(self.temp.name) / "claude.pid"
        job = subprocess.Popen(["bash", str(self.box / "lib/run-job.sh"), "briefing"],
                               env=dict(self.env, FAKE_PID_FILE=str(pid_file)),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        claude = None
        try:
            for _ in range(100):
                if pid_file.exists() and pid_file.read_text():
                    claude = int(pid_file.read_text())
                    break
                time.sleep(0.05)
            self.assertIsNotNone(claude, "가짜 claude가 시작하지 않았습니다")
            # launchd bootout: 업무 본체에 TERM, 끝나면 그 프로세스 묶음에 남은 것을 정리한다.
            job.send_signal(signal.SIGTERM)
            job.wait(timeout=10)
            try:
                os.killpg(job.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.5)
            alive = True
            try:
                os.kill(claude, 0)
            except ProcessLookupError:
                alive = False
            self.assertFalse(alive, "업무를 내려도 claude가 고아로 남았습니다")
            self.assertEqual(self.sent(), "")
            self.assertFalse((self.box / "state/last-run.briefing").exists())
        finally:
            if claude:
                try:
                    os.kill(claude, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if job.poll() is None:
                job.kill()

    def test_한도도달시_codex로_자동전환하고_비밀stderr는_차단한다(self):
        secret = "SYNTHETIC_CLAUDE_STDERR_SECRET_429"
        codex_secret = "SYNTHETIC_CODEX_STDERR_SECRET_999"
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            f"print('429 Too Many Requests: hit your usage limit {secret}', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport sys\nfrom pathlib import Path\n"
            "prompt = sys.stdin.read()\n"
            f"print('debug {codex_secret}', file=sys.stderr)\n"
            "out_path = sys.argv[sys.argv.index('-o') + 1]\n"
            "Path(out_path).write_text('Codex 자동 전환 브리핑 완료\\n', encoding='utf-8')\n"
            "sys.exit(0)\n"
        )
        (self.bin / "codex").chmod(0o700)

        r = self.run_job("briefing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.box / "state/last-run.briefing").exists())
        sent = self.sent()
        self.assertIn("ARGS:briefing\nCodex 자동 전환 브리핑 완료", sent)
        self.assertNotIn("--fail", sent)

        log_text = (self.box / "logs/briefing.log").read_text(encoding="utf-8")
        self.assertIn("fallback: claude (rate_limit) -> codex", log_text)
        self.assertIn("ok (codex fallback", log_text)

        date = today()
        err_text = (self.box / f"logs/briefing.{date}.err").read_text(encoding="utf-8")
        self.assertEqual(err_text.strip(), "CLI rc=1 reason=rate_limit (stderr suppressed)")
        out_text = (self.box / f"logs/briefing.{date}.out").read_text(encoding="utf-8")
        self.assertIn("Codex 자동 전환 브리핑 완료", out_text)

        for blob in (r.stdout, r.stderr, sent, log_text, err_text, out_text):
            self.assertNotIn(secret, blob)
            self.assertNotIn(codex_secret, blob)

    def test_인증만료시_보조CLI가_없으면_원인과_claude_login_복구안내를_보내고_비밀을_누출하지않는다(self):
        secret = "SYNTHETIC_OAUTH_TOKEN_SECRET_401"
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            f"print('401 Unauthorized: not logged in {secret}', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)

        r = self.run_job("briefing", ILSON_CODEX_FALLBACK="0")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.box / "state/last-run.briefing").exists())

        sent = self.sent()
        self.assertIn("ARGS:briefing --fail", sent)
        self.assertIn("원인: Claude 구독 로그인 세션 만료", sent)
        self.assertIn("복구: 터미널에서 claude login 을 실행한 뒤 다시 확인하세요.", sent)

        date = today()
        err_text = (self.box / f"logs/briefing.{date}.err").read_text(encoding="utf-8")
        self.assertEqual(err_text.strip(), "CLI rc=1 reason=auth_expired (stderr suppressed)")
        out_text = (self.box / f"logs/briefing.{date}.out").read_text(encoding="utf-8")
        self.assertIn("원인: Claude 구독 로그인 세션 만료", out_text)
        self.assertIn("claude login", out_text)

        log_text = (self.box / "logs/briefing.log").read_text(encoding="utf-8")
        self.assertIn("FAILED rc=1 (auth_expired; stderr suppressed)", log_text)
        for blob in (r.stdout, r.stderr, sent, log_text, err_text, out_text):
            self.assertNotIn(secret, blob)

    def test_한도도달후_codex_전환도_실패하면_실패알림에_안내를_포함하고_비밀을_차단한다(self):
        secret1 = "SYNTHETIC_SECRET_CLAUDE_RL"
        secret2 = "SYNTHETIC_SECRET_CODEX_FAIL"
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            f"print('usage limit reached {secret1}', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            f"print('codex error {secret2}', file=sys.stderr)\n"
            "sys.exit(2)\n"
        )
        (self.bin / "codex").chmod(0o700)

        r = self.run_job("briefing")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.box / "state/last-run.briefing").exists())
        sent = self.sent()
        self.assertIn("ARGS:briefing --fail", sent)
        self.assertIn("원인: Claude 구독 사용량 한도 도달", sent)
        self.assertIn("보조 CLI(Codex) 자동 전환도 실패했습니다.", sent)
        log_text = (self.box / "logs/briefing.log").read_text(encoding="utf-8")
        self.assertIn("fallback codex failed (rc=2 reason=cli_error; stderr suppressed)", log_text)
        for blob in (r.stdout, r.stderr, sent, log_text):
            self.assertNotIn(secret1, blob)
            self.assertNotIn(secret2, blob)

    def test_codex_전환은_격리플래그와_vault_경로를_전달하고_학습경계위반과_토큰유출을_차단한다(self):
        import json
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            "print('429 Too Many Requests: usage limit reached', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)

        args_file = Path(self.temp.name) / "codex.args.json"
        stdin_file = Path(self.temp.name) / "codex.stdin.txt"
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport json, os, sys\nfrom pathlib import Path\n"
            "Path(os.environ['CODEX_ARGS_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "Path(os.environ['CODEX_STDIN_FILE']).write_text(sys.stdin.read(), encoding='utf-8')\n"
            "if os.environ.get('CODEX_VIOLATE_LEARNING'):\n"
            "    p = Path(os.environ['ILSON_HOME']) / 'vault/.ilson-learning/tamper.md'\n"
            "    p.parent.mkdir(parents=True, exist_ok=True)\n"
            "    p.write_text('tampered', encoding='utf-8')\n"
            "out_path = sys.argv[sys.argv.index('-o') + 1]\n"
            "Path(out_path).write_text(os.environ.get('CODEX_OUT_BODY', '안전 브리핑 완료\\n'), encoding='utf-8')\n"
            "sys.exit(0)\n"
        )
        (self.bin / "codex").chmod(0o700)

        # 1) 격리 플래그 및 -C $VAULT 확인
        r = self.run_job("briefing", CODEX_ARGS_FILE=str(args_file), CODEX_STDIN_FILE=str(stdin_file))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = json.loads(args_file.read_text(encoding="utf-8"))
        for flag in ("exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                     "--sandbox", "workspace-write", "--skip-git-repo-check", "--color", "never", "-C"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("-C") + 1], str(self.box / "vault"))
        self.assertEqual(argv[-1], "-")
        stdin_text = stdin_file.read_text(encoding="utf-8")
        self.assertIn(".ilson-learning/", stdin_text)
        self.assertIn("lessons/approved-learning.md", stdin_text)

        # 2) 학습 경계 위반 시 결과 차단 + mark_run 금지
        (self.box / "state/last-run.briefing").unlink(missing_ok=True)
        self.capture.unlink(missing_ok=True)
        r_viol = self.run_job("briefing", CODEX_ARGS_FILE=str(args_file), CODEX_STDIN_FILE=str(stdin_file),
                              CODEX_VIOLATE_LEARNING="1", CODEX_OUT_BODY="위반된 출력 본문\n")
        self.assertNotEqual(r_viol.returncode, 0)
        self.assertFalse((self.box / "state/last-run.briefing").exists())
        log_text = (self.box / "logs/briefing.log").read_text(encoding="utf-8")
        self.assertIn("FAILED: codex fallback violated learning boundary", log_text)
        self.assertIn("ARGS:briefing --fail", self.sent())
        self.assertNotIn("위반된 출력 본문", self.sent())

        # 3) 페어링된 텔레그램 봇 토큰이 codex 출력에 포함되면 차단 + 토큰 미노출
        secret_tok = "123456789:FAKE_PAIRING_BOT_TOKEN_XYZ123456"
        (self.box / "state/pairing.json").write_text(
            json.dumps({"telegram_bot_token": secret_tok, "telegram_chat_id": "12345"}),
            encoding="utf-8",
        )
        (self.box / "state/last-run.briefing").unlink(missing_ok=True)
        self.capture.unlink(missing_ok=True)
        r_tok = self.run_job("briefing", CODEX_ARGS_FILE=str(args_file), CODEX_STDIN_FILE=str(stdin_file),
                             CODEX_OUT_BODY=f"누출 테스트 {secret_tok}\n")
        self.assertNotEqual(r_tok.returncode, 0)
        self.assertFalse((self.box / "state/last-run.briefing").exists())
        date = today()
        out_text = (self.box / f"logs/briefing.{date}.out").read_text(encoding="utf-8")
        log_text = (self.box / "logs/briefing.log").read_text(encoding="utf-8")
        self.assertIn("paired secret detected", log_text)
        for blob in (r_tok.stdout, r_tok.stderr, self.sent(), out_text, log_text):
            self.assertNotIn(secret_tok, blob)

    def test_권한거절_JSON과_stderr는_우선분류되어_codex로_전환하지않는다(self):
        codex_called = Path(self.temp.name) / "codex.called"
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport os, sys\nfrom pathlib import Path\n"
            f"Path({str(codex_called)!r}).write_text('called')\n"
            "sys.exit(0)\n"
        )
        (self.bin / "codex").chmod(0o700)

        # Case 1: JSON permission_denials + stderr에 rate_limit 문구가 섞여도 permission_denied 우선
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport json, sys\nsys.stdin.read()\n"
            "print('429 rate limit exceeded', file=sys.stderr)\n"
            "print(json.dumps({'is_error': False, 'permission_denials': [{'tool_name': 'Bash'}], 'result': '429 rate limit'}))\n"
            "sys.exit(0)\n"
        )
        (self.bin / "claude").chmod(0o700)
        r1 = self.run_job("briefing")
        self.assertNotEqual(r1.returncode, 0)
        self.assertFalse(codex_called.exists())
        date = today()
        self.assertEqual(
            (self.box / f"logs/briefing.{date}.err").read_text(encoding="utf-8").strip(),
            "CLI rc=0 reason=permission_denied (stderr suppressed)",
        )

        # Case 2: stderr에 permission_denied + login 문구가 섞여도 permission_denied 우선 (auth_expired 오분류 금지)
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            "print('permission_denied: cannot access login token', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)
        r2 = self.run_job("briefing")
        self.assertEqual(r2.returncode, 1)
        self.assertFalse(codex_called.exists())
        self.assertEqual(
            (self.box / f"logs/briefing.{date}.err").read_text(encoding="utf-8").strip(),
            "CLI rc=1 reason=permission_denied (stderr suppressed)",
        )

    def test_error_max_turns와_일반본문_한도로그인은_codex로_전환하지않는다(self):
        codex_called = Path(self.temp.name) / "codex.called"
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport sys\nfrom pathlib import Path\n"
            f"Path({str(codex_called)!r}).write_text('called')\n"
            "sys.exit(0)\n"
        )
        (self.bin / "codex").chmod(0o700)
        date = today()

        cases = [
            ("max_turns_korean", 0, {"is_error": True, "subtype": "error_max_turns",
                                     "result": "사용량 한도와 로그인 만료 안내 문구 작성 중 최대 턴 도달"}),
            ("bare_korean_words", 1, {"is_error": True, "result": "거래처 결제 한도 및 홈페이지 로그인 개선 보고"}),
            ("non_error_result_ignored", 1, {"is_error": False, "result": "429 usage limit not logged in"}),
        ]
        for label, rc, payload in cases:
            with self.subTest(case=label):
                codex_called.unlink(missing_ok=True)
                (self.bin / "claude").write_text(
                    "#!" + sys.executable + "\nimport json, sys\nsys.stdin.read()\n"
                    f"print(json.dumps({payload!r}, ensure_ascii=False))\n"
                    f"sys.exit({rc})\n"
                )
                (self.bin / "claude").chmod(0o700)
                r = self.run_job("briefing")
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse(codex_called.exists(), f"codex should not run for {label}")
                err_txt = (self.box / f"logs/briefing.{date}.err").read_text(encoding="utf-8").strip()
                self.assertEqual(err_txt, f"CLI rc={rc} reason=cli_error (stderr suppressed)")

    def test_codex_전환중_SIGTERM은_자식을_정리하고_임시파일누수와_실패알림을_남기지않는다(self):
        import signal
        (self.bin / "gtimeout").write_text(
            "#!" + sys.executable + "\nimport os,signal,subprocess,sys\nos.setpgid(0,0)\n"
            "child=subprocess.Popen(sys.argv[4:])\n"
            "signal.signal(signal.SIGTERM,lambda s,f:child.send_signal(s))\n"
            "sys.exit(child.wait())\n"
        )
        (self.bin / "gtimeout").chmod(0o700)
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            "print('429 Too Many Requests: usage limit reached', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)
        codex_pid_file = Path(self.temp.name) / "codex.pid"
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport os, sys, time\nfrom pathlib import Path\n"
            "sys.stdin.read()\n"
            "Path(os.environ['FAKE_CODEX_PID_FILE']).write_text(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        (self.bin / "codex").chmod(0o700)

        job_tmp = Path(self.temp.name) / "job_tmpdir"
        job_tmp.mkdir()
        job = subprocess.Popen(
            ["bash", str(self.box / "lib/run-job.sh"), "briefing"],
            env=dict(self.env, TMPDIR=str(job_tmp), FAKE_CODEX_PID_FILE=str(codex_pid_file)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        codex_pid = None
        try:
            for _ in range(100):
                if codex_pid_file.exists() and codex_pid_file.read_text():
                    codex_pid = int(codex_pid_file.read_text())
                    break
                time.sleep(0.05)
            self.assertIsNotNone(codex_pid, "가짜 codex가 시작하지 않았습니다")
            job.send_signal(signal.SIGTERM)
            job.wait(timeout=10)
            time.sleep(0.3)
            alive = True
            try:
                os.kill(codex_pid, 0)
            except ProcessLookupError:
                alive = False
            self.assertFalse(alive, "SIGTERM 후에도 codex 자식이 살아 있습니다")
            self.assertEqual(list(job_tmp.iterdir()), [], "임시 파일이 정리되지 않았습니다")
            self.assertEqual(self.sent(), "")
            self.assertFalse((self.box / "state/last-run.briefing").exists())
        finally:
            if codex_pid:
                try:
                    os.kill(codex_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if job.poll() is None:
                job.kill()

    def test_하이픈으로_시작하는_업무프롬프트도_codex_stdin으로_안전하게_전달된다(self):
        import json
        (self.box / ".claude/commands/dashjob.md").write_text(
            "--not-a-flag -C /tmp\n실제 하이픈 시작 업무 $ARGUMENTS\n",
            encoding="utf-8",
        )
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            "print('429 usage limit', file=sys.stderr)\n"
            "sys.exit(1)\n"
        )
        (self.bin / "claude").chmod(0o700)
        args_file = Path(self.temp.name) / "dash.args.json"
        stdin_file = Path(self.temp.name) / "dash.stdin.txt"
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport json, os, sys\nfrom pathlib import Path\n"
            "Path(os.environ['CODEX_ARGS_FILE']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "Path(os.environ['CODEX_STDIN_FILE']).write_text(sys.stdin.read(), encoding='utf-8')\n"
            "out_path = sys.argv[sys.argv.index('-o') + 1]\n"
            "Path(out_path).write_text('하이픈 업무 완료\\n', encoding='utf-8')\n"
            "sys.exit(0)\n"
        )
        (self.bin / "codex").chmod(0o700)

        r = self.run_job("dashjob", CODEX_ARGS_FILE=str(args_file), CODEX_STDIN_FILE=str(stdin_file))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = json.loads(args_file.read_text(encoding="utf-8"))
        self.assertNotIn("--not-a-flag", argv)
        self.assertIn("--not-a-flag -C /tmp", stdin_file.read_text(encoding="utf-8"))
        self.assertIn("ARGS:dashjob\n하이픈 업무 완료", self.sent())


class ChatGuidanceTests(unittest.TestCase):
    def test_관리대화는_예약업무_시험을_대화안에서_직접돌리지않는다(self):
        rules = (ROOT / "template/CLAUDE.md").read_text()
        self.assertNotIn("`bash lib/run-job.sh <업무명>`으로 시험할 수 있습니다", rules)
        line = next(l for l in rules.splitlines() if "run-job.sh" in l)
        self.assertIn("별도", line)
        self.assertIn("터미널", line)
        # 나머지 등록 규칙은 유지한다.
        self.assertIn("`.claude/commands/<업무명>.md`와 `launchd/jobs.conf`에 정의하고 `ilson start`로 새 업무를 등록합니다", rules)
        # 기본 경로(~/ilson)가 아닌 Box도 맞게 시험하도록 실제 폴더를 채워 안내한다.
        self.assertIn("실제 Box 폴더", line)

    def test_기본관리업무_다시등록_절차가_ilson의_경로와_이름에_맞다(self):
        rules = (ROOT / "template/CLAUDE.md").read_text()
        line = next(l for l in rules.splitlines() if "launchctl bootout" in l)
        for step in ("ilson start", "launchctl bootout gui/$(id -u)/com.ilson.<업무명>",
                     "cp launchd/rendered/com.ilson.<업무명>.plist ~/Library/LaunchAgents/",
                     "launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ilson.<업무명>.plist",
                     "ilson doctor"):
            self.assertIn(step, line)
        self.assertLess(line.index("launchctl bootout"), line.index("cp launchd/rendered"))
        self.assertLess(line.index("cp launchd/rendered"), line.index("launchctl bootstrap"))
        cli = (ROOT / "ilson").read_text()
        for actual in ('LAUNCH_AGENTS="$HOME/Library/LaunchAgents"', 'local out="$ILSON_HOME/launchd/rendered"',
                       'launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/', 'com.ilson.$job.plist'):
            self.assertIn(actual, cli)

    def test_사용법문서는_화면과_같은_업무이름을_쓴다(self):
        doc = (ROOT / "docs/사용법.md").read_text()
        line = next(l for l in doc.splitlines() if "ilson pause" in l)
        self.assertIn("복구용 기록", line)
        self.assertNotIn("기억 백업", line)
        # 멈춘 회차가 이미 고친 파일은 남을 수 있으므로 '결과가 없다'고 말하지 않는다.
        self.assertIn("알림과 성공 기록은 남지 않습니다(그 사이 고친 파일은 남을 수 있습니다)", line)
        self.assertNotIn("결과는 남지 않습니다", line)
        cli = (ROOT / "ilson").read_text()
        self.assertIn("알림·성공 기록은 남지 않습니다", cli)


class DoctorUpdateFeedTests(unittest.TestCase):
    """doctor는 업데이트 주소가 있는지만 알리고 주소 자체는 출력하지 않는다."""
    ADDRESS = "https://updates.example.invalid/feed/secret-path"

    def setUp(self):
        self.s = setup_fixtures.SetupTests()
        self.s.setUp()
        self.addCleanup(self.s.doCleanups)
        self.cli = self.s.base / "cli"
        (self.cli / "tools").mkdir(parents=True)
        (self.cli / "tools/update.py").write_text("FEED=''\n")
        (self.s.box / ".updates").mkdir(parents=True)
        self.s.env = dict(self.s.env, ILSON_UPDATE_FEED="")

    def check(self):
        r = self.s.shell(f'SELF_DIR="{self.cli}"; check_update_feed; echo "W=$WARN F=$FAIL P=$PASS"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn(self.ADDRESS, r.stdout + r.stderr)
        self.assertNotIn("secret-path", r.stdout + r.stderr)
        return r.stdout

    def test_주소가_없으면_경고만_하고_설정방법을_안내한다(self):
        out = self.check()
        self.assertIn("W=1 F=0 P=0", out)
        self.assertIn("업데이트 주소 없음 — 자동 업데이트를 건너뜁니다. 설치를 도와준 담당자에게 받은 주소로 ilson update --feed <주소> 를 한 번 실행하세요", out)

    def test_기본주소_줄이_있으면_설정됨으로_본다(self):
        (self.cli / "tools/update.py").write_text("FEED=''\nDEFAULT_FEED='https://feed.example/latest-v2.json'\n")
        self.assertIn("W=0 F=0 P=1", self.check())
        (self.cli / "tools/update.py").write_text("FEED=''\nDEFAULT_FEED=''\n")
        self.assertIn("W=1 F=0 P=0", self.check())

    DEFAULT_LINE = "FEED=''\nDEFAULT_FEED='https://feed.example/latest-v2.json'\n"

    def broken_cases(self):
        feed = self.s.box / ".updates/feed"
        target = self.s.base / "elsewhere"
        target.write_text(self.ADDRESS)
        return {
            "link": lambda: feed.symlink_to(target),
            "dangling link": lambda: feed.symlink_to(self.s.base / "missing"),
            "folder": lambda: feed.mkdir(),
            "http": lambda: feed.write_text("http://updates.example.invalid/feed/secret-path\n"),
            "two lines": lambda: feed.write_text(self.ADDRESS + "\n" + self.ADDRESS + "\n"),
            "quote": lambda: feed.write_text("https://updates.example.invalid/secret-path'x\n"),
            "too long": lambda: feed.write_text("https://updates.example.invalid/secret-path" + "a" * 4096),
            "not text": lambda: feed.write_bytes(b"\xff\xfesecret-path\n"),
        }

    def clear_feed(self):
        feed = self.s.box / ".updates/feed"
        if feed.is_dir() and not feed.is_symlink():
            feed.rmdir()
        else:
            feed.unlink(missing_ok=True)

    def test_쓸수없는_주소파일은_기본주소가_있어도_경고한다(self):
        (self.cli / "tools/update.py").write_text(self.DEFAULT_LINE)
        for name, prepare in self.broken_cases().items():
            with self.subTest(case=name):
                self.clear_feed()
                prepare()
                out = self.check()
                self.assertIn("W=1 F=0 P=0", out)
                self.assertIn("업데이트 주소 파일을 쓸 수 없음", out)
                self.assertNotIn("설정됨", out)
        self.clear_feed()

    def test_링크된_업데이트폴더도_경고한다(self):
        (self.cli / "tools/update.py").write_text(self.DEFAULT_LINE)
        elsewhere = self.s.base / "elsewhere-store"
        elsewhere.mkdir()
        (self.s.box / ".updates").rmdir()
        (self.s.box / ".updates").symlink_to(elsewhere)
        for lines in (self.DEFAULT_LINE, f"FEED='{self.ADDRESS}'\n"):
            (self.cli / "tools/update.py").write_text(lines)
            out = self.check()
            self.assertIn("W=1 F=0 P=0", out)
            self.assertIn("실제 폴더로 되돌린 뒤", out)
            self.assertNotIn("지운 뒤", out)

    def test_주소파일_크기_경계는_4096바이트다(self):
        (self.cli / "tools/update.py").write_text(self.DEFAULT_LINE)
        feed = self.s.box / ".updates/feed"
        start = "https://updates.example.invalid/"
        feed.write_text(start + "a" * (4096 - len(start)))
        self.assertEqual(feed.stat().st_size, 4096)
        self.assertIn("W=0 F=0 P=1", self.check())
        feed.write_text(start + "a" * (4097 - len(start)))
        self.assertEqual(feed.stat().st_size, 4097)
        self.assertIn("W=1 F=0 P=0", self.check())

    def test_NUL이_든_주소파일은_언어설정과_상관없이_쓸수없다(self):
        (self.cli / "tools/update.py").write_text(self.DEFAULT_LINE)
        feed = self.s.box / ".updates/feed"
        feed.write_bytes(b"https://updates.example.invalid/a\0b\n")
        for locale in ("C", "ko_KR.UTF-8", "en_US.UTF-8"):
            with self.subTest(locale=locale):
                self.s.env["LC_ALL"] = locale
                self.assertIn("W=1 F=0 P=0", self.check())
        del self.s.env["LC_ALL"]

    def test_올바르거나_비어있는_주소파일은_기본주소와_함께_괜찮다(self):
        (self.cli / "tools/update.py").write_text(self.DEFAULT_LINE)
        feed = self.s.box / ".updates/feed"
        for body in (self.ADDRESS + "\n", "  " + self.ADDRESS + "  \n\n", "", " \n"):
            with self.subTest(body=body):
                feed.write_text(body)
                self.assertIn("W=0 F=0 P=1", self.check())

    def stamped_sources(self):
        return {
            "stamped": lambda: (self.cli / "tools/update.py").write_text(f"FEED='{self.ADDRESS}'\nDEFAULT_FEED='https://feed.example/x'\n"),
            "env": lambda: self.s.env.update(ILSON_UPDATE_FEED=self.ADDRESS),
        }

    def reset_source(self):
        self.clear_feed()
        self.s.env["ILSON_UPDATE_FEED"] = ""
        (self.cli / "tools/update.py").write_text("FEED=''\n")

    def test_링크나_폴더인_주소파일은_찍힌_주소가_있어도_경고한다(self):
        # update.py walks .updates for links on every run, and saves the address into this path after applying.
        cases = self.broken_cases()
        for source, prepare_source in self.stamped_sources().items():
            for name in ("link", "dangling link", "folder"):
                with self.subTest(source=source, case=name):
                    self.reset_source()
                    prepare_source()
                    cases[name]()
                    out = self.check()
                    self.assertIn("W=1 F=0 P=0", out)
                    self.assertIn("업데이트 주소 파일을 쓸 수 없음", out)
        self.reset_source()

    def test_찍힌_주소가_있으면_잘못된_주소_글자는_다음_성공때_새로_쓰인다(self):
        # The stamped address outranks the saved text, and a successful run rewrites it.
        cases = self.broken_cases()
        for source, prepare_source in self.stamped_sources().items():
            for name in ("http", "two lines", "quote", "too long", "not text"):
                with self.subTest(source=source, case=name):
                    self.reset_source()
                    prepare_source()
                    cases[name]()
                    self.assertIn("W=0 F=0 P=1", self.check())
        self.reset_source()

    def test_세가지_출처_중_하나만_있어도_설정됨으로_본다(self):
        feed = self.s.box / ".updates/feed"
        cases = {
            "env": lambda: self.s.env.update(ILSON_UPDATE_FEED=self.ADDRESS),
            "stamped": lambda: (self.cli / "tools/update.py").write_text(f"x=1\nFEED='{self.ADDRESS}'\n"),
            "remembered": lambda: feed.write_text(self.ADDRESS + "\n"),
        }
        for name, prepare in cases.items():
            with self.subTest(source=name):
                self.s.env["ILSON_UPDATE_FEED"] = ""
                (self.cli / "tools/update.py").write_text("FEED=''\n")
                feed.unlink(missing_ok=True)
                prepare()
                self.assertIn("W=0 F=0 P=1", self.check())

    def test_링크이거나_빈_기억파일은_주소로_치지않는다(self):
        feed = self.s.box / ".updates/feed"
        target = self.s.base / "elsewhere"
        target.write_text(self.ADDRESS)
        feed.symlink_to(target)
        self.assertIn("W=1", self.check())
        feed.unlink()
        feed.write_text(" \n")
        self.assertIn("W=1", self.check())

    def test_도움말에_업데이트_주소_옵션이_있다(self):
        r = self.s.shell("usage")
        line = next(l for l in r.stdout.splitlines() if l.strip().startswith("update "))
        self.assertIn("--feed <주소>", line)


if __name__ == "__main__":
    unittest.main()
