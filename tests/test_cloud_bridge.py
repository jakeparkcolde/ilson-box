import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = ROOT / "template" / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

import cloud_bridge as cb  # noqa: E402


SAMPLE_RAW_CODE = "ILSON-4K7M-92XQ-HR3T-8NPW"
SAMPLE_NORM_CODE = "4K7M92XQHR3T8NPW"
SAMPLE_COMPANY_ID = "11111111-2222-3333-4444-555555555555"
SAMPLE_RUNNER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SAMPLE_EMAIL = "runner-11111111@ilson.invalid"
SAMPLE_JWT = "eyJhbGciOiJIUzI1NiJ9.mock-jwt.sig"
SAMPLE_TOKEN = "THQAA_super_secret_oauth_token_999"
NOW = dt.datetime(2026, 11, 24, 10, 0, 0, tzinfo=dt.timezone.utc)


def _json_resp(status: int, payload):
    if payload is None:
        return status, b""
    return status, json.dumps(payload).encode("utf-8")


class FakeCloud:
    """Deterministic in-memory mock of the ilson.work Supabase endpoints."""

    def __init__(self):
        self.calls = []
        self.claim_response = _json_resp(
            200,
            {
                "ok": True,
                "runner_id": SAMPLE_RUNNER_ID,
                "company_id": SAMPLE_COMPANY_ID,
                "label": "학생1 맥",
                "email": SAMPLE_EMAIL,
            },
        )
        self.auth_status = 200
        self.handoffs = []
        self.approvals = []
        self.approval_patch_status = 204
        self.approval_patch_raises = False
        self.runner_state_status = 201
        self.heartbeat_status = 204
        self.submit_draft_status = 201
        self.on_handoff_patch = None

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
            return self.claim_response

        if "/auth/v1/token?grant_type=password" in url:
            if self.auth_status >= 400:
                return _json_resp(self.auth_status, {"error": "invalid_grant"})
            return _json_resp(200, {"access_token": SAMPLE_JWT, "token_type": "bearer"})

        if "/rest/v1/link_handoff_live" in url and method == "GET":
            return _json_resp(200, self.handoffs)

        if "/rest/v1/link_handoff?id=eq." in url and method == "PATCH":
            if self.on_handoff_patch:
                self.on_handoff_patch(url, parsed_body)
            return _json_resp(204, None)

        if "/rest/v1/runner?id=eq." in url and method == "PATCH":
            return _json_resp(self.heartbeat_status, None)

        if "/rest/v1/approval?on_conflict=" in url and method == "POST":
            if self.submit_draft_status >= 400:
                return _json_resp(self.submit_draft_status, {"message": "forbidden"})
            return _json_resp(
                self.submit_draft_status,
                [{"id": "appr-draft-001", **(parsed_body or {})}],
            )

        if "/rest/v1/approval?" in url and method == "GET":
            return _json_resp(200, self.approvals)

        if "/rest/v1/approval?id=eq." in url and method == "PATCH":
            if self.approval_patch_raises:
                raise cb.CloudBridgeError("simulated network drop on approval patch")
            return _json_resp(self.approval_patch_status, None)

        if "/rest/v1/runner_state" in url and method == "POST":
            return _json_resp(self.runner_state_status, None)

        return _json_resp(404, {"error": f"unhandled {method} {url}"})


