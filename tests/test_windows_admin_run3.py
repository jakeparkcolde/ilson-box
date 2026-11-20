"""Review D23 (SF-1, notes 2-4) and Windows laptop run 3 (N2, N7), 2026-11-20.

SF-1: a folder whose propagation scan refused it left its whole subtree unrepaired, and a scan
that could not finish was reported as a link. Note 2: a fix-owner fallback that the second scan
refused had already changed the owner but counted as refused. Note 3: the refusal lines said no
file had changed. Note 4: any lock OSError read as another install. N2: an elevated doctor read
counted objects its own repair refuses as admin-owned. N7: rollback chose the backup folder with
the newest mtime, and a re-created folder made an older backup look newest.
"""
import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_windows_elevated_owner import (ME, BA, SY, OW, OI, CI, ID, ROOT, FakeWin32, node, guarded_tree, course_license, payload,
                                         diag, fake_license, nt_os, load)
from test_windows_admin_run2 import guard_layout
from course_bundle import sources
import test_course_update as cu

lic = course_license
STATE = 'C:\\Users\\me\\.ilson-course'


def elevated_state_root(*children):
    """%USERPROFILE%\\.ilson-course made by an elevated first run: mkdir(0o700) gives owner BA and a
    protected SY/BA/OW DACL with no entry for the user (the SF-1 scenario)."""
    return node(STATE, BA, [(SY, True, OI | CI), (BA, True, OI | CI), (OW, True, OI | CI)], dir=True, protected=True,
                children=[c['path'] for c in children])


def fix_owner_file(path, **flags):
    return node(path, BA, [(ME, True, ID), (SY, True, ID)], **flags)


class ScanRefusalTests(unittest.TestCase):
    """SF-1: a refused folder does not stop the repair of what lies below it."""

    def test_unscanned_folder_keeps_its_own_count_and_its_children_are_repaired(self):
        token = fix_owner_file(STATE + '\\token')
        busy = fix_owner_file(STATE + '\\busy.log', busy=True)  # open by another program: the scan cannot read it
        model = [elevated_state_root(token, busy), token, busy]
        fake = guarded_tree(model, STATE)
        self.assertEqual(fake.unscanned, 1)
        self.assertEqual(fake.actions, ['howner:' + STATE + '\\token'])  # the child, on its own handle
        self.assertEqual(fake.counts, [3, 1, 0, 0, 0, 1, 0, 0])  # busy.log: error (sharing), not refused
        self.assertEqual((model[0]['owner'], fake.propagated), (BA, []))

    def test_linked_folder_is_refused_and_its_other_children_are_repaired(self):
        token = fix_owner_file(STATE + '\\token')
        link = fix_owner_file(STATE + '\\hl.txt', links=2)
        model = [elevated_state_root(token, link), token, link]
        fake = guarded_tree(model, STATE)
        self.assertEqual((fake.actions, fake.counts, fake.unscanned), (['howner:' + STATE + '\\token'], [3, 1, 0, 0, 0, 0, 0, 2], 0))
        self.assertEqual(model[0]['owner'], BA)

    def test_scan_stops_at_protected_children(self):
        # The user's own private folder (protected, user-only) holds a hard-linked file, and a
        # protected file has a second link too. Propagation rewrites neither, so the root is repaired.
        sub = node(STATE + '\\curator', ME, [(ME, True, OI | CI)], dir=True, protected=True, children=[STATE + '\\curator\\x.json'])
        inner = node(STATE + '\\curator\\x.json', ME, [(ME, True, ID)], links=2)
        pinned = node(STATE + '\\pinned.txt', ME, [(ME, True)], protected=True, links=2)
        model = [elevated_state_root(sub, pinned), sub, inner, pinned]
        w32 = FakeWin32(model)
        self.assertIsNone(lic._linked_below(w32, STATE))
        self.assertNotIn(STATE + '\\curator\\x.json', [path for path, _ in w32.opened])  # not entered
        fake = guarded_tree(model, STATE)
        self.assertEqual(fake.actions, ['hprivate:' + STATE])
        self.assertEqual((fake.propagated, inner['rules'][0]['flags']), ([], ID))  # nothing below a protected child changed
        self.assertEqual((fake.counts, fake.unscanned), ([4, 1, 0, 0, 0, 0, 0, 0], 0))

    def test_unscanned_private_folder_is_a_storage_error_not_a_redirect(self):
        folder = 'C:\\state\\curator'
        model = [node('C:\\state', ME, [(ME, True, OI | CI)], dir=True, children=[folder]),
                 node(folder, BA, [(ME, True, OI | CI | ID)], dir=True, children=[folder + '\\x.json']),
                 node(folder + '\\x.json', ME, [(ME, True)], denied=True)]
        fake = FakeWin32(model)
        with self.assertRaises(ValueError) as caught: lic.guarded_private(folder, False, fake, ['C:\\state'])
        self.assertNotIsInstance(caught.exception, lic.GuardRefusedError)
        self.assertEqual((str(caught.exception), fake.actions, fake.handles), ('STORAGE_ERROR', [], {}))


