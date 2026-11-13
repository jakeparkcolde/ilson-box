"""Offline, consent-gated Box knowledge digest. No AI or network execution path."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = 1
MAX_FILE = 256 * 1024
MAX_FILES = 100
MAX_TOTAL = 2 * 1024 * 1024
INPUTS = ('company/**/*.md', 'journal/YYYY-MM-DD.md', 'reports/briefing/*.md', 'reports/weekly/*.md')
FORBIDDEN = {'management', 'people', 'pending', 'attachments', 'credentials', 'config', 'conversations', 'node_modules'}


class CuratorError(Exception):
    pass


def canonical(path):
    """Normalize only Apple's system aliases, never resolve user symlinks."""
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    if os.name == 'nt':
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        if str(path).startswith('\\\\') or drive_type(str(path.anchor)) == 4:
            raise CuratorError('REMOTE_VAULT_UNSUPPORTED')
    if sys.platform == 'darwin' and len(path.parts) > 1 and path.parts[1] in ('var', 'tmp', 'etc'):
        alias = Path('/') / path.parts[1]
        if alias.is_symlink() and os.readlink(alias) == '/private' + str(alias):
            path = Path('/private').joinpath(*path.parts[1:])
    return path


def check_path(path):
    for part in reversed([path, *path.parents]):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CuratorError('UNSAFE_PATH')
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise CuratorError('UNSAFE_PATH')


@contextmanager
def directory(path, create=False, private=False):
    """POSIX traversal pins every ancestor with O_NOFOLLOW; Windows rejects reparse points."""
    path = canonical(path)
    check_path(path)
    if os.name == 'nt':
        # Pin every Windows directory without FILE_SHARE_DELETE: a junction/parent
        # cannot be swapped between validation and opening its child.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        open_handle = kernel.CreateFileW
        open_handle.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        open_handle.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handles = []
        try:
            for part in reversed([path, *path.parents]):
                if not part.exists() and create:
                    part.mkdir(mode=0o700 if private else 0o755)
                check_path(part)
                handle = open_handle(str(part), 0x80, 3, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise CuratorError('UNSAFE_PATH')
                handles.append(handle)
                check_path(part)
            if not path.is_dir():
                raise CuratorError('UNSAFE_PATH')
            if private:
                license_module().windows_acl(path, create=create)
            yield None
            check_path(path)
        finally:
            for handle in reversed(handles):
                kernel.CloseHandle(handle)
        return
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700 if private else 0o755, dir_fd=fd)
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        info = os.fstat(fd)
        if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise CuratorError('PRIVATE_STATE_REQUIRED')
        yield fd
    finally:
        os.close(fd)


def read_file(path, limit=MAX_FILE, private=False):
    path = canonical(path)
    with directory(path.parent, private=private) as parent:
        check_path(path)
        fd = os.open(path if parent is None else path.name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0),
                     **({} if parent is None else {'dir_fd': parent}))
        try:
            info = os.fstat(fd)
            if os.name == 'nt':
                import ctypes
                import msvcrt
                from ctypes import wintypes
                final_name = ctypes.windll.kernel32.GetFinalPathNameByHandleW
                final_name.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                buffer = ctypes.create_unicode_buffer(32768)
                length = final_name(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
                actual = buffer.value.removeprefix('\\\\?\\')
                if not length or length >= len(buffer) or os.path.normcase(actual) != os.path.normcase(str(path)):
                    raise CuratorError('UNSAFE_PATH')
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise CuratorError('UNSAFE_OR_LARGE_FILE')
            if private and os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise CuratorError('PRIVATE_STATE_REQUIRED')
            with os.fdopen(fd, 'rb') as stream:
                fd = -1
                data = stream.read(limit + 1)
                after = os.fstat(stream.fileno())
            if len(data) > limit or (info.st_mtime_ns, info.st_size) != (after.st_mtime_ns, after.st_size):
                raise CuratorError('FILE_CHANGED')
            check_path(path)
            if path.stat().st_ino != info.st_ino:
                raise CuratorError('FILE_CHANGED')
            return data, info
        finally:
            if fd >= 0:
                os.close(fd)


def load_json(path):
    try:
        data, _ = read_file(path, 32768, private=True)
        value = json.loads(data)
        if not isinstance(value, dict) or value.get('schema') != SCHEMA:
            raise CuratorError('UNSUPPORTED_STATE')
        return value
    except FileNotFoundError:
        return {'schema': SCHEMA}
    except (ValueError, UnicodeError):
        raise CuratorError('INVALID_STATE') from None


def save_json(path, value):
    value = dict(value, schema=SCHEMA)
    with directory(path.parent, create=True, private=True) as parent:
        name = '.state-' + os.urandom(12).hex()
        kwargs = {} if parent is None else {'dir_fd': parent}
        temporary = path.parent / name if parent is None else name
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, **kwargs)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            check_path(path)
            if path.exists() and path.stat().st_nlink != 1:
                raise CuratorError('UNSAFE_PATH')
            if parent is None:
                os.replace(temporary, path)
            else:
                os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, **kwargs)
            except FileNotFoundError:
                pass


