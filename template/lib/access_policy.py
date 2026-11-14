"""Company file boundary. OS EUID is identity; names and environment are not.

The root-owned company.json and immutable vault anchors are provisioned by
company init. File I/O uses directory descriptors, never check-then-open paths.
No configuration means the original single-user layout.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

SHARED = Path('/Users/Shared/Ilson')
# D-a / D-b / D-c / D-d: one editable policy contract, no seat/licence-server change.
DEFAULTS = dict(company_staff_write=True, personal_private=True,
                licence='one-company-device', employee_web=False)
ID = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')

class AccessDenied(ValueError):
    pass


def deny():
    raise AccessDenied('회사 접근 거절: 등록·권한·경로를 대표에게 확인하세요.')


def parts(value):
    value = str(value)
    if not value or value.startswith('/') or '\\' in value:
        deny()
    result = value.split('/')
    if any(p in ('', '.', '..') or any(ord(c) < 32 for c in p) for p in result):
        deny()
    return tuple(result)


@contextmanager
def directory(path):
    """Walk from / with O_NOFOLLOW; macOS's fixed /var alias only is normalized."""
    path = Path(os.path.abspath(path))
    if str(path).startswith('/var/'):
        path = Path('/private') / path.relative_to('/')
    if str(path).startswith('/tmp/'):
        path = Path('/private') / path.relative_to('/')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_regular(fd, name, limit=2 * 1024 * 1024):
    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(file)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            deny()
        chunks = []
        size = 0
        while size <= limit:
            chunk = os.read(file, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(file)
        if size > limit or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink):
            deny()
        return b''.join(chunks), after
    finally:
        os.close(file)


@dataclass(frozen=True)
class Actor:
    person: str
    uid: int
    role: str


def validate(config):
    try:
        if config['schema'] != 1 or not ID.fullmatch(config['id']):
            deny()
        rows = config['people']
        if not rows or len({p['id'] for p in rows}) != len(rows) or len({p['uid'] for p in rows}) != len(rows):
            deny()
        for p in rows:
            if not ID.fullmatch(p['id']) or not ID.fullmatch(p['account']) or type(p['uid']) is not int or p['uid'] < 501 or p['role'] not in ('owner', 'staff') or type(p['active']) is not bool:
                deny()
        owners = [p for p in rows if p['role'] == 'owner' and p['active']]
        if len(owners) != 1 or owners[0]['uid'] != config['owner_uid']:
            deny()
        if not Path(config['runtime']).is_absolute() or not Path(config['vault']).is_absolute():
            deny()
        if config.get('defaults') != DEFAULTS:
            deny()  # Unknown policy version never silently broadens access.
    except (KeyError, TypeError):
        deny()
    return config


def resolve_actor(config, *, uid=None):
    # uid is a test seam; no CLI/API accepts it. Never use USER, HOME or group names.
    uid = os.geteuid() if uid is None else uid
    for person in validate(config)['people']:
        if person['uid'] == uid and person['active']:
            return Actor(person['id'], uid, person['role'])
    deny()


def can_access(config, actor, resource, action='read', *, company_only=False):
    try:
        if actor != resolve_actor(config, uid=actor.uid) or action not in ('read', 'write', 'list'):
            return False
        p = parts(resource)
        if p[0] == 'company':
            return action != 'write' or actor.role == 'owner' or config['defaults']['company_staff_write']
        if company_only:
            return False
        if p[0] == 'people':
            return len(p) >= 2 and p[1] == actor.person
        return p[0] == 'management' and actor.role == 'owner'
    except (AccessDenied, AttributeError):
        return False


def _trusted_config(path):
    with directory(path.parent) as fd:
        parent = os.fstat(fd)
        raw, info = read_regular(fd, path.name, 65536)
        if parent.st_uid != 0 or parent.st_mode & 0o022 or info.st_uid != 0 or info.st_mode & 0o022:
            deny()
        return json.loads(raw)


def load(home):
    """A private connection holds only company ID, never a user/role/UID assertion."""
    home = Path(home)
    marker = home / 'state/company.json'
    try:
        with directory(marker.parent) as fd:
            raw, info = read_regular(fd, marker.name, 1024)
        ident = json.loads(raw)['company']
    except FileNotFoundError:
        return None
    except (KeyError, TypeError, json.JSONDecodeError):
        deny()
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        deny()
    config = validate(_trusted_config(SHARED / ident / 'company.json'))
    if config['id'] != ident or Path(config['vault']) != SHARED / ident / 'vault':
        deny()
    actor = resolve_actor(config)
    if actor.role == 'owner' and Path(config['runtime']) != home.absolute():
        deny()
    policy = Policy(config, actor)
    policy.config_path = SHARED / ident / 'company.json'
    return policy


