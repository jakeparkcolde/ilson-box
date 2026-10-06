"""웹 화면 갱신과 실패 재시도를 임시 Box에서 검증한다."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebAdminUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ilson-web-update-")
        self.addCleanup(self.temp.cleanup)
        self.box = Path(self.temp.name) / "box"
        for name in ("state/web-admin", "vault/reports/briefing", "lib", ".claude", "web", "template/.git"):
            (self.box / name).mkdir(parents=True)
        shutil.copy2(ROOT / "template/lib/common.sh", self.box / "lib/common.sh")
        shutil.copy2(ROOT / "template/lib/update.sh", self.box / "lib/update.sh")
        self.package = self.box / "template/template"
        for name in ("lib", "claude/commands", "web"):
            (self.package / name).mkdir(parents=True)
        shutil.copy2(ROOT / "template/lib/common.sh", self.package / "lib/common.sh")
        (self.package / "CLAUDE.md").write_text("new instructions")
        (self.package / "open.command").write_text("#!/bin/bash\nexit 0\n")
        (self.package / "web/index.html").write_text("new web version")
        (self.package / "lib/web-admin.py").write_text(
            "import pathlib,sys\n"
            "assert sys.argv[1]=='install'\n"
            "home=pathlib.Path(sys.argv[sys.argv.index('--home')+1])\n"
            "if (home/'state/fail-web').exists():sys.exit(42)\n"
            "(home/'state/web-reloaded').write_text('yes')\n")
        notify = self.package / "lib/notify.sh"
        notify.write_text("#!/bin/bash\ncat >/dev/null\nexit 0\n")
        notify.chmod(0o700)
        self.data = self.box / "vault/reports/briefing/customer.md"
        self.data.write_text("existing customer report")
        self.secret = secrets.token_urlsafe(32)
        (self.box / "state/web-admin/token").write_text(self.secret)
        (self.box / "state/web-admin/config.json").write_text('{"version":1,"port":18794}')
        (self.box / "state/web-admin/enabled").touch()
        (self.box / "state/pairing.json").write_text(json.dumps({"update_repo": "fixture"}))
        fakebin = Path(self.temp.name) / "bin"
        fakebin.mkdir()
        git = fakebin / "git"
        git.write_text("#!/bin/bash\ncase \" $* \" in *' rev-parse '*)\n"
                       "if [ -f \"$ILSON_HOME/state/pulled\" ]; then echo bbb; "
                       "else touch \"$ILSON_HOME/state/pulled\"; echo aaa; fi;; esac\nexit 0\n")
        git.chmod(0o700)
        self.env = dict(os.environ, ILSON_HOME=str(self.box), PATH=str(fakebin) + ":" + os.environ["PATH"])

    def update(self):
        return subprocess.run(["bash", str(self.box / "lib/update.sh")], env=self.env,
                              text=True, capture_output=True, timeout=5)

    def test_화면과_서버갱신이_기존보고서와_접속정보를_보존한다(self):
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.box / "web/index.html").read_text(), "new web version")
        self.assertTrue((self.box / "state/web-reloaded").exists())
        self.assertTrue((self.box / "state/last-run.update").exists())
        self.assertEqual(self.data.read_text(), "existing customer report")
        self.assertEqual((self.box / "state/web-admin/token").read_text(), self.secret)
        self.assertFalse((self.box / "state/update-pending").exists())

    def test_관리자갱신_실패는_다음실행에서_같은리비전이어도_재시도한다(self):
        fail = self.box / "state/fail-web"
        fail.touch()
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.box / "state/update-pending").exists())
        self.assertFalse((self.box / "state/last-run.update").exists())
        fail.unlink()
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.box / "state/web-reloaded").exists())
        self.assertFalse((self.box / "state/update-pending").exists())

    def test_미설정이나_샌드박스_박스의_관리자를_자동으로_시작하지않는다(self):
        for mode in ("missing", "sandbox"):
            with self.subTest(mode=mode):
                if mode == "missing":
                    (self.box / "state/web-admin/config.json").unlink()
                else:
                    (self.box / "state/web-admin/config.json").write_text("{}")
                    (self.box / "state/sandbox").touch()
                    (self.box / "state/update-pending").touch()
                result = self.update()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((self.box / "state/web-reloaded").exists())
                self.assertEqual((self.box / "web/index.html").read_text(), "new web version")

    def test_웹폴더_심볼릭링크로_다른폴더를_덮어쓰지않는다(self):
        self.box.joinpath("web").rmdir()
        target = Path(self.temp.name) / "private-folder"
        target.mkdir()
        (target / "index.html").write_text("keep me")
        self.box.joinpath("web").symlink_to(target)
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "index.html").read_text(), "keep me")
        self.assertFalse((self.box / "state/last-run.update").exists())

    def test_사용자가_중지한_관리자는_업데이트로_다시켜지않는다(self):
        (self.box / "state/web-admin/enabled").unlink()
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.box / "state/web-reloaded").exists())
        self.assertEqual((self.box / "web/index.html").read_text(), "new web version")
        self.assertTrue((self.box / "state/web-admin/config.json").exists())


if __name__ == "__main__":
    unittest.main()
