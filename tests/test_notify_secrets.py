"""알림 비밀값 회귀 시험. Telegram/Claude 호출 없이 합성 값과 PATH 스텁만 쓴다."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:NOT_A_REAL_BOT_TOKEN_for_tests_only"
CHAT = "-1009876543210"
PRIVATE = "SYNTHETIC_PRIVATE_STDERR_8f2d"
BODY = 'PRIVATE_REPORT_4e7a: 한글 "인용" \\ 경로\n다음 줄\r\n탭\t수직\v끝'

# Observations travel over a test-only socket, never to an on-disk secret capture.
# Deliberately echo sensitive values on BOTH curl streams, even on success.
CURL_STUB = r'''
import json, os, socket, subprocess, sys
from pathlib import Path
pairing = json.loads((Path(os.environ['ILSON_HOME']) / 'state/pairing.json').read_text())
token = pairing['telegram_bot_token']
config = sys.stdin.read()
ps = subprocess.check_output(
    ['/bin/ps', '-ww', '-p', f'{os.getpid()},{os.getppid()}', '-o', 'command='], text=True)
observed = {'argv': sys.argv[1:], 'ps': ps, 'config': config,
            'exported_secret': any(token in value or 'PRIVATE_REPORT_4e7a' in value
                                   for value in os.environ.values())}
with socket.socket(fileno=int(os.environ['NOTIFY_TEST_FD'])) as channel:
    channel.sendall(json.dumps(observed).encode())
print(token + '\n' + config + '\nSYNTHETIC_PRIVATE_STDERR_8f2d', file=sys.stderr)
if 'NOTIFY_LOOPBACK' in os.environ:
    # Only the expected fixed arguments/config may reach real curl. No external
    # network is used, even if notify.sh regresses to URL/body arguments.
    import re
    expected = ['-q', '-fsS', '--max-time', '15', '-X', 'POST', '--config', '-']
    lines = config.splitlines()
    assert sys.argv[1:] == expected
    assert len(lines) == 3
    assert all(re.fullmatch(r'(url|data-urlencode) = "(?:[^"\\\r\n]|\\[\\"nrtv])*"', line)
               for line in lines)
    url = 'https://api.telegram.org/bot' + token + '/sendMessage'
    assert lines[0] == 'url = "' + url + '"'
    local = config.replace(url, os.environ['NOTIFY_LOOPBACK'], 1)
    result = subprocess.run(['/usr/bin/curl', *sys.argv[1:], '--proto', '=http', '--noproxy', '*'],
                            input=local, text=True, timeout=20)
    sys.exit(result.returncode)
print(token + '\n' + config + '\nSYNTHETIC_PRIVATE_RESPONSE_9a3b')
sys.exit(int(os.environ.get('NOTIFY_CURL_RC', '0')))
'''


class NotifySecretsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-notify-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.box = self.base / "box"
        shutil.copytree(ROOT / "template", self.box)
        (self.box / "claude").rename(self.box / ".claude")
        (self.box / "state").mkdir()
        self.pairing = self.box / "state/pairing.json"
        self.pairing.write_text(json.dumps({"telegram_bot_token": TOKEN, "telegram_chat_id": CHAT}))
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.scratch = self.base / "tmp"
        self.scratch.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), ILSON_HOME=str(self.box),
                        TMPDIR=str(self.scratch), PATH=str(self.bin) + ":" + os.environ["PATH"])
        self.executable("curl", "#!" + sys.executable + "\n" + CURL_STUB)

    def executable(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o700)  # Only this test's private temporary directory.

    def run_script(self, script="notify.sh", *, body=BODY, fail=False, **extra):
        receiver, sender = socket.socketpair()
        with receiver, sender:
            env = dict(self.env, NOTIFY_TEST_FD=str(sender.fileno()), **extra)
            args = ["/bin/bash", str(self.box / "lib" / script), "briefing"]
            if fail:
                args.append("--fail")
            result = subprocess.run(args, input=body, text=True, capture_output=True,
                                    env=env, pass_fds=(sender.fileno(),), timeout=25)
            sender.close()
            receiver.settimeout(5)
            chunks = []
            while chunk := receiver.recv(65536):
                chunks.append(chunk)
        observed = json.loads(b"".join(chunks)) if chunks else None
        return result, observed

    def log(self):
        path = self.box / "logs/briefing.log"
        return path.read_text() if path.exists() else ""

    def assert_private(self, result, observed):
        public = result.stdout + result.stderr
        if observed:
            public += json.dumps(observed["argv"]) + observed["ps"]
            self.assertFalse(observed["exported_secret"])
            self.assertIn("--config", observed["argv"])
            self.assertEqual(observed["argv"][0], "-q")
        for path in (self.box / "logs").glob("*"):
            public += path.read_text()
        for secret in (TOKEN, CHAT, "PRIVATE_REPORT_4e7a", PRIVATE, "SYNTHETIC_PRIVATE_RESPONSE_9a3b"):
            self.assertNotIn(secret, public)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(list(self.scratch.iterdir()), [])
        # Exclude only known test inputs: pairing and the deliberately hostile
        # stub source. All other files (including unexpected curl traces) count.
        for path in self.base.rglob("*"):
            if path.is_file() and path != self.pairing and self.bin not in path.parents:
                data = path.read_bytes()
                for secret in (TOKEN, "PRIVATE_REPORT_4e7a", PRIVATE, "SYNTHETIC_PRIVATE_RESPONSE_9a3b"):
                    self.assertNotIn(secret.encode(), data, str(path))

    def test_success_hides_argv_response_stderr_and_leaves_no_temporary_files(self):
        result, observed = self.run_script()
        self.assertEqual(result.returncode, 0)
        self.assertIn("notify sent", self.log())
        self.assert_private(result, observed)

    def test_http_and_transport_failures_keep_exit_one_and_safe_reason(self):
        for code, reason in ((22, "http error"), (6, "transport error"), (60, "transport error")):
            with self.subTest(code=code):
                result, observed = self.run_script(NOTIFY_CURL_RC=str(code))
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{reason}; curl rc={code}", self.log())
                self.assert_private(result, observed)

    def test_timeout_keeps_exit_one_and_safe_reason(self):
        result, observed = self.run_script(NOTIFY_CURL_RC="28")
        self.assertEqual(result.returncode, 1)
        self.assertIn("timeout; curl rc=28", self.log())
        self.assertEqual(observed["argv"][observed["argv"].index("--max-time") + 1], "15")
        self.assert_private(result, observed)

    def test_unpaired_skips_curl_and_does_not_log_message_preview(self):
        for fields in ({}, {"telegram_bot_token": TOKEN}, {"telegram_chat_id": CHAT}):
            with self.subTest(fields=list(fields)):
                self.pairing.write_text(json.dumps(fields))
                result, observed = self.run_script()
                self.assertEqual(result.returncode, 0)
                self.assertIsNone(observed)
                self.assertIn("notify skipped (unpaired)", self.log())
                self.assert_private(result, observed)

    def test_empty_input_still_succeeds_without_curl_or_log(self):
        result, observed = self.run_script(body="\n\n")
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(observed)
        self.assertEqual(self.log(), "")
        self.assert_private(result, observed)

    def test_system_curl_preserves_plaintext_and_blocks_config_injection_and_curlrc(self):
        bodies = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                bodies.append((self.path, parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'SYNTHETIC_PRIVATE_RESPONSE_9a3b')

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # If -q is omitted, even stderr redirection cannot prevent this file.
            trace = self.base / "curl.trace"
            (self.home / ".curlrc").write_text(f'trace-ascii = "{trace}"\n')
            local = f"http://127.0.0.1:{server.server_port}/sendMessage"
            hostile = BODY + '\n"\nurl = "http://127.0.0.1:1/extra"\n# @file & ? = %'
            for body, fail in ((hostile, False), ("x" * 3600, False), (hostile, True)):
                with self.subTest(fail=fail, size=len(body)):
                    result, observed = self.run_script(body=body, fail=fail, NOTIFY_LOOPBACK=local,
                                                       CURL_HOME=str(self.home))
                    self.assertEqual(result.returncode, 0, self.log())
                    expected = body.encode()[:3500].decode()
                    if fail:
                        expected = "⚠️ 예약 업무 실패: briefing\n" + expected
                    self.assertEqual(bodies[-1], ("/sendMessage", {"chat_id": [CHAT], "text": [expected]}))
                    self.assert_private(result, observed)
            self.assertEqual(len(bodies), 3)
            self.assertFalse(trace.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_job_stderr_is_not_saved_or_forwarded_and_exit_codes_are_preserved(self):
        self.executable("gtimeout", '#!/bin/sh\nshift 3\nexec "$@"\n')
        self.executable("claude", "#!" + sys.executable + "\n" + r'''
import json, os, sys
from pathlib import Path
sys.stdin.read()
token = json.loads((Path(os.environ['ILSON_HOME']) / 'state/pairing.json').read_text())['telegram_bot_token']
print(token + ' SYNTHETIC_PRIVATE_STDERR_8f2d', file=sys.stderr)
print(json.dumps({'is_error': False, 'permission_denials': [], 'result': '정상 보고'}))
sys.exit(int(os.environ['NOTIFY_JOB_RC']))
''')
        for paired in (True, False):
            for code in (0, 7, 124, 137):
                with self.subTest(paired=paired, code=code):
                    self.pairing.write_text(json.dumps({"telegram_bot_token": TOKEN,
                                                       "telegram_chat_id": CHAT if paired else ""}))
                    result, observed = self.run_script("run-job.sh", body="", NOTIFY_JOB_RC=str(code))
                    self.assertEqual(result.returncode, code)
                    self.assertEqual(observed is not None, paired)
                    self.assert_private(result, observed)
                    if paired and code:
                        self.assertIn(f"rc={code}", observed["config"])
                        for secret in (PRIVATE, TOKEN):
                            # Token belongs only in the URL, never in the report.
                            self.assertNotIn(secret, observed["config"].splitlines()[-1])
                    if code:
                        reason = "time limit reached" if code in (124, 137) else "command failed"
                        self.assertIn(f"FAILED rc={code} ({reason}; stderr suppressed)", self.log())


if __name__ == "__main__":
    unittest.main()
