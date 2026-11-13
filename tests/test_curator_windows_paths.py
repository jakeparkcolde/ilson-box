"""Win32 directory traversal simulations; real course bootstrap/CLI on the host OS."""
import base64
from contextlib import ExitStack
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('curator_windows_test', ROOT / 'template/lib/curator.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
SCRATCH = ROOT / '.scratch'
SCRATCH.mkdir(exist_ok=True)


def win_error(number):
    cls = FileNotFoundError if number in (2, 3) else PermissionError if number == 5 else OSError
    error = cls('PRIVATE path must never be printed')
    error.winerror = number
    return error


class WindowsDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='curator-win 한글 ', dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.kernel = mock.Mock()
        self.kernel.CreateFileW.side_effect = lambda *_: self.kernel.CreateFileW.call_count
        self.acl = mock.Mock()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(ctypes, 'WinDLL', return_value=self.kernel, create=True))
        self.stack.enter_context(mock.patch.object(ctypes, 'WinError', side_effect=win_error, create=True))
        self.stack.enter_context(mock.patch.object(ctypes, 'get_last_error', return_value=32, create=True))
        self.stack.enter_context(mock.patch.object(c, 'license_module', return_value=SimpleNamespace(windows_acl=self.acl)))

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch('sys.stdout', out), mock.patch('sys.stderr', err):
            code = c.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_missing_state_status_is_off_all_editions_without_creating_or_reading_notes(self):
        with mock.patch.object(c, 'directory', c.windows_directory), \
                mock.patch.object(c, 'collect_notes', side_effect=AssertionError('note read')), \
                mock.patch.object(c, 'candidates', side_effect=AssertionError('enumeration')):
            for edition in ('full-mac', 'intel-course', 'windows-course'):
                with self.subTest(edition=edition):
                    home = self.home / edition
                    code, out, err = self.cli('--home', str(home), '--edition', edition, '--status')
                    self.assertEqual((code, err), (0, ''))
                    self.assertFalse(json.loads(out)['enabled'])
                    self.assertFalse(home.exists())
        self.acl.assert_not_called()
        self.assertEqual(self.kernel.CloseHandle.call_count, self.kernel.CreateFileW.call_count)

    def test_first_off_and_on_create_private_state_and_locks_without_vault_reads(self):
        with mock.patch.object(c, 'directory', c.windows_directory), \
                mock.patch.object(c, 'collect_notes', side_effect=AssertionError('note read')):
            for edition in ('full-mac', 'intel-course', 'windows-course'):
                for option in ('--off', '--on'):
                    with self.subTest(edition=edition, option=option):
                        home = self.home / edition / option[2:]
                        args = ['--home', str(home), '--edition', edition]
                        with mock.patch('sys.stdin.isatty', return_value=True), mock.patch('builtins.input', return_value='y'):
                            self.assertEqual(self.cli(*args, option)[0], 0)
                        store = c.Store(home, edition)
                        self.assertEqual(store.enabled(), option == '--on')
                        self.assertTrue((store.state / 'run.lock').is_file())
                        self.assertTrue((store.state / 'config.lock').is_file())
                        self.assertFalse(store.vault.exists())
        self.assertTrue(any(call.kwargs.get('create') for call in self.acl.call_args_list))

    def test_missing_vault_is_missing_not_reparse_and_existing_empty_vault_can_publish(self):
        store = c.Store(self.home)
        with mock.patch.object(c, 'directory', c.windows_directory):
            c.set_enabled(store, True)
            with self.assertRaises(FileNotFoundError):
                c.run_once(store, license_check=lambda *_: True)
            store.vault.mkdir()
            notes, counts = c.collect_notes(store, 0, 1)
            self.assertEqual(notes, [])
            self.assertEqual(counts, dict(read=0, excluded=0, limited=0, failed=0))
            self.assertEqual(c.run_once(store, license_check=lambda *_: True), 'OK')
            self.assertEqual(len(list((store.vault / 'journal/curator').glob('*.md'))), 1)
        self.assertEqual(self.kernel.CloseHandle.call_count, self.kernel.CreateFileW.call_count)

    def test_existing_file_at_directory_is_not_misreported_as_missing(self):
        target = self.home / 'state'
        target.write_text('not a directory')
        with self.assertRaisesRegex(c.CuratorError, '^PATH_NOT_DIRECTORY$'):
            with c.windows_directory(target):
                self.fail('unsafe directory entered')

    def test_native_missing_sharing_access_errors_release_already_pinned_handles(self):
        for number, expected in ((2, 'PATH_MISSING'), (3, 'PATH_MISSING'), (32, 'SHARING_VIOLATION'),
                                 (33, 'LOCK_VIOLATION'), (5, 'ACCESS_DENIED'), (267, 'PATH_NOT_DIRECTORY')):
            with self.subTest(number=number):
                self.kernel.reset_mock()
                self.kernel.CreateFileW.side_effect = [101, ctypes.c_void_p(-1).value]
                with mock.patch.object(ctypes, 'get_last_error', return_value=number):
                    with self.assertRaises(OSError) as raised:
                        with c.windows_directory(self.home):
                            self.fail('failed open entered')
                self.assertEqual(c.io_code(raised.exception), expected)
                self.kernel.CloseHandle.assert_called_once_with(101)
                call = self.kernel.CreateFileW.call_args.args
                self.assertEqual((call[1], call[2], call[5]), (0x80, 3, 0x02200000))

    def test_missing_state_race_at_native_open_is_optional_but_sharing_is_not(self):
        for number in (2, 3, 32):
            with self.subTest(number=number), mock.patch.object(c, 'directory', c.windows_directory), \
                    mock.patch.object(ctypes, 'get_last_error', return_value=number):
                self.kernel.CreateFileW.side_effect = None
                self.kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
                if number in (2, 3):
                    self.assertEqual(c.load_json(self.home / 'config.json'), {'schema': 1})
                else:
                    with self.assertRaises(OSError) as raised:
                        c.load_json(self.home / 'config.json')
                    self.assertEqual(c.io_code(raised.exception), 'SHARING_VIOLATION')

    def test_cloud_tags_symlink_mount_and_unknown_reparse_remain_blocked_before_open(self):
        tags = [(0x9000001A | (i << 12), 'CLOUD_FOLDER_UNSUPPORTED') for i in range(16)]
        tags += [(0xA0000003, 'PATH_MOUNT_POINT_UNSUPPORTED'), (0xA000000C, 'PATH_SYMLINK_UNSUPPORTED'),
                 (0x80000021, 'PATH_REPARSE_UNSUPPORTED'), (0xDEADBEEF, 'PATH_REPARSE_UNSUPPORTED')]
        for tag, code in tags:
            with self.subTest(tag=hex(tag)):
                info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400, st_reparse_tag=tag)
                self.kernel.reset_mock()
                with mock.patch.object(Path, 'lstat', return_value=info):
                    with self.assertRaisesRegex(c.CuratorError, '^' + code + '$'):
                        with c.windows_directory(self.home):
                            self.fail('reparse directory entered')
                self.kernel.CreateFileW.assert_not_called()

    def test_cloud_file_is_not_opened_or_hydrated(self):
        path = self.home / 'cloud-only.md'
        path.write_text('must not be opened')
        real_lstat = Path.lstat
        def cloud_info(item, *args, **kwargs):
            if item == path:
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=0x1400,
                                       st_reparse_tag=0x9000601A)
            return real_lstat(item, *args, **kwargs)
        with mock.patch.object(Path, 'lstat', cloud_info), mock.patch.object(os, 'open', side_effect=AssertionError('hydration')), \
                mock.patch.object(c, 'directory', c.windows_directory):
            with self.assertRaisesRegex(c.CuratorError, '^CLOUD_FILE_UNSUPPORTED$'):
                c.read_file(path)

    def test_offline_and_recall_attributes_are_rejected_without_confusing_extended_attributes(self):
        for attributes in (0x1000, 0x400000, 0x401000):
            for mode, kind in ((stat.S_IFREG, 'FILE'), (stat.S_IFDIR, 'FOLDER')):
                with self.subTest(attributes=attributes, kind=kind):
                    info = SimpleNamespace(st_mode=mode | 0o700, st_file_attributes=attributes)
                    with self.assertRaisesRegex(c.CuratorError, '^OFFLINE_' + kind + '_UNSUPPORTED$'):
                        c.check_info(info)
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=0x40000)
        c.check_info(info)  # EA on stat metadata is not RECALL_ON_OPEN.
        with self.assertRaisesRegex(c.CuratorError, '^OFFLINE_FILE_UNSUPPORTED$'):
            c.check_info(info, enumerated=True)

    def test_cloud_only_entries_are_excluded_and_counted_without_content_reads(self):
        store = c.Store(self.home)
        store.vault.mkdir()
        company = store.vault / 'company'
        company.mkdir()
        cloud_file = SimpleNamespace(name='cloud.md')
        cloud_file.stat = lambda **_: SimpleNamespace(st_mode=stat.S_IFREG | 0o600,
                                                      st_file_attributes=0x400, st_reparse_tag=0x9000001A)
        cloud_folder = SimpleNamespace(name='cloud-folder')
        cloud_folder.stat = lambda **_: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700,
                                                        st_file_attributes=0x400, st_reparse_tag=0x9000F01A)
        recall = SimpleNamespace(name='recall.md')
        recall.stat = lambda **_: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_file_attributes=0x40000)
        entries = mock.MagicMock()
        entries.__enter__.return_value = [cloud_file, cloud_folder, recall]
        with mock.patch.object(c, 'directory', c.windows_directory), mock.patch.object(os, 'scandir', return_value=entries), \
                mock.patch.object(c, 'read_file', side_effect=AssertionError('hydration')):
            notes, counts = c.collect_notes(store, 0, 1)
        self.assertEqual(notes, [])
        self.assertEqual((counts['read'], counts['excluded'], counts['failed']), (0, 3, 0))

    def test_error_output_has_precise_codes_and_cloud_action_without_private_path(self):
        errors = [(win_error(n), code) for n, code in ((2, 'PATH_MISSING'), (32, 'SHARING_VIOLATION'), (5, 'ACCESS_DENIED'))]
        errors += [(c.CuratorError(code), code) for code in ('CLOUD_FOLDER_UNSUPPORTED', 'CLOUD_FILE_UNSUPPORTED', 'PATH_MOUNT_POINT_UNSUPPORTED')]
        for error, expected in errors:
            with self.subTest(expected=expected), mock.patch.object(c, 'status', side_effect=error):
                code, out, err = self.cli('--home', str(self.home), '--status')
                self.assertEqual((code, out), (1, ''))
                self.assertEqual(err.split(':')[0].strip(), expected)
                self.assertNotIn(str(self.home), err)
                self.assertNotIn('PRIVATE', err)
                if expected.startswith('CLOUD_'):
                    self.assertIn('동기화 밖의 로컬', err)


