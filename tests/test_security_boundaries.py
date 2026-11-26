"""Stage 5 보안 경계 하드닝 회귀 시험:
- job-settings.json 민감 경로 Read 차단 규칙
- search.sh 아웃바운드 DLP 차단 + 예약 업무당 3회 검색 예산 + 심볼릭 링크 거부
- run-job.sh 검색 카운터 주입(임시 파일 누수 0건) + Claude/Codex 출력 시크릿 유출 차단
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class JobSettingsBoundaryTests(unittest.TestCase):
    def test_job_settings_json_valid_and_contains_hardened_read_denies(self) -> None:
        policy_path = ROOT / "template/lib/job-settings.json"
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertTrue(data["disableAllHooks"])
        self.assertEqual(data["permissions"]["defaultMode"], "dontAsk")

        # Existing allow rules preserved
        for expected_allow in (
            "Read",
            "Glob",
            "Grep",
            "Edit(./vault/**)",
            "Write(./vault/**)",
            "WebSearch",
            "WebFetch",
            "Bash(date)",
            "Bash(bash lib/search.sh *)",
        ):
            self.assertIn(expected_allow, data["permissions"]["allow"])

        deny = data["permissions"]["deny"]
        # Existing deny rules preserved + new sensitive host/state/credential Read denies
        for expected_deny in (
            "Read(**/pairing.json)",
            "Read(**/.env*)",
            "Read(./vault/.ilson-learning/**)",
            "Edit(./state/**)",
            "Write(./state/**)",
            "Read(./state/**)",
            "Read(**/.ssh/**)",
            "Read(**/.aws/**)",
            "Read(**/.gnupg/**)",
            "Read(**/.claude.json)",
            "Read(**/.claude/**)",
            "Read(**/.codex/**)",
            "Read(**/id_rsa*)",
            "Read(**/id_ed25519*)",
            "Read(**/*.pem)",
            "Read(**/*.key)",
            "Read(**/*credentials*)",
        ):
            self.assertIn(expected_deny, deny, f"missing deny rule: {expected_deny}")


class SearchEgressHardGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-sec-search-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.box = self.base / "box"
        (self.box / "state").mkdir(parents=True)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.called = self.base / "tvly.calls"
        tvly = self.bin / "tvly"
        tvly.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> {shlex.quote(str(self.called))}\n'
            'printf \'{"results":[{"title":"OK","url":"https://example.com","content":"safe"}]}\\n\'\n',
            encoding="utf-8",
        )
        tvly.chmod(0o700)
        gtimeout = self.bin / "gtimeout"
        gtimeout.write_text('#!/bin/sh\nshift 3\nexec "$@"\n', encoding="utf-8")
        gtimeout.chmod(0o700)
        self.env = dict(
            os.environ,
            ILSON_HOME=str(self.box),
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            ILSON_SEARCH_TIMEOUT="5",
        )

    def run_search(self, query: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(self.env, **extra)
        return subprocess.run(
            ["bash", str(ROOT / "template/lib/search.sh"), query, "general", "week"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_dlp_blocks_secret_and_control_char_queries_without_echo(self) -> None:
        blocked_queries = [
            "check sk-ant-api03-SECRETTOKEN1234567890",
            "key sk-proj_1234567890abcdefghij",
            "token ghp_1234567890abcdefghij123456",
            "pat github_pat_11ABCDEFG_secretvalue",
            "google AIzaSyDummySecretKey1234567890abcd",
            "slack xoxb-1234567890-secret-token",
            "aws AKIAIOSFODNN7EXAMPLE1",
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
            "tg 123456789:ABCDEF_fake_telegram_bot_token_12345",
            "pem -----BEGIN RSA PRIVATE KEY-----",
            "auth Bearer secret_bearer_token_1234567890",
            "line1\nline2",
            "line1\rline2",
            "tab\x07bell",
        ]
        for q in blocked_queries:
            with self.subTest(query=q[:20]):
                self.called.unlink(missing_ok=True)
                r = self.run_search(q)
                self.assertEqual(r.returncode, 2, f"expected exit 2 for {q!r}: {r.stdout} {r.stderr}")
                self.assertFalse(self.called.exists(), f"tvly must not be invoked for {q!r}")
                self.assertIn("검색어에 민감한 인증 정보 형식이 포함되어 외부 검색을 차단했습니다.", r.stderr)
                self.assertEqual(r.stdout, "")
                # Never echo any part of the rejected query or secret
                self.assertNotIn(q, r.stderr)
                for token_piece in ("sk-ant-", "ghp_", "github_pat_", "AIzaSy", "xoxb-", "AKIA", "eyJhbGci", "PRIVATE KEY", "Bearer "):
                    self.assertNotIn(token_piece, r.stderr)

    def test_per_job_search_budget_enforces_max_3_and_rejects_symlink_or_corrupt(self) -> None:
        counter = self.base / "search.cnt"
        counter.write_text("0\n", encoding="utf-8")

        for i in range(1, 4):
            r = self.run_search(f"공개 산업 뉴스 {i}", ILSON_SEARCH_COUNTER_FILE=str(counter))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(counter.read_text(encoding="utf-8").strip(), str(i))

        # 4th call MUST be blocked with exit 2 without invoking tvly
        calls_before = self.called.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls_before), 3)
        r4 = self.run_search("공개 산업 뉴스 4", ILSON_SEARCH_COUNTER_FILE=str(counter))
        self.assertEqual(r4.returncode, 2)
        self.assertIn("예약 업무당 외부 검색은 최대 3회까지 허용됩니다.", r4.stderr)
        self.assertEqual(len(self.called.read_text(encoding="utf-8").splitlines()), 3)

        # Symlinked counter file MUST fail closed with exit 2
        real_cnt = self.base / "real.cnt"
        real_cnt.write_text("0\n", encoding="utf-8")
        sym_cnt = self.base / "sym.cnt"
        sym_cnt.symlink_to(real_cnt)
        r_sym = self.run_search("공개 뉴스", ILSON_SEARCH_COUNTER_FILE=str(sym_cnt))
        self.assertEqual(r_sym.returncode, 2)
        self.assertEqual(len(self.called.read_text(encoding="utf-8").splitlines()), 3)

        # Corrupted / non-numeric counter file MUST fail closed with exit 2
        bad_cnt = self.base / "bad.cnt"
        bad_cnt.write_text("not-a-number\n", encoding="utf-8")
        r_bad = self.run_search("공개 뉴스", ILSON_SEARCH_COUNTER_FILE=str(bad_cnt))
        self.assertEqual(r_bad.returncode, 2)
        self.assertEqual(len(self.called.read_text(encoding="utf-8").splitlines()), 3)

        # Interactive usage (unset ILSON_SEARCH_COUNTER_FILE) remains unrestricted
        self.called.unlink()
        for i in range(4):
            r_int = self.run_search(f"대화형 공개 뉴스 {i}")
            self.assertEqual(r_int.returncode, 0, r_int.stderr)
        self.assertEqual(len(self.called.read_text(encoding="utf-8").splitlines()), 4)


class RunJobSecurityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-sec-runjob-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.box = self.base / "box"
        shutil.copytree(ROOT / "template", self.box)
        (self.box / "lib/license.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (self.box / "claude").rename(self.box / ".claude")
        (self.box / "state").mkdir(exist_ok=True)
        self.capture = self.base / "notify.txt"
        notify = self.box / "lib/notify.sh"
        notify.write_text(
            '#!/bin/bash\n{ printf "ARGS:%s\\n" "$*"; cat; printf "\\n--END--\\n"; } >> "$NOTIFY_CAPTURE"\n',
            encoding="utf-8",
        )
        notify.chmod(0o700)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "gtimeout").write_text('#!/bin/sh\nshift 3\nexec "$@"\n', encoding="utf-8")
        (self.bin / "gtimeout").chmod(0o700)
        (self.bin / "tvly").write_text(
            '#!/bin/sh\nprintf \'{"results":[{"title":"News","url":"https://example.com","content":"ok"}]}\\n\'\n',
            encoding="utf-8",
        )
        (self.bin / "tvly").chmod(0o700)
        self.tmpdir = self.base / "job-tmp"
        self.tmpdir.mkdir()
        self.env = dict(
            os.environ,
            ILSON_HOME=str(self.box),
            NOTIFY_CAPTURE=str(self.capture),
            TMPDIR=str(self.tmpdir),
            PATH=str(self.bin) + ":" + os.environ["PATH"],
        )

    def _run_job(self, name: str = "briefing", **extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(self.env, **extra)
        return subprocess.run(
            ["bash", str(self.box / "lib/run-job.sh"), name],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_run_job_wires_search_counter_enforces_3_limit_and_cleans_tmpdir(self) -> None:
        # Fake claude invokes lib/search.sh 4 times using inherited ILSON_SEARCH_COUNTER_FILE
        probe_out = self.base / "search_rcs.json"
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\n"
            "import json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "sys.stdin.read()\n"
            "cfile = os.environ.get('ILSON_SEARCH_COUNTER_FILE', '')\n"
            "assert cfile and os.path.isfile(cfile) and not os.path.islink(cfile), f'bad counter: {cfile!r}'\n"
            "rcs = []\n"
            "for i in range(4):\n"
            "    p = subprocess.run(['bash', 'lib/search.sh', f'시장 동향 {i}'], capture_output=True, text=True)\n"
            "    rcs.append(p.returncode)\n"
            f"Path({str(probe_out)!r}).write_text(json.dumps({{'cfile': cfile, 'rcs': rcs}}), encoding='utf-8')\n"
            "print(json.dumps({'is_error': False, 'permission_denials': [], 'result': '정상 브리핑 완료'}))\n",
            encoding="utf-8",
        )
        (self.bin / "claude").chmod(0o700)

        r = self._run_job("briefing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        info = json.loads(probe_out.read_text(encoding="utf-8"))
        self.assertEqual(info["rcs"], [0, 0, 0, 2])
        # Zero temp files left behind in TMPDIR!
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertFalse(Path(info["cfile"]).exists())

    def test_claude_primary_output_leaking_secret_is_blocked_without_echo_or_mark_run(self) -> None:
        paired_token = "987654321:FAKE_PAIRED_TOKEN_NEVER_LEAK_999999"
        (self.box / "state/pairing.json").write_text(
            json.dumps({"telegram_bot_token": paired_token, "telegram_chat_id": "-100123456"}),
            encoding="utf-8",
        )
        secrets_to_test = [
            ("paired_telegram", paired_token),
            ("anthropic_key", "sk-ant-api03-LEAKED_ANTHROPIC_KEY_123456"),
            ("aws_key", "AKIAIOSFODNN7EXAMPLE9"),
            ("github_pat", "ghp_1234567890abcdefghijklmnop"),
            ("private_key", "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA"),
            ("jwt", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"),
        ]
        for label, secret in secrets_to_test:
            with self.subTest(case=label):
                self.capture.unlink(missing_ok=True)
                (self.box / "state/last-run.briefing").unlink(missing_ok=True)
                (self.bin / "claude").write_text(
                    "#!" + sys.executable + "\n"
                    "import json, sys\n"
                    "sys.stdin.read()\n"
                    f"print(json.dumps({{'is_error': False, 'permission_denials': [], 'result': '보고서 본문 ' + {secret!r}}}))\n",
                    encoding="utf-8",
                )
                (self.bin / "claude").chmod(0o700)

                r = self._run_job("briefing")
                self.assertNotEqual(r.returncode, 0, f"secret {label} was not blocked!")
                self.assertFalse((self.box / "state/last-run.briefing").exists())
                sent = self.capture.read_text(encoding="utf-8")
                self.assertIn("ARGS:briefing --fail", sent)
                self.assertIn("민감 정보 노출 감지로 보고 전송을 차단했습니다", sent)
                self.assertEqual(list(self.tmpdir.iterdir()), [])

                log_blobs = [r.stdout, r.stderr, sent]
                for p in (self.box / "logs").glob("*"):
                    log_blobs.append(p.read_text(encoding="utf-8"))
                for blob in log_blobs:
                    self.assertNotIn(secret, blob, f"secret {label} leaked into logs/output!")

    def test_codex_fallback_blocks_generic_secret_even_when_unpaired_and_receives_search_counter(self) -> None:
        # Unpaired box: pairing.json absent, codex outputs an Anthropic key
        leaked_key = "sk-ant-api03-CODEX_LEAKED_SECRET_987654"
        seen_cfile = self.base / "codex_cfile.txt"
        (self.bin / "claude").write_text(
            "#!" + sys.executable + "\nimport sys\nsys.stdin.read()\n"
            "print('429 Too Many Requests: usage limit reached', file=sys.stderr)\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        (self.bin / "claude").chmod(0o700)
        (self.bin / "codex").write_text(
            "#!" + sys.executable + "\nimport os, sys\nfrom pathlib import Path\n"
            "sys.stdin.read()\n"
            f"Path({str(seen_cfile)!r}).write_text(os.environ.get('ILSON_SEARCH_COUNTER_FILE', ''), encoding='utf-8')\n"
            "out_path = sys.argv[sys.argv.index('-o') + 1]\n"
            f"Path(out_path).write_text('Codex leaked ' + {leaked_key!r} + '\\n', encoding='utf-8')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        (self.bin / "codex").chmod(0o700)

        r = self._run_job("briefing")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.box / "state/last-run.briefing").exists())
        self.assertTrue(seen_cfile.read_text(encoding="utf-8").strip())
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        sent = self.capture.read_text(encoding="utf-8")
        self.assertIn("ARGS:briefing --fail", sent)
        self.assertIn("민감 정보 노출 감지로 보고 전송을 차단했습니다", sent)
        for p in (self.box / "logs").glob("*"):
            self.assertNotIn(leaked_key, p.read_text(encoding="utf-8"))
        self.assertNotIn(leaked_key, sent)


if __name__ == "__main__":
    unittest.main()
