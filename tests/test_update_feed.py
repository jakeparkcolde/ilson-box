"""업데이트 주소 보존 시험. install.sh는 임시 HOME·CLI·박스에서만 실행한다."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = 'https://legacy.example/pack-library/downloads/box/latest-v2.json'
FEED = 'https://feed.example/pack-library/downloads/box/latest-v2.json'
PRIVATE_HOST = re.compile(rb'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b', re.I)
# Built from pieces so this file does not match itself.
PRIVATE_HOMES = [b'/Users/' + name for name in (b'koldeum' + b'aegmini', b'jake' + b'_mini')]

# One list for both address checks (tools/update.py valid_feed and install.sh valid_feed).
FEED_CASES = [
    ('https://feed.example/box/latest-v2.json', True),
    ('https://h.example:10000/a/b?x=1&y=2', True),
    ('https://h/%41~_.-+', True),
    ('https://127.0.0.1:8443/x', True),
    ('https://h.example', True),
    ('https://h.example/', True),
    ('https://h:1/x', True),
    ('https://h:65535/x', True),
    ('https://h/a,b;c!d*(e)=f', True),
    ('http://h/x', False),
    ('HTTPS://h/x', False),
    ('Https://h/x', False),
    ('ftp://h/x', False),
    ('https://', False),
    ('https:///x', False),
    ('https://h:0/x', False),
    ('https://h:00000/x', False),
    ('https://h:65536/x', False),
    ('https://h:99999/x', False),
    ('https://h:/x', False),
    ('https://h:12a/x', False),
    ('https://user@h/x', False),
    ('https://user:pw@h/x', False),
    ('https://h/a@b', False),
    ('https://h/a b', False),
    ("https://h/'x", False),
    ('https://h/"x', False),
    ('https://h/`id`', False),
    ('https://h/$(id)', False),
    ('https://h/x#frag', False),
    ('https://h/x\nevil', False),
    ('https://h/x\n', False),
    ('https://h/x\t', False),
    ('https://h/x\\y', False),
    ('https://[::1]/x', False),
    ('https://-h/x', False),
    ('https://.h/x', False),
    ('https://h.example?x=1', False),
    ('https://한글.example/x', False),
    ('', False),
]


@unittest.skipUnless(sys.platform == 'darwin', 'install.sh supports macOS only')
class InstallerFeedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='ilson-feed-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home, self.box, self.cli, self.bin = (self.base / n for n in ('home', 'box', 'cli', 'bin'))
        self.home.mkdir()
        # Minimal source unit: the installer only needs ilson + template/CLAUDE.md; tools/ ships the plain updater.
        self.src = self.base / 'src'
        (self.src / 'template').mkdir(parents=True)
        (self.src / 'tools').mkdir()
        (self.src / 'ilson').write_text('#!/bin/sh\necho "ilson test"\n')
        (self.src / 'template/CLAUDE.md').write_text('# test\n')
        (self.src / 'tools/update.py').write_bytes((ROOT / 'tools/update.py').read_bytes())
        self.feed_file = self.box / '.updates/feed'

    def old_cli(self, feed_line):
        (self.cli / 'tools').mkdir(parents=True)
        (self.cli / 'ilson').write_text('#!/bin/sh\n')
        (self.cli / 'tools/update.py').write_text('import os\n' + feed_line + '\nLIMIT=1\n')

    def install(self, *args, env=None, code=0):
        environ = {k: v for k, v in os.environ.items() if not k.startswith('ILSON_')}
        environ.update(HOME=str(self.home), ILSON_SRC=str(self.src), ILSON_CLI_DIR=str(self.cli),
                       ILSON_BIN_DIR=str(self.bin), ILSON_HOME=str(self.box),
                       PATH=str(self.bin) + ':' + os.environ['PATH'], **(env or {}))
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--cli-only', *args], env=environ,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def test_기존_CLI의_내장주소를_박스에_보존한다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.install()
        self.assertEqual(self.feed_file.read_text(), LEGACY + '\n')
        # The new CLI keeps the plain source updater; the address lives on the box.
        self.assertEqual((self.cli / 'tools/update.py').read_bytes(), (ROOT / 'tools/update.py').read_bytes())

    def test_내장주소는_저장된_주소보다_우선한다(self):
        # Same order as update.py: the stamped address beats the saved one (e.g. right after a domain move).
        self.old_cli("FEED='" + LEGACY + "'")
        self.feed_file.parent.mkdir(parents=True)
        self.feed_file.write_text(FEED + '\n')
        self.install(env={'ILSON_UPDATE_FEED': 'https://env.example/latest-v2.json'})
        self.assertEqual(self.feed_file.read_text(), LEGACY + '\n')

    def test_환경변수는_저장된_올바른_주소를_덮어쓰지않는다(self):
        self.feed_file.parent.mkdir(parents=True)
        self.feed_file.write_text(FEED + '\n')
        self.install(env={'ILSON_UPDATE_FEED': 'https://env.example/latest-v2.json'})
        self.assertEqual(self.feed_file.read_text(), FEED + '\n')

    def test_잘못된_저장주소는_없는것으로_보고_채운다(self):
        self.feed_file.parent.mkdir(parents=True)
        for bad in ('http://old.example/latest-v2.json\n', 'https://a b\n', 'https://a.example/x\nhttps://b.example/y\n'):
            with self.subTest(bad=bad):
                self.feed_file.write_text(bad)
                self.install(env={'ILSON_UPDATE_FEED': FEED})
                self.assertEqual(self.feed_file.read_text(), FEED + '\n')
        self.feed_file.write_text('http://old.example/latest-v2.json\n')
        (self.cli / 'tools/update.py').write_text("FEED='" + LEGACY + "'\n")
        self.install()
        self.assertEqual(self.feed_file.read_text(), LEGACY + '\n')

    def test_feed_옵션은_저장된_주소를_바꾼다(self):
        self.feed_file.parent.mkdir(parents=True)
        self.feed_file.write_text(LEGACY + '\n')
        self.install('--feed', FEED)
        self.assertEqual(self.feed_file.read_text(), FEED + '\n')

    def test_환경변수_주소는_빈자리만_채운다(self):
        self.install(env={'ILSON_UPDATE_FEED': FEED})
        self.assertEqual(self.feed_file.read_text(), FEED + '\n')

    def test_빈주소나_잘못된주소는_쓰지않는다(self):
        self.old_cli("FEED=''")
        self.install()
        self.assertFalse(self.feed_file.exists())
        self.assertFalse((self.box / '.updates').exists())
        for bad in ['', 'http://feed.example/latest-v2.json', "https://feed.example/x'y", 'https://feed.example/a b']:
            with self.subTest(bad=bad):
                self.install('--feed', bad, code=1)
                self.assertFalse(self.feed_file.exists())
        self.install('--feed', code=1)
        self.assertFalse(self.feed_file.exists())

    def test_내장주소가_https가_아니면_옮기지않는다(self):
        self.old_cli("FEED='http://legacy.example/latest-v2.json'")
        self.install()
        self.assertFalse(self.feed_file.exists())

    def test_링크된_주소파일은_따라가지않는다(self):
        target = self.base / 'elsewhere'
        target.write_text('keep\n')
        self.feed_file.parent.mkdir(parents=True)
        self.feed_file.symlink_to(target)
        # Nothing to write: the installer leaves the link alone.
        self.install()
        self.install('--feed', FEED, code=1)
        self.assertEqual(target.read_text(), 'keep\n')
        self.assertTrue(self.feed_file.is_symlink())


    def test_기존_빈_주소파일은_없는것으로_보고_채운다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.feed_file.parent.mkdir(parents=True)
        for empty in ('', '  \n'):
            with self.subTest(empty=empty):
                self.feed_file.write_text(empty)
                self.install()
                self.assertEqual(self.feed_file.read_text(), LEGACY + '\n')
                # The reinstalled CLI has the plain source; stamp the old one again for the next round.
                (self.cli / 'tools/update.py').write_text("FEED='" + LEGACY + "'\n")

    def assert_refused_before_replacing_cli(self, *args):
        before = (self.cli / 'tools/update.py').read_bytes()
        result = self.install(*args, code=1)
        self.assertIn('업데이트 주소', result.stderr)
        # The old CLI (and the address it carries) must still be there.
        self.assertEqual((self.cli / 'tools/update.py').read_bytes(), before)

    def test_주소를_쓸수없는_자리면_CLI를_지우기전에_멈춘다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.box.mkdir()
        (self.box / '.updates').write_text('not a folder')
        self.assert_refused_before_replacing_cli()
        self.assert_refused_before_replacing_cli('--feed', FEED)
        self.assertEqual((self.box / '.updates').read_text(), 'not a folder')
        (self.box / '.updates').unlink()
        self.feed_file.mkdir(parents=True)
        self.assert_refused_before_replacing_cli()
        self.feed_file.rmdir()
        target = self.base / 'elsewhere'
        target.write_text('keep\n')
        self.feed_file.symlink_to(target)
        self.assert_refused_before_replacing_cli()
        self.assertEqual(target.read_text(), 'keep\n')

    def test_깨진_링크인_박스자리면_CLI를_지우기전에_멈춘다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.box.symlink_to(self.base / 'missing-box')
        self.assert_refused_before_replacing_cli()
        self.assertFalse((self.base / 'missing-box').exists())

    def unlock_later(self, path):
        self.addCleanup(lambda: path.exists() and path.chmod(0o700))

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root can write anywhere')
    def test_쓸수없는_박스폴더면_CLI를_지우기전에_멈춘다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        for locked in (self.box, self.box / '.updates'):
            with self.subTest(locked=locked.name):
                locked.mkdir(parents=True, exist_ok=True)
                locked.chmod(0o500)
                self.unlock_later(locked)
                self.assert_refused_before_replacing_cli()
                self.assertFalse(self.feed_file.exists())
                locked.chmod(0o700)
        # A box that does not exist yet needs a writable parent.
        (self.box / '.updates').rmdir()
        self.box.rmdir()
        self.base.chmod(0o500)
        self.unlock_later(self.base)
        self.assert_refused_before_replacing_cli()
        self.base.chmod(0o700)

    def test_박스자리가_파일이면_CLI를_지우기전에_멈춘다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.box.write_text('not a folder')
        self.assert_refused_before_replacing_cli()

    def test_주소는_임시파일을_거쳐_쓰고_남기지않는다(self):
        self.old_cli("FEED='" + LEGACY + "'")
        self.install()
        self.assertEqual(sorted(p.name for p in (self.box / '.updates').iterdir()), ['feed'])
        script = (ROOT / 'install.sh').read_text()
        self.assertIn('mktemp "$BOX_HOME/.updates/', script)
        self.assertNotIn('.tmp.$$', script)

    def test_설치기와_업데이트도구의_주소검사가_같다(self):
        function = re.search(r'^valid_feed\(\) \{.*?^\}', (ROOT / 'install.sh').read_text(), re.S | re.M).group(0)
        script = function + '\nfor u in "$@"; do if valid_feed "$u"; then echo 1; else echo 0; fi; done\n'
        shell = subprocess.run(['sh', '-c', script, 'sh', *[url for url, _ in FEED_CASES]],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(shell.returncode, 0, shell.stderr)
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('feed_case_updater', ROOT / 'tools/update.py')
            updater = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(updater)
        finally:
            sys.path.remove(str(ROOT / 'tools'))
        for (url, expected), answer in zip(FEED_CASES, shell.stdout.split()):
            with self.subTest(url=url):
                self.assertEqual(updater.valid_feed(url), expected, 'update.py')
                self.assertEqual(answer == '1', expected, 'install.sh')
        self.assertEqual(len(shell.stdout.split()), len(FEED_CASES))


class RepositoryPrivacyTests(unittest.TestCase):
    def test_저장소에_tailnet_호스트와_개인_홈경로가_없다(self):
        listed = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                cwd=ROOT, capture_output=True)
        if listed.returncode != 0:
            self.skipTest('git checkout required')
        found = []
        for name in filter(None, listed.stdout.decode().split('\0')):
            path = ROOT / name
            if not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            if PRIVATE_HOST.search(data) or any(home in data for home in PRIVATE_HOMES):
                found.append(name)
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
