"""Windows-only isolated checks; deliberately keep scratch data for operator review."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(os.name == 'nt', 'Windows-specific ACL and locking checks')
class WindowsCourseTest(unittest.TestCase):
    def setUp(self):
        # The operational laptop has a no-delete rule, including test files.
        self.scratch = Path(tempfile.mkdtemp(prefix='ilson-course-test-'))
        self.vault = self.scratch / '한글 볼트'
        self.vault.mkdir()
        self.learn = load('win_learn_test', ROOT / 'template/lib/selflearn.py')
        self.license = load('win_license_test', ROOT / 'template/lib/license.py')

    def test_lock_serializes_processes_and_korean_data(self):
        store = self.learn.Store(self.vault, flat_vault=True)
        acquired = self.scratch / 'acquired'
        release = self.scratch / 'release'
        code = '''
import importlib.util, pathlib, sys, time
spec=importlib.util.spec_from_file_location('learn_child',sys.argv[1]); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
store=m.Store(sys.argv[2],flat_vault=True)
with store.locked():
 pathlib.Path(sys.argv[3]).write_text('locked')
 while not pathlib.Path(sys.argv[4]).exists(): time.sleep(.05)
'''
        child = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'template/lib/selflearn.py'),
                                  str(self.vault), str(acquired), str(release)])
        try:
            end = time.monotonic() + 15
            while not acquired.exists() and time.monotonic() < end:
                if child.poll() is not None:
                    self.fail('first lock holder exited early')
                time.sleep(.05)
            self.assertTrue(acquired.exists(), 'first lock was not acquired')
            # Nonblocking byte lock must fail while the child owns the same byte.
            import msvcrt
            fd = os.open(str(store.base / 'lock'), os.O_RDWR)
            try:
                with self.assertRaises(OSError):
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            finally:
                os.close(fd)
        finally:
            release.write_text('release')
            child.wait(timeout=15)
        with store.locked():
            state = self.learn.blank()
            state['note'] = '한글 내용'
            store.save(state)
            self.assertEqual(store.load()['note'], '한글 내용')

    def test_synthetic_serial_acl_and_offline_grace(self):
        lic = self.license
        seed = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        lic.PUBLIC_KEYS[1] = lic.public_key(seed)
        now = int(time.time())
        payload = struct.pack('>BB16sHBII', 1, 1, b'w' * 16, 1, 1, now - 30, 0xffffffff)
        serial = lic.encode_serial(payload, seed)
        def offline(*_):
            raise OSError('offline test only')
        home = self.scratch / '라이선스 상태'
        self.assertEqual(lic.evaluate(home, serial, now=now, transport=offline), (True, 'OFFLINE_GRACE'))
        self.assertEqual(lic.evaluate(home, now=now + lic.GRACE, transport=offline), (False, 'GRACE_EXPIRED'))
        directory = home / 'state/license'
        lic.windows_acl(directory)
        lic.windows_acl(directory / 'serial')
        self.assertEqual(lic.safe_read(directory / 'serial'), serial)
        with self.assertRaises(ValueError):
            lic.parse_serial('invalid', now=now)

    def test_installed_cmd_forwards_korean_json_in_an_isolated_profile(self):
        installed = os.environ.get('ILSON_TEST_INSTALLED_WRAPPER')
        if not installed:
            self.skipTest('installed wrapper not supplied')
        shadow = self.scratch / 'localappdata'
        root = shadow / 'ilson-course'
        lib = root / 'lib'; lib.mkdir(parents=True)
        bin_dir = root / 'bin'; bin_dir.mkdir()
        shutil.copyfile(installed, bin_dir / 'ilson.cmd')
        (root / 'python-path.txt').write_text(sys.executable, encoding='utf-8')
        shutil.copyfile(ROOT / 'course/ilson.py', lib / 'ilson.py')
        shutil.copyfile(ROOT / 'template/lib/selflearn.py', lib / 'selflearn.py')
        source = (ROOT / 'template/lib/license.py').read_text(encoding='utf-8')
        old = '6455f743370eba4adf230aeb65b23fc2cd4e0ff7df35108e48e2c63bf0f35feb'
        seed = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        public = self.license.public_key(seed).hex()
        self.assertEqual(source.count(old), 1)
        (lib / 'license.py').write_text(source.replace(old, public), encoding='utf-8')
        lic = load('win_synthetic_wrapper_license', lib / 'license.py')
        now = int(time.time())
        payload = struct.pack('>BB16sHBII', 1, 1, b'j' * 16, 1, 1, now - 30, 0xffffffff)
        serial = lic.encode_serial(payload, seed)
        home = self.scratch / '별도 상태'
        fake_active = lambda *_: {'status': 'active', 'server_time': now, 'paid_until': None}
        self.assertTrue(lic.evaluate(home, serial, now=now, transport=fake_active)[0])
        store = self.learn.Store(self.vault, flat_vault=True)
        state = self.learn.blank(); state['enabled'] = True; store.save(state)
        env = dict(os.environ, LOCALAPPDATA=str(shadow), ILSON_COURSE_STATE=str(home),
                   ILSON_COURSE_VAULT=str(self.vault))
        lesson = {'kind': 'correction', 'issue': 'unsupported_claim', 'action': 'check_evidence',
                  'rule': '근거를 확인합니다.'}
        result = subprocess.run(['cmd.exe', '/d', '/c', str(bin_dir / 'ilson.cmd'), 'learn', 'lesson'],
                                input=json.dumps(lesson, ensure_ascii=False), text=True, encoding='utf-8',
                                capture_output=True, env=env, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'recorded')


if __name__ == '__main__':
    unittest.main()