class FallbackAfterOwnerChangeTests(unittest.TestCase):
    """Review D23 note 2: the owner already changed, so a refused fallback is an error."""

    def test_refused_fallback_after_the_owner_change_counts_as_error(self):
        r = 'C:\\ilson-course'; f = r + '\\f'
        model = [node(r, ME, [(ME, True, OI | CI)], dir=True, children=[f]),
                 node(f, BA, [(ME, True, OI | CI | ID), (SY, True, OI | CI | ID)], dir=True, ownerdrop=True, children=[f + '\\hl.txt']),
                 node(f + '\\hl.txt', ME, [(ME, True, ID)], links=2)]
        fake = guarded_tree(model, r)
        self.assertEqual(fake.actions, ['howner:' + f])  # no DACL: the scan refused the fallback
        self.assertEqual(fake.counts, [2, 0, 0, 0, 0, 1, 0, 0])  # error, not refused, not repaired
        self.assertEqual(model[1]['owner'], ME)  # what the error is about: the owner did change


class ElevatedReadTests(unittest.TestCase):
    """N2: an elevated doctor read counts what its own repair would refuse in that category."""

    def test_read_and_repair_agree_and_the_read_changes_nothing(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                r, _, model = guard_layout(nested=nested)
                w32 = FakeWin32(model)
                read = lic.guarded_tree([r], 5000, w32, repair=False)
                self.assertEqual((w32.actions, w32.propagated, w32.handles), ([], [], {}))
                self.assertFalse([path for path, write in w32.opened if write])
                repaired = guarded_tree(model, r)
                self.assertEqual(read['refused'], repaired.counts[7])
                self.assertEqual(read['admin_owned'], repaired.counts[1])
                self.assertEqual((read['refused'], read['admin_owned'], read['repaired']), (3 if nested else 2, 1, 0))

    def test_doctor_lines_for_refused_unscanned_and_repairable_together(self):
        base = {'checked': 9, 'repaired': 0, 'admin_owned': 0, 'no_access': 0, 'foreign': 0, 'error': 0, 'skipped': 0}
        tree = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'os', nt_os()), patch.dict(os.environ, {'LOCALAPPDATA': temp}), \
                patch.dict(sys.modules, license=fake_license(tree=tree)):
            tree.return_value = dict(base, refused=2, admin_owned=1)
            value = diag.windows_permissions()
            lines = diag.permission_lines(value)
            self.assertEqual((value['state'], value['unscanned'], len(lines)), ('redirected', 0, 2))
            self.assertIn('연결(바로가기)', lines[0]); self.assertIn('2개', lines[0])
            self.assertIn('--fix-permissions', lines[1]); self.assertIn('1개', lines[1])
            tree.return_value = dict(base, unscanned=1)
            value = diag.windows_permissions()
            lines = diag.permission_lines(value)
            self.assertEqual((value['state'], len(lines)), ('unscanned', 1))
            self.assertNotIn('일반 PowerShell', lines[0]); self.assertNotIn('연결(바로가기)', lines[0])
            self.assertIn('관리자: Windows PowerShell', lines[0]); self.assertIn('강사', lines[0]); self.assertIn('1개', lines[0])
            tree.return_value = dict(base, refused=1, unscanned=2)
            lines = diag.permission_lines(diag.windows_permissions())
            self.assertEqual(len(lines), 2); self.assertIn('1개', lines[0]); self.assertIn('2개', lines[1])
            with patch('builtins.print'):
                tree.return_value = dict(base, repaired=3, unscanned=1)
                self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 1)
                tree.return_value = dict(base, repaired=3)
                self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 0)

    def test_installer_names_the_unscanned_folders_without_the_normal_window(self):
        tree = Mock(return_value={'checked': 3, 'repaired': 2, 'admin_owned': 0, 'no_access': 0, 'foreign': 0, 'error': 0, 'skipped': 0,
                                  'refused': 0, 'unscanned': 1})
        module = payload.acl_module(sources()); module.windows_tree = tree
        with tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', True), \
                patch.object(payload, 'acl_module', return_value=module), patch('builtins.print') as output:
            root = Path(temp).resolve() / 'lib'; root.mkdir()
            payload.install(root, sources())
        lines = [c.args[0] for c in output.call_args_list]
        self.assertIn('HELPER_PERMISSIONS=left', lines)
        self.assertIn(module.UNSCANNED_HINT, lines)
        self.assertNotIn(module.REDIRECTED_HINT, lines); self.assertNotIn(module.ELEVATED_OWNER_HINT, lines)
        for text in (module.UNSCANNED_HINT, payload.UNSCANNED_FALLBACK):
            self.assertNotIn('일반 PowerShell', text); self.assertIn('관리자: Windows PowerShell', text)


