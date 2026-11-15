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


class WindowsMoveTests(unittest.TestCase):
    def test_verified_copy_does_not_overwrite_and_never_removes_changed_source(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source=root/'source.md';destination=root/'approved.md'
            source.write_bytes('합성 초안'.encode());expected=hashlib.sha256(source.read_bytes()).hexdigest()
            destination.write_text('preserve')
            with self.assertRaises(FileExistsError): platform.copy_verified(source,destination,expected)
            self.assertEqual(destination.read_text(),'preserve');self.assertTrue(source.exists())
            destination.unlink();source.write_text('changed')
            with self.assertRaises(ValueError): platform.copy_verified(source,destination,expected)
            self.assertTrue(source.exists());self.assertFalse(destination.exists())
            source.write_bytes('합성 초안'.encode());platform.copy_verified(source,destination,expected)
            self.assertFalse(source.exists());self.assertEqual(destination.read_text(),'합성 초안')

    def test_windows_one_drive_hard_link_failure_uses_verified_copy(self):
        import approval_dispatch as dispatch
        import approval_store as store
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();vault=root/'notes';pending=vault/'reports/pending';pending.mkdir(parents=True)
            body='합성 초안';(pending/'draft.md').write_text(body)
            req=SimpleNamespace(target={'channel':'local_note','account':'local','object_id':'draft.md'},body=body,body_sha256=store.digest(body),id='a'*32)
            home_token=dispatch._ACTIVE_HOME.set(root);vault_token=dispatch._ACTIVE_VAULT.set(vault)
            try:
                with patch.object(platform,'IS_WINDOWS',True),patch.object(dispatch.os,'link',side_effect=OSError(errno.EXDEV,'OneDrive')):
                    self.assertEqual(dispatch.execute_note(req).status,'success')
                self.assertFalse((pending/'draft.md').exists());self.assertEqual((vault/'reports/approved/draft.md').read_text(),body)
            finally:
                dispatch._ACTIVE_HOME.reset(home_token);dispatch._ACTIVE_VAULT.reset(vault_token)
