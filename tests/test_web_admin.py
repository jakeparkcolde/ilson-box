"""로컬 Box 관리자의 인증·조회 경계. 실제 계정·launchd·LLM은 사용하지 않는다."""
import contextlib
from http.client import HTTPConnection
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("box_web_admin", ROOT / "template/lib/web-admin-server.py")
admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admin)


class BoxFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-admin-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "box"
        self.user_home = Path(self.temp.name) / "user"
        self.user_home.mkdir()
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_urlsafe(24)
        self.now = [1791255600.0]
        self.calls = []
        self.write("state/web-admin/token", self.token, mode=0o600)
        self.write("state/web-admin/instance", self.instance, mode=0o600)
        self.write("web/index.html", "<html><body>일손 관리자</body></html>")
        self.write("web/app.js", "console.log('local only')")
        self.write("web/styles.css", "body{color:#222}")
        self.write("vault/CONTEXT.md", "# 회사\n- 회사명: 시험 회사\n비공개 전체 맥락 문자열\n")
        self.write("vault/journal/private.md", "보여주면 안 되는 일지")
        self.write("vault/reports/briefing/2026-10-06.md", "# 아침 보고\n오늘 할 일입니다.\n")
        self.write("launchd/jobs.conf", "# job | script | args | schedule\nbriefing | run-job.sh | briefing | daily 08:00\nweekly | run-job.sh | weekly | weekly 5 17:00\nwatchdog | watchdog.sh | | every 600\n")
        self.write("state/last-run.briefing", str(int(self.now[0] - 60)))
        self.write("state/setup-complete", "")
        self.write("lib/search.sh", "# 검색 실행기\n")
        self.write(".claude/skills/ilson-search/SKILL.md", "검색 스킬")
        (self.user_home / ".claude.json").write_text(json.dumps({"projects": {str(self.home): {"hasTrustDialogAccepted": True}}, "not_for_web": "계정 설정 원문"}))
        self.probe = admin.Probe(self.home, run=self.run_probe, which=lambda name: "/mock/" + name)
        self.box = admin.Box(self.home, probe=self.probe, user_home=self.user_home, clock=lambda: self.now[0])

    def write(self, path, text, mode=None):
        target = self.home / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if mode is not None:
            target.chmod(mode)
        return target

    def run_probe(self, args):
        self.calls.append(args)
        if args == ["/mock/claude", "auth", "status"]:
            return 0, '{"loggedIn":true,"email":"private@example.com","secret":"NEVER_RETURN_RAW_AUTH"}'
        if args == ["/mock/launchctl", "list"]:
            return 0, "PID\tStatus\tLabel\n-\t0\tcom.ilson.briefing\n42\t0\tcom.other.service\n"
        self.fail("예상하지 않은 명령: " + repr(args))


