"""공개 게시 전 검사 시험. 임시 git 저장소와 임시 ZIP만 쓰고 네트워크를 쓰지 않는다."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FEED = 'https://feed.example/box/latest-v2.json'
# Built from pieces so this file does not match the repository privacy test or carry a real value.
PRIVATE_HOST = '.'.join(['box', 'tail' + '0a1b2c', 'ts', 'net'])
PRIVATE_FEED = 'https://' + PRIVATE_HOST + ':8443/box/latest-v2.json'
TOKEN = 'gh' + 'p_' + 'A1b2C3d4' * 4
PERSON = '/Users/' + 'someone.private'
MAIL = 'someone' + '@' + 'example.com'
CLIENT = '비밀거래처'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load('check_public_tool', ROOT / 'tools/check_public.py')
u = load('check_public_updater', ROOT / 'tools/update.py')


class CheckPublicTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = self.tmp / 'repo'
        (self.repo / 'tools').mkdir(parents=True)
        (self.repo / 'tools/update.py').write_bytes((ROOT / 'tools/update.py').read_bytes())
        (self.repo / 'plain.txt').write_text('public text\n')
        (self.repo / 'note.txt').write_text('contact ' + MAIL + ' at ' + PERSON + ' for ' + CLIENT + '\n')
        (self.repo / 'tokened.txt').write_text('key ' + TOKEN + '\n')
        (self.repo / 'hosted.txt').write_text('open https://' + PRIVATE_HOST + '/\n')
        (self.repo / 'linked.txt').symlink_to('plain.txt')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-qm', 'first')
        self.denylist = self.tmp / 'denylist.txt'
        self.denylist.write_text('# clients\n\n' + CLIENT + '\n', encoding='utf-8')

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True)

    def stage(self, rows, manifest_extra=None, drop=()):
        # rows: {member: bytes}. The manifest lists them unless named in drop.
        archive, manifest = self.tmp / 'release.zip', self.tmp / 'release-9.9.json'
        with zipfile.ZipFile(archive, 'w') as z:
            for name, data in rows.items():
                z.writestr(name, data)
        files = []
        for name in rows:
            if name not in drop:
                area, path = name.split('/', 1)
                files.append({'area': area, 'path': path, 'sha256': u.digest(rows[name])})
        release = {'schema': 1, 'version': '9.9', 'archive': archive.name, 'archive_sha256': u.digest(archive.read_bytes()), 'files': files}
        release.update(manifest_extra or {})
        manifest.write_text(json.dumps(release, ensure_ascii=False))
        return archive, manifest

    def stamped(self, feed=FEED):
        return u.stamp_feed((ROOT / 'tools/update.py').read_bytes(), feed)

    def check(self, archive, manifest, **options):
        options.setdefault('denylist', self.denylist)
        return c.check(archive, manifest, root=self.repo, **options)

    def patterns(self, found):
        return {(where, pattern) for where, pattern, _ in found}

    def test_저장소와_같고_주소만_기록한_묶음은_통과한다(self):
        report = self.check(*self.stage({'cli/tools/update.py': self.stamped(), 'cli/template/web/plain.txt': b'public text\n'}))
        self.assertFalse(report.blocked, report.blocks)
        self.assertEqual((report.members, report.new), (2, []))

    def test_기록주소도_검사한다(self):
        report = self.check(*self.stage({'cli/tools/update.py': self.stamped(PRIVATE_FEED)}))
        self.assertIn(('cli/tools/update.py', 'ts-net-host'), self.patterns(report.blocks))
        # An already-public updater does not excuse a LAN address stamped into it.
        report = self.check(*self.stage({'cli/tools/update.py': self.stamped('https://192.168.0.9/box/latest-v2.json')}))
        self.assertIn(('cli/tools/update.py FEED', 'lan-ip'), self.patterns(report.blocks))

    def test_금지항목은_이미_공개된_파일에서도_막는다(self):
        report = self.check(*self.stage({'cli/template/web/tokened.txt': b'key ' + TOKEN.encode() + b'\n', 'cli/template/web/hosted.txt': b'open https://' + PRIVATE_HOST.encode() + b'/\n'}))
        self.assertEqual(report.new, [])
        self.assertEqual({('cli/template/web/tokened.txt', 'github-token'), ('cli/template/web/hosted.txt', 'ts-net-host'), ('cli/template/web/hosted.txt', 'tailnet-label')}, self.patterns(report.blocks))

    def test_비밀과_내부주소_패턴(self):
        samples = {
            'ts-net-host': 'x.y' + '.ts' + '.net',
            'tailnet-label': 'tail' + '0a1b2c',
            'machine-host': 'mac' + 'mini-host',
            'tailnet-ip': '100.' + '100.1.2',
            'github-token': TOKEN,
            'anthropic-openai-key': 'sk-' + 'ant-' + 'a1b2c3d4' * 4,
            'google-key': 'AI' + 'za' + 'a1B2c3D4' * 5,
            'aws-key': 'AK' + 'IA' + 'A1B2C3D4E5F6G7H8',
            'slack-token': 'xo' + 'xb-' + '1234567890-abc',
            'telegram-bot': '123456789' + ':AA' + 'a1b2c3d4' * 5,
            'jwt': 'ey' + 'J' + 'a' * 20 + '.ey' + 'J' + 'b' * 20 + '.c',
            'private-key': '-----BEGIN ' + 'RSA PRIVATE KEY-----',
            'assigned-secret': 'api_key = "' + 'a1b2c3d4' * 3 + '"',
        }
        for name, sample in samples.items():
            with self.subTest(name):
                self.assertIn(name, dict(c.hits(c.HARD, sample.encode())))

    def test_버전번호와_일반단어는_내부주소가_아니다(self):
        text = b'2026.10.13.5.1 tailwind tailfade 1.100.100.1.2 100.63.1.1 172.32.0.1 10.0.0.1.5'
        self.assertEqual(c.hits(c.HARD, text), [])
        self.assertEqual(c.hits(c.SOFT, text), [])
        self.assertEqual(dict(c.hits(c.SOFT, b'go to 10.0.0.1.'))['lan-ip'], 1)

    def test_새파일은_개인정보도_막고_공개파일은_알리기만_한다(self):
        text = ('contact ' + MAIL + ' at ' + PERSON + ' for ' + CLIENT + '\n').encode()
        public = self.check(*self.stage({'cli/template/web/note.txt': text}), use_denylist=False)
        self.assertFalse(public.blocked, public.blocks)
        self.assertEqual(self.patterns(public.notes), {('cli/template/web/note.txt', 'email'), ('cli/template/web/note.txt', 'personal-home')})
        fresh = self.check(*self.stage({'cli/template/web/new.txt': text + b'changed\n'}))
        self.assertTrue(fresh.blocked)
        self.assertEqual(self.patterns(fresh.blocks), {('cli/template/web/new.txt', p) for p in ('email', 'personal-home', 'denylist-line-3')})
        self.assertEqual(fresh.new, ['cli/template/web/new.txt'])
        for sample, name in ((b'/Volumes/My Disk/x', 'external-drive'), (b'192.168.1.5', 'lan-ip'), (b'010-1234-5678', 'phone-kr')):
            with self.subTest(name):
                self.assertIn(name, {p for _, p, _ in self.check(*self.stage({'cli/template/web/new.txt': sample})).blocks})

    def test_거래처_이름은_이미_공개된_파일에서도_막는다(self):
        # A client name committed to a tracked template must not ship with 결과: 통과.
        text = ('contact ' + MAIL + ' at ' + PERSON + ' for ' + CLIENT + '\n').encode()
        report = self.check(*self.stage({'cli/template/web/note.txt': text}))
        self.assertEqual(report.new, [])
        self.assertTrue(report.blocked)
        self.assertEqual(self.patterns(report.blocks), {('cli/template/web/note.txt', 'denylist-line-3')})
        self.assertEqual(self.patterns(report.notes), {('cli/template/web/note.txt', 'email'), ('cli/template/web/note.txt', 'personal-home')})
        self.assertIn('결과: 차단 1건', report.lines())
        self.assertFalse(hasattr(report, 'warnings'))

    def test_커밋을_지정해_비교한다(self):
        (self.repo / 'plain.txt').write_text('changed ' + MAIL + '\n')
        self.git('add', 'plain.txt')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-qm', 'second')
        rows = {'cli/template/web/plain.txt': ('changed ' + MAIL + '\n').encode()}
        self.assertFalse(self.check(*self.stage(rows)).blocked)
        self.assertTrue(self.check(*self.stage(rows), commit='HEAD~1').blocked)
        with self.assertRaisesRegex(ValueError, '커밋'):
            self.check(*self.stage(rows), commit='no-such-commit')

    def commit(self, message='next'):
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-qm', message)

    def exact(self, archive, manifest, **options):
        return self.check(archive, manifest, exact_commit=True, **options)

    def not_in_commit(self, report):
        return {where for where, pattern, _ in report.blocks if pattern == 'not-in-commit'}

    def committed_rows(self):
        return {'cli/tools/update.py': self.stamped(), 'cli/template/web/plain.txt': b'tracked web file\n'}

    def track_web_file(self):
        (self.repo / 'template/web').mkdir(parents=True, exist_ok=True)
        (self.repo / 'template/web/plain.txt').write_text('tracked web file\n')
        self.commit()

    def test_커밋과_같은_묶음은_통과한다(self):
        self.track_web_file()
        report = self.exact(*self.stage(self.committed_rows()))
        self.assertFalse(report.blocked, report.blocks)

    def test_한_커밋_전에_만든_묶음은_막는다(self):
        self.track_web_file()
        rows = self.committed_rows()
        (self.repo / 'template/web/plain.txt').write_text('changed after the build\n')
        self.commit('later change')
        stage = self.stage(rows)
        self.assertFalse(self.check(*stage).blocked)
        self.assertEqual(self.not_in_commit(self.exact(*stage)), {'cli/template/web/plain.txt'})

    def test_옛_내용이_다른_경로에_있어도_낡은_묶음을_막는다(self):
        self.track_web_file()
        rows = dict(self.committed_rows(), **{'cli/template/web/plain.txt': b'public text\n'})
        report = self.exact(*self.stage(rows))
        self.assertEqual(self.not_in_commit(report), set())
        self.assertIn('commit-file-not-in-stage', {p for _, p, _ in report.blocks})

    def test_빌드뒤_추가한_파일이_묶음에_없으면_막는다(self):
        self.track_web_file()
        rows = self.committed_rows()
        (self.repo / 'template/web/added.txt').write_text('added after the build\n')
        self.commit('later file')
        report = self.exact(*self.stage(rows))
        self.assertEqual([(p, n) for _, p, n in report.blocks], [('commit-file-not-in-stage', 1)])

    def test_커밋되지_않은_내용을_담은_allow_dirty_묶음은_막는다(self):
        self.track_web_file()
        rows = dict(self.committed_rows(), **{'cli/template/web/plain.txt': b'tracked web file\nuncommitted line\n'})
        self.assertEqual(self.not_in_commit(self.exact(*self.stage(rows))), {'cli/template/web/plain.txt'})

    def test_무시된_파일을_담은_깨끗한_빌드도_막는다(self):
        self.track_web_file()
        ignored = {'cli/template/lib/__pycache__/helper.py': b'# ignored note\n', 'cli/template/web/current/.orca/notes.json': b'{"n":1}'}
        report = self.exact(*self.stage(dict(self.committed_rows(), **ignored)))
        self.assertEqual(self.not_in_commit(report), set(ignored))

    def test_팩_전용_파일은_이번_팩_버전에서만_예외다(self):
        self.track_web_file()
        pack = 'box/packs/research/0.16.9/'
        rows = dict(self.committed_rows(), **{pack + name: b'pack file ' + name.encode() for name in ('README.txt', 'manifest.json', 'serve.py', 'start.sh')})
        extra = {'research_version': '0.16.9'}
        self.assertFalse(self.exact(*self.stage(rows, extra)).blocked)
        self.assertEqual(len(self.not_in_commit(self.exact(*self.stage(rows)))), 4)
        self.assertEqual(len(self.not_in_commit(self.exact(*self.stage(rows, {'research_version': '0.16.8'})))), 4)
        other = dict(rows, **{pack + 'engine.py': b'X=1\n', 'box/packs/research/0.16.8/serve.py': b'old pack\n'})
        self.assertEqual(self.not_in_commit(self.exact(*self.stage(other, extra))), {pack + 'engine.py', 'box/packs/research/0.16.8/serve.py'})

    def test_명령행에서_커밋_고정을_켠다(self):
        archive, manifest = self.stage({'cli/template/web/new.txt': b'not in this repository\n'})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(c.main([str(archive), str(manifest), '--no-denylist']), 0)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(c.main([str(archive), str(manifest), '--no-denylist', '--exact-commit']), 1)
        self.assertIn('not-in-commit', out.getvalue())

    def test_심볼릭_링크_내용은_공개로_치지않는다(self):
        report = self.check(*self.stage({'cli/template/web/fresh.txt': b'plain.txt'}))
        self.assertEqual(report.new, ['cli/template/web/fresh.txt'])

    def test_민감한_경로와_이름을_막는다(self):
        for name in ('box/.env', 'box/.env.local', 'box/state/x.txt', 'box/vault/a.md', 'box/logs/a.txt', 'box/credentials.json',
                     'box/token.json', 'box/work.sqlite3', 'box/x.db', 'box/id.pem', 'box/server.key'):
            with self.subTest(name):
                self.assertIn((name, 'sensitive-path'), self.patterns(self.check(*self.stage({name: b'public text\n'})).blocks))
        self.assertFalse(self.check(*self.stage({'box/lib/state.py': b'public text\n'})).blocked)
        named = self.check(*self.stage({'box/' + CLIENT + '.txt': b'public text\n'}))
        self.assertIn(('box/' + CLIENT + '.txt', 'denylist-line-3'), self.patterns(named.blocks))

    def test_manifest도_검사한다(self):
        rows = {'cli/template/web/plain.txt': b'public text\n'}
        hard = self.check(*self.stage(rows, {'note': 'see https://' + PRIVATE_HOST + '/'}))
        self.assertIn(('release-9.9.json', 'ts-net-host'), self.patterns(hard.blocks))
        soft = self.check(*self.stage(rows, {'note': CLIENT + ' ' + MAIL}))
        self.assertEqual({'denylist-line-3', 'email'}, {p for _, p, _ in soft.blocks})
        archive, manifest = self.stage(dict(rows, **{'cli/template/web/extra.txt': b'public text\n'}), drop=('cli/template/web/extra.txt',))
        self.assertIn(('release-9.9.json', 'file-list-mismatch'), self.patterns(self.check(archive, manifest).blocks))
        archive, manifest = self.stage(rows, {'archive_sha256': '0' * 64})
        self.assertIn(('release-9.9.json', 'archive-hash-mismatch'), self.patterns(self.check(archive, manifest).blocks))
        manifest.write_text('not json')
        self.assertIn(('release-9.9.json', 'manifest-format'), self.patterns(self.check(archive, manifest).blocks))

    def test_찾은_값은_출력하지_않는다(self):
        text = (MAIL + ' ' + PERSON + ' ' + CLIENT + ' ' + TOKEN + ' https://' + PRIVATE_HOST + '/\n').encode()
        printed = '\n'.join(self.check(*self.stage({'cli/template/web/new.txt': text})).lines())
        self.assertIn('[차단] cli/template/web/new.txt · github-token · 1회', printed)
        for secret in (MAIL, PERSON, CLIENT, TOKEN, PRIVATE_HOST):
            self.assertNotIn(secret, printed)

    def test_한글_이름은_정규화_형식이_달라도_찾는다(self):
        import unicodedata
        text = unicodedata.normalize('NFD', CLIENT).encode()
        self.assertIn('denylist-line-3', {p for _, p, _ in self.check(*self.stage({'cli/template/web/new.txt': text})).blocks})
        self.denylist.write_text('AcMe\n', encoding='utf-8')
        self.assertTrue(self.check(*self.stage({'cli/template/web/new.txt': b'by acme inc'})).blocked)

    def test_목록이_없거나_비면_거부하고_명시하면_건너뛴다(self):
        rows = self.stage({'cli/template/web/plain.txt': b'public text\n'})
        for name, body in (('absent.txt', None), ('empty.txt', '# only a comment\n\n')):
            with self.subTest(name):
                path = self.tmp / name
                if body is not None:
                    path.write_text(body)
                with self.assertRaisesRegex(ValueError, '확인하지 않았습니다'):
                    self.check(*rows, denylist=path)
        report = self.check(*rows, denylist=self.tmp / 'absent.txt', use_denylist=False)
        self.assertFalse(report.blocked)
        self.assertIn('거래처 이름은 확인하지 않았습니다', '\n'.join(report.lines()))

    def test_명령행_종료코드(self):
        archive, manifest = self.stage({'cli/template/web/plain.txt': b'public text\n'})
        with redirect_stdout(io.StringIO()) as out:
            code = c.main([str(archive), str(manifest), '--no-denylist'])
        # The repository under test here is the real checkout, where this member is new but clean.
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn('거래처 이름은 확인하지 않았습니다', out.getvalue())
        archive, manifest = self.stage({'cli/template/web/new.txt': b'key ' + TOKEN.encode()})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(c.main([str(archive), str(manifest), '--no-denylist']), 1)
        with self.assertRaises(SystemExit) as stop:
            c.main([str(archive), str(manifest), '--denylist', str(self.tmp / 'absent.txt')])
        self.assertIn('확인하지 않았습니다', str(stop.exception.code))
        with patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
            c.main([str(archive), str(manifest), '--denylist', 'x', '--no-denylist'])


if __name__ == '__main__':
    unittest.main()
