"""Course pinned updates use fixture installers, never a real download or install."""
import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('course_update_test', ROOT / 'course/lib/course_update.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
p = u.payload_module()
SCRATCH = ROOT / '.scratch'


def sources():
    return {name: (ROOT / 'course' / ('' if name in ('ilson.py', 'install_payload.py') else 'lib') / name).read_text() for name in p.ALLOWED_FILES}


def installer(files, windows=False):
    values = {'payload': base64.b64encode(gzip.compress(json.dumps(files).encode())).decode(),
              'bootstrap': base64.b64encode(files['install_payload.py'].encode()).decode()}
    if windows:
        return '\n'.join('$Course'+k.title()+"='"+v+"'" for k,v in values.items()).encode()
    return '\n'.join('COURSE_'+k.upper()+"='"+v+"'" for k,v in values.items()).encode()


class CourseUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='강의 갱신 ', dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'lib'
        self.root.mkdir()

    def seed_old(self, revision='e9e41a3'):
        for name in ('ilson.py', 'license.py', 'selflearn.py', 'skill_share.py', 'weekly_summary.py', 'install_diagnostics.py'):
            data = subprocess.check_output(['git', 'show', revision+':course/'+('' if name=='ilson.py' else 'lib/')+name], cwd=ROOT)
            (self.root/name).write_bytes(data)
        return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.iterdir()}

    def pin(self, data, edition='intel-course'):
        return {'schema':1, 'edition':edition, 'source_ref':'a'*40, 'sha256':hashlib.sha256(data).hexdigest()}

    def test_pinned_installer_payload_upgrades_and_cli_rollback_restores_original_code(self):
        before = self.seed_old()
        keep = self.root.parent / 'notes.md'
        keep.write_text('개인 노트')
        keep_before = (keep.read_bytes(), keep.stat().st_mtime_ns)
        data = installer(sources())
        with mock.patch.object(u, 'payload_module', wraps=u.payload_module) as loader:
            backup = u.upgrade(self.root, self.pin(data), installer=data)
        self.assertIsNotNone(backup)
        self.assertEqual(json.loads((self.root/'.course-update-pin.json').read_text()), self.pin(data))
        env = dict(os.environ, HOME=str(self.root.parent), ILSON_COURSE_STATE=str(self.root.parent/'state'))
        result = subprocess.run([sys.executable, str(self.root/'ilson.py'), 'update', '--rollback'], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        for name,(old,_) in before.items():
            self.assertEqual((self.root/name).read_bytes(), old)
        self.assertFalse((self.root/'curator.py').exists())
        self.assertEqual((keep.read_bytes(), keep.stat().st_mtime_ns), keep_before)

    def test_windows_transport_baseline_is_a_known_upgrade_source(self):
        before = self.seed_old('67a5a67')
        data = installer(sources())
        backup = u.upgrade(self.root, self.pin(data), installer=data)
        self.assertIsNotNone(backup)
        p.rollback(self.root, backup)
        for name, (old, _) in before.items():
            self.assertEqual((self.root/name).read_bytes(), old)

    def test_windows_fixture_uses_same_bundle_without_executing_powershell(self):
        files = sources()
        data = installer(files, windows=True)
        extracted, bootstrap = u.extract(data)
        self.assertEqual(extracted, files)
        self.assertEqual(bootstrap, files['install_payload.py'].encode())
        self.assertEqual(u.validate_pin(self.pin(data, 'windows-course'), 'windows-course')['source_ref'], 'a'*40)

    def test_hash_mismatch_and_moving_refs_fail_before_installation(self):
        before = self.seed_old()
        data = installer(sources())
        with self.assertRaises(u.UpdateError):
            u.upgrade(self.root, self.pin(data), installer=data+b'changed')
        for ref in ('main', 'v1', '../ref'):
            pin = self.pin(data)
            pin['source_ref'] = ref
            with self.assertRaises(u.UpdateError):
                u.validate_pin(pin, 'intel-course')
        self.assertEqual({name: path.read_bytes() for name,path in ((x,self.root/x) for x in before)}, {name: value[0] for name,value in before.items()})
        self.assertFalse((self.root/'.install-backups').exists())

    def test_unknown_student_edit_blocks_all_code_changes(self):
        self.seed_old()
        target = self.root/'selflearn.py'
        target.write_text('# student edit')
        before = {path.name:path.read_bytes() for path in self.root.iterdir()}
        data = installer(sources())
        with self.assertRaises(ValueError):
            u.upgrade(self.root, self.pin(data), installer=data)
        for name,value in before.items():
            self.assertEqual((self.root/name).read_bytes(), value)
        self.assertFalse((self.root/'curator.py').exists())

    def test_failed_self_check_recovers_dependencies_and_entry_point(self):
        before = self.seed_old()
        data = installer(sources())
        with mock.patch.object(u, 'self_check', side_effect=u.UpdateError('SELF_CHECK_FAILED')):
            with self.assertRaises(u.UpdateError):
                u.upgrade(self.root, self.pin(data), installer=data)
        for name,(value,_) in before.items():
            self.assertEqual((self.root/name).read_bytes(), value)
        self.assertFalse((self.root/'curator.py').exists())
        self.assertFalse((self.root/'.course-update-pin.json').exists())
        with mock.patch.object(u, 'payload_module', return_value=p):
            with self.assertRaises(u.UpdateError):
                u.last_backup(self.root)

    def test_rollback_io_failure_recovers_already_restored_code(self):
        self.seed_old()
        backup = p.install(self.root, sources())
        before = {name: (self.root/name).read_bytes() for name in p.ALLOWED_FILES}
        original = p.atomic_write
        def fail_entry(path, data):
            if path.name == 'ilson.py':
                raise OSError('fixture disk failure')
            return original(path, data)
        with mock.patch.object(p, 'atomic_write', side_effect=fail_entry):
            with self.assertRaises(OSError):
                p.rollback(self.root, backup)
        for name, data in before.items():
            self.assertEqual((self.root/name).read_bytes(), data)
        p.rollback(self.root, backup)
        self.assertFalse((self.root/'curator.py').exists())

    def test_cli_without_pin_does_not_download(self):
        p.install(self.root, sources())
        env = dict(os.environ, HOME=str(self.root.parent))
        result = subprocess.run([sys.executable, str(self.root/'ilson.py'), 'update'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('PIN_REQUIRED', result.stdout)

    def test_full_and_course_aliases_status_off_and_course_auto_without_license(self):
        p.install(self.root, sources())
        env = dict(os.environ, HOME=str(self.root.parent), ILSON_COURSE_STATE=str(self.root.parent/'state'), ILSON_COURSE_VAULT=str(self.root.parent/'볼트'))
        for alias in ('diary','curator'):
            for args in (['--status'], ['--off']):
                result = subprocess.run([sys.executable, str(self.root/'ilson.py'), alias, *args], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([sys.executable, str(self.root/'ilson.py'), alias, '--auto-on'], env=env, capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('AUTO_UNSUPPORTED',result.stdout)
        self.assertFalse((self.root.parent/'볼트').exists())
        env['ILSON_HOME'] = str(self.root.parent/'box')
        for alias in ('diary','curator'):
            for flag in ('--status','--off'):
                result = subprocess.run(['bash',str(ROOT/'ilson'),alias,flag],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse((self.root.parent/'box/vault').exists())
        self.assertFalse((self.root.parent/'box/state/license').exists())

    def test_intel_suggested_rules_backed_up_refreshed_and_idempotent(self):
        source = (ROOT/'course/install-intel-mac.sh').read_text()
        code = source.split("<<'PYRULES'\n",1)[1].split('\nPYRULES',1)[0]
        target = self.root/'CLAUDE-course-suggested.md'
        target.write_text('사용자가 검토하던 옛 제안')
        original = target.read_bytes()
        rules = base64.b64encode((ROOT/'course/CLAUDE.md').read_bytes()).decode()
        for _ in range(2):
            result = subprocess.run([sys.executable,'-c',code,str(target),rules],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(target.read_bytes(),(ROOT/'course/CLAUDE.md').read_bytes())
        backups=list(self.root.glob('CLAUDE-course-suggested.*.bak.md'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),original)
        link = self.root/'link.md'
        link.symlink_to(target)
        result=subprocess.run([sys.executable,'-c',code,str(link),rules],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(target.read_bytes(),(ROOT/'course/CLAUDE.md').read_bytes())


if __name__ == '__main__':
    unittest.main()