class 상태조회시험(BoxFixture):
    def test_고정loopback바인드는_역방향DNS를_조회하지않는다(self):
        with patch("socket.getfqdn", side_effect=AssertionError("역방향 DNS를 호출하면 안 됩니다")):
            server = admin.Server(self.box, 0)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        self.assertEqual(server.server_name, "localhost")
        self.assertEqual(server.server_port, server.server_address[1])
        self.assertGreater(server.server_port, 0)

    def test_회사명이비면_다음줄의맥락을_회사명으로_읽지않는다(self):
        self.write("vault/CONTEXT.md", "# 회사\n- 회사명:\n비공개 내부 메모\n")
        result = self.box.overview()
        self.assertEqual(result["box"]["company_name"], "우리 회사")
        self.assertEqual(next(row["state"] for row in result["checks"] if row["id"] == "company"), "attention")
        self.assertNotIn("비공개 내부 메모", json.dumps(result, ensure_ascii=False))

    def test_현재상태와_성공기록을_구분하고_원본맥락은_내보내지_않는다(self):
        result = self.box.overview()
        self.assertEqual(result["box"]["company_name"], "시험 회사")
        self.assertEqual(result["box"]["setup_state"], "ready")
        self.assertFalse(result["box"]["sandbox"])
        checks = {row["id"]: row for row in result["checks"]}
        self.assertEqual(checks["claude"]["state"], "ok")
        self.assertEqual(checks["trust"]["state"], "ok")
        jobs = {row["id"]: row for row in result["jobs"]}
        self.assertEqual(jobs["briefing"]["registration"], "loaded")
        self.assertEqual(jobs["weekly"]["registration"], "not_loaded")
        self.assertEqual(jobs["briefing"]["last_success_state"], "recorded")
        self.assertEqual(jobs["weekly"]["last_success_state"], "missing")
        self.assertTrue(all(row["execution_state"] == "unknown" for row in jobs.values()))
        raw = json.dumps(result, ensure_ascii=False)
        for value in (self.token, "비공개 전체 맥락 문자열", "계정 설정 원문", "NEVER_RETURN_RAW_AUTH", "private@example.com", str(self.home)):
            self.assertNotIn(value, raw)

    def test_계정과_예약조회는_고정명령이며_30초캐시한다(self):
        self.box.overview()
        self.box.overview()
        self.assertEqual(self.calls, [["/mock/claude", "auth", "status"], ["/mock/launchctl", "list"]])
        self.assertNotIn("-p", repr(self.calls))

    def test_조회실패와_등록없음을_혼동하지_않는다(self):
        for value in (None, (1, ""), (0, "format changed"), (0, "PID Status Label\nbroken\n")):
            with self.subTest(value=value):
                probe = admin.Probe(self.home, run=lambda _: value, which=lambda name: "/mock/" + name)
                self.assertIsNone(probe.jobs())
        probe = admin.Probe(self.home, run=lambda _: (0, "PID Status Label\n"), which=lambda name: "/mock/" + name)
        self.assertEqual(probe.jobs(), set())
        self.box.probe = admin.Probe(self.home, run=lambda _: None, which=lambda name: "/mock/" + name)
        result = self.box.overview()
        self.assertEqual(result["checks"][0]["state"], "unknown")
        self.assertTrue(all(job["registration"] == "unknown" for job in result["jobs"]))

    def test_명시적_로그인안됨과_명령실패를_구분한다(self):
        for response, expected in (((1, '{"loggedIn":false}'), "attention"), ((0, '{"loggedIn":true}'), "ok"), ((1, '{"loggedIn":true}'), "unknown"), ((0, '{}'), "unknown"), ((0, 'error raw secret'), "unknown")):
            with self.subTest(response=response):
                probe = admin.Probe(self.home, run=lambda _: response, which=lambda name: "/mock/" + name)
                self.assertEqual(probe.claude()[0], expected)

    def test_샌드박스는_계정과_launchctl을_호출하지_않는다(self):
        self.write("state/sandbox", "")
        result = self.box.overview()
        self.assertTrue(result["box"]["sandbox"])
        self.assertEqual(result["box"]["setup_state"], "pending")
        self.assertEqual(self.calls, [])
        self.assertTrue(all(job["registration"] == "sandbox" for job in result["jobs"]))

    def test_잘못된일정과_중복업무_쉘문자열을_실행하지_않는다(self):
        self.write("launchd/jobs.conf", "briefing | run-job.sh | briefing | daily 08:00\nbriefing | run-job.sh | x | daily 09:00\n../outside | run-job.sh | x | daily 08:00\nx | $(touch nope) | x | daily 08:00\nx | run-job.sh | x | daily 99:99\ncustom | run-job.sh | anything | weekly 1 10:15\n")
        self.write(".claude/commands/custom.md", '---\ndescription: 내 업무 정리\n---\n')
        result = self.box.overview()
        self.assertEqual([row["id"] for row in result["jobs"]], ["briefing", "custom"])
        self.assertEqual(result["jobs"][1]["label"], "내 업무 정리")
        self.assertEqual(result["jobs"][1]["schedule"], "매주 월요일 10:15")
        self.assertIn("일부 예약 설정", result["limitations"][0])
        self.assertFalse((self.home / "nope").exists())

    def test_미래시각과_깨진성공기록은_확인불가이다(self):
        for text in ("not-a-time", str(int(self.now[0] + 3600)), "-1", "0"):
            with self.subTest(text=text):
                self.write("state/last-run.briefing", text)
                row = self.box.overview()["jobs"][0]
                self.assertIsNone(row["last_success_at"])
                self.assertEqual(row["last_success_state"], "unknown")

    def test_텔레그램은_설정과_이전확인시각만_노출한다(self):
        token = "123456789:" + secrets.token_urlsafe(30)
        self.write("state/pairing.json", json.dumps({"telegram_bot_token": token, "telegram_chat_id": -42, "telegram_bot_username": "fixture_bot", "telegram_verified_at": "2026-10-06T10:00:00+09:00", "private_field": "원본 페어링"}))
        result = self.box.overview()
        self.assertEqual(result["telegram"]["state"], "configured")
        self.assertEqual(result["telegram"]["bot_username"], "fixture_bot")
        raw = json.dumps(result, ensure_ascii=False)
        for value in (token, "telegram_chat_id", "원본 페어링"):
            self.assertNotIn(value, raw)
        self.assertIn("별도 확인", next(c["detail"] for c in result["checks"] if c["id"] == "telegram"))

    def test_시작시_토큰권한과_심볼릭링크를_검사한다(self):
        path = self.home / "state/web-admin/token"
        path.chmod(0o644)
        with self.assertRaises(admin.AdminError):
            admin.Box(self.home, user_home=self.user_home)
        path.chmod(0o600)
        outside = Path(self.temp.name) / "outside-token"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaises(admin.AdminError):
            admin.Box(self.home, user_home=self.user_home)

    def test_명령_시간초과는_원문없이_확인불가로_끝난다(self):
        start = time.monotonic()
        result = admin.Probe(self.home).command([sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - start, 5)


class 보고서시험(BoxFixture):
    def test_보고서목록은_경로대신_ID이고_본문은_평문이다(self):
        self.write("vault/reports/pending/draft.md", '# 초안\n<script>alert("x")</script>\n[외부](https://example.com)')
        result = self.box.reports()
        self.assertEqual(len(result["reports"]), 2)
        row = next(row for row in result["reports"] if row["title"] == "초안")
        self.assertRegex(row["id"], r"^[a-f0-9]{32}$")
        self.assertNotIn("path", row)
        detail = self.box.report(row["id"])
        self.assertIn('<script>alert("x")</script>', detail["text"])
        self.assertFalse(detail["truncated"])
        self.assertNotIn(str(self.home), json.dumps(detail))

    def test_비밀값이_보고서에_섞여도_응답에서_가린다(self):
        token = "123456789:" + secrets.token_urlsafe(30)
        self.write("state/pairing.json", json.dumps({"telegram_bot_token": token, "telegram_chat_id": 42}))
        self.write("vault/reports/test.md", "# 비밀이 잘못 섞인 보고\n" + self.token + "\n" + token)
        row = next(row for row in self.box.reports()["reports"] if row["title"].startswith("비밀"))
        body = self.box.report(row["id"])["text"]
        self.assertNotIn(self.token, body)
        self.assertNotIn(token, body)
        self.assertEqual(body.count("[비밀값 숨김]"), 2)

    def test_보고서심볼릭링크_폴더링크_하드링크를_열지_않는다(self):
        secret = Path(self.temp.name) / "outside.md"
        secret.write_text("OUTSIDE_PRIVATE")
        (self.home / "vault/reports/link.md").symlink_to(secret)
        (self.home / "vault/reports/linked-folder").symlink_to(secret.parent)
        os.link(secret, self.home / "vault/reports/hard.md")
        result = self.box.reports()
        self.assertEqual([row["title"] for row in result["reports"]], ["아침 보고"])
        self.assertNotIn("OUTSIDE_PRIVATE", json.dumps(result))

    def test_목록후_파일이링크로바뀌어도_내용을_보여주지_않는다(self):
        row = self.box.reports()["reports"][0]
        original = self.home / "vault/reports/briefing/2026-10-06.md"
        original.unlink()
        original.symlink_to(self.home / "vault/CONTEXT.md")
        with self.assertRaises(admin.AdminError):
            self.box.report(row["id"])

    def test_깊이_개수_본문바이트상한과_잘못된인코딩을_알린다(self):
        for i in range(admin.REPORT_LIMIT + 2):
            self.write(f"vault/reports/copy-{i}.md", f"# 문서 {i}\n본문")
        self.write("vault/reports/a/b/c/d/too-deep.md", "# 너무 깊음")
        self.write("vault/reports/too-big.md", "x" * (admin.REPORT_BYTES + 1))
        (self.home / "vault/reports/binary.md").write_bytes(b'\xff')
        result = self.box.reports()
        self.assertEqual(len(result["reports"]), admin.REPORT_LIMIT)
        self.assertTrue(result["limited"])
        titles = {row["title"] for row in result["reports"]}
        self.assertNotIn("너무 깊음", titles)
        self.assertNotIn("too-big", titles)
        self.assertNotIn("binary", titles)

    def test_임의경로와_알수없는_ID를_거부한다(self):
        for identity in ("../CONTEXT.md", "/state/pairing.json", "%2e%2e", "a" * 32):
            with self.subTest(identity=identity), self.assertRaises(admin.AdminError) as caught:
                self.box.report(identity)
            self.assertEqual(caught.exception.status, 404)


class HTTP시험(BoxFixture):
    def setUp(self):
        super().setUp()
        self.server = admin.Server(self.box, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, path, payload=None, headers=None, raw=None):
        headers = dict(headers or {})
        if payload is not None:
            raw = json.dumps(payload).encode()
            headers.setdefault("Content-Type", "application/json")
        if method == "POST":
            headers.setdefault("Origin", f"http://127.0.0.1:{self.server.server_port}")
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=6)
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            data = response.read()
            body = json.loads(data) if data and response.getheader("Content-Type", "").startswith("application/json") else data
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def login(self):
        status, headers, body = self.request("POST", "/api/session", {"token": self.token})
        self.assertEqual(status, 200, body)
        self.assertNotIn(self.token, json.dumps(body))
        return headers["Set-Cookie"].split(";", 1)[0], headers

    def test_로컬127주소에만_묶고_건강응답엔_신원만_넣는다(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for path in ("/api/health", "/health"):
            status, _, body = self.request("GET", path)
            self.assertEqual((status, body), (200, {"service": "ilson-box-admin", "instance": self.instance}))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request("GET", "/")[0], 200)

    def test_비로그인조회는_계정명령도_실행하지_않는다(self):
        for path in ("/api/session", "/api/overview", "/api/reports", "/api/reports/" + "a" * 32):
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 401)
            self.assertIn("ilson open", body["error"])
            self.assertNotIn("ilson admin open", body["error"])
        self.assertEqual(self.calls, [])

    def test_세션쿠키로만_조회하고_만료_로그아웃을_검사한다(self):
        cookie, headers = self.login()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertNotIn(self.token, headers["Set-Cookie"])
        self.assertEqual(self.request("GET", "/api/session", headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("GET", "/api/overview", headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("POST", "/api/logout", {}, headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("GET", "/api/overview", headers={"Cookie": cookie})[0], 401)
        cookie, _ = self.login()
        self.now[0] += admin.SESSION_SECONDS
        self.assertEqual(self.request("GET", "/api/session", headers={"Cookie": cookie})[0], 401)

    def test_Host_Origin_외부POST를_차단한다(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/api/session", {"token": self.token}, headers=headers)[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Sec-Fetch-Site": "cross-site"})[0], 200)
        cookie, _ = self.login()
        self.assertEqual(self.request("POST", "/api/logout", {}, headers={"Cookie": cookie, "Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/session", headers={"Cookie": cookie})[0], 200)

    def test_토큰을쿼리로받지않고_오입력은_원문없이_실패한다(self):
        for value in ("incorrect-token", "한글 토큰", ["token"], None):
            with self.subTest(value=value):
                status, _, body = self.request("POST", "/api/session", {"token": value})
                self.assertEqual(status, 401)
                self.assertNotIn(self.token, json.dumps(body))
                self.assertIn("ilson open", body["error"])
                self.assertNotIn("ilson admin open", body["error"])
        self.assertEqual(self.request("GET", "/api/overview?token=" + self.token)[0], 404)

    def test_파일탐색과_실행_설정API가_없다(self):
        cookie, _ = self.login()
        for path in ("/state/pairing.json", "/../state/web-admin/token", "/web/../state/web-admin/token", "/%2e%2e/vault/CONTEXT.md", "/api/reports/%2e%2e%2fCONTEXT.md", "/vault/journal/private.md"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path, headers={"Cookie": cookie})
                self.assertEqual(status, 404)
                self.assertNotIn(self.token, json.dumps(body))
        for path in ("/api/exec", "/api/jobs/run", "/api/settings", "/api/reports"):
            self.assertEqual(self.request("POST", path, {}, headers={"Cookie": cookie})[0], 404)
        self.assertEqual(self.calls, [])

    def test_보고서HTML을_실행가능한페이지로_반환하지_않는다(self):
        self.write("vault/reports/html.md", '# 악성 문서\n<script>fetch("https://attacker.example")</script>')
        cookie, _ = self.login()
        status, _, body = self.request("GET", "/api/reports", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        row = next(row for row in body["reports"] if row["title"] == "악성 문서")
        status, headers, body = self.request("GET", "/api/reports/" + row["id"], headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("<script>", body["text"])

    def test_정적파일도_링크를_거부한다(self):
        page = self.home / "web/index.html"
        page.unlink()
        page.symlink_to(self.home / "state/web-admin/token")
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 404)
        self.assertNotIn(self.token, json.dumps(body))

    def test_로그인횟수와_본문크기_JSON을_제한한다(self):
        for _ in range(10):
            self.assertEqual(self.request("POST", "/api/session", {"token": "wrong"})[0], 401)
        status, _, body = self.request("POST", "/api/session", {"token": self.token})
        self.assertEqual(status, 429)
        self.assertIn("ilson open", body["error"])
        self.assertNotIn("ilson admin open", body["error"])
        self.now[0] += 60
        self.assertEqual(self.request("POST", "/api/session", {"token": self.token})[0], 200)
        for raw in (b'{"token":NaN}', b'{"token":1,"token":2}', b'\xff', b'[]'):
            self.assertEqual(self.request("POST", "/api/session", raw=raw, headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/api/session", raw=b'x' * (admin.BODY_LIMIT + 1), headers={"Content-Type": "application/json"})[0], 413)
        self.assertEqual(self.request("POST", "/api/session", raw=b'{}', headers={"Content-Type": "text/plain"})[0], 415)


if __name__ == "__main__":
    unittest.main()