def resolve_vault(home, edition, vault=None):
    """Replaceable resolver boundary for a future actor-aware vault policy; single user only."""
    if edition == 'full-mac':
        if vault is not None:
            raise CuratorError('VAULT_OVERRIDE_UNSUPPORTED')
        return canonical(Path(home) / 'vault')
    return canonical(vault or os.environ.get('ILSON_COURSE_VAULT', Path.home() / 'Documents/일손강의-1기'))


class Store:
    def __init__(self, home, edition='full-mac', vault=None):
        self.home = canonical(home)
        self.edition = edition
        self.vault = resolve_vault(self.home, edition, vault)
        ident = hashlib.sha256(os.fsencode(os.path.normcase(str(self.vault)))).hexdigest()[:32]
        self.state = self.home / 'state/curator' / ident

    def config(self):
        return load_json(self.state / 'config.json')

    def result(self):
        return load_json(self.state / 'result.json')

    def enabled(self):
        return self.config().get('enabled') is True

    def record(self, code, counts=None, **extra):
        # Deliberately no paths, titles, note text or exception strings.
        save_json(self.state / 'result.json', dict(self.result(), edition=self.edition,
                  mode='local', at=time.time(), code=code, counts=counts or {}, **extra))


@contextmanager
def vault_lock(store, blocking=False):
    with directory(store.state, create=True, private=True) as parent:
        path = store.state / 'run.lock'
        check_path(path)
        fd = os.open(path if parent is None else path.name,
                     os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600,
                     **({} if parent is None else {'dir_fd': parent}))
        locked = False
        try:
            info = os.fstat(fd)
            if os.name == 'nt':
                import ctypes
                import msvcrt
                from ctypes import wintypes
                final_name = ctypes.windll.kernel32.GetFinalPathNameByHandleW
                final_name.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                buffer = ctypes.create_unicode_buffer(32768)
                length = final_name(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
                actual = buffer.value.removeprefix('\\\\?\\')
                if not length or length >= len(buffer) or os.path.normcase(actual) != os.path.normcase(str(path)):
                    raise CuratorError('UNSAFE_PATH')
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CuratorError('UNSAFE_PATH')
            if os.name == 'nt':
                import msvcrt
                if not info.st_size:
                    os.write(fd, b'0')
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            locked = True
            yield
        except (BlockingIOError, PermissionError):
            if locked:
                raise
            raise CuratorError('LOCKED') from None
        finally:
            os.close(fd)  # OS locks release on exit, including a killed process.


def set_enabled(store, enabled):
    # Write revocation before waiting: active readers check between files and at publication.
    cfg = store.config()
    cfg.update(enabled=bool(enabled), auto=False, changed_at=time.time())
    save_json(store.state / 'config.json', cfg)
    with vault_lock(store, blocking=True):
        pass  # Drains our bounded local worker; no process-name/PID-based killing.


def license_module():
    path = Path(__file__).absolute().parent / 'license.py'
    spec = importlib.util.spec_from_file_location('_curator_license', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_license(home, now=None):
    """Read-only valid local cache. Never invoke evaluate(), transport(), or a CLI check."""
    now = time.time() if now is None else now
    try:
        module = license_module()
        folder = canonical(home) / 'state/license'
        with directory(folder, private=True):
            serial, _ = read_file(folder / 'serial', 8192, private=True)
            cache, _ = read_file(folder / 'state.json', 8192, private=True)
        info = module.parse_serial(serial.decode().strip(), now)
        state = json.loads(cache)
        success = state.get('last_success')
        if (state.get('id') != info['id'] or state.get('registered') is not True or state.get('denied')
                or not isinstance(success, (int, float)) or not success
                or now < state.get('last_observed', now) - 300
                or now < success - 300 or now >= success + module.CHECK_INTERVAL):
            return False
        return True
    except (OSError, ValueError, CuratorError, KeyError, TypeError):
        return False


def allowed_parts(parts):
    return all(not part.startswith('.') and not any(ord(char) < 32 for char in part)
               and part.casefold() not in FORBIDDEN
               and Path(part).stem.casefold() not in {'credentials', 'secrets', 'passwords', 'tokens', 'settings', 'config', 'conversation', 'transcript'}
               for part in parts)


def candidates(vault):
    """Enumerate only allowlisted subtrees. Never enumerate management/ or people/."""
    excluded = [0]
    def walk(folder, recursive=False, journal=False):
        try:
            with directory(folder) as fd:
                with os.scandir(folder if fd is None else fd) as entries:
                    for item in sorted(entries, key=lambda e: e.name):
                        parts = (folder / item.name).relative_to(vault).parts
                        if not allowed_parts(parts):
                            excluded[0] += 1
                            continue
                        info = item.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                            excluded[0] += 1
                            continue
                        if stat.S_ISDIR(info.st_mode) and recursive:
                            yield from walk(folder / item.name, recursive=True)
                        elif stat.S_ISREG(info.st_mode) and item.name.endswith('.md'):
                            if not journal or re.fullmatch(r'\d{4}-\d{2}-\d{2}\.md', item.name):
                                yield folder / item.name
        except FileNotFoundError:
            pass
        except (OSError, CuratorError):
            excluded[0] += 1
    def all_paths():
        with directory(vault):
            yield from walk(vault / 'company', recursive=True)
            yield from walk(vault / 'journal', journal=True)
            yield from walk(vault / 'reports/briefing')
            yield from walk(vault / 'reports/weekly')
    return all_paths(), excluded


def collect_notes(store, start, end):
    notes, counts = [], {'read': 0, 'excluded': 0, 'limited': 0, 'failed': 0}
    paths, excluded = candidates(store.vault)
    total = 0
    for path in paths:
        if not store.enabled():
            raise CuratorError('OFF')
        try:
            info = path.lstat()
            if info.st_nlink != 1:
                counts['excluded'] += 1
                continue
            if info.st_size > MAX_FILE or counts['read'] >= MAX_FILES or total + info.st_size > MAX_TOTAL:
                counts['limited'] += 1
                continue
            data, info = read_file(path, min(MAX_FILE, MAX_TOTAL - total))
            total += len(data)
            counts['read'] += 1
            text = data.decode('utf-8')
            # Extract only defined syntax; nothing from a note is ever executed.
            tags = set(re.findall(r'(?<![\w/])#([\w가-힣/-]+)', text))
            links = re.findall(r'\[\[([^\]\n]+)\]\]', text)
            done, checks = [], []
            for line in text.splitlines():
                if re.match(r'^\s*[-*]\s+\[[xX]\]\s+', line):
                    done.append(line.strip()[:300])
                if re.match(r'^\s*[-*]\s+\[ \]\s+', line) or '확인 필요' in line:
                    checks.append(line.strip()[:300])
            notes.append({'path': path.relative_to(store.vault).as_posix(), 'changed': start <= info.st_mtime <= end,
                          'tags': tags, 'links': links, 'done': done[:20], 'checks': checks[:20]})
        except UnicodeError:
            counts['failed'] += 1
        except (OSError, CuratorError):
            counts['failed'] += 1
    counts['excluded'] += excluded[0]
    return notes, counts


def wikilink(path):
    # Plain literal label + percent-encoded relative link, preventing Markdown/wiki injection.
    from urllib.parse import quote
    label = literal(path)
    return '[' + label + '](' + quote('../../' + path, safe='/') + ')'


def literal(text):
    text = text.replace('\r', ' ').replace('\n', ' ').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~-])', r'\\\1', text)


