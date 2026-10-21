"""배포 게시 시험. 실제 서버·네트워크 대신 임시 폴더와 가짜 HTTPS 응답을 사용한다."""
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://feed.example/pack-library/downloads/box'
FEED = BASE + '/latest-v2.json'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


u = load('publish_test_updater', ROOT / 'tools/update.py')


class PublishReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load('publish_test_builder', ROOT / 'tools/build_release.py')
        cls.publisher = load('publish_test_publisher', ROOT / 'tools/publish_release.py')
        cls.tmp = tempfile.TemporaryDirectory()
        # build_release only accepts a pack built from the current template sources.
        pack = Path(cls.tmp.name) / 'pack.zip'
        web = ROOT / 'template/web/current/pack-library'
        with zipfile.ZipFile(pack, 'w') as z:
            z.writestr('manifest.json', json.dumps({'version': '0.15.0'}))
            for source in (ROOT / 'template/lib/research').glob('*.py'):
                z.writestr(source.name, source.read_bytes())
            for source in sorted(web.rglob('*')):
                if source.is_file():
                    z.writestr('web/' + source.relative_to(web).as_posix(), source.read_bytes())
        cls.stage = Path(cls.tmp.name) / 'stage'
        cls.release = cls.builder.build(cls.stage, '9999.5', pack, FEED)
        with zipfile.ZipFile(cls.stage / cls.release['archive']) as z:
            cls.body = z.read('cli/tools/update.py')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def server(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = Path(tmp.name) / 'box'
        server.mkdir()
        (server / 'install-updater.sh').write_text(
            "#!/bin/bash\nUPDATER='updater-2026.10.13.6.py'\nSHA='" + '0' * 64 + "'\n")
        return server

    def serve(self, server, base=BASE):
        # Answer HTTPS reads from the server folder, like the real static host would.
        def urlopen(url, timeout=None):
            self.assertTrue(url.startswith(base + '/'), url)
            return io.BytesIO((server / url[len(base) + 1:]).read_bytes())
        return patch.object(self.publisher.urllib.request, 'urlopen', side_effect=urlopen)

    def snapshot(self, server):
        return {p.name: p.read_bytes() for p in server.iterdir()}

    def restage(self, body):
        # A stage whose archive carries a different updater, with consistent hashes.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stage = Path(tmp.name)
        release = json.loads(json.dumps(self.release))
        buf = io.BytesIO()
        with zipfile.ZipFile(self.stage / release['archive']) as old, zipfile.ZipFile(buf, 'w') as new:
            for info in old.infolist():
                new.writestr(info.filename, body if info.filename == 'cli/tools/update.py' else old.read(info))
        archive = buf.getvalue()
        for item in release['files']:
            if item['area'] == 'cli' and item['path'] == 'tools/update.py':
                item['sha256'] = u.digest(body)
        release['archive_sha256'] = u.digest(archive)
        (stage / release['archive']).write_bytes(archive)
        (stage / ('release-' + release['version'] + '.json')).write_text(json.dumps(release))
        return stage

    def test_bootstrap에_주소기록본_SHA를_고정한다(self):
        server = self.server()
        with self.serve(server), redirect_stdout(io.StringIO()):
            self.publisher.publish(self.stage, server, BASE + '/')
        sha = hashlib.sha256(self.body).hexdigest()
        script = (server / 'install-updater.sh').read_text()
        self.assertIn("'" + sha + "'", script)
        self.assertIn('updater-9999.5.py', script)
        self.assertNotIn('0' * 64, script)
        self.assertEqual((server / 'updater-9999.5.py').read_bytes(), self.body)
        self.assertEqual(u.feed_of(self.body), FEED)
        self.assertNotEqual(sha, hashlib.sha256((ROOT / 'tools/update.py').read_bytes()).hexdigest())
        self.assertEqual((server / 'latest-v2.json').read_bytes(),
                         (self.stage / 'release-9999.5.json').read_bytes())

    def test_다른_배포주소는_거부하고_서버를_건드리지않는다(self):
        server = self.server()
        before = self.snapshot(server)
        other = 'https://other.example/pack-library/downloads/box'
        with self.serve(server, other) as urlopen:
            with self.assertRaisesRegex(ValueError, '주소'):
                self.publisher.publish(self.stage, server, other)
        urlopen.assert_not_called()
        self.assertEqual(self.snapshot(server), before)

    def test_도메인이전_배포는_옛주소에서_새주소를_기록해_게시한다(self):
        new_feed = 'https://new.example/box/latest-v2.json'
        stage = self.restage(u.stamp_feed(u.unstamp(self.body), new_feed))
        server = self.server()
        before = self.snapshot(server)
        # Without the explicit option the stamped feed must equal --base/latest-v2.json.
        with self.serve(server) as urlopen, self.assertRaisesRegex(ValueError, '주소'):
            self.publisher.publish(stage, server, BASE)
        urlopen.assert_not_called()
        self.assertEqual(self.snapshot(server), before)
        with self.serve(server), self.assertRaisesRegex(ValueError, '주소'):
            self.publisher.publish(stage, server, BASE, 'https://other.example/box/latest-v2.json')
        with self.serve(server), self.assertRaisesRegex(ValueError, '주소'):
            self.publisher.publish(stage, server, BASE, 'http://new.example/box/latest-v2.json')
        self.assertEqual(self.snapshot(server), before)
        with self.serve(server), redirect_stdout(io.StringIO()):
            self.publisher.publish(stage, server, BASE, new_feed)
        published = (server / 'updater-9999.5.py').read_bytes()
        self.assertEqual(u.feed_of(published), new_feed)
        self.assertIn("'" + hashlib.sha256(published).hexdigest() + "'", (server / 'install-updater.sh').read_text())

    def test_명령행에서_기록주소를_따로_지정한다(self):
        calls = []
        with patch.object(self.publisher, 'publish', side_effect=lambda *a: calls.append(a)):
            self.publisher.main(['--stage', 's', '--server', 'v', '--base', BASE])
            self.publisher.main(['--stage', 's', '--server', 'v', '--base', BASE, '--stamped-feed', 'https://new.example/x/latest-v2.json'])
        self.assertEqual([c[3] for c in calls], [None, 'https://new.example/x/latest-v2.json'])

    def test_주소없는_updater나_빌드뒤_수정한_updater는_거부한다(self):
        cases = {
            '주소': u.unstamp(self.body),
            '변경': self.body + b'\n# edited after build\n',
        }
        for message, body in cases.items():
            with self.subTest(message):
                server = self.server()
                before = self.snapshot(server)
                with self.serve(server) as urlopen:
                    with self.assertRaisesRegex(ValueError, message):
                        self.publisher.publish(self.restage(body), server, BASE)
                urlopen.assert_not_called()
                self.assertEqual(self.snapshot(server), before)


if __name__ == '__main__':
    unittest.main()
