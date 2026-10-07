"""실제 설치/갱신 경로와 예약 실행기의 프롬프트 전달 회귀 시험."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class JobPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-prompt-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.box = self.base / "box"
        shutil.copytree(ROOT / "template", self.box)
        (self.box / "claude").rename(self.box / ".claude")
        (self.box / "state").mkdir()
        (self.box / "state/sandbox").touch()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.capture = self.base / "call.json"
        self.env = dict(os.environ, ILSON_HOME=str(self.box),
                        PATH=str(self.bin) + ":" + os.environ["PATH"])
        self.executable("gtimeout", '#!/bin/sh\nshift 3\nexec "$@"\n')
        # CLI 파서가 프롬프트를 옵션으로 오인하는 조건을 재현한다.
        # LLM/텔레그램/실제 서비스는 호출하지 않는다.
        self.executable("claude", '#!' + sys.executable + '\n' +
                        'import json,sys\nfrom pathlib import Path\n' +
                        'args=sys.argv[1:]\n' +
                        'if any(a.startswith("---") for a in args):\n' +
                        ' print("error: unknown option", file=sys.stderr); sys.exit(1)\n' +
                        'body=sys.stdin.read()\n' +
                        f'Path({str(self.capture)!r}).write_text(json.dumps({{"args":args,"body":body}}))\n' +
                        'print(json.dumps({"is_error":False,"permission_denials":[],"result":"정리 완료"}))\n')

    def executable(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o700)

    def run_job(self, name="tidy"):
        return subprocess.run(["bash", str(self.box / "lib/run-job.sh"), name],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def assert_prompt(self, expected, name="tidy"):
        result = self.run_job(name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        call = json.loads(self.capture.read_text())
        self.assertEqual(call["body"], expected)
        self.assertNotIn(expected.strip(), call["args"])
        self.assertTrue((self.box / f"state/last-run.{name}").exists())

    def test_기본_예약업무의_머리말을_제외하고_본문만_표준입력으로_전달한다(self):
        for name in ("tidy", "briefing", "weekly"):
            with self.subTest(name=name):
                source = (self.box / f".claude/commands/{name}.md").read_text()
                body = source.split("---\n", 2)[2]
                today = subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
                self.assert_prompt(body.replace("$ARGUMENTS", today), name)

    def test_머리말없는_사용자업무와_본문속_구분선을_보존한다(self):
        body = "--본문으로 시작\n\n---\n본문 구분선\n$ARGUMENTS\n"
        (self.box / ".claude/commands/custom.md").write_text(body)
        today = subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
        self.assert_prompt(body.replace("$ARGUMENTS", today), "custom")

    def test_BOM과_CRLF_머리말도_제외한다(self):
        (self.box / ".claude/commands/tidy.md").write_bytes(
            '\ufeff---\r\ndescription: 정리\r\n---\r\n정리 본문\r\n'.encode())
        self.assert_prompt("정리 본문\n")

    def test_닫히지않은_머리말과_빈본문은_모델호출없이_실패한다(self):
        for body in ("---\ndescription: 정리\n", "---\ndescription: 정리\n---\n", "  \n"):
            with self.subTest(body=body):
                (self.box / ".claude/commands/tidy.md").write_text(body)
                result = self.run_job()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.capture.exists())
                self.assertFalse((self.box / "state/last-run.tidy").exists())
                self.assertIn("프롬프트", result.stderr)

    def assert_installed_job(self):
        source = (ROOT / "template/claude/commands/tidy.md").read_text()
        today = subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
        self.assert_prompt(source.split("---\n", 2)[2].replace("$ARGUMENTS", today))
        self.assertEqual((self.box / "vault/company/customer.md").read_bytes(), b"keep customer note\n")
        rules = (self.box / "lib/job-rules.md").read_text()
        for required in ("파일은 Write/Edit 도구로만 저장", "작업 폴더 기준 상대 경로", "파일 읽기·목록 확인은 Read/Glob/Grep 도구로만"):
            self.assertIn(required, rules)


    def test_설치와_재설치후에도_수정된_tidy가_실행된다(self):
        note = self.box / "vault/company/customer.md"
        note.write_bytes(b"keep customer note\n")
        env = dict(self.env, ILSON_SRC=str(ROOT), ILSON_CLI_DIR=str(self.base / "cli"),
                   ILSON_BIN_DIR=str(self.bin))
        for _ in range(2):
            result = subprocess.run(["sh", str(ROOT / "install.sh"), "--sandbox"],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_installed_job()

    def test_업데이트후에도_수정된_tidy가_실행된다(self):
        (self.box / "vault/company/customer.md").write_bytes(b"keep customer note\n")
        # 별도 임시 저장소를 실제 clone하는 업데이트 경로를 통과시킨다.
        repo = self.base / "release"
        repo.mkdir()
        shutil.copytree(ROOT / "template", repo / "template")
        for args in (["init", "-q"], ["add", "template"],
                     ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                      "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        (self.box / "state/pairing.json").write_text(json.dumps({"update_repo":str(repo)}))
        (self.box / "lib/run-job.sh").write_text("exit 99\n")
        result = subprocess.run(["bash", str(self.box / "lib/update.sh")], env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_installed_job()


if __name__ == "__main__":
    unittest.main()