class Policy:
    def __init__(self, config, actor=None):
        self.config = validate(config)
        self.actor = actor or resolve_actor(config)
        self.vault = Path(config['vault'])
        self.config_path = None

    def require(self, relative, action='read', company_only=False):
        if self.config_path is not None:
            current = validate(_trusted_config(self.config_path))
            if current['vault'] != str(self.vault) or resolve_actor(current) != self.actor:
                deny()
            self.config = current
        if not can_access(self.config, self.actor, relative, action, company_only=company_only):
            deny()
        return parts(relative)

    @contextmanager
    def folder(self, relative, *, create=False, company_only=False):
        chain = self.require(relative, 'write' if create else 'list', company_only)
        with directory(self.vault) as root:
            fd = os.dup(root)
            try:
                for index, part in enumerate(chain):
                    if create and index >= (2 if chain[0] == 'people' else 1):
                        try:
                            os.mkdir(part, 0o770 if chain[0] == 'company' else 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                yield fd
            finally:
                os.close(fd)

    def read(self, relative, limit=2 * 1024 * 1024, *, company_only=False):
        p = self.require(relative, company_only=company_only)
        with self.folder('/'.join(p[:-1]), company_only=company_only) as fd:
            return read_regular(fd, p[-1], limit)

    def create(self, relative, raw):
        p = self.require(relative, 'write')
        with self.folder('/'.join(p[:-1]), create=True) as fd:
            tmp = '.ilson-' + os.urandom(16).hex()
            out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o660 if p[0] == 'company' else 0o600, dir_fd=fd)
            try:
                with os.fdopen(out, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(tmp, p[-1], src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                os.fsync(fd)
            finally:
                os.unlink(tmp, dir_fd=fd)

    def files(self, relative='company', *, suffix=None, limit=1000):
        self.require(relative, 'list')
        found = []
        def walk(rel, depth=0):
            if depth > 20 or len(found) >= limit:
                return
            try:
                with self.folder(rel) as fd:
                    entries = sorted(os.scandir(fd), key=lambda e: e.name)
                    for entry in entries:
                        if entry.name.startswith('.') or len(found) >= limit:
                            continue
                        info = entry.stat(follow_symlinks=False)
                        name = rel + '/' + entry.name
                        if stat.S_ISDIR(info.st_mode):
                            walk(name, depth + 1)
                        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and (suffix is None or name.endswith(suffix)):
                            found.append(name)
            except FileNotFoundError:
                pass
        walk(relative)
        return found

    def personal(self):
        return 'people/' + self.actor.person


def require_owner(home):
    policy = load(home)
    if policy and (policy.actor.role != 'owner' or Path(home).stat().st_uid != os.geteuid()):
        raise AccessDenied('회사 런타임은 대표 계정만 관리합니다. 직원은 company join 후 본인 Claude로 파일을 사용하세요.')
    return policy


def vault_path(home):
    policy = load(home)
    return policy.vault if policy else Path(home) / 'vault'


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('action', choices=('guard', 'vault', 'mode', 'doctor'))
    args = parser.parse_args()
    try:
        policy = load(args.home)
        if args.action == 'guard':
            require_owner(args.home)
        elif args.action == 'vault':
            print(policy.vault if policy else Path(args.home) / 'vault')
        elif args.action == 'mode':
            print('company' if policy else 'single')
        else:
            print('회사 모드: ' + ('대표 · 런타임/웹 관리자 담당' if policy.actor.role == 'owner' else '직원 · 파일 사용만, 예약/관리자 없음') if policy else '단일 사용자 모드')
            if policy:
                print('개인 자료는 본인만. 회사 자동화는 company만 읽습니다. 로그아웃·재부팅 뒤 대표 GUI 로그인과 서비스 복구를 확인하세요.')
        return 0
    except (OSError, ValueError):
        print('회사 접근 거절: 대표 계정·등록·설정을 확인하세요. 직원은 회사 런타임 start/pause/update/admin을 실행할 수 없습니다.', file=__import__('sys').stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
