"""Transactional known-source course upgrades, with student edits preserved."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('course_payload',ROOT/'course/install_payload.py')
payload=importlib.util.module_from_spec(spec);spec.loader.exec_module(payload)
BASELINE_FILES = {'ilson.py', 'selflearn.py', 'license.py', 'skill_share.py', 'weekly_summary.py'}

from course_bundle import sources, target_path


class CourseUpgradeTests(unittest.TestCase):
    def test_baseline_and_public_versions_upgrade_and_rollback_exactly(self):
        for entry in (None,'course-legacy-ilson.py','course-skill-share-ilson.py'):
            with self.subTest(entry=entry),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve()/'lib';root.mkdir()
                for name in BASELINE_FILES:
                    old=subprocess.check_output(['git','show','49f683a:course/'+('' if name=='ilson.py' else 'lib/')+name],cwd=ROOT)
                    (root/name).write_bytes(old)
                if entry: (root/'ilson.py').write_bytes((ROOT/'tests/fixtures'/entry).read_bytes())
                old={p.name:p.read_bytes() for p in root.iterdir() if p.is_file() and not p.name.startswith('.')}
                backup=payload.install(root,sources())
                self.assertIsNotNone(backup)
                for name,text in sources().items(): self.assertEqual(target_path(root,name).read_text(),text)
                payload.rollback(root,backup)
                for name,data in old.items(): self.assertEqual((root/name).read_bytes(),data)
                self.assertFalse((root/'install_diagnostics.py').exists())

    def test_all_files_have_independent_known_hashes_and_modified_files_block_atomically(self):
        self.assertEqual(set(payload.KNOWN_HELPER_SHA256),payload.ALLOWED_FILES)
        for changed in payload.KNOWN_HELPER_SHA256:
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve()/'lib';root.mkdir()
                edited=target_path(root,changed);edited.parent.mkdir(parents=True,exist_ok=True);edited.write_text('# student edit')
                before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError): payload.install(root,sources())
                self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_write_failure_recovers_previously_replaced_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()/'lib';root.mkdir()
            files=sources(); files['license.py'] += '\n# reviewed future version\n'
            for name in BASELINE_FILES:
                (root/name).write_bytes(subprocess.check_output(['git','show','49f683a:course/'+('' if name=='ilson.py' else 'lib/')+name],cwd=ROOT))
            old={p.name:p.read_bytes() for p in root.iterdir()}
            original=payload.atomic_write
            def fail_entry(path,data):
                if path.name=='ilson.py': raise OSError('synthetic disk full')
                return original(path,data)
            with mock.patch.object(payload,'atomic_write',side_effect=fail_entry):
                with self.assertRaises(OSError): payload.install(root,files)
            for name,data in old.items(): self.assertEqual((root/name).read_bytes(),data)
            self.assertFalse((root/'install_diagnostics.py').exists())

    def test_known_intel_wrapper_changes_python_path_and_unknown_wrapper_is_preserved(self):
        import shlex
        source=(ROOT/'course/install-intel-mac.sh').read_text()
        code=source.split("<<'PYWRAP'\n",1)[1].split('\nPYWRAP',1)[0]
        for edited in (False,True):
            with self.subTest(edited=edited),tempfile.TemporaryDirectory() as temp:
                home=Path(temp).resolve();lib=home/'.ilson-course/lib';lib.mkdir(parents=True)
                bin_dir=home/'.local/bin';bin_dir.mkdir(parents=True)
                wrapper=bin_dir/'ilson'
                old_python="/a path/old-python/bin/python3.9"
                new_python="/a path/with'quote/bin/python3.14"
                old=('#!/bin/sh\nexec '+shlex.quote(old_python)+' -X utf8 '+shlex.quote(str(lib/'ilson.py'))+' "$@"\n').encode()
                if edited: old+=b'# student wrapper customization\n'
                wrapper.write_bytes(old)
                result=subprocess.run([__import__('sys').executable,'-c',code,new_python,str(lib),str(home),'/bin/zsh',str(home/'notes')],capture_output=True,text=True,timeout=5)
                if edited:
                    self.assertNotEqual(result.returncode,0)
                    self.assertEqual(wrapper.read_bytes(),old)
                    self.assertFalse((home/'.ilson-course/.launcher-backups').exists())
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    tokens=shlex.split(wrapper.read_text().splitlines()[1])
                    self.assertEqual(tokens[1],new_python)
                    backups=list((home/'.ilson-course/.launcher-backups').iterdir())
                    self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),old)

    def test_rollback_refuses_later_student_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()/'lib';root.mkdir();backup=payload.install(root,sources())
            (root/'ilson.py').write_text('# new student edit')
            before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
            with self.assertRaises(ValueError): payload.rollback(root,backup)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if p.is_file()})

    def test_origin_main_installation_upgrades_and_rolls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()/'lib';root.mkdir()
            current=sources()
            for name,text in current.items():
                dest=target_path(root,name);dest.parent.mkdir(parents=True,exist_ok=True)
                if name=='license.py':
                    dest.write_bytes(subprocess.check_output(['git','show','origin/main:course/lib/license.py'],cwd=ROOT))
                elif name=='install_payload.py':
                    dest.write_bytes(subprocess.check_output(['git','show','origin/main:course/install_payload.py'],cwd=ROOT))
                else:
                    dest.write_text(text,encoding='utf-8')
            old_lic=(root/'license.py').read_bytes()
            old_payload=(root/'install_payload.py').read_bytes()
            backup=payload.install(root,current)
            self.assertIsNotNone(backup)
            self.assertEqual((root/'license.py').read_text(encoding='utf-8'),current['license.py'])
            self.assertEqual((root/'install_payload.py').read_text(encoding='utf-8'),current['install_payload.py'])
            payload.rollback(root,backup)
            self.assertEqual((root/'license.py').read_bytes(),old_lic)
            self.assertEqual((root/'install_payload.py').read_bytes(),old_payload)

    def test_status_markers_crlf_and_legacy_pre_v2_license_auto_upgrade(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'lib'
            root.mkdir()
            current = sources()
            # 1. Fresh install -> HELPER_STATUS=INSTALLED
            out = io.StringIO()
            with redirect_stdout(out):
                backup = payload.install(root, current)
            self.assertIsNotNone(backup)
            self.assertIn('HELPER_STATUS=INSTALLED', out.getvalue())

            # 2. Re-run on latest -> HELPER_STATUS=UP_TO_DATE, no extra backup
            out = io.StringIO()
            with redirect_stdout(out):
                again = payload.install(root, current)
            self.assertIsNone(again)
            self.assertIn('HELPER_STATUS=UP_TO_DATE', out.getvalue())

            # 3. CRLF-normalized official license.py upgrades cleanly -> HELPER_STATUS=UPDATED
            old_lic = subprocess.check_output(['git', 'show', '49f683a:course/lib/license.py'], cwd=ROOT)
            (root / 'license.py').write_bytes(old_lic.replace(b'\n', b'\r\n'))
            out = io.StringIO()
            with redirect_stdout(out):
                upgraded = payload.install(root, current)
            self.assertIsNotNone(upgraded)
            self.assertIn('HELPER_STATUS=UPDATED', out.getvalue())
            self.assertEqual((root / 'license.py').read_text(encoding='utf-8'), current['license.py'])

            # 4. Early pre-V2 official license.py variant (without is_short_serial) upgrades + rolls back cleanly
            pre_v2 = old_lic.replace(b'# Public verification key only;', b'# Legacy pre-V2 verification key;')
            self.assertNotIn(b'is_short_serial', pre_v2)
            (root / 'license.py').write_bytes(pre_v2)
            out = io.StringIO()
            with redirect_stdout(out):
                upgraded2 = payload.install(root, current)
            self.assertIsNotNone(upgraded2)
            self.assertIn('HELPER_STATUS=UPDATED', out.getvalue())
            self.assertEqual((root / 'license.py').read_text(encoding='utf-8'), current['license.py'])
            payload.rollback(root, upgraded2)
            self.assertEqual((root / 'license.py').read_bytes(), pre_v2)


if __name__=='__main__':unittest.main()
