"""Consent-based skill sharing. All network access requires online validation."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import license as licensing
import selflearn

MAX_BYTES = 48000
MAX_FILES = 10
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.md\Z')
ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
ADDRESS = re.compile(r'(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[^\n]{0,45}(?:시|군|구|읍|면|동|로|길)\s*\d')

class Problem(Exception):
    pass


def check_path(base, path, *, missing=False):
    base = Path(base).absolute()
    path = Path(path).absolute()
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        raise Problem('경로가 작업 폴더 밖입니다') from None
    for current in (base, *(base.joinpath(*parts[:n]) for n in range(1, len(parts) + 1))):
        try:
            st = current.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise Problem('파일 또는 폴더가 없습니다') from None
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise Problem('심볼릭 링크 또는 연결 경로를 허용하지 않습니다')
        if os.name != 'nt' and st.st_uid != os.getuid():
            raise Problem('파일 소유자를 확인하세요')
        if current != path and not stat.S_ISDIR(st.st_mode):
            raise Problem('상위 경로가 폴더가 아닙니다')
    return path


def read_file(base, path, maximum=MAX_BYTES):
    path = check_path(base, path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o111 or st.st_size > maximum:
            raise Problem('일반 텍스트 파일만 허용하며 실행 파일과 크기 초과는 금지됩니다')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise Problem('파일 크기 상한을 초과했습니다')
        return raw.decode('utf-8')
    except UnicodeError:
        raise Problem('UTF-8 텍스트만 허용합니다') from None
    finally:
        os.close(fd)


def company_names(home, flat=False):
    root = Path(home) / ('company' if flat else 'vault/company')
    check_path(home, root, missing=True)
    if not root.exists():
        return set()
    names = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            check_path(home, path)
            candidate = path.stem if path.is_file() else name
            if not candidate.startswith('_') and len(candidate) >= 2:
                names.add(unicodedata.normalize('NFKC', candidate).casefold())
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() == '.md':
                for line in read_file(home, path).splitlines():
                    # Explicit company-name fields avoid treating ordinary headings as names.
                    match = re.match(r'^\s*(?:[-*]\s*)?(?:\*\*)?(?:회사명|기업명|거래처명|담당자명|고객명|대표명|이름)(?:\*\*)?\s*[:：]\s*(.{2,80}?)\s*$', line)
                    if match:
                        value = match.group(1).strip(' \t\'"')
                        if len(value) >= 2:
                            names.add(unicodedata.normalize('NFKC', value).casefold())
    return names


def inspect_files(files, names=()):
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or 'SKILL.md' not in files:
        raise Problem('SKILL.md를 포함한 최대 10개 파일이 필요합니다')
    total = 0
    findings = []
    for filename, content in files.items():
        if not isinstance(filename, str) or not FILENAME.fullmatch(filename) or not isinstance(content, str):
            raise Problem('파일 이름 또는 형식이 올바르지 않습니다')
        if any(pattern.search(filename) for pattern in selflearn.SENSITIVE):
            findings.append(f'{filename}: 파일 이름에 개인정보 또는 비밀값')
        total += len(content.encode('utf-8'))
        if re.search(r'[\x00-\x08\x0b-\x1f\x7f]', content):
            raise Problem(f'{filename}: 제어 문자는 허용하지 않습니다')
        for lineno, line in enumerate(content.splitlines(), 1):
            scanned = re.sub(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', '', line)
            if any(pattern.search(scanned) for pattern in selflearn.SENSITIVE):
                findings.append(f'{filename}:{lineno}: 개인정보 또는 비밀값')
            if ADDRESS.search(line):
                findings.append(f'{filename}:{lineno}: 주소 형태')
            normalized = unicodedata.normalize('NFKC', line).casefold()
            if any(name in normalized for name in names):
                findings.append(f'{filename}:{lineno}: 회사 고유 이름')
            if selflearn.UNSAFE.search(line) or selflearn.PRIVILEGE.search(line):
                findings.append(f'{filename}:{lineno}: 실행·외부 연결 또는 권한 우회 지시')
    if total > MAX_BYTES:
        raise Problem('전체 파일 크기는 48000바이트 이하여야 합니다')
    return findings


def bundle(home, name, flat=False):
    if not NAME.fullmatch(name):
        raise Problem('스킬 이름을 확인하세요')
    if any(pattern.search(name) for pattern in selflearn.SENSITIVE):
        raise Problem('스킬 이름: 개인정보 또는 비밀값')
    root = check_path(home, Path(home) / '.claude' / 'skills' / name)
    if not root.is_dir():
        raise Problem('스킬 폴더가 아닙니다')
    names = company_names(home, flat)
    if any(company in unicodedata.normalize('NFKC', name).casefold() for company in names):
        raise Problem('스킬 이름: 회사 고유 이름')
    files = {}
    for path in sorted(root.iterdir()):
        check_path(home, path)
        if not FILENAME.fullmatch(path.name):
            raise Problem(f'{path.name}: Markdown 파일만 허용합니다')
        if any(company in unicodedata.normalize('NFKC', path.name).casefold() for company in names):
            raise Problem(f'{path.name}: 회사 고유 이름')
        files[path.name] = read_file(home, path)
        if len(files) > MAX_FILES:
            raise Problem('파일 개수 상한을 초과했습니다')
    findings = inspect_files(files, names)
    if findings:
        raise Problem('\n'.join(findings))
    return files


def confirm(prompt):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Problem('실제 터미널에서 직접 확인해야 합니다')
    return input(prompt + ' [yes 입력]: ').strip() == 'yes'


def show(item):
    print('스킬:', item['name'], '기수:', item.get('cohort', '-'), '별칭:', item.get('alias', '-'))
    for name, text in sorted(item['files'].items()):
        print('\n--- ' + name + ' ---\n' + text)


def request(home, action, **extra):
    directory = licensing.private_dir(home)
    serial = licensing.safe_read(directory / 'serial').strip()
    device = licensing.safe_read(directory / 'device-id').strip()
    licensing.parse_serial(serial)
    if not re.fullmatch('[a-f0-9]{64}', device):
        raise Problem('기기 등록을 확인하세요')
    nonce = secrets.token_hex(16)
    data = json.dumps(dict(serial=serial, device_id=device, nonce=nonce, **extra), ensure_ascii=False).encode('utf-8')
    url = licensing.API_URL
    if urllib.parse.urlparse(url).scheme != 'https':
        raise Problem('서버 연결을 확인하세요')
    req = urllib.request.Request(url.rstrip('/') + '/api/v1/skill-' + action, data, {'Content-Type':'application/json', 'Cache-Control':'no-store'}, method='POST')
    try:
        with urllib.request.build_opener(licensing.NoRedirect).open(req, timeout=5) as response:
            raw = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        try:
            result = json.loads(error.read(8193))
            status = result.get('status') if result.get('nonce') == nonce else None
        except (ValueError, OSError):
            status = None
        raise Problem('서버가 요청을 거부했습니다: ' + (status or '연결 오류')) from None
    except OSError:
        raise Problem('서버에 연결할 수 없습니다. 오프라인 유예 중에는 나눔을 사용할 수 없습니다') from None
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('nonce') != nonce or result.get('status') != 'ok' or not isinstance(result.get('server_time'), int) or abs(int(time.time()) - result['server_time']) > 300:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise Problem('서버 응답을 확인할 수 없습니다') from None


def validate_item(item):
    if not isinstance(item, dict):
        raise Problem('받은 스킬 정보가 올바르지 않습니다')
    name, ident, alias, cohort, files = (item.get(k) for k in ('name', 'id', 'alias', 'cohort', 'files'))
    if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(ident, str) or not ID.fullmatch(ident) or not isinstance(alias, str) or not re.fullmatch(r'나눔-[a-f0-9]{10}', alias) or type(cohort) is not int or not 1 <= cohort <= 65535:
        raise Problem('받은 스킬 정보가 올바르지 않습니다')
    findings = inspect_files(files)
    if findings:
        raise Problem('\n'.join(findings))
    return name, ident, alias, cohort, files


def install(home, item):
    name, ident, alias, cohort, files = validate_item(item)
    skills = Path(home) / '.claude' / 'skills'
    check_path(home, skills, missing=True)
    skills.mkdir(parents=True, exist_ok=True)
    check_path(home, skills)
    target = skills / name
    check_path(home, target, missing=True)
    try:
        target.mkdir()  # Exclusive: never overwrite a user's skill.
    except FileExistsError:
        raise Problem('같은 이름의 스킬이 있어 덮어쓰지 않았습니다') from None
    try:
        for filename, content in files.items():
            if filename == 'SKILL.md':
                content += f'\n\n출처: 스킬 나눔 · {cohort}기 · {alias} · {ident}\n'
            with (target / filename).open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
    except BaseException:
        for filename in files:
            path = target / filename
            if path.is_file() and not path.is_symlink():
                path.unlink()
        target.rmdir()
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='시리얼 사용자 스킬 나눔')
    parser.add_argument('--home', required=True)
    parser.add_argument('--license-home', required=True)
    parser.add_argument('--flat-vault', action='store_true')
    parser.add_argument('action', choices=('share', 'list', 'get', 'withdraw'))
    parser.add_argument('value', nargs='?')
    args = parser.parse_args(argv)
    try:
        if args.action == 'list':
            if args.value: raise Problem('목록에는 이름을 입력하지 않습니다')
            for item in request(args.license_home, 'list')['items']:
                print(item['id'], item['name'], str(item['cohort']) + '기', item['alias'])
        elif args.action == 'share':
            files = bundle(args.home, args.value or '', args.flat_vault)
            show({'name':args.value, 'files':files})
            if not confirm('위 내용을 검토 대기로 올릴까요?'): raise Problem('취소했습니다')
            result = request(args.license_home, 'share', name=args.value, files=files)
            print('검토 대기:', result['id'])
        else:
            if not args.value or not ID.fullmatch(args.value): raise Problem('스킬 ID를 확인하세요')
            if args.action == 'withdraw':
                request(args.license_home, 'withdraw', id=args.value)
                print('공유를 내렸습니다')
            else:
                item = request(args.license_home, 'get', id=args.value)['item']
                # Validate before printing, so terminal control characters cannot be injected.
                validate_item(item)
                show(item)
                if not confirm('위 스킬을 설치할까요?'): raise Problem('취소했습니다')
                current = request(args.license_home, 'get', id=args.value)['item']
                validate_item(current)
                if current != item:
                    raise Problem('검토한 내용이 바뀌어 설치를 중단했습니다. 다시 확인하세요')
                print('설치:', install(args.home, item))
        return 0
    except (Problem, OSError, ValueError, KeyError, TypeError) as error:
        print('스킬 나눔: ' + str(error), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