def build_local_digest(notes, counts, start, end, target):
    changed = [n for n in notes if n['changed']]
    by_path = {n['path']: n for n in notes}
    def target_note(source, value):
        value = value.split('|')[0].split('#')[0].strip()
        if not value or '\\' in value or value.startswith('/') or '..' in Path(value).parts:
            return None
        if not value.endswith('.md'):
            value += '.md'
        choices = [value, (Path(source['path']).parent / value).as_posix()]
        matches = [by_path[p] for p in choices if p in by_path]
        if not matches and '/' not in value:
            matches = [n for n in notes if Path(n['path']).name == value]
        return matches[0] if len(matches) == 1 else None
    related = set()
    for source in changed:
        for value in source['links']:
            other = target_note(source, value)
            if other and other['path'] != source['path']:
                related.add((source['path'], other['path'], '기존 내부 링크'))
        for other in notes:
            shared = sorted(source['tags'] & other['tags'])
            if source['path'] != other['path'] and shared:
                related.add((source['path'], other['path'], '같은 태그: ' + ', '.join('#' + s for s in shared[:5])))
    local = lambda stamp: datetime.fromtimestamp(stamp).astimezone().isoformat(timespec='seconds')
    lines = [f'# 지식 큐레이터 · {target}', '', '로컬 규칙으로 정리 · AI 요약 없음', '',
             f'수집 구간: {local(start)} ~ {local(end)}', f'대상일: {target} · 현재 파일의 수정 시각 기준 (과거 본문 복원 아님)',
             f"읽음 {counts['read']} · 제외 {counts['excluded']} · 한도 초과 {counts['limited']} · 읽기 실패 {counts['failed']}",
             '', '## 하루 기록', '']
    for note in changed:
        lines.append('- 수정: ' + wikilink(note['path']) + ' (완료를 뜻하지 않음)')
        lines.extend('  - 명시적 완료 표시: ' + literal(line) for line in note['done'])
    if not changed:
        lines.append('수집 구간에 변경된 노트가 없습니다.')
    lines += ['', '## 관련 노트', '']
    lines += ['- ' + wikilink(a) + ' → ' + wikilink(b) + ' · ' + reason for a, b, reason in sorted(related)[:100]]
    if not related:
        lines.append('태그·기존 내부 링크로 확인한 연결이 없습니다.')
    lines += ['', '## 확인할 항목', '']
    checks = [(n, line) for n in changed for line in n['checks']]
    lines += ['- ' + wikilink(n['path']) + ': ' + literal(line) for n, line in checks]
    if not checks:
        lines.append('정해진 미완료·확인 필요 표시가 없습니다.')
    lines += ['', '## 누락 안내', '', '허용된 입력만 읽습니다. 관리·개인 영역, 숨김 경로, 링크·공유 하드링크, 승인 대기, 첨부, 큐레이터 출력은 제외합니다.',
              '파일당 256 KiB, 최대 100개·합계 2 MiB. 관련 노트도 이 한도 안에서만 찾습니다.']
    if counts['limited'] or counts['failed']:
        lines.append('일부 자료가 빠진 부분 결과입니다. 원본을 변경하지 않았습니다.')
    return '\n'.join(lines) + '\n'


