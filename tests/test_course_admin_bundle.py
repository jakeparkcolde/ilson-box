"""Admin payload contents, last published upgrade, rollback, and live-server exclusion."""
import ast
import base64
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from course_bundle import sources, target_path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('course_admin_payload',ROOT/'course/install_payload.py')
payload=importlib.util.module_from_spec(spec);spec.loader.exec_module(payload)
sys.path.insert(0,str(ROOT/'template/lib'))
import ilson_platform as platform


class AdminBundleTests(unittest.TestCase):
    def test_static_allowlist_is_fully_bundled_without_full_box_dependencies_or_fonts(self):
        files=sources()
        self.assertEqual(set(files),payload.ALLOWED_FILES)
        self.assertEqual({value[0] for value in platform.COURSE_STATIC.values()},payload.WEB_FILES)
        self.assertNotIn('replies_dispatch.py',files)
        self.assertFalse(any(name.endswith('.woff2') for name in files))
        for name,text in files.items():
            if name.endswith('.py'): ast.parse(text,filename=name,feature_version=(3,10))
        for name in ('install-windows.ps1','install-intel-mac.sh'):
            self.assertLess((ROOT/'course'/name).stat().st_size,1024*1024)

    def test_actual_last_published_embedded_bundle_upgrades_and_rolls_back(self):
        published=subprocess.check_output(['git','show','v2026.11.14.1:course/install-windows.ps1'],cwd=ROOT).decode('ascii')
        value=re.search(r"\$CoursePayload='([^']+)'",published).group(1)
        old=json.loads(gzip.decompress(base64.b64decode(value)))
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'ILSON_COURSE_STATE':str(Path(temp)/'private-state')}):
            root=Path(temp).resolve()/'lib';root.mkdir()
            for name,text in old.items():
                path=target_path(root,name);path.parent.mkdir(exist_ok=True,parents=True);path.write_text(text)
            notes=root.parent/'notes.md';notes.write_text('student notes');before=notes.stat().st_mtime_ns
            backup=payload.install(root,sources())
            self.assertTrue((root.parent/'web/course.html').is_file())
            for name,text in sources().items():self.assertEqual(target_path(root,name).read_text(),text)
            payload.rollback(root,backup)
            for name,text in old.items():self.assertEqual(target_path(root,name).read_text(),text)
            self.assertFalse((root.parent/'web/course.html').exists())
            self.assertEqual((notes.read_text(),notes.stat().st_mtime_ns),('student notes',before))

    def test_server_lock_blocks_install_and_rollback_before_any_code_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()/'lib';state=root.parent/'private-state'
            private=platform.private_dir(state/'state/web-admin')
            with patch.dict(os.environ,{'ILSON_COURSE_STATE':str(state)}):
                fd=platform.acquire_lock(private/'server.lock')
                try:
                    with self.assertRaisesRegex(ValueError,'ilson admin stop'):payload.install(root,sources())
                    self.assertFalse((root/'ilson.py').exists());self.assertFalse((root.parent/'web/course.html').exists())
                finally:os.close(fd)
                backup=payload.install(root,sources())
                fd=platform.acquire_lock(private/'server.lock')
                try:
                    with self.assertRaisesRegex(ValueError,'ilson admin stop'):payload.rollback(root,backup)
                    self.assertTrue((root/'ilson.py').exists());self.assertTrue((root.parent/'web/course.html').exists())
                finally:os.close(fd)
                payload.rollback(root,backup)
                self.assertFalse((root/'ilson.py').exists())

    def test_modified_web_file_blocks_entire_upgrade_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'ILSON_COURSE_STATE':str(Path(temp)/'state')}):
            root=Path(temp).resolve()/'lib';root.mkdir()
            target=root.parent/'web/course.js';target.parent.mkdir();target.write_text('// student edit')
            with self.assertRaises(ValueError):payload.install(root,sources())
            self.assertFalse((root/'ilson.py').exists());self.assertEqual(target.read_text(),'// student edit')
            target.unlink();backup=payload.install(root,sources());target.write_text('// later edit')
            with self.assertRaises(ValueError):payload.rollback(root,backup)
            self.assertTrue((root/'ilson.py').exists());self.assertEqual(target.read_text(),'// later edit')

    def test_installer_windows_lock_branch_uses_nonblocking_one_byte_lock(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'ILSON_COURSE_STATE':str(Path(temp))}):
            path=Path(temp)/'state/web-admin/server.lock';path.parent.mkdir(parents=True);path.write_bytes(b'0')
            fake=SimpleNamespace(LK_NBLCK=11,locking=Mock())
            proxy=SimpleNamespace(**{name:getattr(os,name) for name in dir(os) if not name.startswith('__')})
            proxy.name='nt'
            with patch.object(payload,'os',proxy),patch.dict(sys.modules,msvcrt=fake):
                with payload.admin_stopped():pass
                self.assertEqual(fake.locking.call_args.args[1:],(11,1))
                fake.locking.side_effect=OSError('busy')
                with self.assertRaisesRegex(ValueError,'ilson admin stop'):
                    with payload.admin_stopped():pass
