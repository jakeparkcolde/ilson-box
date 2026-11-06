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
    def test_embedded_helpers_match_source_and_never_overwrite_edits(self):
        shell = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        windows = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        mac_bundle = re.search(r"COURSE_PAYLOAD='([^']+)'", shell).group(1)
        win_bundle = re.search(r"\$CoursePayload='([^']+)'", windows).group(1)
        self.assertEqual(mac_bundle, win_bundle)
        files = json.loads(gzip.decompress(base64.b64decode(mac_bundle)))
        self.assertEqual(files['selflearn.py'], (ROOT / 'template/lib/selflearn.py').read_text(encoding='utf-8'))
        self.assertEqual(files['license.py'], (ROOT / 'template/lib/license.py').read_text(encoding='utf-8'))
        self.assertEqual(files['ilson.py'], (ROOT / 'course/ilson.py').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '한글 폴더'
            env = dict(os.environ, ILSON_COURSE_PAYLOAD=mac_bundle)
            cmd = [sys.executable, str(ROOT / 'course/install_payload.py'), str(target)]
            self.assertEqual(subprocess.run(cmd, env=env, capture_output=True).returncode, 0)
            (target / 'ilson.py').write_text('user edit', encoding='utf-8')
            self.assertNotEqual(subprocess.run(cmd, env=env, capture_output=True).returncode, 0)
            self.assertEqual((target / 'ilson.py').read_text(encoding='utf-8'), 'user edit')

    def test_only_learning_is_locked_and_synthetic_license_unlocks_it(self):
        with tempfile.TemporaryDirectory(prefix='일손 시험 ') as tmp:
            root = Path(tmp)
            lib = root / 'lib'; lib.mkdir()
            vault = root / '한글 볼트'; vault.mkdir()
            state = root / '상태'
            shutil.copyfile(ROOT / 'course/ilson.py', lib / 'ilson.py')
            shutil.copyfile(ROOT / 'template/lib/selflearn.py', lib / 'selflearn.py')
            source = (ROOT / 'template/lib/license.py').read_text(encoding='utf-8')
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
