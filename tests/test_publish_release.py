"""배포 게시 시험. 실제 서버·네트워크 대신 임시 폴더와 가짜 HTTPS 응답을 사용한다."""
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://feed.example/pack-library/downloads/box'
FEED = BASE + '/latest-v2.json'
SHA = 'a1b2c3d4' * 5


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


class FakeGitHub:
    """Stands in for gh and for anonymous downloads. Tests never run the real gh or open a connection."""
    def __init__(self, repo, commits=(SHA,)):
        self.repo, self.commits = repo, set(commits)
        self.releases, self.latest, self.tags, self.calls = {}, None, set(), []
        self.broken_latest = False

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == 'api':
            return self.api(args[1])
        tag = args[2]
        if args[:2] == ['release', 'create']:
            self.releases[tag] = {Path(p).name: Path(p).read_bytes() for p in args[3:] if p.startswith('/')}
            self.tags.add(tag)
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        if args[:2] == ['release', 'edit']:
            self.latest = tag
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        raise AssertionError(args)

    def api(self, path):
        base = 'repos/' + self.repo + '/'
        self.assert_prefix(path, base)
        rest = path[len(base):]
        tag = rest.rsplit('/', 1)[-1]
        found = None
        if rest.startswith('commits/'):
            found = {'sha': tag} if tag in self.commits else None
        elif rest == 'releases/latest':
            found = {'tag_name': self.latest, 'assets': []} if self.latest else None
        elif rest.startswith('releases/tags/'):
            if tag in self.releases:
                found = {'tag_name': tag, 'assets': [{'name': n} for n in self.releases[tag]]}
        elif rest.startswith('git/ref/tags/'):
            found = {'ref': tag} if tag in self.tags else None
        else:
            raise AssertionError(path)
        if found is None:
            return SimpleNamespace(returncode=1, stdout=b'{}', stderr=b'gh: Not Found (HTTP 404)')
        return SimpleNamespace(returncode=0, stdout=json.dumps(found).encode(), stderr=b'')

    def assert_prefix(self, path, base):
        if not path.startswith(base):
            raise AssertionError(path)

    def fetch(self, url):
        host = 'https://github.com/' + self.repo + '/releases/'
        if not url.startswith(host):
            raise AssertionError(url)
        rest = url[len(host):]
        if rest.startswith('latest/download/'):
            if self.broken_latest or self.latest is None:
                raise OSError('404')
            tag, name = self.latest, rest.rsplit('/', 1)[1]
        else:
            tag, name = rest.split('/')[1:]
        return self.releases[tag][name]

    def of(self, *head):
        return [c for c in self.calls if c[:len(head)] == list(head)]


