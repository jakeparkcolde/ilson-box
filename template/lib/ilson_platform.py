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

    def listdir(self, parts=(), limit=1001):
        descriptor = self.open_dir(parts)
        try:
            rows = []
            with os.scandir(descriptor) as entries:
                for index, entry in enumerate(entries):
                    if index >= limit: break
                    linked = entry.is_symlink()
                    rows.append((entry.name, not linked and entry.is_dir(follow_symlinks=False),
                                 not linked and entry.is_file(follow_symlinks=False)))
            return rows
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

    def listdir(self, parts=(), limit=1001):
        path = self.checked(parts)
        with os.scandir(path) as entries:
            rows = []
            for index, entry in enumerate(entries):
                if index >= limit: break
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


COURSE_FEATURES = frozenset({'home', 'approvals', 'reports', 'usage-history', 'replies'})
BOX_FEATURES = COURSE_FEATURES | {'jobs', 'settings', 'sns', 'sns-accounts', 'vault', 'received-files',
    'dashboard', 'staff', 'org', 'skills', 'research', 'knowledge', 'packs', 'opensource', 'learn', 'telegram_approval'}
COURSE_STATIC = {
    '/': ('web/course.html', 'text/html; charset=utf-8'),
    '/index.html': ('web/course.html', 'text/html; charset=utf-8'),
    '/approval': ('web/course.html', 'text/html; charset=utf-8'),
    '/reports': ('web/course.html', 'text/html; charset=utf-8'),
    '/replies': ('web/course.html', 'text/html; charset=utf-8'),
    '/usage-history': ('web/course.html', 'text/html; charset=utf-8'),
    '/course.js': ('web/course.js', 'application/javascript; charset=utf-8'),
    '/course.css': ('web/course.css', 'text/css; charset=utf-8'),
    '/current/base.css': ('web/current/base.css', 'text/css; charset=utf-8'),
    '/current/shell.css': ('web/current/shell.css', 'text/css; charset=utf-8'),
    '/usage-history.js': ('web/usage-history.js', 'application/javascript; charset=utf-8'),
    '/usage-history.css': ('web/usage-history.css', 'text/css; charset=utf-8'),
}


def features(profile):
    if profile not in ('box', 'course'): raise ValueError('관리자 프로필을 확인하세요.')
    return COURSE_FEATURES if profile == 'course' else BOX_FEATURES


def course_route(method, path):
    if method in ('GET', 'HEAD'):
        return path in COURSE_STATIC or path in {'/health', '/api/health', '/api/session', '/api/overview',
            '/api/approvals', '/api/reports', '/api/usage-history/summary'} or bool(__import__('re').fullmatch('/api/reports/[a-f0-9]{32}', path))
    if method == 'POST':
        return path in {'/api/session', '/api/logout', '/api/admin/shutdown', '/api/replies/draft'} or path in {
            '/api/approvals/' + action for action in ('create', 'approve', 'change', 'reject', 'run')} or path in {
            '/api/usage-history/' + action for action in ('on', 'off', 'collect', 'delete-local', 'export', 'link', 'unlink', 'sync')}
    return False


def copy_verified(source, destination, expected):
    """OneDrive/NTFS fallback: exclusive copy, hash, unchanged source, then unlink."""
    import hashlib
    source, destination = safe_path(source), safe_path(destination)
    raw, before = WindowsFiles(source.parent).read(source.name, 256000)
    if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('초안이 변경되었습니다.')
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
        copied, _ = WindowsFiles(destination.parent).read(destination.name, 256000)
        after = source.lstat()
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_nlink)
        if (hashlib.sha256(copied).hexdigest() != expected or identity(before) != identity(after) or is_link(after)):
            raise ValueError('초안이 변경되었습니다.')
        source.unlink()
    except Exception:
        try:
            now = destination.lstat()
            if (now.st_dev, now.st_ino) == (created.st_dev, created.st_ino): destination.unlink()
        except FileNotFoundError: pass
        raise


def acquire_lock(path, *, blocking=False):
    path = safe_path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError('잠금 파일을 확인하세요.')
        lock(fd, blocking=blocking)
        return fd
    except Exception:
        os.close(fd)
        raise


def atomic_write(path, data):
    import tempfile
    path = safe_path(path)
    if path.exists() and path.lstat().st_nlink != 1: raise ValueError('개인 파일을 확인하세요.')
    fd, name = tempfile.mkstemp(prefix='.admin-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def code_digest(library):
    import hashlib
    library = safe_path(library)
    root = library.parent
    sources = sorted(library.glob('*.py'))
    web = root / 'web'
    safe_path(web)
    if web.exists(): sources += sorted(p for p in web.rglob('*') if p.is_file())
    result = hashlib.sha256()
    for path in sources:
        safe_path(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise ValueError('실행 파일을 확인하세요.')
        result.update(str(path.relative_to(root)).replace('\\', '/').encode())
        result.update(b'\0'); result.update(path.read_bytes())
    return result.hexdigest()


def process_identity(pid):
    """Executable and OS creation time, for a specifically recorded PID only."""
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: raise ValueError('프로세스 신원을 확인하지 못했습니다.')
        try:
            size=wintypes.DWORD(32768);name=ctypes.create_unicode_buffer(size.value)
            created,ended,system,user=(wintypes.FILETIME() for _ in range(4))
            if not kernel.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)) or not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(ended),ctypes.byref(system),ctypes.byref(user)):
                raise ValueError('프로세스 신원을 확인하지 못했습니다.')
            started=((created.dwHighDateTime<<32)|created.dwLowDateTime)/10000000-11644473600
            return str(Path(name.value).resolve()), started
        finally: kernel.CloseHandle(handle)
    import subprocess
    import datetime
    name=subprocess.run(['/bin/ps','-p',str(pid),'-o','comm='],capture_output=True,text=True,timeout=3)
    start=subprocess.run(['/bin/ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True,timeout=3,env=dict(os.environ,LC_ALL='C'))
    if name.returncode or start.returncode: raise ValueError('프로세스 신원을 확인하지 못했습니다.')
    return str(Path(name.stdout.strip()).resolve()), datetime.datetime.strptime(start.stdout.strip(),'%a %b %d %H:%M:%S %Y').timestamp()