def write_new_note(store, filename, content):
    folder = store.vault / 'journal/curator'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:\.addendum-\d{2,})?\.md', filename):
        raise CuratorError('INVALID_OUTPUT')
    # Staging is private and on the destination filesystem, including external course vaults.
    with directory(folder, create=True) as output:
        staging = folder / '.staging'
        with directory(staging, create=True, private=True) as stage:
            name = 'note-' + os.urandom(16).hex()
            kwargs = {} if stage is None else {'dir_fd': stage}
            temporary = staging / name if stage is None else name
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, **kwargs)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if not store.enabled():
                    raise CuratorError('OFF')
                check_path(folder)
                if output is None:
                    # Windows rename is atomic and fails when destination exists.
                    os.rename(temporary, folder / filename)
                else:
                    os.link(name, filename, src_dir_fd=stage, dst_dir_fd=output, follow_symlinks=False)
                    os.fsync(output)
            finally:
                try:
                    os.unlink(temporary, **kwargs)
                except FileNotFoundError:
                    pass


def timezone_id():
    return '|'.join(time.tzname) + ':' + str(time.timezone) + ':' + os.environ.get('TZ', '')


def due_run(store, now=None):
    now = time.time() if now is None else now
    cfg, result = store.config(), store.result()
    zone = timezone_id()
    if result.get('zone', zone) != zone or now < result.get('observed', 0) - 300:
        raise CuratorError('CLOCK_REVIEW_REQUIRED')
    local = datetime.fromtimestamp(now)
    target = local.date() if local.hour >= 23 else (local - timedelta(days=1)).date()
    if result.get('last_date', '') >= str(target) or cfg.get('changed_at', now) > datetime.combine(target, datetime.min.time()).replace(hour=23).timestamp():
        return None
    return str(target)