class RefusalTextTests(unittest.TestCase):
    """Review D23 note 3: the refusal names what it left unchanged, the helper, and nothing more."""

    def test_refusal_lines_claim_only_the_helper(self):
        for code in (4, 5):
            text = diag.HELPER_REFUSALS[code][1]
            self.assertNotIn('바뀐 파일은 없습니다', text)
            self.assertIn('학습 도우미(일손 코드)는 바꾸지 않았습니다', text)
        for name in ('course/install-intel-mac.sh', 'course/lib/install_diagnostics.py', 'template/lib/install_diagnostics.py'):
            self.assertNotIn('바뀐 파일은 없습니다', (ROOT / name).read_text(encoding='utf-8'), name)


class LockContentionTests(unittest.TestCase):
    """Review D23 note 4: only a held lock reads as another install or a running admin."""

    def test_install_lock(self):
        for error, refused in ((BlockingIOError(errno.EWOULDBLOCK, 'held'), True), (OSError(errno.EIO, 'disk'), False)):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temp, patch.object(fcntl, 'flock', side_effect=error):
                root = Path(temp).resolve() / 'lib'
                with self.assertRaises(OSError if not refused else payload.Refusal) as caught:
                    with payload.update_lock(root): pass
                if refused: self.assertEqual(caught.exception.code, 'INSTALL_BUSY')
                else: self.assertNotIsInstance(caught.exception, payload.Refusal)

    def test_admin_lock(self):
        for error, refused in ((BlockingIOError(errno.EAGAIN, 'held'), True), (OSError(errno.EIO, 'disk'), False)):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temp:
                state = Path(temp).resolve() / 'state'; lock = state / 'state/web-admin/server.lock'
                lock.parent.mkdir(parents=True); lock.write_bytes(b'')
                with patch.dict(os.environ, ILSON_COURSE_STATE=str(state)), patch.object(fcntl, 'flock', side_effect=error):
                    with self.assertRaises(OSError if not refused else payload.Refusal) as caught:
                        with payload.admin_stopped(): pass
                if refused: self.assertEqual(caught.exception.code, 'ADMIN_RUNNING')
                else: self.assertNotIsInstance(caught.exception, payload.Refusal)

    def test_windows_lock_errors(self):
        with patch.object(os, 'name', 'nt'):
            windows = load('course_payload_nt_locks', ROOT / 'course/install_payload.py')
        self.assertTrue(windows.lock_held(PermissionError(errno.EACCES, 'locked')))
        self.assertFalse(windows.lock_held(OSError(errno.EIO, 'disk')))
        self.assertFalse(payload.lock_held(PermissionError(errno.EACCES, 'denied')))  # POSIX flock never reports a held lock so


