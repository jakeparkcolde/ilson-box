"""배포 게시 시험. 실제 서버·네트워크 대신 임시 폴더와 가짜 HTTPS 응답을 사용한다."""
import hashlib
import importlib.util
import inspect
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
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
        self.releases, self.latest, self.tags, self.calls = {}, None, {}, []
        self.broken_latest = False
        self.prerelease, self.during_create, self.after_create = {}, None, None

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == 'api':
            return self.api(args[1])
        tag = args[2]
        if args[:2] == ['release', 'create']:
            if self.during_create:
                self.during_create(args)
            self.releases[tag] = {Path(p).name: Path(p).read_bytes() for p in args[3:] if p.startswith('/')}
            self.tags[tag] = args[args.index('--target') + 1]
            self.prerelease[tag] = '--prerelease' in args
            if self.after_create:
                self.after_create(tag)
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
                found = {'tag_name': tag, 'prerelease': self.prerelease.get(tag, True), 'assets': [{'name': n} for n in self.releases[tag]]}
        elif rest.startswith('git/ref/tags/'):
            found = {'object': {'sha': self.tags[tag], 'type': 'commit'}} if tag in self.tags else None
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
        cls.real_check = staticmethod(cls.publisher.checker.check)
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
        self.assertNotIn(str(self.stage), [str(Path(a).parent) for a in create[3:] if a.startswith('/')])
        self.assertEqual(sorted(p.name for p in self.stage.iterdir()), ['ilson-box-2026.11.3.1.zip', 'release-2026.11.3.1.json'])
        notes = create[create.index('--notes') + 1]
        self.assertEqual(notes, 'Box 2026.11.3.1 · research 0.15.0')
        self.assertIn('--github owner/ilson-box --promote', printed)
        self.assertEqual(self.hub.of('release', 'edit'), [])

    def test_기본주소는_게시_주소와_같다(self):
        self.assertEqual(u.DEFAULT_FEED, self.publisher.github_feed('jakeparkcolde/ilson-box'))
        self.assertEqual(u.DEFAULT_FEED, 'https://github.com/jakeparkcolde/ilson-box/releases/latest/download/latest-v2.json')

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
        self.check.side_effect = ValueError('차단 이름 목록이 없어 확인하지 않았습니다')
        with self.assertRaisesRegex(ValueError, '확인하지 않았습니다'):
            self.create()
        self.assertEqual(self.hub.calls, [])

    def test_공개검사는_올릴_사본을_HEAD에_고정해_검사한다(self):
        seen = {}
        def check(archive, manifest, **options):
            seen.update(zip=Path(archive), feed=Path(manifest), zip_bytes=Path(archive).read_bytes(), feed_bytes=Path(manifest).read_bytes())
            return self.report(False)
        self.check.side_effect = check
        with redirect_stdout(io.StringIO()):
            self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch, denylist=Path('/x'))
        self.assertEqual(self.check.call_args.kwargs, {'commit': SHA, 'denylist': Path('/x'), 'exact_commit': True})
        create, = self.hub.of('release', 'create')
        self.assertEqual(create[3:5], [str(seen['zip']), str(seen['feed'])])
        self.assertEqual({'ilson-box-2026.11.3.1.zip': seen['zip_bytes'], 'latest-v2.json': seen['feed_bytes']}, self.hub.releases['v2026.11.3.1'])
        self.assertFalse(seen['zip'].exists())

    def test_진짜_공개검사가_저장소에_없는_묶음을_막는다(self):
        # The stage's members are not at this commit: an older build, a dirty build or ignored files all look like this.
        with tempfile.TemporaryDirectory() as folder:
            repo, denylist = Path(folder) / 'repo', Path(folder) / 'denylist.txt'
            repo.mkdir()
            (repo / 'other.txt').write_text('other\n')
            denylist.write_text('가나다라마바사\n', encoding='utf-8')
            for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-qm', 'x']):
                subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
            def check(archive, manifest, commit, denylist, exact_commit):
                return self.real_check(archive, manifest, 'HEAD', denylist, True, repo, exact_commit)
            self.check.side_effect = check
            with redirect_stdout(io.StringIO()) as out, self.assertRaisesRegex(ValueError, '공개 검사'):
                self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch, denylist=denylist)
        self.assertIn('not-in-commit', out.getvalue())
        self.assertEqual(self.hub.calls, [])

    def test_거래처_목록_없이는_게시할_방법이_없다(self):
        self.check.side_effect = self.real_check
        with tempfile.TemporaryDirectory() as folder:
            for body in (None, '# only a comment\n'):
                path = Path(folder) / 'denylist.txt'
                if body is not None:
                    path.write_text(body)
                with self.subTest(body=body), self.assertRaises(ValueError) as refused:
                    self.publisher.create_release(self.stage, self.REPO, gh=self.hub, fetch=self.hub.fetch, denylist=path)
                self.assertIn('확인하지 않았습니다', str(refused.exception))
                self.assertNotIn('--no-denylist', str(refused.exception))
        self.assertEqual(self.hub.calls, [])
        self.assertNotIn('use_denylist', inspect.signature(self.publisher.create_release).parameters)
        source = (ROOT / 'tools/publish_release.py').read_text()
        self.assertNotIn('no-denylist', source)
        self.assertNotIn('use_denylist', source)
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as stop:
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--no-denylist'])
        self.assertEqual(stop.exception.code, 2)

    def test_만든_뒤_GitHub에서_다시_읽어_확인한다(self):
        def third(tag):
            self.hub.releases[tag]['third.bin'] = b'x'
        def missing(tag):
            self.hub.releases[tag].pop('latest-v2.json')
        def full(tag):
            self.hub.prerelease[tag] = False
        def elsewhere(tag):
            self.hub.tags[tag] = 'f' * 40
        def moved(tag):
            self.hub.latest = tag
        cases = (('파일 구성', third), ('파일 구성', missing), ('사전 공개', full), ('태그 커밋', elsewhere), ('Latest', moved))
        for word, damage in cases:
            with self.subTest(word=word, damage=damage.__name__):
                self.hub = FakeGitHub(self.REPO)
                self.hub.after_create = damage
                with self.assertRaisesRegex(ValueError, '예상과 다릅니다.*' + word):
                    self.create()

    def test_거부된_릴리스는_다시_실행해도_승격해도_거부한다(self):
        # An earlier refusal leaves the release on GitHub, so nothing may treat it as good later.
        def elsewhere(tag):
            self.hub.tags[tag] = 'f' * 40
        def full(tag):
            self.hub.prerelease[tag] = False
        for word, damage in (('태그 커밋', elsewhere), ('사전 공개', full)):
            with self.subTest(word=word):
                self.hub = FakeGitHub(self.REPO)
                self.hub.after_create = damage
                with self.assertRaisesRegex(ValueError, word):
                    self.create()
                self.hub.after_create = None
                with self.assertRaisesRegex(ValueError, word):
                    self.create()
                with self.assertRaisesRegex(ValueError, word):
                    self.promote()
                self.assertEqual(self.hub.of('release', 'edit'), [])
                self.assertIsNone(self.hub.latest)

    def test_Latest_올리기는_HEAD의_태그만_받는다(self):
        self.create()
        with patch.object(self.publisher, 'head_commit', return_value='e' * 40), self.assertRaisesRegex(ValueError, '태그 커밋'):
            self.promote()
        self.assertEqual(self.hub.of('release', 'edit'), [])

    def test_이미_Latest면_HEAD가_달라도_바이트만_확인한다(self):
        self.create()
        self.promote()
        self.hub.calls.clear()
        with patch.object(self.publisher, 'head_commit', return_value='e' * 40):
            self.assertIn('이미 Latest', self.promote())
        self.assertEqual(self.hub.of('release'), [])

    def test_스테이징이_검사중에_바뀌어도_검사한_바이트를_올린다(self):
        stage = Path(self.tmp.name) / 'stage-copy'
        shutil.copytree(self.stage, stage)
        original = self.files()
        def check(archive, manifest, **options):
            (stage / 'ilson-box-2026.11.3.1.zip').write_bytes(b'swapped after the read')
            return self.report(False)
        self.check.side_effect = check
        self.create(stage)
        self.assertEqual(self.hub.releases['v2026.11.3.1'], original)

    def test_올릴_사본이_바뀌면_gh_앞뒤에서_멈춘다(self):
        def before(archive, manifest, **options):
            Path(archive).write_bytes(b'changed after the scan')
            return self.report(False)
        self.check.side_effect = before
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.create()
        self.assertEqual(self.hub.of('release'), [])
        self.check.side_effect = None
        self.hub.during_create = lambda args: Path(args[3]).write_bytes(b'changed during the upload')
        with self.assertRaisesRegex(ValueError, '바뀌었습니다'):
            self.create()

    def test_gh_실패와_파일_오류를_깔끔하게_알린다(self):
        with patch.object(self.publisher.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 1)), self.assertRaisesRegex(ValueError, '제한 시간'):
            self.publisher.run_gh(['api', 'x'])
        with patch.object(self.publisher.subprocess, 'run', side_effect=FileNotFoundError()), self.assertRaisesRegex(ValueError, 'gh 명령'):
            self.publisher.run_gh(['api', 'x'])
        with patch.object(self.publisher.subprocess, 'run') as run:
            self.publisher.run_gh(['api', 'x'])
        self.assertEqual(run.call_args.kwargs['timeout'], self.publisher.GH_TIMEOUT)
        for error in (OSError('disk'), zipfile.BadZipFile('bad'), KeyError('version')):
            with patch.object(self.publisher, 'create_release', side_effect=error), self.assertRaises(SystemExit) as stop:
                self.publisher.main(['--stage', 's', '--github', self.REPO])
            self.assertIn('게시하지 않았습니다', str(stop.exception.code))

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
        self.hub.tags['v2026.11.3.1'] = 'abc'
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
            stage + ['--server', 'v', '--base', BASE, '--denylist', 'x'],
            stage + ['--github', self.REPO, '--promote', '--denylist', 'x'],
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
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--denylist', 'x'])
            self.publisher.main(['--stage', 's', '--github', self.REPO, '--promote'])
        self.assertEqual(create.call_args_list[0].kwargs, {'denylist': self.publisher.checker.DEFAULT_DENYLIST})
        self.assertEqual(create.call_args_list[1].kwargs, {'denylist': Path('x')})
        promote.assert_called_once_with(Path('s'), self.REPO)
        with patch.object(self.publisher, 'create_release', side_effect=ValueError('막힘')), self.assertRaises(SystemExit) as stop:
            self.publisher.main(['--stage', 's', '--github', self.REPO])
        self.assertIn('막힘', str(stop.exception.code))


if __name__ == '__main__':
    unittest.main()