def run_ai_summary(*_args, **_kwargs):
    raise CuratorError('AI_DISABLED')  # Future opt-in hook: deliberately no sending implementation.


def run_once(store, now=None, addendum=False, automatic=False, license_check=None):
    now = time.time() if now is None else now
    if not store.enabled():
        return 'OFF'
    with vault_lock(store):
        if not store.enabled():
            return 'OFF'
        if automatic and (store.edition != 'full-mac' or store.config().get('auto') is not True or not watchdog_active(store)):
            return 'AUTO_OFF'
        target = due_run(store, now) if automatic else str(datetime.fromtimestamp(now).date())
        if target is None:
            return 'NOT_DUE'
        result = store.result()
        zone = timezone_id()
        if result.get('zone', zone) != zone or now < result.get('observed', 0) - 300 or target < result.get('last_date', ''):
            raise CuratorError('CLOCK_REVIEW_REQUIRED')
        filename = target + '.md'
        folder = store.vault / 'journal/curator'
        check_path(folder)
        if addendum:
            for number in range(1, 1000):
                filename = f'{target}.addendum-{number:02d}.md'
                if not os.path.lexists(folder / filename):
                    break
            else:
                raise CuratorError('ADDENDUM_LIMIT')
        elif os.path.lexists(folder / filename) or result.get('last_date') == target:
            return 'already_exists'
        if not (license_check or local_license)(store.home, now):
            store.record('LICENSE_LOCAL_REQUIRED', observed=now, zone=zone)
            return 'LICENSE_LOCAL_REQUIRED'
        end = now
        previous = result.get('last_end')
        start = previous if isinstance(previous, (int, float)) else datetime.combine(datetime.fromisoformat(target).date() - timedelta(days=1), datetime.min.time()).replace(hour=23).timestamp()
        notes, counts = collect_notes(store, start, end)
        content = build_local_digest(notes, counts, start, end, target)
        if not store.enabled():
            return 'OFF'
        try:
            write_new_note(store, filename, content)
        except FileExistsError:
            return 'already_exists'
        code = 'PARTIAL' if counts['limited'] or counts['failed'] else 'OK'
        store.record(code, counts, last_date=target, last_end=end, observed=now, zone=zone)
        return code


