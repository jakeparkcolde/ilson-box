"""Real POSIX and simulated Windows OS boundaries, without real ACL changes."""
import errno
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
import ilson_platform as platform


class PlatformTests(unittest.TestCase):
    def test_posix_lock_preserves_shared_and_exclusive_flags(self):
        import fcntl
        with patch.object(platform, 'IS_WINDOWS', False), patch.object(fcntl, 'flock') as flock:
            platform.lock(7)
            flock.assert_called_with(7, fcntl.LOCK_EX)
            platform.lock(7, exclusive=False, blocking=False)
            flock.assert_called_with(7, fcntl.LOCK_SH | fcntl.LOCK_NB)

    def test_windows_nonblocking_and_retry_timeout(self):
        busy = OSError(errno.EACCES, 'busy')
        native = SimpleNamespace(LK_NBLCK=9, locking=Mock(side_effect=[busy, None]))
        with tempfile.TemporaryFile() as stream, patch.object(platform, 'IS_WINDOWS', True), patch.dict(sys.modules, msvcrt=native), patch.object(platform.time, 'sleep'):
            platform.lock(stream.fileno(), timeout=1)
            self.assertEqual(native.locking.call_count, 2)
            native.locking.side_effect = busy
            with self.assertRaises(BlockingIOError): platform.lock(stream.fileno(), blocking=False)
            with self.assertRaises(BlockingIOError): platform.lock(stream.fileno(), timeout=0)

    def test_windows_acl_fails_closed_and_private_reads_are_checked_once(self):
        import license
        with tempfile.TemporaryDirectory() as temp, patch.object(platform, 'IS_WINDOWS', True), patch.object(license, 'windows_acl', create=True) as acl:
            path = Path(temp) / 'private'; platform.private_dir(path)
            acl.assert_called_once_with(path, create=True)
            (path/'token').write_text('fixture')
            reader = platform.WindowsFiles(path)
            reader.text('token', 100, private=True)
            reader.text('token', 100, private=True)
            self.assertEqual(acl.call_count, 2)
            acl.side_effect = ValueError('denied')
            with self.assertRaises(ValueError): platform.private_dir(path)

    def test_both_readers_reject_links_hardlinks_traversal_and_large_files(self):
        for reader_type in (platform.PosixFiles, platform.WindowsFiles):
            with self.subTest(reader=reader_type), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve(); (root/'ok').write_text('hello')
                reader = reader_type(root)
                self.assertEqual(reader.text('ok', 5)[0], 'hello')
                for name in ('../ok', '/ok'):
                    with self.assertRaises(platform.Unreadable): reader.read(name, 100)
                with self.assertRaises(platform.Unreadable): reader.read('ok', 4)
                (root/'link').symlink_to(root/'ok')
                with self.assertRaises(platform.Unreadable): reader.read('link', 100)
                os.link(root/'ok', root/'hard')
                with self.assertRaises(platform.Unreadable): reader.read('hard', 100)

    def test_windows_reparse_and_windows_paths_are_rejected_on_mac(self):
        info = SimpleNamespace(st_mode=0o100600, st_file_attributes=0x400)
        self.assertTrue(platform.is_link(info))
        with tempfile.TemporaryDirectory() as temp:
            reader = platform.WindowsFiles(temp)
            for name in ('C:/secrets', 'C:secrets', 'dir\\secrets', 'file:stream', 'dir//file', './file'):
                with self.subTest(name=name), self.assertRaises(platform.Unreadable): reader.read(name, 100)


if __name__ == '__main__': unittest.main()
