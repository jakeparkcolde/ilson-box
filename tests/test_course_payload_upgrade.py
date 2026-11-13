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

def sources():
    return {name:(ROOT/'course'/('' if name=='ilson.py' else 'lib')/name).read_text() for name in payload.ALLOWED_FILES}


class CourseUpgradeTests(unittest.TestCase):
    def test_baseline_and_public_versions_upgrade_and_rollback_exactly(self):
        for entry in (None,'course-legacy-ilson.py','course-skill-share-ilson.py'):
            with self.subTest(entry=entry),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve()
                for name in payload.KNOWN_HELPER_SHA256:
                    old=subprocess.check_output(['git','show','49f683a:course/'+('' if name=='ilson.py' else 'lib/')+name],cwd=ROOT)
                    (root/name).write_bytes(old)
                if entry: (root/'ilson.py').write_bytes((ROOT/'tests/fixtures'/entry).read_bytes())
                old={p.name:p.read_bytes() for p in root.iterdir()}
                backup=payload.install(root,sources())
                self.assertIsNotNone(backup)
                for name,text in sources().items(): self.assertEqual((root/name).read_text(),text)
                payload.rollback(root,backup)
                for name,data in old.items(): self.assertEqual((root/name).read_bytes(),data)
                self.assertFalse((root/'install_diagnostics.py').exists())

    def test_all_files_have_independent_known_hashes_and_modified_files_block_atomically(self):
        self.assertEqual(set(payload.KNOWN_HELPER_SHA256),{'ilson.py','selflearn.py','license.py','skill_share.py','weekly_summary.py'})
        for changed in payload.KNOWN_HELPER_SHA256:
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve()
                (root/changed).write_text('# student edit')
                before={p.name:p.read_bytes() for p in root.iterdir()}
                with self.assertRaises(ValueError): payload.install(root,sources())
                self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_write_failure_recovers_previously_replaced_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            files=sources(); files['license.py'] += '\n# reviewed future version\n'
            for name in payload.KNOWN_HELPER_SHA256:
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

    def test_rollback_refuses_later_student_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();backup=payload.install(root,sources())
            (root/'ilson.py').write_text('# new student edit')
            before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
            with self.assertRaises(ValueError): payload.rollback(root,backup)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if p.is_file()})


if __name__=='__main__':unittest.main()