class FreshCourseStatusTests(unittest.TestCase):
    def test_actual_embedded_fresh_install_cli_status_off_with_no_vault_or_state_created(self):
        for filename, marker in (('install-intel-mac.sh', 'COURSE_'), ('install-windows.ps1', r'\$Course')):
            with self.subTest(installer=filename), tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
                home = Path(temporary)
                source = (ROOT / 'course' / filename).read_text()
                bootstrap = re.search(marker + ("Bootstrap" if filename.endswith('.ps1') else "BOOTSTRAP") + "='([^']+)'", source).group(1)
                payload = re.search(marker + ("Payload" if filename.endswith('.ps1') else "PAYLOAD") + "='([^']+)'", source).group(1)
                self.assertEqual(base64.b64decode(bootstrap), (ROOT / 'course/install_payload.py').read_bytes())
                lib = home / 'lib'
                boot = 'import base64,sys;exec(base64.b64decode(sys.stdin.buffer.readline()))'
                installed = subprocess.run([sys.executable, '-X', 'utf8', '-c', boot, str(lib)],
                                           input=(bootstrap + '\r\n' + payload + '\r\n').encode(), capture_output=True, timeout=15)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                vault, state = home / 'absent-notes', home / 'absent-state'
                env = dict(os.environ, ILSON_COURSE_VAULT=str(vault), ILSON_COURSE_STATE=str(state))
                status = subprocess.run([sys.executable, str(lib / 'ilson.py'), 'curator', '--status'],
                                        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertFalse(json.loads(status.stdout)['enabled'])
                self.assertFalse(vault.exists())
                self.assertFalse(state.exists())


if __name__ == '__main__':
    unittest.main()
