"""Company provisioning plans. Never apply ACLs without --apply + a human prompt."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import sys

import access_policy as access

# D-e is deliberately an on-site checklist, not automated machine configuration.
RIGHTS = 'read,write,append,execute,delete_child,readattr,writeattr,readextattr,writeextattr,readsecurity,file_inherit,directory_inherit'
READ_RIGHTS = 'read,execute,readattr,readextattr,readsecurity,file_inherit,directory_inherit'

class CompanyError(ValueError):
    pass

CLIENT_FILES = ('access_policy.py', 'company.py', 'curator.py', 'company_runtime.py', 'install_diagnostics.py')


def account(value, role):
    fields = value.split(':')
    if len(fields) != 2 or not all(access.ID.fullmatch(f) for f in fields):
        raise CompanyError('사람은 변경하지 않을 ID:macOS계정 형식으로 지정하세요.')
    entry = pwd.getpwnam(fields[1])
    if entry.pw_uid < 501:
        raise CompanyError('일반 사용자 계정만 연결하세요.')
    return dict(id=fields[0], account=entry.pw_name, uid=entry.pw_uid, role=role, active=True)


def configuration(ident, home, owner, staff):
    if not access.ID.fullmatch(ident) or owner['uid'] != os.geteuid():
        access.deny()
    return access.validate(dict(schema=1, id=ident, owner_uid=owner['uid'],
        runtime=str(Path(home).absolute()), vault=str(access.SHARED / ident / 'vault'),
        defaults=access.DEFAULTS.copy(), people=[owner, *staff]))


def init_plan(config, source):
    """Fresh install only: never reset existing ACLs or implicitly migrate notes."""
    base = access.SHARED / config['id']
    vault = base / 'vault'
    group = 'ilson_' + config['id']
    commands = [['/bin/test', '!', '-e', str(base)],
        ['/usr/sbin/dseditgroup', '-o', 'create', group],
        ['/usr/bin/install', '-d', '-m', '755', str(access.SHARED)],
        ['/usr/bin/install', '-d', '-m', '755', str(base), str(vault), str(base / 'client')],
        ['/usr/bin/install', '-d', '-m', '755', str(vault / 'people')],
        ['/usr/bin/install', '-d', '-m', '700', str(vault / 'company'), str(vault / 'management')],
        ['/usr/bin/chgrp', group, str(vault / 'company')],
        ['/bin/chmod', '+a', f"group:{group} allow {RIGHTS if config['defaults']['company_staff_write'] else READ_RIGHTS}", str(vault / 'company')]]
    for p in config['people']:
        commands += [['/usr/sbin/dseditgroup', '-o', 'edit', '-a', p['account'], '-t', 'user', group],
            ['/usr/bin/install', '-d', '-m', '700', str(vault / 'people' / p['id'])],
            ['/bin/chmod', '+a', f"user:{p['account']} allow {RIGHTS}", str(vault / 'people' / p['id'])]]
        if p['role'] == 'owner':
            commands.append(['/bin/chmod', '+a', f"user:{p['account']} allow {RIGHTS}", str(vault / 'company')])
            commands.append(['/bin/chmod', '+a', f"user:{p['account']} allow {RIGHTS}", str(vault / 'management')])
    for name in CLIENT_FILES:
        commands.append(['/usr/bin/install', '-m', '644', str(Path(source) / name), str(base / 'client' / name)])
    commands.append(['/usr/bin/install', '-m', '755', str(Path(source) / 'company-client.sh'), str(base / 'client/ilson')])
    # The owner home is not a shared code or secrets directory. Parent traversal stops staff.
    commands += [['/bin/chmod', '-N', config['runtime']], ['/bin/chmod', '700', config['runtime']]]
    return commands


def offboard_plan(config, person):
    p = next((p for p in config['people'] if p['id'] == person and p['role'] == 'staff' and p['active']), None)
    if p is None:
        raise CompanyError('활성 직원 ID를 확인하세요.')
    vault = Path(config['vault'])
    dest = vault / 'management/offboarding' / person
    # Move and revoke ACL before marking inactive. Root owns the anchor; preserving
    # employee ACLs after mv would expose the archive, so normalize the moved tree.
    owner = next(p for p in config['people'] if p['role'] == 'owner')
    return [['/bin/test', '!', '-e', str(dest)],
        ['/bin/chmod', '+a#', '0', f"user:{p['account']} deny read,write,execute,delete,delete_child,readattr,writeattr,readextattr,writeextattr,readsecurity,file_inherit,directory_inherit", str(vault / 'company')],
        ['/usr/sbin/dseditgroup', '-o', 'edit', '-d', p['account'], '-t', 'user', 'ilson_' + config['id']],
        ['/usr/bin/install', '-d', '-m', '700', str(dest.parent)],
        ['/bin/mv', str(vault / 'people' / person), str(dest)],
        ['/bin/chmod', '-R', '-P', '-N', str(dest)],
        ['/usr/sbin/chown', '-R', '-P', str(config['owner_uid']), str(dest)],
        ['/bin/chmod', '-R', '-P', 'u+rwX,go-rwx', str(dest)],
        ['/bin/chmod', '+a', f"user:{owner['account']} allow {RIGHTS}", str(dest.parent)]]


def anchor_script():
    # mkdir is atomic under macOS's root-owned sticky /Users/Shared. If another
    # user pre-created Ilson, reject it before install/chmod can follow anything.
    shared = shlex.quote(str(access.SHARED))
    return (f'if ! /bin/mkdir -m 755 {shared} 2>/dev/null; then\n'
            f'  /bin/test ! -L {shared}\n'
            f'  /bin/test "$(/usr/bin/stat -f %u:%Lp {shared})" = "0:755"\n'
            'fi')


def apply_plan(commands, config):
    # No sudo, shell password reading or credentials in argv. Standard macOS GUI prompt.
    if sys.platform != 'darwin':
        raise CompanyError('ACL 적용은 macOS에서만 지원합니다.')
    base = access.SHARED / config['id']
    text = 'set -eu\numask 077\n' + anchor_script() + '\n' + '\n'.join(shlex.join(c) for c in commands)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    text += '\nprintf %s ' + shlex.quote(payload) + ' > ' + shlex.quote(str(base / 'company.json.next'))
    text += '\n/bin/chmod 644 ' + shlex.quote(str(base / 'company.json.next'))
    text += '\n/bin/mv ' + shlex.quote(str(base / 'company.json.next')) + ' ' + shlex.quote(str(base / 'company.json'))
    script = 'do shell script ' + json.dumps(text, ensure_ascii=False) + ' with administrator privileges'
    subprocess.run(['/usr/bin/osascript', '-e', script], check=True)


def private_write(path, raw, mode=0o600):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with access.directory(path.parent) as fd:
        out = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
        with os.fdopen(out, 'wb') as stream:
            stream.write(raw)


def connection(home, ident):
    path = Path(home) / 'state/company.json'
    raw = json.dumps({'company': ident}).encode()
    if path.exists():
        with access.directory(path.parent) as fd:
            prior, _ = access.read_regular(fd, path.name, 1024)
        if json.loads(prior) != {'company': ident}:
            access.deny()
        return
    private_write(path, raw)


def join(ident, user_home=None):
    if not access.ID.fullmatch(ident):
        access.deny()
    config = access.validate(access._trusted_config(access.SHARED / ident / 'company.json'))
    actor = access.resolve_actor(config)
    if actor.role != 'staff':
        raise CompanyError('대표는 기존 Box를 사용하세요. join은 직원 연결 명령입니다.')
    user_home = Path(user_home or Path.home())
    local = user_home / '.ilson-company' / ident
    if user_home.stat().st_uid != os.geteuid():
        access.deny()
    connection(local, ident)
    workspace = local / 'workspace'
    workspace.mkdir(mode=0o700, exist_ok=True)
    instructions = ('# 회사 일손 작업공간\n\n본인 Claude 계정으로 로그인하세요.\n'
        f"공용: {config['vault']}/company/\n개인: {config['vault']}/people/{actor.person}/\n"
        '공용 파일 변경은 회사 이력에 남습니다. 개인 내용은 공용 문서에 복사하지 마세요.\n'
        '대표 웹 관리자·예약·승인·라이선스는 대표가 관리합니다.\n')
    if not (workspace / 'CLAUDE.md').exists():
        private_write(workspace / 'CLAUDE.md', instructions.encode())
    wrapper = '#!/bin/sh\nexec python3 ' + shlex.quote(str(access.SHARED / ident / 'client/company.py')) + ' client --home ' + shlex.quote(str(local)) + ' "$@"\n'
    binary = user_home / '.local/bin/ilson'
    if binary.exists() or binary.is_symlink():
        with access.directory(binary.parent) as fd:
            prior, _ = access.read_regular(fd, binary.name, 10000)
        if prior != wrapper.encode():
            raise CompanyError('기존 ilson 명령을 보존했습니다. 별도 계정/기존 설치를 확인하세요.')
    else:
        private_write(binary, wrapper.encode(), 0o700)
    print(f'직원 연결 준비 완료: {workspace}\n이 폴더에서 본인 Claude 로그인·신뢰 확인을 마치세요. 자동 업무는 설치하지 않았습니다.')


def client(home, args):
    policy = access.load(home)
    if not policy:
        access.deny()
    command = args[0] if args else 'doctor'
    if command in ('curator', 'diary'):
        import curator
        return curator.main(['--home', str(home), *args[1:]])
    if command == 'doctor':
        print('회사 모드 · 직원: company와 본인 people 파일만 사용합니다. 웹 관리자·예약·update는 대표 전용입니다.')
        if '--install' in args or '--share' in args:
            import install_diagnostics
            return install_diagnostics.main(args[1:])
        return 0
    if command == 'company' and args[1:] == ['status']:
        print('회사 연결 활성 · 직원 · 웹 로그인 미지원')
        return 0
    raise CompanyError('회사 런타임은 대표 전용입니다. 직원은 본인 Claude·curator·doctor를 사용하세요.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='회사 일손: 대표 런타임 하나 + 사람별 파일 접근')
    parser.add_argument('--home', default=os.environ.get('ILSON_HOME', str(Path.home() / 'ilson')))
    subs = parser.add_subparsers(dest='action', required=True)
    init = subs.add_parser('init')
    init.add_argument('--id', required=True)
    init.add_argument('--owner', required=True, help='불변ID:macOS계정')
    init.add_argument('--staff', action='append', default=[])
    for sub in (init,):
        sub.add_argument('--apply', action='store_true')
        sub.add_argument('--dry-run', action='store_true')
    connect = subs.add_parser('join')
    connect.add_argument('--id', required=True)
    off = subs.add_parser('offboard')
    off.add_argument('person')
    off.add_argument('--apply', action='store_true')
    off.add_argument('--dry-run', action='store_true')
    publish = subs.add_parser('publish')
    publish.add_argument('source', help='management 안의 검토한 보고서 상대 경로')
    publish.add_argument('--to', required=True, help='company 안의 새 상대 경로')
    publish.add_argument('--apply', action='store_true')
    subs.add_parser('status')
    cli = subs.add_parser('client')
    cli.add_argument('--home', required=True, dest='client_home')
    cli.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == 'client':
            return client(args.client_home, args.args)
        if args.action == 'join':
            join(args.id)
            return 0
        if args.action == 'status':
            policy = access.load(args.home)
            print('회사 모드 · ' + policy.actor.role if policy else '단일 사용자 모드')
            return 0
        if args.action == 'publish':
            policy = access.require_owner(args.home)
            if not policy or not args.source.startswith('management/reports/') or not args.to.startswith('company/'):
                access.deny()
            raw, _ = policy.read(args.source, 256 * 1024)
            print('대표 전용 보고서 → 공용 새 문서: ' + args.to)
            if not args.apply:
                print('계획만 표시했습니다. 본문을 검토한 뒤 --apply로 명시적으로 공개하세요.')
                return 0
            if not sys.stdin.isatty() or input('검토한 본문을 직원에게 공개합니까? [yes/N] ').strip() != 'yes':
                raise CompanyError('공개 취소')
            policy.create(args.to, raw)
            print('공용 새 문서 저장 완료. 원본 관리 문서는 보존했습니다.')
            return 0
        if args.action == 'init':
            home = Path(args.home).absolute()
            if home.is_symlink() or home.stat().st_uid != os.geteuid() or not (home / 'lib').is_dir():
                raise CompanyError('대표의 기존 Box 설치를 먼저 확인하세요.')
            config = configuration(args.id, home, account(args.owner, 'owner'), [account(p, 'staff') for p in args.staff])
            if (access.SHARED / args.id).exists():
                raise CompanyError('기존 회사 폴더를 보존했습니다. 재실행으로 ACL을 초기화하지 않습니다.')
            commands = init_plan(config, Path(__file__).parent)
            print('기존 vault 노트: 자동 이관 0. 대표가 파일별 공개 범위·백업·목적지를 검토한 이관 목록을 먼저 작성하세요.')
        else:
            policy = access.require_owner(args.home)
            if not policy:
                access.deny()
            config = policy.config
            commands = offboard_plan(config, args.person)
            config = json.loads(json.dumps(config))
            for p in config['people']:
                if p['id'] == args.person:
                    p['active'] = False
        print('공유 상위 폴더: root 소유·755·링크 아님을 확인, 없을 때만 원자적으로 생성')
        print(anchor_script())
        print('\n'.join(shlex.join(c) for c in commands))
        print('설정 저장: 회사 ID·UID·역할·기본 정책 (root 소유, 직원 수정 불가)')
        if not args.apply or args.dry_run:
            print('계획만 표시했습니다. 변경 0. --apply로 계획을 확인하고 macOS 관리자 인증 후 적용합니다.')
            return 0
        if not sys.stdin.isatty() or input('위 계획을 적용합니까? [yes/N] ').strip() != 'yes':
            raise CompanyError('계획 적용을 취소했습니다.')
        apply_plan(commands, config)
        if args.action == 'init':
            connection(args.home, config['id'])
        print('설정 적용 완료. 두 사용자 실기·SSH·재부팅 복구 점검은 현장 체크리스트로 확인하세요.')
        return 0
    except (CompanyError, access.AccessDenied) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('회사 설정 미완료: 계정·경로·기존 설치·권한을 확인하세요. 기존 데이터는 자동 이관하지 않습니다.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
