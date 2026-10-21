"""리서치 팩 새로 만들기 시험. 이전 팩의 팩 전용 파일에 현재 template 코드를 얹는다."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FEED = 'https://feed.example/pack-library/downloads/box/latest-v2.json'
MANIFEST = {'id': 'research', 'version': '0.15.3', 'requires': ['python3', 'Pillow', 'pillow-heif'],
            'llm_one_of': ['claude', 'codex'], 'optional': ['tvly', 'aside']}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RefreshPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = load('refresh_pack_tool', ROOT / 'tools/refresh_pack.py')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def old_pack(self, files=None, manifest=MANIFEST, name='old.zip'):
        # A previous pack: pack-only files plus stale copies of code the template now owns.
        rows = {'manifest.json': json.dumps(manifest).encode(), 'serve.py': b'print("serve")\n',
                'start.sh': b'#!/bin/sh\nexec python3 serve.py\n', 'README.txt': b'research pack\n',
                'engine.py': b'STALE=1\n', 'obsolete_helper.py': b'OLD=1\n',
                'web/knowledge.js': b'// stale\n', 'web/obsolete.js': b'// gone\n'}
        rows.update(files or {})
        path = self.tmp / name
        with zipfile.ZipFile(path, 'w') as z:
            for key, data in rows.items():
                if data is not None:
                    z.writestr(key, data)
        return path

    def test_팩전용파일은_유지하고_코드는_현재_template으로_바꾼다(self):
        out = self.tmp / 'new.zip'
        with redirect_stdout(io.StringIO()):
            self.r.refresh(self.old_pack(), '0.16.2', out)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(manifest, dict(MANIFEST, version='0.16.2'))
            for name in ('serve.py', 'start.sh', 'README.txt'):
                self.assertIn(name, names)
            self.assertEqual(z.read('serve.py'), b'print("serve")\n')
            self.assertNotIn('obsolete_helper.py', names)
            self.assertNotIn('web/obsolete.js', names)
            for source in (ROOT / 'template/lib/research').glob('*.py'):
                self.assertEqual(z.read(source.name), source.read_bytes())
            web = ROOT / 'template/web/current/pack-library'
            for source in web.rglob('*'):
                if source.is_file():
                    self.assertEqual(z.read('web/' + source.relative_to(web).as_posix()), source.read_bytes())

    def test_새로만든_팩은_릴리스_검사를_통과한다(self):
        out = self.tmp / 'new.zip'
        with redirect_stdout(io.StringIO()):
            self.r.refresh(self.old_pack(), '0.16.2', out)
        builder = load('refresh_pack_builder', ROOT / 'tools/build_release.py')
        release = builder.build(self.tmp / 'stage', '9999.8', out, FEED)
        self.assertEqual(release['research_version'], '0.16.2')

    def test_모르는_구성이나_되돌린_버전은_거부한다(self):
        cases = {
            'wrapping folder': self.old_pack({'research-pack/manifest.json': b'{}'}, name='a.zip'),
            'nested folder': self.old_pack({'lib/extra.py': b'X=1\n'}, name='b.zip'),
            'unknown manifest key': self.old_pack(manifest=dict(MANIFEST, sha256={'engine.py': 'x'}), name='c.zip'),
            'other pack id': self.old_pack(manifest=dict(MANIFEST, id='motion'), name='d.zip'),
            'no serve.py': self.old_pack({'serve.py': None}, name='e.zip'),
            'no manifest': self.old_pack({'manifest.json': None}, name='f.zip'),
            'parent path': self.old_pack({'web/../x.js': b'1'}, name='g.zip'),
        }
        for name, pack in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.r.refresh(pack, '0.16.2', self.tmp / (name + '.zip'))
            self.assertFalse((self.tmp / (name + '.zip')).exists())
        for version in ('0.15.3', '0.15.2', '0.16', '0.16.x', ''):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.r.refresh(self.old_pack(), version, self.tmp / 'v.zip')
        linked = self.tmp / 'link.zip'
        with zipfile.ZipFile(self.old_pack(name='base.zip')) as old, zipfile.ZipFile(linked, 'w') as z:
            for info in old.infolist():
                z.writestr(info, old.read(info))
            info = zipfile.ZipInfo('web/link.js')
            info.external_attr = 0o120777 << 16
            z.writestr(info, 'knowledge.js')
        with self.assertRaises(ValueError):
            self.r.refresh(linked, '0.16.2', self.tmp / 'l.zip')

    def web_names(self):
        web = ROOT / 'template/web/current/pack-library'
        return sorted(p.relative_to(web).as_posix() for p in web.rglob('*') if p.is_file())

    def test_serve의_허용목록에_없는_웹파일은_거부한다(self):
        names = self.web_names()
        listed = "ALLOWED_FILES = {" + ", ".join(repr(n) for n in names + ['downloads/research-pack-0.1.0.zip']) + "}\n"
        out = self.tmp / 'ok.zip'
        with redirect_stdout(io.StringIO()):
            self.r.refresh(self.old_pack({'serve.py': ('import os\n' + listed).encode()}), '0.16.2', out)
        self.assertTrue(out.exists())
        short = "ALLOWED_FILES = {" + ", ".join(repr(n) for n in names[1:]) + "}\n"
        with self.assertRaisesRegex(ValueError, names[0]):
            self.r.refresh(self.old_pack({'serve.py': short.encode()}, name='short.zip'), '0.16.2', self.tmp / 'short-out.zip')
        self.assertFalse((self.tmp / 'short-out.zip').exists())

    def test_허용목록을_읽지못하거나_README버전이_다르면_한줄로_알린다(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.r.refresh(self.old_pack({'serve.py': b'ALLOWED_FILES = set(load_names())\n',
                                          'README.txt': '일손 리서치 팩 0.15.3\n'.encode()}), '0.16.2', self.tmp / 'w.zip')
        lines = out.getvalue().splitlines()
        self.assertEqual(sum('ALLOWED_FILES' in line for line in lines), 1)
        self.assertEqual(sum('README.txt' in line and '0.15.3' in line for line in lines), 1)
        with zipfile.ZipFile(self.tmp / 'w.zip') as z:
            self.assertEqual(z.read('README.txt'), '일손 리서치 팩 0.15.3\n'.encode())
        quiet = io.StringIO()
        with redirect_stdout(quiet):
            self.r.refresh(self.old_pack({'README.txt': '일손 리서치 팩 0.16.2\n'.encode()}, name='q.zip'), '0.16.2', self.tmp / 'q-out.zip')
        self.assertNotIn('README.txt', quiet.getvalue())

    def test_기존_출력파일은_덮어쓰지않는다(self):
        out = self.tmp / 'new.zip'
        out.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            self.r.refresh(self.old_pack(), '0.16.2', out)
        self.assertEqual(out.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