class GitHubPublishTests(unittest.TestCase):
    REPO = 'owner/ilson-box'
    FEED = 'https://github.com/owner/ilson-box/releases/latest/download/latest-v2.json'

    @classmethod
    def setUpClass(cls):
        cls.builder = load('github_test_builder', ROOT / 'tools/build_release.py')
        cls.publisher = load('github_test_publisher', ROOT / 'tools/publish_release.py')
        cls.tmp = tempfile.TemporaryDirectory()
        pack = Path(cls.tmp.name) / 'pack.zip'
        web = ROOT / 'template/web/current/pack-library'
        with zipfile.ZipFile(pack, 'w') as z:
            z.writestr('manifest.json', json.dumps({'version': '0.15.0'}))
            for source in (ROOT / 'template/lib/research').glob('*.py'):
                z.writestr(source.name, source.read_bytes())
            for source in sorted(web.rglob('*')):
                if source.is_file():
                    z.writestr('web/' + source.relative_to(web).as_posix(), source.read_bytes())
        cls.pack = pack
        cls.stage = cls.make_stage('2026.11.3.1')

    @classmethod
    def make_stage(cls, version, feed=None):
        stage = Path(cls.tmp.name) / ('stage-' + version)
        with redirect_stdout(io.StringIO()):
            cls.builder.build(stage, version, cls.pack, feed or cls.FEED)
        return stage

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.hub = FakeGitHub(self.REPO)
        for name, value in (('dirty_files', []),):
            guard = patch.object(self.publisher.builder, name, return_value=value)
            self.dirty = guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(self.publisher, 'head_commit', return_value=SHA)
        guard.start()
        self.addCleanup(guard.stop)
        guard = patch.object(self.publisher.checker, 'check', return_value=self.report(False))
        self.check = guard.start()
        self.addCleanup(guard.stop)

    def report(self, blocked):
        return SimpleNamespace(blocked=blocked, lines=lambda: ['공개 검사 시험'])

    def create(self, stage=None):
        with redirect_stdout(io.StringIO()) as out:
            self.publisher.create_release(stage or self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch)
        return out.getvalue()

    def promote(self, stage=None, **options):
        options.setdefault('sleep', lambda seconds: None)
        with redirect_stdout(io.StringIO()) as out:
            self.publisher.promote_release(stage or self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch, **options)
        return out.getvalue()

    def files(self, stage=None):
        stage = stage or self.stage
        release = json.loads(next(stage.glob('release-*.json')).read_text())
        return {release['archive']: (stage / release['archive']).read_bytes(),
                'latest-v2.json': next(stage.glob('release-*.json')).read_bytes()}

    def test_올리기는_파일_둘을_사전공개로_올리고_Latest를_옮기지_않는다(self):
        printed = self.create()
        self.assertEqual(self.hub.releases['v2026.11.3.1'], self.files())
        self.assertIsNone(self.hub.latest)
        create, = self.hub.of('release', 'create')
        self.assertEqual(create[2], 'v2026.11.3.1')
        for option in (['--repo', self.REPO], ['--target', SHA], ['--prerelease'], ['--latest=false']):
            self.assertIn(option[0], create)
            if len(option) == 2:
                self.assertEqual(create[create.index(option[0]) + 1], option[1])
        assets = [Path(a).name for a in create[3:] if a.startswith('/')]
        self.assertEqual(assets, ['ilson-box-2026.11.3.1.zip', 'latest-v2.json'])
        self.assertNotIn(str(self.stage), [str(Path(a).parent) for a in create[4:] if a.startswith('/')])
        self.assertEqual(sorted(p.name for p in self.stage.iterdir()), ['ilson-box-2026.11.3.1.zip', 'release-2026.11.3.1.json'])
        notes = create[create.index('--notes') + 1]
        self.assertEqual(notes, 'Box 2026.11.3.1 · research 0.15.0')
        self.assertIn('--github owner/ilson-box --promote', printed)
        self.assertEqual(self.hub.of('release', 'edit'), [])

    def test_clobber와_updater_파일은_어디에도_쓰지_않는다(self):
        self.create()
        self.create()
        self.promote()
        for call in self.hub.calls:
            self.assertNotIn('--clobber', call)
            self.assertFalse([a for a in call if 'updater-' in a or 'install-updater' in a], call)

    def test_Latest_올리기와_확인(self):
        self.create()
        printed = self.promote()
        self.assertEqual(self.hub.latest, 'v2026.11.3.1')
        edit, = self.hub.of('release', 'edit')
        self.assertEqual(edit, ['release', 'edit', 'v2026.11.3.1', '--repo', self.REPO, '--prerelease=false', '--latest'])
        self.assertIn('Latest 확인 완료', printed)

    def test_Latest_확인은_update와_같은_주소를_읽는다(self):
        self.create()
        seen = []
        def fetch(url):
            seen.append(url)
            return self.hub.fetch(url)
        with redirect_stdout(io.StringIO()):
            self.publisher.promote_release(self.stage, self.REPO, gh=self.hub, fetch=fetch)
        self.assertEqual(seen[-2:], [self.FEED, u.urllib.parse.urljoin(self.FEED, 'ilson-box-2026.11.3.1.zip')])

    def test_이미_Latest면_고치지_않고_성공한다(self):
        self.create()
        self.promote()
        self.hub.calls.clear()
        self.assertIn('이미 Latest', self.promote())
        self.assertEqual(self.hub.of('release'), [])

    def test_Latest_전파를_기다리고_끝내_다르면_알린다(self):
        self.create()
        waits = []
        self.hub.broken_latest = True
        with self.assertRaisesRegex(ValueError, '공개 주소'):
            self.promote(sleep=waits.append, attempts=3, wait=7)
        self.assertEqual(waits, [7, 7])
        answers = iter([OSError('not yet'), None])
        real = self.hub.fetch
        def late(url):
            if '/latest/' in url:
                answer = next(answers, None)
                if answer:
                    raise answer
            return real(url)
        self.hub.broken_latest = False
        with redirect_stdout(io.StringIO()) as out:
            self.publisher.promote_release(self.stage, self.REPO, gh=self.hub, fetch=late, sleep=lambda s: None)
        self.assertIn('Latest 확인 완료', out.getvalue())

    def test_낮거나_같은_버전은_거부한다(self):
        for latest in ('v2026.11.3.1', 'v2026.11.3.2', 'v2026.12.1.1'):
            with self.subTest(latest=latest):
                self.hub.latest = latest
                with self.assertRaisesRegex(ValueError, 'Latest'):
                    self.create()
                self.assertEqual(self.hub.of('release'), [])
        self.hub.latest = 'v2026.10.28.4'
        self.create()
        self.assertIn('v2026.11.3.1', self.hub.releases)

    def test_Latest를_낮은_버전으로_옮기지_않는다(self):
        self.create()
        self.hub.latest = 'v2026.12.1.1'
        with self.assertRaisesRegex(ValueError, '낮은 버전'):
            self.promote()
        self.assertEqual(self.hub.of('release', 'edit'), [])

    def test_커밋하지_않은_변경이_있으면_gh를_부르지_않는다(self):
        self.dirty.return_value = [' M tools/update.py']
        with self.assertRaisesRegex(ValueError, '커밋하지 않은'):
            self.create()
        self.assertEqual(self.hub.calls, [])

    def test_push하지_않은_HEAD는_거부한다(self):
        self.hub.commits.clear()
        with self.assertRaisesRegex(ValueError, 'push'):
            self.create()
        self.assertEqual(self.hub.of('release'), [])

    def test_GitHub_확인이_실패하면_없는것으로_치지_않는다(self):
        failing = lambda args: SimpleNamespace(returncode=1, stdout=b'', stderr=b'gh: Bad credentials (HTTP 401)')
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'GitHub 확인 실패'):
            self.publisher.create_release(self.stage, self.REPO, gh=failing, fetch=self.hub.fetch)

    def test_기록주소가_다른_저장소면_거부한다(self):
        with self.assertRaisesRegex(ValueError, '주소'):
            self.publisher.create_release(self.stage, 'other/repo', gh=self.hub, fetch=self.hub.fetch)
        stage = self.make_stage('2026.11.3.2', 'https://feed.example/box/latest-v2.json')
        for run in (self.publisher.create_release, self.publisher.promote_release):
            with self.assertRaisesRegex(ValueError, '주소'):
                run(stage, self.REPO, gh=self.hub, fetch=self.hub.fetch)
        self.assertEqual(self.hub.calls, [])
        self.check.assert_not_called()

    def test_저장소_이름_형식을_확인한다(self):
        for bad in ('owner', 'owner/repo/x', '-x/y', 'owner/re po', '../x'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'OWNER/REPO'):
                self.publisher.create_release(self.stage, bad, gh=self.hub, fetch=self.hub.fetch)
        self.assertEqual(self.hub.calls, [])

    def test_공개검사에_막히면_gh를_한번도_부르지_않는다(self):
        self.check.return_value = self.report(True)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, '공개 검사'):
            self.create()
        self.assertEqual(self.hub.calls, [])

    def test_거래처_목록이_없으면_gh를_부르지_않는다(self):
        self.check.side_effect = ValueError('거래처 이름 목록이 없어 확인하지 않았습니다')
        with self.assertRaisesRegex(ValueError, '확인하지 않았습니다'):
            self.create()
        self.assertEqual(self.hub.calls, [])

    def test_공개검사에_스테이징과_목록설정을_넘긴다(self):
        with redirect_stdout(io.StringIO()):
            self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch, denylist=Path('/x'), use_denylist=False)
        args, options = self.check.call_args
        self.assertEqual(args[0], self.stage / 'ilson-box-2026.11.3.1.zip')
        self.assertEqual(args[1], self.stage / 'release-2026.11.3.1.json')
        self.assertEqual(options, {'denylist': Path('/x'), 'use_denylist': False})

    def test_이미_있는_릴리스는_같으면_이어가고_다르면_멈춘다(self):
        self.create()
        self.hub.calls.clear()
        self.assertIn('--promote', self.create())
        self.assertEqual(self.hub.of('release'), [])
        self.hub.releases['v2026.11.3.1']['latest-v2.json'] = b'{"other":1}'
        before = dict(self.hub.releases['v2026.11.3.1'])
        with self.assertRaisesRegex(ValueError, '덮어쓰지'):
            self.create()
        self.assertEqual(self.hub.of('release'), [])
        self.assertEqual(self.hub.releases['v2026.11.3.1'], before)

    def test_이미_있는_릴리스의_파일구성이_다르면_멈춘다(self):
        self.create()
        extra = dict(self.hub.releases['v2026.11.3.1'], **{'install-updater.sh': b'#'})
        for assets in (extra, {'latest-v2.json': self.files()['latest-v2.json']}):
            self.hub.releases['v2026.11.3.1'] = assets
            with self.subTest(names=sorted(assets)):
                with self.assertRaisesRegex(ValueError, '파일 구성'):
                    self.create()
                with self.assertRaisesRegex(ValueError, '파일 구성'):
                    self.promote()

    def test_릴리스_없는_같은_태그는_거부한다(self):
        self.hub.tags.add('v2026.11.3.1')
        with self.assertRaisesRegex(ValueError, '태그'):
            self.create()
        self.assertEqual(self.hub.of('release'), [])

    def test_올린_뒤_공개_다운로드가_다르면_멈춘다(self):
        def fetch(url):
            return b'different'
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, '다릅니다'):
            self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=fetch)
        def offline(url):
            raise OSError('down')
        self.hub = FakeGitHub(self.REPO)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, '공개 다운로드 실패'):
            self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=offline)

    def test_올리지_않은_버전은_Latest로_올릴수_없다(self):
        with self.assertRaisesRegex(ValueError, '먼저'):
            self.promote()
        self.assertEqual(self.hub.of('release'), [])

    def test_Latest_올리기_전에_공개_파일을_다시_확인한다(self):
        self.create()
        self.hub.releases['v2026.11.3.1']['ilson-box-2026.11.3.1.zip'] = b'tampered'
        with self.assertRaisesRegex(ValueError, '다릅니다'):
            self.promote()
        self.assertEqual(self.hub.of('release', 'edit'), [])

    def test_명령행_선택지는_서로_배타적이다(self):
        stage = ['--stage', 's']
        refused = [
            stage,
            stage + ['--server', 'v'],
            stage + ['--base', BASE],
            stage + ['--github', self.REPO, '--server', 'v'],
            stage + ['--github', self.REPO, '--base', BASE],
            stage + ['--github', self.REPO, '--server', 'v', '--base', BASE],
            stage + ['--github', self.REPO, '--stamped-feed', self.FEED],
            stage + ['--server', 'v', '--base', BASE, '--promote'],
            stage + ['--server', 'v', '--base', BASE, '--no-denylist'],
            stage + ['--server', 'v', '--base', BASE, '--denylist', 'x'],
            stage + ['--github', self.REPO, '--denylist', 'x', '--no-denylist'],
            stage + ['--github', self.REPO, '--promote', '--no-denylist'],
        ]
        with patch.object(self.publisher, 'publish') as publish, patch.object(self.publisher, 'create_release') as create, \
                patch.object(self.publisher, 'promote_release') as promote:
            for argv in refused:
                with self.subTest(argv=argv), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as stop:
                    self.publisher.main(argv)
                self.assertEqual(stop.exception.code, 2)
            publish.assert_not_called(); create.assert_not_called(); promote.assert_not_called()

    def test_명령행은_올리기와_Latest_올리기를_나눈다(self):
        with patch.object(self.publisher, 'create_release') as create, patch.object(self.publisher, 'promote_release') as promote:
            self.publisher.main(['--stage', 's', '--github', self.REPO])
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--no-denylist'])
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--denylist', 'x'])
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--promote'])
        self.assertEqual(create.call_args_list[0].kwargs, {'denylist': self.publisher.checker.DEFAULT_DENYLIST, 'use_denylist': True})
        self.assertFalse(create.call_args_list[1].kwargs['use_denylist'])
        self.assertEqual(create.call_args_list[2].kwargs['denylist'], Path('x'))
        promote.assert_called_once_with(Path('s'), self.REPO)
        with patch.object(self.publisher, 'create_release', side_effect=ValueError('막힘')), self.assertRaises(SystemExit) as stop:
            self.publisher.main(['--stage', 's', '--github', self.REPO])
        self.assertIn('막힘', str(stop.exception.code))


if __name__ == '__main__':
    unittest.main()
