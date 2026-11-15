"""Small OS boundary shared by Box and course editions (Python 3.10+)."""
from __future__ import annotations
import errno
import os
from pathlib import Path, PureWindowsPath
import stat
import threading
import time

IS_WINDOWS = os.name == 'nt'


class Unreadable(ValueError):
    pass


def lock(fd, *, exclusive=True, blocking=True, timeout=None):
    if not IS_WINDOWS:
        import fcntl
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if not blocking: flags |= fcntl.LOCK_NB
        fcntl.flock(fd, flags)
        return
    import msvcrt
    if not os.fstat(fd).st_size:
        os.write(fd, b'0')
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
            if not blocking or (deadline is not None and time.monotonic() >= deadline):
                raise BlockingIOError('관리 화면 잠금을 사용할 수 없습니다.') from None
            time.sleep(0.05)


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def safe_path(path):
    """Reject reparse points and links before opening Windows paths."""
    path = Path(path).absolute()
    for part in reversed((path, *path.parents)):
        try: info = part.lstat()
        except FileNotFoundError: continue
        # macOS fixed system aliases are outside user-controlled trees.
        if str(part) in ('/var', '/tmp', '/etc') and part.is_symlink() and os.readlink(part) in ('/private' + str(part), 'private' + str(part)): continue
        if is_link(info): raise ValueError('링크 경로를 사용할 수 없습니다.')
    return path


def private(path, *, directory=False, create=False):
    path = Path(path)
    if IS_WINDOWS:
        safe_path(path)
        from license import windows_acl
        windows_acl(path, create=create)
    else:
        info = path.lstat()
        valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not valid or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('개인 파일의 소유자·권한을 확인하세요.')


def private_dir(path):
    path = Path(path)
    safe_path(path)
    existed = path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir(): raise ValueError('개인 폴더를 확인하세요.')
    private(path, directory=True, create=not existed)
    return path


def vault_root(home, vault=None):
    if vault is not None: return Path(vault)
    if os.environ.get('ILSON_PROFILE') == 'course':
        return Path(os.environ.get('ILSON_COURSE_VAULT', Path.home() / 'Documents/일손강의-1기'))
    return Path(home) / 'vault'


class PosixFiles:
    """허용한 루트 아래 일반 파일만 연다. 모든 경로 요소에서 링크를 거부한다."""
    def __init__(self, home):
        self.home = Path(home).resolve()

    def open_dir(self, parts=()):
        descriptor = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                if part in {"", ".", ".."} or "/" in part:
                    raise Unreadable("경로를 확인할 수 없습니다.")
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def read(self, relative, limit, private=False):
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or any(p in {"", ".", ".."} for p in parts):
            raise Unreadable("경로를 확인할 수 없습니다.")
        directory = None
        descriptor = None
        try:
            directory = self.open_dir(parts[:-1])
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise Unreadable("파일 형식 또는 크기를 확인해주세요.")
            if private and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
                raise Unreadable("관리자 연결 파일의 소유자·권한을 확인해주세요.")
            pieces = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65536))
                if not chunk:
                    break
                pieces.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(pieces)
            if len(raw) > limit:
                raise Unreadable("파일이 너무 큽니다.")
            return raw, info
        except FileNotFoundError:
            raise
        except (OSError, ValueError):
            raise Unreadable("파일을 안전하게 읽지 못했습니다.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory is not None:
                os.close(directory)

    def text(self, relative, limit, private=False):
        raw, info = self.read(relative, limit, private)
        try:
            return raw.decode("utf-8"), info
        except UnicodeError:
            raise Unreadable("문서 인코딩을 확인해주세요.") from None

    def marker(self, relative):
        try:
            self.read(relative, 100)
            return True
        except FileNotFoundError:
            return False
        except Unreadable:
            return None

    def listdir(self, parts=()):
        descriptor = self.open_dir(parts)
        try:
            with os.scandir(descriptor) as entries:
                return [(e.name, e.is_dir(follow_symlinks=False), e.is_file(follow_symlinks=False))
                        for e in entries if not e.is_symlink()]
        finally:
            os.close(descriptor)


class WindowsFiles(PosixFiles):
    def __init__(self, home):
        self.home = safe_path(home)
        self._private_checked = set()

    def checked(self, parts):
        for part in parts:
            if part in ('', '.', '..') or '/' in part or '\\' in part or ':' in part:
                raise Unreadable('경로를 확인할 수 없습니다.')
        try: return safe_path(self.home.joinpath(*parts))
        except ValueError: raise Unreadable('링크 경로를 사용할 수 없습니다.') from None

    def read(self, relative, limit, private=False):
        value = str(relative)
        windows = PureWindowsPath(value)
        parts = value.split('/')
        if windows.drive or windows.root or '\\' in value or not parts:
            raise Unreadable('경로를 확인할 수 없습니다.')
        path = self.checked(parts)
        fd = None
        try:
            before = path.lstat()
            if is_link(before) or not stat.S_ISREG(before.st_mode): raise Unreadable('파일 형식을 확인하세요.')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit or
                    (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
                raise Unreadable('파일 형식 또는 크기를 확인해주세요.')
            if private and path not in self._private_checked:
                from license import windows_acl
                windows_acl(path)
                self._private_checked.add(path)
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - size))
                if not chunk: break
                chunks.append(chunk); size += len(chunk)
            after = os.fstat(fd)
            if size > limit or (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise Unreadable('파일이 변경되었거나 너무 큽니다.')
            return b''.join(chunks), after
        except FileNotFoundError: raise
        except (OSError, ValueError): raise Unreadable('파일을 안전하게 읽지 못했습니다.') from None
        finally:
            if fd is not None: os.close(fd)

    def listdir(self, parts=()):
        path = self.checked(parts)
        with os.scandir(path) as entries:
            rows = []
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if not is_link(info):
                    rows.append((entry.name, stat.S_ISDIR(info.st_mode), stat.S_ISREG(info.st_mode)))
            return rows


def files(home):
    return WindowsFiles(home) if IS_WINDOWS else PosixFiles(home)


_private_cache = set()
_private_lock = threading.Lock()


def cached_private(path, *, directory=False, create=False):
    """ACL check once per file identity; lstat still runs on every access."""
    path = safe_path(path)
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or (not directory and info.st_nlink != 1): raise ValueError('개인 파일 형식을 확인하세요.')
    key = (str(path), info.st_dev, info.st_ino)
    with _private_lock:
        if key not in _private_cache:
            private(path, directory=directory, create=create)
            _private_cache.add(key)
