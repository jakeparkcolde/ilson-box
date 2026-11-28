import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "template" / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import cloud_bridge as cb  # noqa: E402
from test_cloud_bridge import FakeCloud, NOW, SAMPLE_COMPANY_ID, SAMPLE_RAW_CODE  # noqa: E402


class WikiCloudFake(FakeCloud):
    def __init__(self):
        super().__init__()
        self.spaces = {}
        self.wiki_docs = {}

    def send(self, method, url, headers, body, timeout):
        if "/rest/v1/wiki_space" in url:
            if method == "POST":
                rows = json.loads(body.decode("utf-8"))
                out = []
                for idx, row in enumerate(rows, 1):
                    slug = row["slug"]
                    if slug not in self.spaces:
                        self.spaces[slug] = {
                            "id": f"00000000-0000-0000-0000-00000000000{idx}",
                            **row,
                        }
                    out.append(self.spaces[slug])
                return 201, json.dumps(out).encode("utf-8")
        if "/rest/v1/wiki_document" in url:
            if method == "GET":
                return 200, json.dumps(list(self.wiki_docs.values())).encode("utf-8")
            if method == "POST":
                rows = json.loads(body.decode("utf-8"))
                for row in rows:
                    self.wiki_docs[row["doc_key"]] = row
                return 201, json.dumps(rows).encode("utf-8")
        return super().send(method, url, headers, body, timeout)


class CloudWikiSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.vault = Path(self._tmp.name) / "vault"
        self.vault.mkdir()
        self.cloud = WikiCloudFake()
        cb.pair_with_cloud(self.home, SAMPLE_RAW_CODE, http_send=self.cloud.send, now=NOW)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sync_wiki_collects_onboarding_company_wiki_reports_and_scrubs_secrets(self):
        (self.vault / "CONTEXT.md").write_text("# 우리 회사 컨텍스트\n대표: 김대표\n키: sk-ant-secretvalue1234567890123456\n", encoding="utf-8")
        (self.vault / "company").mkdir()
        (self.vault / "company" / "회사-소개.md").write_text("# 회사 소개\n반려동물 전문 브랜드입니다.\n", encoding="utf-8")
        (self.vault / "wiki" / "projects").mkdir(parents=True)
        (self.vault / "wiki" / "projects" / "launch.md").write_text("# 론칭 프로젝트\n일정 정리\n", encoding="utf-8")
        (self.vault / "reports" / "briefing").mkdir(parents=True)
        (self.vault / "reports" / "briefing" / "2026-11-28.md").write_text("# 아침 브리핑\n오늘 할 일 3건\n", encoding="utf-8")
        # Excluded paths must never be uploaded
        (self.vault / "reports" / "pending").mkdir(parents=True)
        (self.vault / "reports" / "pending" / "draft.md").write_text("# 비공개 초안\n비밀\n", encoding="utf-8")
        (self.vault / ".credentials").mkdir()
        (self.vault / ".credentials" / "secret.md").write_text("secret\n", encoding="utf-8")

        res = cb.sync_wiki_to_cloud(self.home, vault=self.vault, http_send=self.cloud.send)
        self.assertTrue(res["ok"])
        self.assertEqual(res["synced"], 4)
        self.assertEqual(set(res["spaces"]), {"company", "wiki", "reports"})
        self.assertIn("CONTEXT.md", self.cloud.wiki_docs)
        self.assertIn("company/회사-소개.md", self.cloud.wiki_docs)
        self.assertIn("wiki/projects/launch.md", self.cloud.wiki_docs)
        self.assertIn("reports/briefing/2026-11-28.md", self.cloud.wiki_docs)
        self.assertNotIn("reports/pending/draft.md", self.cloud.wiki_docs)
        self.assertNotIn(".credentials/secret.md", self.cloud.wiki_docs)
        # Secret scrubbed
        ctx_md = self.cloud.wiki_docs["CONTEXT.md"]["content_md"]
        self.assertNotIn("sk-ant-secretvalue1234567890123456", ctx_md)
        self.assertIn("[REDACTED_KEY]", ctx_md)
        self.assertEqual(self.cloud.wiki_docs["wiki/projects/launch.md"]["section"], "projects")
        self.assertEqual(self.cloud.wiki_docs["company/회사-소개.md"]["source"], "vault_sync")

    def test_preserves_web_docs_and_space_locked_docs(self):
        (self.vault / "company").mkdir()
        (self.vault / "company" / "web-owned.md").write_text("# 로컬 복사본\n덮어쓰면 안됨\n", encoding="utf-8")
        (self.vault / "company" / "locked.md").write_text("# 잠긴 문서\n본문 갱신\n", encoding="utf-8")
        self.cloud.wiki_docs["company/web-owned.md"] = {
            "doc_key": "company/web-owned.md",
            "space_id": "custom-space",
            "visibility": "space",
            "space_locked": False,
            "source": "web",
            "content_md": "웹 원본",
        }
        self.cloud.wiki_docs["company/locked.md"] = {
            "doc_key": "company/locked.md",
            "space_id": "owner-moved-space-id",
            "visibility": "owner_only",
            "space_locked": True,
            "source": "vault_sync",
            "content_md": "이전 본문",
        }

        res = cb.sync_wiki_to_cloud(self.home, vault=self.vault, http_send=self.cloud.send)
        self.assertEqual(res["synced"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(self.cloud.wiki_docs["company/web-owned.md"]["content_md"], "웹 원본")
        self.assertEqual(self.cloud.wiki_docs["company/locked.md"]["space_id"], "owner-moved-space-id")
        self.assertEqual(self.cloud.wiki_docs["company/locked.md"]["visibility"], "owner_only")
        self.assertIn("본문 갱신", self.cloud.wiki_docs["company/locked.md"]["content_md"])

    def test_cli_sync_wiki_dry_run_and_live(self):
        (self.vault / "CONTEXT.md").write_text("# 랑켄 회사 소개\n대표: 윤종민\n", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cb.main(
                ["--home", str(self.home), "sync-wiki", "--vault", str(self.vault), "--dry-run", "--json"],
                http_send=self.cloud.send,
            )
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["dry_run"])
        self.assertEqual(parsed["synced"], 1)
        self.assertEqual(len(self.cloud.wiki_docs), 0)

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = cb.main(
                ["--home", str(self.home), "sync-wiki", "--vault", str(self.vault), "--json"],
                http_send=self.cloud.send,
            )
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(buf2.getvalue())["synced"], 1)
        self.assertIn("CONTEXT.md", self.cloud.wiki_docs)

    def test_symlink_file_is_ignored(self):
        if os.name == "nt":
            self.skipTest("POSIX symlink test")
        outside = Path(self._tmp.name) / "outside.md"
        outside.write_text("# 외부 파일\n절대 업로드 금지\n", encoding="utf-8")
        (self.vault / "company").mkdir()
        (self.vault / "company" / "link.md").symlink_to(outside)
        res = cb.sync_wiki_to_cloud(self.home, vault=self.vault, http_send=self.cloud.send)
        self.assertEqual(res["synced"], 0)
        self.assertEqual(len(self.cloud.wiki_docs), 0)

    def test_schedule_wiki_darwin_on_status_off(self):
        import plistlib

        agents_dir = Path(self._tmp.name) / "LaunchAgents"
        ran = []

        def fake_runner(cmd):
            ran.append(cmd)
            return 0, "", ""

        res_on = cb.schedule_wiki_sync(
            self.home,
            action="on",
            time_str="22:00",
            vault=self.vault,
            platform_name="darwin",
            launch_agents_dir=agents_dir,
            command_runner=fake_runner,
            now=NOW,
        )
        self.assertTrue(res_on["ok"])
        self.assertTrue(res_on["enabled"])
        self.assertEqual(res_on["time"], "22:00")

        plist_path = agents_dir / f"{cb.WIKI_SCHEDULE_LABEL}.plist"
        self.assertTrue(plist_path.is_file())
        data = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(data["Label"], cb.WIKI_SCHEDULE_LABEL)
        self.assertEqual(data["StartCalendarInterval"], {"Hour": 22, "Minute": 0})
        self.assertFalse(data["RunAtLoad"])
        self.assertIn("sync-wiki", data["ProgramArguments"])
        self.assertIn(str(self.vault), data["ProgramArguments"])
        self.assertTrue(any(c[:2] == ["launchctl", "bootstrap"] for c in ran))

        # Reflected in status & get_status
        st = cb.schedule_wiki_sync(
            self.home,
            action="status",
            platform_name="darwin",
            launch_agents_dir=agents_dir,
            command_runner=fake_runner,
        )
        self.assertTrue(st["enabled"])
        self.assertEqual(st["time"], "22:00")
        gs = cb.get_status(self.home, now=NOW)
        self.assertEqual(gs["wiki_schedule"]["time"], "22:00")

        # Off removes plist and state
        res_off = cb.schedule_wiki_sync(
            self.home,
            action="off",
            platform_name="darwin",
            launch_agents_dir=agents_dir,
            command_runner=fake_runner,
        )
        self.assertFalse(res_off["enabled"])
        self.assertFalse(plist_path.exists())
        self.assertIsNone(cb.get_status(self.home, now=NOW)["wiki_schedule"])

    def test_schedule_wiki_windows_powershell_and_fallback(self):
        import base64

        win_vault = Path(self._tmp.name) / "일손강의-1기"
        win_vault.mkdir()
        calls = []

        def ok_ps(cmd):
            calls.append(cmd)
            return 0, "", ""

        res = cb.schedule_wiki_sync(
            self.home,
            action="on",
            time_str="22:00",
            vault=win_vault,
            platform_name="windows",
            python_exe=r"C:\Python\pythonw.exe",
            command_runner=ok_ps,
            now=NOW,
        )
        self.assertTrue(res["enabled"])
        self.assertEqual(res["target"], cb.WIKI_SCHEDULE_WIN_TASK)
        self.assertEqual(calls[0][0], "powershell.exe")
        ps_text = base64.b64decode(calls[0][-1]).decode("utf-16-le")
        self.assertIn("-StartWhenAvailable", ps_text)
        self.assertIn("-Daily -At '22:00'", ps_text)
        self.assertIn("일손강의-1기", ps_text)
        self.assertIn(cb.WIKI_SCHEDULE_WIN_TASK, ps_text)

        # Fallback to schtasks if PowerShell fails
        fb_calls = []

        def ps_fail_then_schtasks(cmd):
            fb_calls.append(cmd)
            if cmd[0] == "powershell.exe":
                return 1, "", "denied"
            return 0, "", ""

        res_fb = cb.schedule_wiki_sync(
            self.home,
            action="on",
            time_str="09:30",
            vault=win_vault,
            platform_name="windows",
            python_exe=r"C:\Python\pythonw.exe",
            command_runner=ps_fail_then_schtasks,
            now=NOW,
        )
        self.assertTrue(res_fb["enabled"])
        self.assertEqual(fb_calls[1][0], "schtasks")
        self.assertIn("09:30", fb_calls[1])

        # Off deletes task
        off_calls = []
        cb.schedule_wiki_sync(
            self.home,
            action="off",
            platform_name="windows",
            command_runner=lambda c: (off_calls.append(c) or (0, "", "")),
        )
        self.assertEqual(off_calls[0][:3], ["schtasks", "/Delete", "/TN"])

    def test_schedule_wiki_invalid_time_and_sandbox_rejected(self):
        with self.assertRaises(cb.CloudBridgeError):
            cb.schedule_wiki_sync(
                self.home,
                action="on",
                time_str="25:99",
                platform_name="darwin",
                launch_agents_dir=Path(self._tmp.name) / "la",
                command_runner=lambda c: (0, "", ""),
            )
        (self.home / "state").mkdir(exist_ok=True)
        (self.home / "state" / "sandbox").write_text("1", encoding="utf-8")
        with self.assertRaises(cb.CloudBridgeError):
            cb.schedule_wiki_sync(
                self.home,
                action="on",
                time_str="22:00",
                platform_name="darwin",
                launch_agents_dir=Path(self._tmp.name) / "la",
                command_runner=lambda c: (0, "", ""),
            )


if __name__ == "__main__":
    unittest.main()
