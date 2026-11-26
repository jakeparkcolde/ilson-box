import datetime as dt
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

import access_policy as ap  # noqa: E402
import cloud_bridge as cb  # noqa: E402

SAMPLE_RAW_CODE = "ILSON-4K7M-92XQ-HR3T-8NPW"
SAMPLE_COMPANY_ID = "11111111-2222-3333-4444-555555555555"
SAMPLE_RUNNER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SAMPLE_EMAIL = "runner-11111111@ilson.invalid"
SAMPLE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.mock_sig_1234567890"
NOW = dt.datetime(2026, 11, 26, 12, 0, 0, tzinfo=dt.timezone.utc)


def _json_resp(status: int, payload):
    if payload is None:
        return status, b""
    return status, json.dumps(payload).encode("utf-8")


class FakeHeadlessCloud:
    """In-memory mock of Supabase PostgREST for headless worker tests."""

    RUNNER_STATE_COLUMNS = frozenset({"company_id", "key", "data", "updated_at"})

    def __init__(self):
        self.calls = []
        self.wiki_jobs = []
        self.research_jobs = []
        self.wiki_table_missing = False
        self.research_table_missing = False
        self.claim_returns_empty = False
        self.mid_flight_status_overrides = {}
        self.on_status_check = None
        self.auth_counter = 0
        self.final_patch_responses = []  # optional queue of (status, body) overrides for PATCH status=eq.running

    def send(self, method, url, headers, body, timeout=30.0):
        parsed_body = json.loads(body.decode("utf-8")) if body else None
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": parsed_body,
            }
        )

        if url.endswith("/rest/v1/rpc/claim_office"):
            return _json_resp(
                200,
                {
                    "ok": True,
                    "runner_id": SAMPLE_RUNNER_ID,
                    "company_id": SAMPLE_COMPANY_ID,
                    "label": "학생 Mac",
                    "email": SAMPLE_EMAIL,
                },
            )
        if "/auth/v1/token?grant_type=password" in url:
            self.auth_counter += 1
            tok = SAMPLE_JWT if self.auth_counter == 1 else f"{SAMPLE_JWT}_refreshed_{self.auth_counter}"
            return _json_resp(200, {"access_token": tok, "token_type": "bearer"})
        if "/rest/v1/runner?id=eq." in url and method == "PATCH":
            return _json_resp(204, None)
        if "/rest/v1/runner_state" in url and method == "POST":
            if not isinstance(parsed_body, dict):
                return _json_resp(400, {"code": "PGRST102", "message": "Invalid runner_state payload"})
            unknown = sorted(set(parsed_body.keys()) - self.RUNNER_STATE_COLUMNS)
            if unknown:
                return _json_resp(
                    400,
                    {
                        "code": "PGRST204",
                        "message": f"Could not find the '{unknown[0]}' column of 'runner_state' in the schema cache",
                    },
                )
            return _json_resp(201, None)

        # wiki_qa_job endpoints
        if "/rest/v1/wiki_qa_job" in url:
            if self.wiki_table_missing:
                return _json_resp(
                    404,
                    {"code": "PGRST205", "message": "Could not find the table 'public.wiki_qa_job'"},
                )
            if method == "GET" and "status=eq.queued" in url:
                queued = [j for j in self.wiki_jobs if j.get("status") == "queued"]
                return _json_resp(200, queued[:1])
            if method == "GET" and "select=id,status" in url:
                for j in self.wiki_jobs:
                    if f"id=eq.{j['id']}" in url:
                        if self.on_status_check:
                            self.on_status_check("wiki_qa_job", j)
                        st = self.mid_flight_status_overrides.get(j["id"], j["status"])
                        return _json_resp(200, [{"id": j["id"], "status": st}])
                return _json_resp(200, [])
            if method == "PATCH" and "status=eq.queued" in url:
                if self.claim_returns_empty:
                    return _json_resp(200, [])
                for j in self.wiki_jobs:
                    if f"id=eq.{j['id']}" in url and j.get("status") == "queued":
                        j.update(parsed_body or {})
                        return _json_resp(200, [dict(j)])
                return _json_resp(200, [])
            if method == "PATCH" and "status=eq.running" in url:
                if self.final_patch_responses:
                    ovr_status, ovr_payload = self.final_patch_responses.pop(0)
                    if 200 <= ovr_status < 300 and ovr_payload != []:
                        for j in self.wiki_jobs:
                            if f"id=eq.{j['id']}" in url and j.get("status") == "running":
                                j.update(parsed_body or {})
                    return _json_resp(ovr_status, ovr_payload)
                prefer = str(headers.get("Prefer") or "")
                for j in self.wiki_jobs:
                    if f"id=eq.{j['id']}" in url and j.get("status") == "running":
                        j.update(parsed_body or {})
                        if "return=representation" in prefer:
                            return _json_resp(200, [dict(j)])
                        return _json_resp(204, None)
                if "return=representation" in prefer:
                    return _json_resp(200, [])
                return _json_resp(204, None)

        # research_job endpoints
        if "/rest/v1/research_job" in url:
            if self.research_table_missing:
                return _json_resp(
                    404,
                    {"code": "PGRST205", "message": "Could not find the table 'public.research_job'"},
                )
            if method == "GET" and "status=eq.queued" in url:
                queued = [j for j in self.research_jobs if j.get("status") == "queued"]
                return _json_resp(200, queued[:1])
            if method == "GET" and "select=id,status" in url:
                for j in self.research_jobs:
                    if f"id=eq.{j['id']}" in url:
                        st = self.mid_flight_status_overrides.get(j["id"], j["status"])
                        return _json_resp(200, [{"id": j["id"], "status": st}])
                return _json_resp(200, [])
            if method == "PATCH" and "status=eq.queued" in url:
                if self.claim_returns_empty:
                    return _json_resp(200, [])
                for j in self.research_jobs:
                    if f"id=eq.{j['id']}" in url and j.get("status") == "queued":
                        j.update(parsed_body or {})
                        return _json_resp(200, [dict(j)])
                return _json_resp(200, [])
            if method == "PATCH" and "status=eq.running" in url:
                if self.final_patch_responses:
                    ovr_status, ovr_payload = self.final_patch_responses.pop(0)
                    if 200 <= ovr_status < 300 and ovr_payload != []:
                        for j in self.research_jobs:
                            if f"id=eq.{j['id']}" in url and j.get("status") == "running":
                                j.update(parsed_body or {})
                    return _json_resp(ovr_status, ovr_payload)
                prefer = str(headers.get("Prefer") or "")
                for j in self.research_jobs:
                    if f"id=eq.{j['id']}" in url and j.get("status") == "running":
                        j.update(parsed_body or {})
                        if "return=representation" in prefer:
                            return _json_resp(200, [dict(j)])
                        return _json_resp(204, None)
                if "return=representation" in prefer:
                    return _json_resp(200, [])
                return _json_resp(204, None)

        return _json_resp(404, {"error": f"unhandled {method} {url}"})


class HeadlessCapsHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeHeadlessCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_publish_headless_caps_exact_payload_and_capabilities(self):
        with mock.patch.object(
            cb,
            "_find_cli_binary",
            side_effect=lambda name, **kw: f"/opt/homebrew/bin/{name}" if name in ("claude", "codex") else None,
        ):
            res = cb.publish_headless_caps(
                self.cfg,
                SAMPLE_JWT,
                host_label="student-macbook",
                http_send=self.cloud.send,
                now=NOW,
            )

        self.assertTrue(res["ok"])
        self.assertEqual(res["key"], "research_runner_caps_v1")
        self.assertEqual(len(self.cloud.calls), 1)
        call = self.cloud.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/rest/v1/runner_state?on_conflict=company_id,key"))
        self.assertEqual(call["headers"]["Prefer"], "resolution=merge-duplicates,return=minimal")
        row = call["body"]
        self.assertEqual(set(row.keys()), {"company_id", "key", "data", "updated_at"})
        self.assertNotIn("value", row)
        self.assertEqual(row["company_id"], SAMPLE_COMPANY_ID)
        self.assertEqual(row["key"], "research_runner_caps_v1")
        self.assertEqual(row["updated_at"], "2026-11-26T12:00:00Z")
        data = row["data"]
        self.assertTrue(data["online"])
        self.assertEqual(data["host"], "student-macbook")
        self.assertEqual(data["label"], "student-macbook")
        self.assertEqual(data["providers"], ["claude", "codex"])
        self.assertEqual(data["capabilities"], ["research", "wiki_qa"])
        self.assertEqual(data["updated_at"], "2026-11-26T12:00:00Z")
        self.assertEqual(data["last_seen"], "2026-11-26T12:00:00Z")
        self.assertEqual(data["agent_version"], cb.AGENT_VERSION)
        self.assertEqual(data["provider_health"], {"claude": {"status": "ok"}, "codex": {"status": "ok"}})

    def test_runner_state_strict_mock_rejects_value_column_with_pgrst204(self):
        status, raw = self.cloud.send(
            "POST",
            f"{self.cfg['supabase_url']}/rest/v1/runner_state?on_conflict=company_id,key",
            {},
            json.dumps({"company_id": SAMPLE_COMPANY_ID, "key": "k", "value": {}, "updated_at": "2026-11-26T12:00:00Z"}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw.decode("utf-8"))["code"], "PGRST204")

    def test_detect_headless_providers_omits_missing_cli_from_provider_health(self):
        with mock.patch.object(
            cb,
            "_find_cli_binary",
            side_effect=lambda name, **kw: "/opt/homebrew/bin/claude" if name == "claude" else None,
        ):
            providers, health = cb.detect_headless_providers(
                health_overrides={
                    "claude": {
                        "status": "cooldown",
                        "category": "rate_limit",
                        "reason": "429 limit",
                        "until": "2026-11-26T12:15:00Z",
                    }
                }
            )
        self.assertEqual(providers, ["claude"])
        self.assertEqual(list(health.keys()), ["claude"])
        self.assertNotIn("codex", health)
        self.assertEqual(health["claude"]["status"], "cooldown")
        self.assertEqual(health["claude"]["category"], "rate_limit")


class WikiQaQueueTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeHeadlessCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_wiki_qa_happy_path_and_secret_scrubbing(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "휴가 신청 절차가 뭔가요?",
                "space_id": "space-hr",
                "provider_pref": "auto",
                "context_prompt": "[문서: HR 가이드]\n휴가는 사내 포털에서 3일 전 신청합니다.",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]

        def fake_runner(provider, **kw):
            return {
                "ok": True,
                "provider": provider,
                "model": "claude-subscription-cli",
                "text": (
                    "휴가는 사내 포털에서 3일 전 신청합니다. (근거: HR 가이드) "
                    "유출테스트 sk-ant-api03-SECRETVALUE1234567890abcdef "
                    f"Bearer {SAMPLE_JWT}"
                ),
            }

        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            host_label="box-1",
            http_send=self.cloud.send,
            cli_runner=fake_runner,
            now=NOW,
        )
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["provider"], "claude")
        job = self.cloud.wiki_jobs[0]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["progress_stage"], "완료")
        self.assertEqual(job["runner_host"], "box-1")
        self.assertEqual(job["error_message"], "")
        ans = job["result_json"]["answer"]
        self.assertIn("HR 가이드", ans)
        self.assertNotIn("sk-ant-api03", ans)
        self.assertNotIn(SAMPLE_JWT, ans)
        self.assertIn("[REDACTED", ans)

    def test_zero_tool_isolation_flags_claude_and_codex_empty_temp_cwd(self):
        # Verify exact Claude isolation flags, stdin piping (never argv), empty 0700 temp cwd outside ILSON_HOME
        captured_claude = {}

        class FakeClaudeProc:
            pid = 99991
            returncode = 0

            def __init__(self, argv, **kwargs):
                captured_claude["argv"] = list(argv)
                captured_claude["cwd"] = kwargs["cwd"]
                captured_claude["cwd_entries"] = list(os.listdir(kwargs["cwd"]))
                captured_claude["cwd_mode"] = stat.S_IMODE(os.stat(kwargs["cwd"]).st_mode)
                captured_claude["start_new_session"] = kwargs["start_new_session"]
                captured_claude["env"] = kwargs["env"]

            def communicate(self, input=None, timeout=None):
                captured_claude["stdin"] = input
                captured_claude["timeout"] = timeout
                return "격리된 Claude 답변", ""

            def poll(self):
                return 0

        with mock.patch.object(cb, "_find_cli_binary", return_value="/usr/local/bin/claude"), \
             mock.patch.object(
                 cb.subprocess,
                 "run",
                 return_value=SimpleNamespace(
                     stdout="--tools --no-session-persistence --strict-mcp-config --disable-slash-commands",
                     stderr="",
                 ),
             ), \
             mock.patch.object(cb.subprocess, "Popen", side_effect=FakeClaudeProc):
            res_c = cb._run_headless_cli(
                "claude",
                system_prompt=cb.WIKI_QA_SYSTEM_PROMPT,
                user_prompt="SENSITIVE_CONTEXT_BODY_ONLY_ON_STDIN",
                timeout_sec=90.0,
                home=self.home,
                purpose="wiki-qa",
            )

        self.assertTrue(res_c["ok"])
        argv = captured_claude["argv"]
        self.assertEqual(argv[0], "/usr/local/bin/claude")
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "text")
        self.assertIn("--system-prompt", argv)
        self.assertNotIn("SENSITIVE_CONTEXT_BODY_ONLY_ON_STDIN", " ".join(argv))
        self.assertEqual(captured_claude["stdin"], "SENSITIVE_CONTEXT_BODY_ONLY_ON_STDIN")
        self.assertTrue(captured_claude["start_new_session"])
        self.assertEqual(captured_claude["cwd_entries"], [])
        self.assertEqual(captured_claude["cwd_mode"], 0o700)
        self.assertFalse(Path(captured_claude["cwd"]).resolve().is_relative_to(self.home.resolve()))
        self.assertFalse(str(Path(captured_claude["cwd"]).resolve()).startswith("/Users/Shared/Ilson"))
        self.assertNotIn("ANTHROPIC_API_KEY", captured_claude["env"])
        self.assertNotIn("OPENAI_API_KEY", captured_claude["env"])

        # Fail-closed when claude --help does NOT advertise --tools
        with mock.patch.object(cb, "_find_cli_binary", return_value="/usr/local/bin/claude"), \
             mock.patch.object(
                 cb.subprocess,
                 "run",
                 return_value=SimpleNamespace(stdout="legacy claude help without tools flag", stderr=""),
             ), \
             mock.patch.object(cb.subprocess, "Popen") as m_popen:
            res_old = cb._run_headless_cli(
                "claude",
                system_prompt=cb.WIKI_QA_SYSTEM_PROMPT,
                user_prompt="test",
                home=self.home,
            )
            self.assertFalse(res_old["ok"])
            self.assertEqual(res_old["error_kind"], "cli_unavailable")
            m_popen.assert_not_called()

        # Verify exact Codex isolation flags, stdin piping, and -o output reading
        captured_codex = {}

        class FakeCodexProc:
            pid = 99992
            returncode = 0

            def __init__(self, argv, **kwargs):
                captured_codex["argv"] = list(argv)
                captured_codex["cwd"] = kwargs["cwd"]
                captured_codex["cwd_entries"] = list(os.listdir(kwargs["cwd"]))
                captured_codex["start_new_session"] = kwargs["start_new_session"]
                out_idx = argv.index("-o") + 1
                Path(argv[out_idx]).write_text("격리된 Codex 답변", encoding="utf-8")

            def communicate(self, input=None, timeout=None):
                captured_codex["stdin"] = input
                return "", ""

            def poll(self):
                return 0

        with mock.patch.object(cb, "_find_cli_binary", return_value="/opt/homebrew/bin/codex"), \
             mock.patch.object(cb.subprocess, "Popen", side_effect=FakeCodexProc):
            res_x = cb._run_headless_cli(
                "codex",
                system_prompt=cb.WIKI_QA_SYSTEM_PROMPT,
                user_prompt="CODEX_CONTEXT_STDIN",
                timeout_sec=90.0,
                home=self.home,
                purpose="wiki-qa",
            )

        self.assertTrue(res_x["ok"])
        self.assertEqual(res_x["text"], "격리된 Codex 답변")
        xargv = captured_codex["argv"]
        self.assertEqual(xargv[:2], ["/opt/homebrew/bin/codex", "exec"])
        for flag in (
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
        ):
            self.assertIn(flag, xargv)
        self.assertEqual(xargv[xargv.index("--sandbox") + 1], "read-only")
        self.assertEqual(xargv[xargv.index("--color") + 1], "never")
        self.assertEqual(xargv[-1], "-")
        self.assertNotIn("CODEX_CONTEXT_STDIN", " ".join(xargv))
        self.assertIn("CODEX_CONTEXT_STDIN", captured_codex["stdin"])
        self.assertEqual(captured_codex["cwd_entries"], [])
        self.assertTrue(captured_codex["start_new_session"])

    def test_claude_to_codex_auto_fallback_on_rate_limit(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-fb-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "배포 일정은?",
                "provider_pref": "auto",
                "context_prompt": "배포는 매주 목요일 14시입니다.",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        seen_providers = []

        def fake_runner(provider, **kw):
            seen_providers.append(provider)
            if provider == "claude":
                return {
                    "ok": False,
                    "provider": "claude",
                    "error_kind": "rate_limit",
                    "error": "HTTP 429 rate limit exceeded",
                    "fallbackable": True,
                }
            return {
                "ok": True,
                "provider": "codex",
                "model": "codex-subscription-cli",
                "text": "배포는 매주 목요일 14시입니다.",
            }

        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=fake_runner,
            now=NOW,
        )
        self.assertEqual(seen_providers, ["claude", "codex"])
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["provider"], "codex")
        meta = self.cloud.wiki_jobs[0]["result_json"]["meta"]
        self.assertTrue(meta["fallback_used"])
        self.assertEqual(meta["fallback_from"], "claude")
        self.assertEqual(meta["fallback_reason"], "rate_limit")
        self.assertEqual(meta["attempted"], ["claude", "codex"])

    def test_provider_pref_claude_does_not_fallback_and_scrubs_error(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-strict-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "테스트",
                "provider_pref": "claude",
                "context_prompt": "컨텍스트",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        seen = []

        def fake_runner(provider, **kw):
            seen.append(provider)
            return {
                "ok": False,
                "provider": provider,
                "error_kind": "execution_error",
                "error": "crash\nwith secret sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "fallbackable": False,
            }

        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=fake_runner,
            now=NOW,
        )
        self.assertEqual(seen, ["claude"])
        self.assertEqual(res["status"], "failed")
        err = self.cloud.wiki_jobs[0]["error_message"]
        self.assertNotIn("\n", err)
        self.assertNotIn("sk-proj-", err)
        self.assertIn("[REDACTED", err)

    def test_mid_flight_cancellation_prevents_overwrite(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-cancel-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "취소될 작업",
                "provider_pref": "auto",
                "context_prompt": "컨텍스트",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]

        def fake_runner(provider, **kw):
            # Simulate user cancelling job while CLI is running
            self.cloud.mid_flight_status_overrides["wqa-cancel-1"] = "cancelled"
            return {
                "ok": True,
                "provider": provider,
                "model": "claude-subscription-cli",
                "text": "이 답변은 덮어쓰면 안 됨",
            }

        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=fake_runner,
            now=NOW,
        )
        self.assertEqual(res["status"], "cancelled")
        self.assertTrue(res["skipped_write"])
        final_patches = [
            c for c in self.cloud.calls
            if c["method"] == "PATCH" and "status=eq.running" in c["url"]
        ]
        self.assertEqual(final_patches, [])

    def test_table_missing_404_pgrst205_fails_soft(self):
        self.cloud.wiki_table_missing = True
        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            now=NOW,
        )
        self.assertIsNone(res)

    def test_wiki_qa_system_prompt_contains_inline_citations_and_injection_guard(self):
        prompt = cb.WIKI_QA_SYSTEM_PROMPT
        self.assertIn("<untrusted_wiki_documents>", prompt)
        self.assertIn("[1]", prompt)
        self.assertIn("[2]", prompt)
        self.assertIn("프롬프트 인젝션", prompt)

    def test_claude_missing_any_of_four_isolation_flags_falls_back_to_codex(self):
        # Missing --strict-mcp-config must fail-closed with cli_unavailable(fallbackable=True)
        with mock.patch.object(cb, "_find_cli_binary", return_value="/usr/local/bin/claude"), \
             mock.patch.object(
                 cb.subprocess,
                 "run",
                 return_value=SimpleNamespace(
                     stdout="--tools --no-session-persistence --disable-slash-commands",
                     stderr="",
                 ),
             ), \
             mock.patch.object(cb.subprocess, "Popen") as m_popen:
            res_missing = cb._run_headless_cli(
                "claude",
                system_prompt=cb.WIKI_QA_SYSTEM_PROMPT,
                user_prompt="test",
                home=self.home,
            )
            self.assertFalse(res_missing["ok"])
            self.assertEqual(res_missing["error_kind"], "cli_unavailable")
            self.assertTrue(res_missing["fallbackable"])
            self.assertIn("--strict-mcp-config", res_missing["error"])
            m_popen.assert_not_called()

        # Verify auto mode falls back to codex cleanly when claude lacks an isolation flag
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-flag-fb",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "격리 폴백 확인",
                "provider_pref": "auto",
                "context_prompt": "<untrusted_wiki_documents>[1] 내용</untrusted_wiki_documents>",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]

        class FakeCodexOnlyProc:
            pid = 99993
            returncode = 0
            stdin = mock.MagicMock()
            stdout = mock.MagicMock()
            stderr = mock.MagicMock()

            def __init__(self, argv, **kwargs):
                out_idx = argv.index("-o") + 1
                Path(argv[out_idx]).write_text("Codex 폴백 답변 [1]", encoding="utf-8")

            def communicate(self, input=None, timeout=None):
                return "", ""

            def poll(self):
                return 0

        with mock.patch.object(cb, "_find_cli_binary", side_effect=lambda name, **kw: f"/opt/homebrew/bin/{name}"), \
             mock.patch.object(
                 cb.subprocess,
                 "run",
                 return_value=SimpleNamespace(stdout="--tools --no-session-persistence", stderr=""),
             ), \
             mock.patch.object(cb.subprocess, "Popen", side_effect=FakeCodexOnlyProc):
            res = cb.process_one_wiki_qa_job(
                self.cfg,
                SAMPLE_JWT,
                home=self.home,
                http_send=self.cloud.send,
                now=NOW,
            )
        self.assertEqual(res["status"], "done")
        self.assertTrue(res["writeback_ok"])
        self.assertEqual(res["provider"], "codex")
        self.assertEqual(res["meta"]["fallback_from"], "claude")
        self.assertEqual(res["meta"]["fallback_reason"], "cli_unavailable")

    def test_timeout_kills_process_group_with_sigkill_and_closes_streams(self):
        fake_stdin = mock.MagicMock()
        fake_stdout = mock.MagicMock()
        fake_stderr = mock.MagicMock()

        class FakeTimedOutProc:
            pid = 424242
            returncode = None
            stdin = fake_stdin
            stdout = fake_stdout
            stderr = fake_stderr

            def __init__(self, *args, **kwargs):
                self._exited = False

            def communicate(self, input=None, timeout=None):
                raise subprocess.TimeoutExpired(cmd=["claude"], timeout=timeout)

            def wait(self, timeout=None):
                # Direct child exits quickly on SIGTERM, yet grandchildren may remain in PGID
                self._exited = True
                return 0

            def poll(self):
                return 0 if self._exited else None

            def terminate(self):
                pass

            def kill(self):
                pass

        with mock.patch.object(cb.subprocess, "Popen", side_effect=FakeTimedOutProc), \
             mock.patch.object(cb.os, "killpg") as m_killpg:
            with self.assertRaises(subprocess.TimeoutExpired):
                cb._exec_isolated_subprocess(
                    ["claude"],
                    stdin_text="hello",
                    cwd="/tmp",
                    env={},
                    timeout_sec=1.0,
                )

        # Must send BOTH SIGTERM and SIGKILL to PGID even when direct child exited on SIGTERM
        kill_sigs = [call.args[1] for call in m_killpg.call_args_list if call.args[0] == 424242]
        self.assertIn(cb.signal.SIGTERM, kill_sigs)
        self.assertIn(cb.signal.SIGKILL, kill_sigs)
        fake_stdin.close.assert_called_once()
        fake_stdout.close.assert_called_once()
        fake_stderr.close.assert_called_once()

    def test_final_patch_401_reauth_retry_and_500_failure_and_empty_200_cancel(self):
        # 1) 401 -> re-auth once -> 200 success
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-401",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "401 재인증 테스트",
                "provider_pref": "claude",
                "context_prompt": "[1] 문서",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        self.cloud.final_patch_responses = [(401, {"message": "JWT expired"}), (200, [{"id": "wqa-401", "status": "done"}])]
        res = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=lambda prov, **kw: {"ok": True, "provider": prov, "model": "claude-sub", "text": "답변 [1]"},
            now=NOW,
        )
        self.assertTrue(res["writeback_ok"])
        self.assertEqual(res["status"], "done")
        auth_calls = [c for c in self.cloud.calls if "/auth/v1/token" in c["url"]]
        self.assertEqual(len(auth_calls), 1)
        final_patches = [c for c in self.cloud.calls if c["method"] == "PATCH" and "status=eq.running" in c["url"]]
        self.assertEqual(len(final_patches), 2)
        self.assertNotEqual(final_patches[0]["headers"]["Authorization"], final_patches[1]["headers"]["Authorization"])

        # 2) 500 -> never silently reports done
        self.cloud.calls.clear()
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-500",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "500 실패 테스트",
                "provider_pref": "claude",
                "context_prompt": "[1] 문서",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        self.cloud.final_patch_responses = [(500, {"message": "db down"})]
        res500 = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=lambda prov, **kw: {"ok": True, "provider": prov, "model": "claude-sub", "text": "답변 [1]"},
            now=NOW,
        )
        self.assertFalse(res500["writeback_ok"])
        self.assertFalse(res500["ok"])
        self.assertEqual(res500["status"], "writeback_failed")
        self.assertEqual(res500["writeback_status"], 500)

        # 3) 200 with empty list on Prefer: return=representation -> treated as cancelled / skipped_write
        self.cloud.calls.clear()
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-race-cancel",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "동시 취소 테스트",
                "provider_pref": "claude",
                "context_prompt": "[1] 문서",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        self.cloud.final_patch_responses = [(200, [])]
        res_empty = cb.process_one_wiki_qa_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=lambda prov, **kw: {"ok": True, "provider": prov, "model": "claude-sub", "text": "답변 [1]"},
            now=NOW,
        )
        self.assertEqual(res_empty["status"], "cancelled")
        self.assertTrue(res_empty["skipped_write"])
        self.assertFalse(res_empty["writeback_ok"])

    def test_worker_loop_survives_transient_cloud_bridge_error_and_reauths(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-loop-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "복구 테스트",
                "provider_pref": "claude",
                "context_prompt": "[1] 문서",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        attempts = {"auth": 0}
        sleeps = []

        def flaky_send(method, url, headers, body, timeout=30.0):
            if "/auth/v1/token" in url:
                attempts["auth"] += 1
                if attempts["auth"] == 1:
                    raise cb.CloudBridgeError(
                        "transient network drop Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.secret_tok_999"
                    )
            return self.cloud.send(method, url, headers, body, timeout)

        err_buf = io.StringIO()
        with mock.patch("sys.stderr", err_buf):
            out = cb.run_headless_worker_loop(
                self.home,
                once=False,
                poll_interval=0.2,
                max_jobs=1,
                http_send=flaky_send,
                cli_runner=lambda prov, **kw: {"ok": True, "provider": prov, "model": "claude-sub", "text": "복구 완료 [1]"},
                now=NOW,
                sleep_fn=sleeps.append,
            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["total_processed"], 1)
        self.assertEqual(out["errors"], 1)
        self.assertGreaterEqual(attempts["auth"], 2)
        self.assertGreaterEqual(len(sleeps), 1)
        logged = err_buf.getvalue()
        self.assertNotIn("secret_tok_999", logged)
        self.assertIn("[REDACTED", logged)


class ResearchQueueTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeHeadlessCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_research_happy_path_url_sanitization_and_fallback(self):
        self.cloud.research_jobs = [
            {
                "id": "res-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "2026 국내 SaaS 보안 동향",
                "mode": "deep",
                "period": "month",
                "history": [
                    {"question": "이전 보안 질문", "summary": "이전 요약 내용"},
                ],
                "provider_pref": "auto",
                "status": "queued",
                "created_at": "2026-11-26T11:58:00Z",
            }
        ]
        calls = []
        captured_prompts = []

        def fake_runner(provider, **kw):
            calls.append(provider)
            captured_prompts.append(kw.get("user_prompt") or "")
            if provider == "claude":
                return {
                    "ok": False,
                    "provider": "claude",
                    "error_kind": "rate_limit",
                    "error": "429 too many requests",
                    "fallbackable": True,
                }
            payload = {
                "summary": "제로트러스트와 구독형 로컬 워커가 핵심입니다. token=THQAA_super_secret_oauth_token_999",
                "bullets": ["로컬 구독 CLI 격리 실행", "테넌트별 데이터 분리"],
                "sources": [
                    {"title": "공식 가이드", "url": "https://www.example.org/security", "snippet": "핵심 보안 스니펫"},
                    {"title": "평문 HTTP 금지", "url": "http://example.org/insecure"},
                    {"title": "로컬 파일 금지", "url": "file:///etc/passwd"},
                    {"title": "내부망 금지", "url": "https://127.0.0.1/admin"},
                    {"title": "사설IP 금지", "url": "https://192.168.1.10/secret"},
                    {"title": "메타데이터 금지", "url": "https://169.254.169.254/latest"},
                    {"title": "인증정보 포함 금지", "url": "https://user:pass@example.org/a"},
                    {"title": "로컬호스트 금지", "url": "https://localhost/internal"},
                    {"title": "8진수 우회 금지", "url": "https://0177.0.0.1/admin"},
                    {"title": "16진수 우회 금지", "url": "https://0x7f.0.0.1/admin"},
                    {"title": "축약IP 금지", "url": "https://127.1/admin"},
                    {"title": "깨진 IPv6 금지", "url": "https://[::1/bad"},
                    {"title": "IPv4매핑 IPv6 금지", "url": "https://[::ffff:127.0.0.1]/admin"},
                    {"title": "시크릿 URL 금지", "url": "https://example.org/cb?key=sk-ant-api03-SECRETVALUE1234567890abcdef"},
                ],
                "followups": ["회사 모드 권한 검증 방법은?"],
            }
            return {
                "ok": True,
                "provider": "codex",
                "model": "codex-subscription-cli",
                "text": json.dumps(payload, ensure_ascii=False),
            }

        res = cb.process_one_research_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            host_label="student-mac",
            http_send=self.cloud.send,
            cli_runner=fake_runner,
            now=NOW,
        )
        self.assertEqual(calls, ["claude", "codex"])
        self.assertEqual(res["status"], "done")
        self.assertTrue(res["writeback_ok"])
        self.assertEqual(res["provider"], "codex")
        self.assertEqual(res["sources_count"], 1)

        # Verify poll query selects mode, period, history and prompt includes them
        poll_calls = [c for c in self.cloud.calls if c["method"] == "GET" and "status=eq.queued" in c["url"]]
        self.assertEqual(len(poll_calls), 1)
        for col in ("mode", "period", "history"):
            self.assertIn(col, poll_calls[0]["url"])
        self.assertIn("deep", captured_prompts[0])
        self.assertIn("month", captured_prompts[0])
        self.assertIn("이전 보안 질문", captured_prompts[0])

        rj = self.cloud.research_jobs[0]["result_json"]
        expected_keys = {
            "question",
            "summary",
            "grounded",
            "provider",
            "model",
            "runner_host",
            "checked_at",
            "claims",
            "sources",
            "checks",
            "limitations",
            "related_questions",
            "meta",
        }
        self.assertEqual(set(rj.keys()), expected_keys)
        self.assertEqual(rj["question"], "2026 국내 SaaS 보안 동향")
        self.assertNotIn("THQAA_", rj["summary"])
        self.assertTrue(rj["grounded"])
        self.assertEqual(rj["provider"], "codex")
        self.assertEqual(rj["model"], "codex-subscription-cli")
        self.assertEqual(rj["runner_host"], "student-mac")
        self.assertEqual(rj["checked_at"], "2026-11-26T12:00:00Z")
        self.assertEqual(
            rj["sources"],
            [
                {
                    "id": 1,
                    "title": "공식 가이드",
                    "url": "https://www.example.org/security",
                    "domain": "example.org",
                    "snippet": "핵심 보안 스니펫",
                }
            ],
        )
        self.assertEqual(len(rj["claims"]), 2)
        self.assertEqual(rj["claims"][0]["detail"], "로컬 구독 CLI 격리 실행")
        self.assertEqual(rj["claims"][0]["text"], "로컬 구독 CLI 격리 실행")
        self.assertEqual(rj["claims"][0]["kind"], "finding")
        self.assertEqual(rj["claims"][0]["confidence"], "medium")
        self.assertEqual(rj["claims"][0]["source_ids"], [1])
        self.assertEqual(rj["checks"], [])
        self.assertEqual(rj["limitations"], [])
        self.assertEqual(rj["related_questions"], ["회사 모드 권한 검증 방법은?"])
        self.assertEqual(rj["meta"], {"fallback_from": "claude", "fallback_reason": "rate_limit"})

    def test_research_no_fallback_omits_meta_and_empty_sources_sets_grounded_false(self):
        self.cloud.research_jobs = [
            {
                "id": "res-2",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "단독 실행 테스트",
                "mode": "quick",
                "period": "all",
                "history": [],
                "provider_pref": "claude",
                "status": "queued",
                "created_at": "2026-11-26T11:58:00Z",
            }
        ]
        res = cb.process_one_research_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            host_label="student-mac",
            http_send=self.cloud.send,
            cli_runner=lambda prov, **kw: {
                "ok": True,
                "provider": "claude",
                "model": "claude-subscription-cli",
                "text": json.dumps({"summary": "요약입니다.", "bullets": ["포인트 1"], "sources": []}, ensure_ascii=False),
            },
            now=NOW,
        )
        self.assertEqual(res["status"], "done")
        rj = self.cloud.research_jobs[0]["result_json"]
        self.assertFalse(rj["grounded"])
        self.assertNotIn("meta", rj)

    def test_is_safe_public_https_url_blocks_obfuscated_ips_malformed_ipv6_ctrl_and_secrets(self):
        bad_urls = [
            "https://[::1/bad",
            "https://example.org:99999/badport",
            "https://example.org/a\nb",
            "https://example.org/a\rb",
            "https://example.org/\x00null",
            "https://example.org/with space",
            "https://example.org/\ttab",
            "https://user@example.org/a",
            "https://user:pass@example.org/a",
            "https://@example.org/a",
            "https://[::ffff:127.0.0.1]/",
            "https://[::ffff:169.254.169.254]/latest",
            "https://[2002:7f00:0001::1]/",
            "https://[2001:0000:4136:e378:8000:63bf:3fff:fdd2]/",
            "https://0177.0.0.1/",
            "https://0x7f.0.0.1/",
            "https://127.1/",
            "https://2130706433/",
            "https://0x7f000001/",
            "https://example.org/?k=sk-ant-api03-SECRETVALUE1234567890abcdef",
            "https://example.org/?access_token=abcdefghijklmnop",
            "http://example.org/not-https",
        ]
        for bad in bad_urls:
            self.assertFalse(cb._is_safe_public_https_url(bad), f"Expected rejected: {bad!r}")

        self.assertTrue(cb._is_safe_public_https_url("https://example.org/docs?q=1"))
        self.assertTrue(cb._is_safe_public_https_url("https://[2606:4700:4700::1111]/dns"))

    def test_research_final_patch_401_reauth_retry(self):
        self.cloud.research_jobs = [
            {
                "id": "res-401",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "리서치 401 재시도",
                "mode": "quick",
                "period": "all",
                "history": [],
                "provider_pref": "claude",
                "status": "queued",
                "created_at": "2026-11-26T11:58:00Z",
            }
        ]
        self.cloud.final_patch_responses = [(401, {"message": "expired"}), (200, [{"id": "res-401", "status": "done"}])]
        res = cb.process_one_research_job(
            self.cfg,
            SAMPLE_JWT,
            home=self.home,
            http_send=self.cloud.send,
            cli_runner=lambda prov, **kw: {
                "ok": True,
                "provider": "claude",
                "model": "claude-subscription-cli",
                "text": json.dumps({"summary": "재시도 성공", "bullets": ["항목"], "sources": []}, ensure_ascii=False),
            },
            now=NOW,
        )
        self.assertTrue(res["writeback_ok"])
        self.assertEqual(res["status"], "done")
        auth_calls = [c for c in self.cloud.calls if "/auth/v1/token" in c["url"]]
        self.assertEqual(len(auth_calls), 1)


class CompanyModeGuardAndCLITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeHeadlessCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_company_mode_staff_and_malformed_and_symlink_fail_closed(self):
        state = self.home / "state"
        marker = state / "company.json"

        # 1. Malformed company.json must fail closed
        marker.write_text("{broken json", encoding="utf-8")
        with self.assertRaises(cb.CloudBridgeError):
            cb.run_headless_worker_once(self.home, http_send=self.cloud.send)
        with self.assertRaises(cb.CloudBridgeError):
            cb.sync_once(self.home, http_send=self.cloud.send)

        # 2. Symlink company.json must fail closed
        marker.unlink()
        target = self.home / "real.json"
        target.write_text('{"company": "acme"}', encoding="utf-8")
        marker.symlink_to(target)
        with self.assertRaises(cb.CloudBridgeError):
            cb.run_headless_worker_once(self.home, http_send=self.cloud.send)

        # 3. Valid marker but staff actor must fail closed
        marker.unlink()
        marker.write_text('{"company": "acme"}', encoding="utf-8")
        staff_policy = SimpleNamespace(actor=ap.Actor(person="alice", uid=os.geteuid(), role="staff"))
        with mock.patch.object(ap, "load", return_value=staff_policy):
            with self.assertRaises(cb.CloudBridgeError) as ctx:
                cb.run_headless_worker_once(self.home, http_send=self.cloud.send)
            self.assertIn("대표", str(ctx.exception))
            with self.assertRaises(cb.CloudBridgeError):
                cb.sync_once(self.home, http_send=self.cloud.send)

        # 4. Valid marker with owner actor succeeds
        owner_policy = SimpleNamespace(actor=ap.Actor(person="boss", uid=os.geteuid(), role="owner"))
        with mock.patch.object(ap, "load", return_value=owner_policy):
            out = cb.run_headless_worker_once(self.home, http_send=self.cloud.send, now=NOW)
            self.assertTrue(out["ok"])

    def test_cli_worker_once_smoke_test(self):
        self.cloud.wiki_jobs = [
            {
                "id": "wqa-cli-1",
                "company_id": SAMPLE_COMPANY_ID,
                "question": "CLI 스모크 질문",
                "provider_pref": "auto",
                "context_prompt": "정답은 42입니다.",
                "status": "queued",
                "created_at": "2026-11-26T11:59:00Z",
            }
        ]
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = cb.main(
                ["worker", "--home", str(self.home), "--once", "--json"],
                http_send=self.cloud.send,
                cli_runner=lambda prov, **kw: {
                    "ok": True,
                    "provider": prov,
                    "model": f"{prov}-subscription-cli",
                    "text": "정답은 42입니다.",
                },
            )
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["ok"])
        self.assertEqual(data["iterations"], 1)
        self.assertEqual(data["total_processed"], 1)
        self.assertEqual(data["wiki_qa"]["status"], "done")
        self.assertIsNone(data["research"])

        # Also verify `ilson --help` documents `cloud pair|sync|worker|status|submit-draft`
        help_proc = subprocess.run(
            ["bash", str(ROOT / "ilson"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        self.assertIn("cloud pair|sync|worker|status|submit-draft", help_proc.stdout)


if __name__ == "__main__":
    unittest.main()