def watchdog_active(store):
    if store.edition != 'full-mac' or sys.platform != 'darwin':
        return False
    marker = store.home / 'state/enabled.watchdog'
    check_path(marker)
    if not marker.is_file():
        return False
    try:
        return subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/com.ilson.watchdog'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def status(store):
    cfg, result = store.config(), store.result()
    active = watchdog_active(store)
    try:
        code, _ = read_file(store.home / 'lib/watchdog.sh')
        compatible = b'curator.py' in code
    except (OSError, CuratorError):
        compatible = False
    return {'schema': SCHEMA, 'enabled': cfg.get('enabled') is True, 'mode': 'local', 'ai': 'disabled',
            'inputs': INPUTS, 'output': 'journal/curator/YYYY-MM-DD.md',
            'auto_supported': store.edition == 'full-mac', 'auto_enabled': cfg.get('auto') is True,
            'watchdog_active': active, 'watchdog_compatible': compatible,
            'schedule_running': bool(active and compatible and cfg.get('enabled') and cfg.get('auto')),
            'clock_review_required': bool(result.get('zone', timezone_id()) != timezone_id() or time.time() < result.get('observed', 0) - 300),
            'last': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description='지식 큐레이터: 로컬 규칙 정리 · AI/네트워크 호출 없음')
    parser.add_argument('--home', default=os.environ.get('ILSON_HOME', str(Path.home() / 'ilson')))
    parser.add_argument('--edition', choices=('full-mac', 'intel-course', 'windows-course'), default='full-mac')
    parser.add_argument('--vault')
    group = parser.add_mutually_exclusive_group()
    for option in ('status', 'on', 'off', 'auto-on', 'auto-off', 'addendum', 'ai-on', 'ai-off', 'tick'):
        group.add_argument('--' + option, action='store_true')
    args = parser.parse_args(argv)
    try:
        store = Store(args.home, args.edition, args.vault)
        if args.status:
            print(json.dumps(status(store), ensure_ascii=False, indent=2))
            return 0
        if args.ai_on:
            print('AI_DISABLED: AI 요약은 제공하지 않습니다. 로컬 정리만 사용할 수 있습니다.')
            return 2
        if args.ai_off:
            print('AI_DISABLED')
            return 0
        if args.off:
            set_enabled(store, False)
            print('OFF: 이후 수동·자동 읽기를 중단했습니다. 기존 결과는 보존합니다.')
            return 0
        if args.auto_on or args.auto_off:
            if store.edition != 'full-mac':
                print('AUTO_UNSUPPORTED: 강의판은 수동 명령만 제공합니다. 예약 미지원.')
                return 2
            if args.auto_on and not store.enabled():
                print('OFF: 먼저 ilson curator --on 으로 동의하세요.')
                return 2
            with vault_lock(store):
                cfg = store.config()
                cfg['auto'] = args.auto_on
                save_json(store.state / 'config.json', cfg)
            print('자동 설정 저장: 현지시각 23:00 · 기존 watchdog 약 10분 간격. 실제 가동 상태는 --status 로 확인하세요.')
            return 0
        if args.on or not store.enabled():
            if args.tick:
                return 0
            print('로컬 규칙으로 정리 · AI 요약 없음 · 네트워크 호출 없음\n입력: ' + ', '.join(INPUTS) + '\n출력: journal/curator/YYYY-MM-DD.md (새 노트만)\n기능 동의와 자동 실행 동의는 별개입니다.')
            if not sys.stdin.isatty():
                print('CONSENT_REQUIRED: 일반 터미널에서 설명을 읽고 직접 선택하세요.')
                return 2
            if input('기능 사용에 동의합니까? [y/N] ').strip().lower() not in ('y', 'yes'):
                return 2
            set_enabled(store, True)
            if args.on:
                print('ON: 수동 사용 가능. 자동 실행은 꺼져 있습니다.')
                return 0
        code = run_once(store, addendum=args.addendum, automatic=args.tick)
        if not args.tick:
            print(code)
        return 0 if code in ('OK', 'PARTIAL', 'already_exists', 'NOT_DUE', 'OFF', 'AUTO_OFF') else 1
    except (CuratorError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, CuratorError) else 'LOCAL_IO_ERROR'
        print(code, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