class OfficeCodeParityTests(unittest.TestCase):
    def test_normalize_accepts_variants(self):
        self.assertEqual(cb.normalize_office_code(SAMPLE_RAW_CODE), SAMPLE_NORM_CODE)
        self.assertEqual(cb.normalize_office_code("  ilson-4k7m 92xq hr3t 8npw "), SAMPLE_NORM_CODE)
        self.assertEqual(cb.normalize_office_code(SAMPLE_NORM_CODE.lower()), SAMPLE_NORM_CODE)

    def test_normalize_rejects_invalid_length_and_ambiguous_chars(self):
        for bad in ("", "SHORT", "ILSON-4K7M-92XQ-HR3T-8NPW-XXXX", None):
            with self.assertRaises(cb.OfficeCodeError):
                cb.normalize_office_code(bad)  # type: ignore[arg-type]
        for forbidden in ("0", "O", "1", "I", "L", "U"):
            bad_code = forbidden + SAMPLE_NORM_CODE[1:]
            with self.assertRaises(cb.OfficeCodeError):
                cb.normalize_office_code(bad_code)

    def test_derive_runner_password_matches_office_code_protocol(self):
        expected = hashlib.sha256(
            ("ilson-runner-pw-v1:" + SAMPLE_NORM_CODE).encode("utf-8")
        ).hexdigest()
        got = cb.derive_runner_password(SAMPLE_RAW_CODE)
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 64)
        self.assertEqual(cb.derive_runner_password("ilson 4k7m92xqhr3t8npw"), expected)


class PrivateFileStoreTests(unittest.TestCase):
    def test_atomic_write_sets_0600_and_blocks_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            target = home / "state" / "cloud-runner.json"
            cb._write_private_json(target, {"hello": "world"})
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(cb._read_private_json(target), {"hello": "world"})

            # Target symlink must be rejected
            real = home / "outside.json"
            real.write_text("{}")
            link_target = home / "state" / "sns-tokens.json"
            link_target.symlink_to(real)
            with self.assertRaises(cb.CloudBridgeError):
                cb._write_private_json(link_target, {"a": 1})
            with self.assertRaises(cb.CloudBridgeError):
                cb._read_private_json(link_target)

            # Parent symlink must be rejected
            other_dir = home / "other"
            other_dir.mkdir()
            sym_home = home / "symbox"
            sym_home.mkdir()
            (sym_home / "state").symlink_to(other_dir)
            with self.assertRaises(cb.CloudBridgeError):
                cb._write_private_json(sym_home / "state" / "cloud-runner.json", {"x": 1})


class PairingAndHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeCloud()

    def tearDown(self):
        self._td.cleanup()

    def test_pair_with_cloud_happy_path_no_plaintext_code_and_initial_heartbeat(self):
        res = cb.pair_with_cloud(
            self.home,
            SAMPLE_RAW_CODE,
            http_send=self.cloud.send,
            now=NOW,
        )
        self.assertEqual(res["company_id"], SAMPLE_COMPANY_ID)
        self.assertEqual(res["runner_id"], SAMPLE_RUNNER_ID)
        self.assertNotIn("derived_password", res)
        self.assertNotIn("access_token", res)
        self.assertNotIn("code", res)

        cfg_path = self.home / "state" / "cloud-runner.json"
        self.assertEqual(stat.S_IMODE(cfg_path.stat().st_mode), 0o600)
        raw_text = cfg_path.read_text(encoding="utf-8")
        self.assertNotIn(SAMPLE_RAW_CODE, raw_text)
        self.assertNotIn(SAMPLE_NORM_CODE, raw_text)

        cfg = json.loads(raw_text)
        self.assertEqual(cfg["derived_password"], cb.derive_runner_password(SAMPLE_RAW_CODE))
        self.assertEqual(cfg["email"], SAMPLE_EMAIL)

        # Sequence: claim_office -> auth token -> initial heartbeat
        self.assertEqual(len(self.cloud.calls), 3)
        self.assertTrue(self.cloud.calls[0]["url"].endswith("/rest/v1/rpc/claim_office"))
        self.assertEqual(self.cloud.calls[0]["body"], {"code": SAMPLE_NORM_CODE})
        self.assertIn("/auth/v1/token?grant_type=password", self.cloud.calls[1]["url"])
        self.assertEqual(self.cloud.calls[2]["method"], "PATCH")
        self.assertIn(f"/rest/v1/runner?id=eq.{SAMPLE_RUNNER_ID}", self.cloud.calls[2]["url"])
        self.assertEqual(set(self.cloud.calls[2]["body"].keys()), cb.SAFE_BEAT_COLUMNS)
        self.assertEqual(self.cloud.calls[2]["body"]["linked_accounts"], [])

    def test_pair_refuses_in_sandbox(self):
        (self.home / "state").mkdir(parents=True)
        (self.home / "state" / "sandbox").touch()
        with self.assertRaises(cb.CloudBridgeError) as ctx:
            cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send)
        self.assertIn("샌드박스", str(ctx.exception))
        self.assertEqual(self.cloud.calls, [])

    def test_pair_handles_mismatch_and_locked(self):
        self.cloud.claim_response = _json_resp(200, {"ok": False, "reason": "mismatch"})
        with self.assertRaises(cb.CloudBridgeError) as ctx:
            cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send)
        self.assertIn("일치하지 않습니다", str(ctx.exception))

        self.cloud.claim_response = _json_resp(200, {"ok": False, "reason": "locked"})
        with self.assertRaises(cb.CloudBridgeError) as ctx:
            cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send)
        self.assertIn("잠겼습니다", str(ctx.exception))
        self.assertFalse((self.home / "state" / "cloud-runner.json").exists())

    def test_pair_does_not_persist_when_auth_fails(self):
        self.cloud.auth_status = 400
        with self.assertRaises(cb.CloudBridgeError):
            cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send)
        self.assertFalse((self.home / "state" / "cloud-runner.json").exists())

    def test_build_safe_linked_accounts_only_4_allowlisted_keys(self):
        vault = {
            "accounts": {
                "threads:alice": {
                    "platform": "threads",
                    "user_id": "u-123",
                    "username": "alice",
                    "access_token": SAMPLE_TOKEN,
                    "refresh_token": "secret-refresh",
                    "expires_at": "2027-01-01T00:00:00Z",
                    "claimed_at": "2026-11-24T09:00:00Z",
                },
                "instagram:bob": {
                    "platform": "instagram",
                    "user_id": "u-456",
                    "username": "bob",
                    "access_token": "IG_old_token",
                    "expires_at": "2026-11-20T00:00:00Z",
                },
            }
        }
        safe = cb.build_safe_linked_accounts(vault, now=NOW)
        self.assertEqual(len(safe), 2)
        for item in safe:
            self.assertEqual(set(item.keys()), cb.SAFE_LINKED_ACCOUNT_KEYS)
        by_user = {item["username"]: item for item in safe}
        self.assertEqual(by_user["alice"]["state"], "ok")
        self.assertEqual(by_user["bob"]["state"], "expired")
        dumped = json.dumps(safe)
        self.assertNotIn(SAMPLE_TOKEN, dumped)
        self.assertNotIn("IG_old_token", dumped)
        self.assertNotIn("secret-refresh", dumped)
        self.assertNotIn("u-123", dumped)


class HandoffAndDraftTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_claim_link_handoffs_persists_0600_before_burning_cloud(self):
        self.cloud.handoffs = [
            {
                "id": "ho-1",
                "platform": "threads",
                "state": "csrf-state-1",
                "access_token": SAMPLE_TOKEN,
                "user_id": "th-9001",
                "username": "student_alpha",
                "token_expires": "2027-01-15T00:00:00Z",
                "status": "ready",
            },
            {
                "id": "ho-empty",
                "platform": "threads",
                "state": "csrf-state-2",
                "access_token": "",
                "user_id": "th-9002",
                "username": "no_token",
                "status": "ready",
            },
        ]

        vault_seen_at_burn = {}

        def _check_local_saved_before_burn(url, body):
            vault_path = self.home / "state" / "sns-tokens.json"
            self.assertTrue(vault_path.exists(), "local vault must exist before burning cloud handoff")
            self.assertEqual(stat.S_IMODE(vault_path.stat().st_mode), 0o600)
            vault_seen_at_burn.update(json.loads(vault_path.read_text(encoding="utf-8")))
            self.assertEqual(body, {"status": "claimed"})

        self.cloud.on_handoff_patch = _check_local_saved_before_burn

        res = cb.claim_link_handoffs(
            self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, now=NOW
        )
        self.assertEqual(res["claimed"], 1)
        self.assertEqual(res["accounts"], [{"platform": "threads", "username": "student_alpha"}])
        self.assertNotIn(SAMPLE_TOKEN, json.dumps(res))
        self.assertIn("threads:student_alpha", vault_seen_at_burn["accounts"])
        self.assertEqual(
            vault_seen_at_burn["accounts"]["threads:student_alpha"]["access_token"], SAMPLE_TOKEN
        )

        # Heartbeat immediately reports safe linked_accounts without token
        hb = cb.send_heartbeat(self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, now=NOW)
        self.assertEqual(len(hb["linked_accounts"]), 1)
        self.assertEqual(set(hb["linked_accounts"][0].keys()), cb.SAFE_LINKED_ACCOUNT_KEYS)
        self.assertEqual(hb["linked_accounts"][0]["username"], "student_alpha")
        self.assertEqual(hb["linked_accounts"][0]["state"], "ok")

    def test_submit_draft_enforces_pending_status_and_blocks_local_paths(self):
        res = cb.submit_draft(
            self.home,
            source_key="lesson-01-post-1",
            platform="Threads",
            account="student_alpha",
            title="1주차 후기",
            body="오늘 일손 설치 완료!",
            media_urls=["https://cdn.example.com/img1.png"],
            scheduled_at="2026-11-24T12:00:00Z",
            http_send=self.cloud.send,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "pending")
        post_calls = [c for c in self.cloud.calls if c["method"] == "POST" and "/rest/v1/approval" in c["url"]]
        self.assertEqual(len(post_calls), 1)
        body = post_calls[0]["body"]
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["company_id"], SAMPLE_COMPANY_ID)
        self.assertEqual(body["source_key"], "lesson-01-post-1")
        self.assertEqual(body["platform"], "threads")
        self.assertEqual(body["payload"]["media_urls"], ["https://cdn.example.com/img1.png"])
        self.assertIn("resolution=merge-duplicates", post_calls[0]["headers"]["Prefer"])

        # Local path and plaintext http:// URL must be rejected before network
        for bad_url in (
            "/Users/student/secret.png",
            "file:///etc/passwd",
            "http://example.com/a.jpg",
        ):
            with self.subTest(bad_url=bad_url):
                with self.assertRaises(cb.CloudBridgeError) as ctx:
                    cb.submit_draft(
                        self.home,
                        source_key="bad-media",
                        platform="threads",
                        account="student_alpha",
                        body="test",
                        media_urls=[bad_url],
                        http_send=self.cloud.send,
                    )
                self.assertIn("https://", str(ctx.exception))


class PublishDispatchAndIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeCloud()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cfg = cb._load_runner_config(self.home)
        cb._write_private_json(
            self.home / "state" / "sns-tokens.json",
            {
                "accounts": {
                    "threads:student_alpha": {
                        "platform": "threads",
                        "user_id": "th-9001",
                        "username": "student_alpha",
                        "access_token": SAMPLE_TOKEN,
                        "expires_at": "2027-01-15T00:00:00Z",
                        "claimed_at": "2026-11-24T08:00:00Z",
                    },
                    "instagram:expired_ig": {
                        "platform": "instagram",
                        "user_id": "ig-1001",
                        "username": "expired_ig",
                        "access_token": "IG_EXPIRED",
                        "expires_at": "2026-11-01T00:00:00Z",
                        "claimed_at": "2026-10-01T00:00:00Z",
                    },
                }
            },
        )
        self.cloud.calls.clear()

    def tearDown(self):
        self._td.cleanup()

    def test_publish_idempotency_schedule_expiry_and_403_fallback(self):
        self.cloud.approval_patch_status = 403  # Legacy P-STAMP trigger blocks runner PATCH
        self.cloud.approvals = [
            {
                "id": "appr-due-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "scheduled_at": "2026-11-24T09:30:00Z",
                "payload": {"body": "예약된 첫 글", "media_urls": []},
            },
            {
                "id": "appr-future-2",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "scheduled_at": "2026-11-24T15:00:00Z",
                "payload": {"body": "미래 글", "media_urls": []},
            },
            {
                "id": "appr-expired-3",
                "status": "approved",
                "platform": "instagram",
                "account": "expired_ig",
                "scheduled_at": None,
                "payload": {"body": "만료 계정", "media_urls": ["https://cdn.example.com/1.jpg"]},
            },
            {
                "id": "appr-missing-4",
                "status": "approved",
                "platform": "threads",
                "account": "unknown_user",
                "scheduled_at": None,
                "payload": {"body": "미연결 계정"},
            },
            {
                "id": "appr-non-sns-5",
                "status": "approved",
                "platform": None,
                "account": None,
                "payload": {"body": "회의록 승인"},
            },
        ]

        published_calls = []

        def fake_publisher(**kw):
            published_calls.append(kw)
            return "remote-post-777"

        res1 = cb.dispatch_approved_publishes(
            self.home,
            self.cfg,
            SAMPLE_JWT,
            http_send=self.cloud.send,
            publisher=fake_publisher,
            now=NOW,
        )
        self.assertFalse(res1["locked"])
        self.assertEqual(len(published_calls), 1)
        self.assertEqual(published_calls[0]["platform"], "threads")
        self.assertEqual(published_calls[0]["text"], "예약된 첫 글")
        self.assertEqual(len(res1["published"]), 1)
        self.assertEqual(res1["published"][0]["remote_id"], "remote-post-777")
        self.assertFalse(res1["published"][0]["cloud_status_updated"])
        self.assertTrue(res1["published"][0]["runner_state_updated"])

        # runner_state updated with student_publish_log_v1
        rs_calls = [c for c in self.cloud.calls if "/rest/v1/runner_state" in c["url"]]
        self.assertEqual(len(rs_calls), 1)
        self.assertEqual(rs_calls[0]["body"]["key"], "student_publish_log_v1")
        self.assertIn("appr-due-1", rs_calls[0]["body"]["data"]["published"])

        # Future & non-SNS skipped; expired & missing recorded as errors
        skip_reasons = {s["approval_id"]: s["reason"] for s in res1["skipped"]}
        self.assertEqual(skip_reasons["appr-future-2"], "not_due_yet")
        self.assertEqual(skip_reasons["appr-non-sns-5"], "unsupported_platform")
        err_ids = {e["approval_id"] for e in res1["errors"]}
        self.assertEqual(err_ids, {"appr-expired-3", "appr-missing-4"})

        # Durable log written with 0600
        pub_log_path = self.home / "state" / "cloud-published.json"
        self.assertEqual(stat.S_IMODE(pub_log_path.stat().st_mode), 0o600)

        # Second run MUST NOT double-publish appr-due-1!
        res2 = cb.dispatch_approved_publishes(
            self.home,
            self.cfg,
            SAMPLE_JWT,
            http_send=self.cloud.send,
            publisher=fake_publisher,
            now=NOW,
        )
        self.assertEqual(len(published_calls), 1)
        self.assertEqual(res2["published"], [])
        skip_reasons2 = {s["approval_id"]: s["reason"] for s in res2["skipped"]}
        self.assertEqual(skip_reasons2["appr-due-1"], "already_published")

    def test_network_drop_after_publish_still_prevents_double_post(self):
        self.cloud.approval_patch_raises = True
        self.cloud.approvals = [
            {
                "id": "appr-drop-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "payload": {"body": "네트워크 드롭 시험"},
            }
        ]
        count = {"n": 0}

        def fake_publisher(**kw):
            count["n"] += 1
            return "remote-drop-1"

        res1 = cb.dispatch_approved_publishes(
            self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, publisher=fake_publisher, now=NOW
        )
        self.assertEqual(count["n"], 1)
        self.assertEqual(len(res1["published"]), 1)

        # Retry after network recovers: must NOT publish a second time
        self.cloud.approval_patch_raises = False
        res2 = cb.dispatch_approved_publishes(
            self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, publisher=fake_publisher, now=NOW
        )
        self.assertEqual(count["n"], 1)
        self.assertEqual(res2["published"], [])

    def test_parse_iso_datetime_postgres_formats_and_fail_closed_scheduled_at(self):
        # Postgres timestamptz / ISO variants on Python 3.9
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24T10:00:00.12345+00:00"),
            dt.datetime(2026, 11, 24, 10, 0, 0, 123450, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24T10:00:00.5+00"),
            dt.datetime(2026, 11, 24, 10, 0, 0, 500000, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24T19:00:00+0900"),
            dt.datetime(2026, 11, 24, 10, 0, 0, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24T10:00:00z"),
            dt.datetime(2026, 11, 24, 10, 0, 0, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24T10:00:00"),
            dt.datetime(2026, 11, 24, 10, 0, 0, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(
            cb._parse_iso_datetime("2026-11-24 05:00:00.123456789-05"),
            dt.datetime(2026, 11, 24, 10, 0, 0, 123456, tzinfo=dt.timezone.utc),
        )
        self.assertIsNone(cb._parse_iso_datetime("not-a-timestamp"))

        # Fail-closed on unparseable scheduled_at + Postgres future fractional timestamps
        self.cloud.approvals = [
            {
                "id": "appr-bad-sched",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "scheduled_at": "invalid-date-string",
                "payload": {"body": "파싱 불가 예약은 절대 발행 금지"},
            },
            {
                "id": "appr-pg-future-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "scheduled_at": "2026-11-24T10:30:00.12345+00:00",
                "payload": {"body": "5자리 소수초 미래 예약"},
            },
            {
                "id": "appr-pg-future-2",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "scheduled_at": "2026-11-24T19:30:00.5+0900",
                "payload": {"body": "KST 짧은 오프셋 미래 예약"},
            },
        ]
        called = []
        res = cb.dispatch_approved_publishes(
            self.home,
            self.cfg,
            SAMPLE_JWT,
            http_send=self.cloud.send,
            publisher=lambda **kw: called.append(kw) or "should-not-publish",
            now=NOW,
        )
        self.assertEqual(called, [])
        self.assertEqual(res["published"], [])
        skip_reasons = {s["approval_id"]: s["reason"] for s in res["skipped"]}
        self.assertEqual(skip_reasons["appr-bad-sched"], "invalid_scheduled_at")
        self.assertEqual(skip_reasons["appr-pg-future-1"], "not_due_yet")
        self.assertEqual(skip_reasons["appr-pg-future-2"], "not_due_yet")

    def test_lock_symlink_rejected_with_o_nofollow(self):
        real_lock = self.home / "outside.lock"
        real_lock.write_text("")
        (self.home / "state" / "cloud-publish.lock").symlink_to(real_lock)
        with self.assertRaises(cb.CloudBridgeError):
            cb.dispatch_approved_publishes(
                self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, now=NOW
            )

    def test_dry_run_does_not_publish_or_mutate_state(self):
        self.cloud.approvals = [
            {
                "id": "appr-dry-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "payload": {"body": "드라이런 테스트"},
            }
        ]
        called = []
        res = cb.dispatch_approved_publishes(
            self.home,
            self.cfg,
            SAMPLE_JWT,
            http_send=self.cloud.send,
            publisher=lambda **kw: called.append(kw) or "should-not-run",
            now=NOW,
            dry_run=True,
        )
        self.assertTrue(res["dry_run"])
        self.assertEqual(called, [])
        self.assertEqual(res["published"], [])
        self.assertEqual(len(res["would_publish"]), 1)
        self.assertEqual(res["would_publish"][0]["approval_id"], "appr-dry-1")
        self.assertFalse((self.home / "state" / "cloud-published.json").exists())

    def test_flock_prevents_concurrent_double_publish(self):
        lock_path = self.home / "state" / "cloud-publish.lock"
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            res = cb.dispatch_approved_publishes(
                self.home,
                self.cfg,
                SAMPLE_JWT,
                http_send=self.cloud.send,
                publisher=lambda **kw: "never",
                now=NOW,
            )
            self.assertTrue(res["locked"])
            self.assertEqual(res["published"], [])
            self.assertEqual(self.cloud.calls, [])
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_publisher_error_redacts_token(self):
        self.cloud.approvals = [
            {
                "id": "appr-err-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "payload": {"body": "에러 레닥트"},
            }
        ]

        def failing_pub(**kw):
            raise RuntimeError(f"boom with token={kw['token']}")

        res = cb.dispatch_approved_publishes(
            self.home, self.cfg, SAMPLE_JWT, http_send=self.cloud.send, publisher=failing_pub, now=NOW
        )
        self.assertEqual(res["published"], [])
        self.assertEqual(len(res["errors"]), 1)
        self.assertNotIn(SAMPLE_TOKEN, res["errors"][0]["error"])
        self.assertIn("[REDACTED]", res["errors"][0]["error"])
        self.assertFalse((self.home / "state" / "cloud-published.json").exists())

    def test_default_publish_routes_to_meta_publish(self):
        with mock.patch("social.meta_publish.publish_threads", return_value="th-1") as m_th, \
             mock.patch("social.meta_publish.publish_threads_media", return_value="th-m") as m_thm, \
             mock.patch("social.meta_publish.publish_instagram", return_value="ig-1") as m_ig, \
             mock.patch("social.meta_publish.publish_instagram_carousel", return_value="ig-c") as m_igc:
            self.assertEqual(
                cb._default_publish(
                    platform="threads", account="a", user_id="u1", token="t1",
                    text="hi", media_urls=[], approval={}
                ),
                "th-1",
            )
            m_th.assert_called_once_with(token="t1", user_id="u1", text="hi")

            self.assertEqual(
                cb._default_publish(
                    platform="threads", account="a", user_id="u1", token="t1",
                    text="hi2", media_urls=["https://x/1.jpg", "https://x/2.jpg"], approval={}
                ),
                "th-m",
            )
            m_thm.assert_called_once()

            self.assertEqual(
                cb._default_publish(
                    platform="instagram", account="a", user_id="u2", token="t2",
                    text="cap", media_urls=["https://x/v.mp4"], approval={}
                ),
                "ig-1",
            )
            m_ig.assert_called_once_with(
                kind="video", token="t2", user_id="u2", url="https://x/v.mp4", caption="cap"
            )

            self.assertEqual(
                cb._default_publish(
                    platform="instagram", account="a", user_id="u2", token="t2",
                    text="car", media_urls=["https://x/1.jpg", "https://x/2.jpg"], approval={}
                ),
                "ig-c",
            )
            m_igc.assert_called_once()


class SyncOnceAndCLITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.cloud = FakeCloud()

    def tearDown(self):
        self._td.cleanup()

    def test_sync_once_full_cycle_order(self):
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cloud.calls.clear()
        self.cloud.handoffs = [
            {
                "id": "ho-sync-1",
                "platform": "threads",
                "state": "s1",
                "access_token": SAMPLE_TOKEN,
                "user_id": "th-9001",
                "username": "student_alpha",
                "token_expires": "2027-01-15T00:00:00Z",
                "status": "ready",
            }
        ]
        self.cloud.approvals = [
            {
                "id": "appr-sync-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "payload": {"body": "동기화 직후 발행"},
            }
        ]

        res = cb.sync_once(
            self.home,
            http_send=self.cloud.send,
            publisher=lambda **kw: "post-sync-99",
            now=NOW,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["handoffs"]["claimed"], 1)
        self.assertEqual(len(res["heartbeat"]["linked_accounts"]), 1)
        self.assertEqual(len(res["publishes"]["published"]), 1)
        self.assertNotIn(SAMPLE_TOKEN, json.dumps(res))

        # Verify sequence: auth -> get handoffs -> patch handoff -> patch runner -> get approvals -> ...
        urls = [(c["method"], c["url"]) for c in self.cloud.calls]
        self.assertIn("/auth/v1/token", urls[0][1])
        self.assertIn("/rest/v1/link_handoff_live", urls[1][1])
        self.assertIn("/rest/v1/link_handoff?id=eq.ho-sync-1", urls[2][1])
        self.assertIn(f"/rest/v1/runner?id=eq.{SAMPLE_RUNNER_ID}", urls[3][1])
        self.assertIn("/rest/v1/approval?", urls[4][1])

    def test_sync_once_dry_run_is_strictly_read_only(self):
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)
        self.cloud.calls.clear()
        self.cloud.handoffs = [
            {
                "id": "ho-dry-1",
                "platform": "threads",
                "state": "s1",
                "access_token": SAMPLE_TOKEN,
                "user_id": "th-9001",
                "username": "student_alpha",
                "token_expires": "2027-01-15T00:00:00Z",
                "status": "ready",
            }
        ]
        self.cloud.approvals = [
            {
                "id": "appr-dry-sync-1",
                "status": "queued",
                "platform": "threads",
                "account": "student_alpha",
                "payload": {"body": "드라이런 무변이 테스트"},
            }
        ]
        called = []
        res = cb.sync_once(
            self.home,
            dry_run=True,
            http_send=self.cloud.send,
            publisher=lambda **kw: called.append(kw) or "never",
            now=NOW,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["handoffs"]["skipped_dry_run"])
        self.assertEqual(res["handoffs"]["claimed"], 0)
        self.assertTrue(res["heartbeat"]["skipped_dry_run"])
        self.assertTrue(res["publishes"]["dry_run"])
        self.assertEqual(called, [])

        # Zero cloud mutations (no link_handoff GET/PATCH, no runner PATCH, no approval PATCH, no runner_state POST)
        methods_urls = [(c["method"], c["url"]) for c in self.cloud.calls]
        self.assertEqual(len(methods_urls), 2)
        self.assertIn("/auth/v1/token", methods_urls[0][1])
        self.assertEqual(methods_urls[1][0], "GET")
        self.assertIn("/rest/v1/approval?", methods_urls[1][1])

        # Zero local state files mutated/created
        self.assertFalse((self.home / "state" / "sns-tokens.json").exists())
        self.assertFalse((self.home / "state" / "cloud-published.json").exists())
        self.assertFalse((self.home / "state" / "cloud-publish.lock").exists())

    def test_cli_status_and_pair_json(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = cb.main(["--home", str(self.home), "status", "--json"])
        self.assertEqual(rc, 0)
        st = json.loads(buf.getvalue())
        self.assertFalse(st["paired"])

        buf2 = io.StringIO()
        with mock.patch("sys.stdout", buf2):
            rc = cb.main(
                ["pair", "--home", str(self.home), "--code", SAMPLE_RAW_CODE, "--json"],
                http_send=self.cloud.send,
            )
        self.assertEqual(rc, 0)
        paired = json.loads(buf2.getvalue())
        self.assertEqual(paired["company_id"], SAMPLE_COMPANY_ID)

        buf3 = io.StringIO()
        with mock.patch("sys.stdout", buf3):
            rc = cb.main(["status", "--home", str(self.home), "--json"])
        self.assertEqual(rc, 0)
        st2 = json.loads(buf3.getvalue())
        self.assertTrue(st2["paired"])
        self.assertEqual(st2["runner_id"], SAMPLE_RUNNER_ID)
        self.assertNotIn("derived_password", st2)

    def test_ilson_shell_cloud_status_and_syntax(self):
        env = dict(os.environ, ILSON_HOME=str(self.home))
        proc = subprocess.run(
            ["bash", str(ROOT / "ilson"), "cloud", "status", "--json"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertFalse(data["paired"])
        self.assertEqual(data["published_count"], 0)

        syntax = subprocess.run(
            ["bash", "-n", str(ROOT / "ilson")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)


if __name__ == "__main__":
    unittest.main()