class BackupChoiceTests(unittest.TestCase):
    """N7: the rollback backup is chosen from what the manifests record, never folder times."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='강의 갱신 ', dir=cu.SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'lib'
        self.root.mkdir()

    def seed(self):
        return cu.CourseUpdateTests.seed_old(self)

    def backup(self, name, manifest, age=0):
        folder = self.root / '.install-backups' / name
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        stamp = 2_000_000_000 + age  # far in the future: newer than any real backup folder
        os.utime(folder, (stamp, stamp))
        return folder

    def current(self):
        return {p.relative_to(self.root.parent): p.read_bytes() for p in self.root.parent.rglob('*')
                if p.is_file() and not {'.install-backups', '__pycache__'} & set(p.parts) and p.name not in ('.install.lock', '.course-update-pin.json')}

    def test_laptop_case_newest_folder_time_does_not_win(self):
        before = self.seed()
        data = cu.installer(sources())
        upgrade = cu.u.upgrade(self.root, {'schema': 1, 'edition': 'intel-course', 'source_ref': 'a' * 40,
                                           'sha256': cu.hashlib.sha256(data).hexdigest()}, installer=data)
        self.assertEqual(json.loads((upgrade / 'manifest.json').read_text())['seq'], 1)
        os.utime(upgrade, (1_000_000_000, 1_000_000_000))
        # An older helper's backup (no seq) whose folder was re-created later; its files are not
        # the installed ones, as on the laptop (upgrade-h2mbsztd).
        self.backup('upgrade-public', {'schema': 1, 'status': 'applied',
                                       'files': [{'name': 'ilson.py', 'before': None, 'after': 'f' * 64}]})
        with patch.object(cu.u, 'payload_module', return_value=cu.p):
            self.assertEqual(cu.u.last_backup(self.root), upgrade)
        env = dict(os.environ, HOME=str(self.root.parent), ILSON_COURSE_STATE=str(self.root.parent / 'state'))
        result = subprocess.run([sys.executable, str(self.root / 'ilson.py'), 'update', '--rollback'], capture_output=True, text=True,
                                env=env, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, (old, _) in before.items():
            self.assertEqual((self.root / name).read_bytes(), old)
        self.assertEqual(json.loads((upgrade / 'manifest.json').read_text())['status'], 'rolled_back')

    def test_numbered_backups_order_themselves_and_ties_fail(self):
        cu.p.install(self.root, sources())  # seq 1
        first = next((self.root / '.install-backups').iterdir())
        os.utime(first, (2_100_000_000, 2_100_000_000))  # the newest folder time
        files = [{'name': 'ilson.py', 'before': None, 'after': 'e' * 64}]
        second = self.backup('upgrade-second', {'schema': 1, 'seq': 2, 'status': 'applied', 'files': files})
        self.backup('upgrade-undone', {'schema': 1, 'seq': 3, 'status': 'rolled_back', 'files': files}, age=5)
        with patch.object(cu.u, 'payload_module', return_value=cu.p):
            self.assertEqual(cu.u.last_backup(self.root), second)
            # The chosen backup does not match the installed files: the rollback refuses, nothing changes.
            before = self.current()
            with self.assertRaises(ValueError): cu.p.rollback(self.root, second)
            self.assertEqual(self.current(), before)
            self.backup('upgrade-copy', {'schema': 1, 'seq': 2, 'status': 'applied', 'files': files})
            with self.assertRaises(cu.u.UpdateError) as caught: cu.u.last_backup(self.root)
            self.assertEqual(str(caught.exception), 'AMBIGUOUS_BACKUP')
        self.assertEqual(cu.p.next_backup_seq(self.root / '.install-backups'), 4)  # rolled-back numbers are never reused

    def test_unnumbered_backups_need_exactly_one_match_with_the_installed_files(self):
        cu.p.install(self.root, sources())
        installed = next((self.root / '.install-backups').iterdir())
        manifest = json.loads((installed / 'manifest.json').read_text())
        manifest.pop('seq')  # as an older helper wrote it
        (installed / 'manifest.json').write_text(json.dumps(manifest))
        os.utime(installed, (1_000_000_000, 1_000_000_000))
        stale = {'schema': 1, 'status': 'applied', 'files': [{'name': 'ilson.py', 'before': None, 'after': 'f' * 64}]}
        self.backup('upgrade-stale', stale)
        with patch.object(cu.u, 'payload_module', return_value=cu.p):
            self.assertEqual(cu.u.last_backup(self.root), installed)
            self.backup('upgrade-twin', manifest)
            with self.assertRaises(cu.u.UpdateError) as caught: cu.u.last_backup(self.root)
            self.assertEqual(str(caught.exception), 'AMBIGUOUS_BACKUP')
            for name in ('upgrade-twin', installed.name):
                path = self.root / '.install-backups' / name / 'manifest.json'
                path.write_text(json.dumps(dict(manifest, status='rolled_back')))
            with self.assertRaises(cu.u.UpdateError) as caught: cu.u.last_backup(self.root)
            self.assertEqual(str(caught.exception), 'NO_BACKUP')

    def test_cli_refuses_an_ambiguous_choice_without_changing_files(self):
        before = self.seed()
        data = cu.installer(sources())
        upgrade = cu.u.upgrade(self.root, {'schema': 1, 'edition': 'intel-course', 'source_ref': 'a' * 40,
                                           'sha256': cu.hashlib.sha256(data).hexdigest()}, installer=data)
        twin = self.root / '.install-backups' / 'upgrade-twin'
        twin.mkdir(); (twin / 'manifest.json').write_bytes((upgrade / 'manifest.json').read_bytes())
        installed = self.current()
        env = dict(os.environ, HOME=str(self.root.parent), ILSON_COURSE_STATE=str(self.root.parent / 'state'))
        result = subprocess.run([sys.executable, str(self.root / 'ilson.py'), 'update', '--rollback'], capture_output=True, text=True,
                                env=env, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn('UPDATE_FAILED', result.stderr)
        self.assertEqual(self.current(), installed)
        self.assertNotEqual({name: (self.root / name).read_bytes() for name in before}, {name: old for name, (old, _) in before.items()})


if __name__ == '__main__':
    unittest.main()
