"""Exercise the course command with a synthetic key and no production requests."""
import importlib.util
import base64
import gzip
import json
import os
from pathlib import Path
import shutil
import struct
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEED = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
PUBLIC = 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'
PRODUCTION_PUBLIC = '6455f743370eba4adf230aeb65b23fc2cd4e0ff7df35108e48e2c63bf0f35feb'


class CourseLearnTest(unittest.TestCase):
    def test_flat_vault_keeps_lessons_inside_visible_vault(self):
        spec = importlib.util.spec_from_file_location('course_flat_learn', ROOT / 'course/lib/selflearn.py')
        learn = importlib.util.module_from_spec(spec); spec.loader.exec_module(learn)
        with tempfile.TemporaryDirectory(prefix='일손 볼트 ') as tmp:
            course = Path(tmp)
            store = learn.Store(course, flat_vault=True)
            target = store.resolve('vault/lessons/approved-learning.md')
            store.transact([(target, None, '한글 기준\n'.encode('utf-8'))])
            self.assertEqual(target.read_text(encoding='utf-8'), '한글 기준\n')
            self.assertEqual(store.recorded_path(target), 'vault/lessons/approved-learning.md')
            self.assertFalse((course / 'vault').exists())

    def test_flat_approved_summary_transaction(self):
        spec = importlib.util.spec_from_file_location('course_export', ROOT / 'course/lib/selflearn.py')
        learn = importlib.util.module_from_spec(spec); spec.loader.exec_module(learn)
        with tempfile.TemporaryDirectory(prefix='강의 볼트 ') as tmp:
            vault = Path(tmp)
            store = learn.Store(vault, flat_vault=True)
            state = learn.blank()
            state['proposals'] = [{'id': 'p', 'type': 'skill', 'status': 'approved', 'name': '문서 정리'},
                                  {'id': 'q', 'type': 'skill', 'status': 'pending', 'name': '미승인 초안'}]
            state['history'] = [{'id': 'h', 'proposal_id': 'p', 'type': 'skill', 'status': 'applied', 'at': '2026-11-08T00:00:00+00:00'}]
            store.transact([store.weekly_summary_change(state)])
            result = (vault / 'reports/weekly/.learning-summary.json').read_text(encoding='utf-8')
            self.assertIn('문서 정리', result)
            self.assertNotIn('미승인 초안', result)
            self.assertFalse((vault / 'vault').exists())

    def test_weekly_command_uses_flat_vault_and_license_check(self):
        with tempfile.TemporaryDirectory(prefix='강의 볼트 ') as tmp:
            root = Path(tmp)
            lib = root / 'lib'; lib.mkdir()
            vault = root / '한글 볼트'; vault.mkdir()
            shutil.copyfile(ROOT / 'course/ilson.py', lib / 'ilson.py')
            shutil.copyfile(ROOT / 'course/lib/weekly_summary.py', lib / 'weekly_summary.py')
            (lib / 'license.py').write_text('import sys; sys.exit(0)\n', encoding='utf-8')
            env = dict(os.environ, ILSON_COURSE_VAULT=str(vault), ILSON_COURSE_STATE=str(root / 'state'))
            result = subprocess.run([sys.executable, str(lib / 'ilson.py'), 'report', 'weekly'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list((vault / 'reports/weekly').glob('*-ilson.md'))), 1)
            self.assertFalse((vault / 'vault').exists())
            (lib / 'license.py').write_text('import sys; sys.exit(1)\n', encoding='utf-8')
            self.assertNotEqual(subprocess.run([sys.executable, str(lib / 'ilson.py'), 'report', 'weekly'], env=env, capture_output=True).returncode, 0)

    def test_embedded_helpers_match_source_and_never_overwrite_edits(self):
        shell = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        windows = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        mac_bundle = re.search(r"COURSE_PAYLOAD='([^']+)'", shell).group(1)
        win_bundle = re.search(r"\$CoursePayload='([^']+)'", windows).group(1)
        self.assertEqual(mac_bundle, win_bundle)
        files = json.loads(gzip.decompress(base64.b64decode(mac_bundle)))
        self.assertEqual(files['selflearn.py'], (ROOT / 'course/lib/selflearn.py').read_text(encoding='utf-8'))
        self.assertEqual(files['license.py'], (ROOT / 'course/lib/license.py').read_text(encoding='utf-8'))
        self.assertEqual(files['ilson.py'], (ROOT / 'course/ilson.py').read_text(encoding='utf-8'))
        self.assertEqual(files['weekly_summary.py'], (ROOT / 'course/lib/weekly_summary.py').read_text(encoding='utf-8'))
        self.assertEqual(files['skill_share.py'], (ROOT / 'course/lib/skill_share.py').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '한글 폴더'
            env = dict(os.environ)
            cmd = [sys.executable, str(ROOT / 'course/install_payload.py'), str(target)]
            self.assertEqual(subprocess.run(cmd, env=env, input=mac_bundle.encode(), capture_output=True).returncode, 0)
            (target / 'ilson.py').write_text('user edit', encoding='utf-8')
            self.assertNotEqual(subprocess.run(cmd, env=env, input=mac_bundle.encode(), capture_output=True).returncode, 0)
            self.assertEqual((target / 'ilson.py').read_text(encoding='utf-8'), 'user edit')

    def test_known_legacy_entry_point_upgrades_but_user_changes_are_preserved(self):
        shell = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        payload = re.search(r"COURSE_PAYLOAD='([^']+)'", shell).group(1)
        files = json.loads(gzip.decompress(base64.b64decode(payload)))
        legacy = (ROOT / 'tests/fixtures/course-legacy-ilson.py').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in ('license.py', 'selflearn.py'):
                (target / name).write_text(files[name], encoding='utf-8')
            (target / 'ilson.py').write_bytes(legacy)
            env = dict(os.environ)
            cmd = [sys.executable, str(ROOT / 'course/install_payload.py'), str(target)]
            result = subprocess.run(cmd, env=env, input=payload.encode(), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual((target / 'ilson.py').read_text(encoding='utf-8'), files['ilson.py'])
            self.assertEqual((target / 'skill_share.py').read_text(encoding='utf-8'), files['skill_share.py'])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in ('license.py', 'selflearn.py'):
                (target / name).write_text(files[name], encoding='utf-8')
            (target / 'ilson.py').write_bytes(legacy + b'\n# user edit\n')
            env = dict(os.environ)
            cmd = [sys.executable, str(ROOT / 'course/install_payload.py'), str(target)]
            self.assertNotEqual(subprocess.run(cmd, env=env, input=payload.encode(), capture_output=True).returncode, 0)
            self.assertEqual((target / 'ilson.py').read_bytes(), legacy + b'\n# user edit\n')
            self.assertFalse((target / 'skill_share.py').exists())

    def test_skill_share_course_entry_point_upgrades(self):
        shell = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        payload = re.search(r"COURSE_PAYLOAD='([^']+)'", shell).group(1)
        files = json.loads(gzip.decompress(base64.b64decode(payload)))
        previous = (ROOT / 'tests/fixtures/course-skill-share-ilson.py').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for name in ('license.py', 'selflearn.py', 'skill_share.py'):
                (target / name).write_text(files[name], encoding='utf-8')
            (target / 'ilson.py').write_bytes(previous)
            env = dict(os.environ)
            result = subprocess.run([sys.executable, str(ROOT / 'course/install_payload.py'), str(target)], env=env, input=payload.encode(), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual((target / 'ilson.py').read_text(encoding='utf-8'), files['ilson.py'])

    def test_only_learning_is_locked_and_synthetic_license_unlocks_it(self):
        with tempfile.TemporaryDirectory(prefix='일손 시험 ') as tmp:
            root = Path(tmp)
            lib = root / 'lib'; lib.mkdir()
            vault = root / '한글 볼트'; vault.mkdir()
            state = root / '상태'
            shutil.copyfile(ROOT / 'course/ilson.py', lib / 'ilson.py')
            shutil.copyfile(ROOT / 'course/lib/selflearn.py', lib / 'selflearn.py')
            source = (ROOT / 'course/lib/license.py').read_text(encoding='utf-8')
            self.assertEqual(source.count(PRODUCTION_PUBLIC), 1)
            (lib / 'license.py').write_text(source.replace(PRODUCTION_PUBLIC, PUBLIC), encoding='utf-8')
            spec = importlib.util.spec_from_file_location('course_synthetic_license', lib / 'license.py')
            lic = importlib.util.module_from_spec(spec); spec.loader.exec_module(lic)
            env = dict(os.environ, ILSON_COURSE_STATE=str(state), ILSON_COURSE_VAULT=str(vault))

            def invoke(*args):
                return subprocess.run([sys.executable, '-X', 'utf8', str(lib / 'ilson.py'), *args],
                                      env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)

            self.assertEqual(invoke('--help').returncode, 0)
            blocked = invoke('learn', 'status')
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn('NO_LICENSE', blocked.stdout)
            self.assertFalse((vault / '.ilson-learning').exists())
            now = int(time.time())
            payload = struct.pack('>BB16sHBII', 1, 1, b't' * 16, 1, 1, now - 100, 0xffffffff)
            serial = lic.encode_serial(payload, SEED)
            active = lambda *_: {'status': 'active', 'server_time': now, 'paid_until': None}
            self.assertTrue(lic.evaluate(state, serial, now=now, transport=active)[0])
            result = invoke('learn', 'status')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)['enabled'])
            self.assertTrue((vault / '.ilson-learning').is_dir())
            self.assertFalse((vault / 'vault').exists())


if __name__ == '__main__':
    unittest.main()
