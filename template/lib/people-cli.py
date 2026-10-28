"""등록 장부는 관리자만 연다. CLI는 로컬 인증 API로 같은 검증·트랜잭션을 사용한다."""
import argparse
import hashlib
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import stat
import sys


class PeopleError(Exception):
    pass


def private_text(home, name):
    folder = home / 'state/web-admin'
    for path in (home, home / 'state', folder):
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
            raise PeopleError('Box 관리 설정 경로와 소유자를 확인하세요.')
    fd = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PeopleError('Box 관리 설정은 현재 사용자만 읽을 수 있어야 합니다.')
        value = stream.read(65537)
        if len(value) > 65536:
            raise PeopleError('Box 관리 설정 크기를 확인하세요.')
        return value


class Client:
    def __init__(self, home):
        self.cookie = ''
        config = json.loads(private_text(home, 'config.json'))
        self.port = config.get('port')
        if config.get('version') != 1 or type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise PeopleError('관리자 포트 설정을 확인하세요.')
        self.origin = 'http://127.0.0.1:' + str(self.port)
        instance = private_text(home, 'instance').strip()
        health = self.call('GET', '/api/health')
        if not re.fullmatch('[A-Za-z0-9_-]{16,128}', instance) or health.get('service') != 'ilson-box-admin' or health.get('instance') != instance:
            raise PeopleError('다른 Box 또는 프로그램의 관리자입니다. 선택한 Box를 확인하세요.')
        token = private_text(home, 'token').strip()
        if not re.fullmatch('[A-Za-z0-9_-]{32,160}', token):
            raise PeopleError('관리자 연결 설정을 확인하세요.')
        self.call('POST', '/api/session', {'token': token})
        expected_cookie = 'ilson_box_admin_' + hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:12] + '='
        if not self.cookie.startswith(expected_cookie):
            self.close()
            raise PeopleError('다른 Box 경로의 관리자입니다. 선택한 Box를 확인하세요.')
        if not self.cookie:
            raise PeopleError('관리자 연결을 확인하지 못했습니다.')

    def call(self, method, path, body=None):
        # http.client does not use proxy settings or follow redirects. Secrets stay in memory.
        connection = HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Origin': self.origin, 'Content-Type': 'application/json'}
        if self.cookie:
            headers['Cookie'] = self.cookie
        try:
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            raw = response.read(8 * 1024 * 1024 + 1)
            if response.status == 401:
                raise PeopleError('관리자 인증이 만료되었거나 거절되었습니다. 같은 요청 ID로 다시 실행하세요.')
            if response.status == 403:
                raise PeopleError('관리자 접근 권한 또는 요청 출처가 거절되었습니다.')
            if len(raw) > 8 * 1024 * 1024 or response.status not in (200, 400, 404, 409):
                raise PeopleError('관리자 응답을 확인하지 못했습니다. 같은 요청 ID로 다시 확인하세요.')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise PeopleError('관리자 응답 형식을 확인하세요.')
            if response.status != 200:
                # Server errors may contain customer input: never echo raw bodies or authentication data.
                messages = {400: '등록 입력을 확인하세요. 이름·역할은 필수이며 부서는 기존 ID여야 합니다.',
                            404: '항목이 없거나 삭제되었습니다. 목록을 확인하세요.',
                            409: '등록 요청이 충돌했습니다. 같은 요청 ID의 내용을 바꾸지 말고 목록을 확인하세요.'}
                raise PeopleError(messages[response.status])
            if path == '/api/session':
                cookie = SimpleCookie();cookie.load(response.getheader('Set-Cookie', ''))
                self.cookie = '; '.join(key + '=' + item.value for key, item in cookie.items())
            return data
        finally:
            connection.close()

    def close(self):
        if self.cookie:
            try:
                self.call('POST', '/api/logout', {})
            except Exception:
                pass
            self.cookie = ''


def main(argv=None):
    parser = argparse.ArgumentParser(description='일손 관리자와 같은 직원 장부를 사용합니다. ILSON_HOME으로 Box를 선택하세요.')
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('ILSON_HOME', str(Path.home() / 'ilson'))))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='직원·부서 목록과 ID 확인')
    get = commands.add_parser('get', help='등록된 직원 ID 확인');get.add_argument('id')
    add = commands.add_parser('add', help='직원 등록; 재시도에는 같은 요청 ID와 내용을 사용')
    add.add_argument('--name', required=True);add.add_argument('--role', required=True)
    add.add_argument('--department-id', default='');add.add_argument('--request-id', required=True)
    args = parser.parse_args(argv)
    client = None
    try:
        if args.command == 'add':
            if not args.name.strip() or len(args.name.strip()) > 80 or not args.role.strip() or len(args.role.strip()) > 2000:
                raise PeopleError('이름(80자 이하)과 역할(2,000자 이하)을 입력하세요. 임의로 만들지 마세요.')
            if not re.fullmatch('[A-Za-z0-9_-]{16,100}', args.request_id):
                raise PeopleError('요청 ID는 영문·숫자·밑줄·하이픈 16~100자로 입력하세요.')
        client = Client(args.home.absolute())
        result = None
        if args.command == 'add':
            result = client.call('POST', '/api/workspace/people/employees/save', {
                'name': args.name.strip(), 'role': args.role.strip(), 'department_id': args.department_id,
                'request_id': args.request_id})
        state = client.call('GET', '/api/workspace/people')
        if args.command in ('get', 'add'):
            key = result['id'] if result else args.id
            employee = next((e for e in state['employees'] if e['id'] == key), None)
            if employee is None:
                raise PeopleError('저장 결과를 확인하지 못했습니다. 같은 요청 ID로 다시 확인하세요.')
            output = {'ok': True, 'id': key, 'employee': employee}
            if result:
                output.update(request_id=args.request_id, replayed=result.get('replayed', False))
        else:
            output = {'employees': state['employees'], 'departments': state['departments']}
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except PeopleError as error:
        print(str(error), file=sys.stderr)
    except Exception:
        print('관리자에 연결하지 못했습니다. 선택한 Box에서 ilson open 후 같은 요청 ID로 다시 확인하세요. 등록 성공으로 처리하지 마세요.', file=sys.stderr)
    finally:
        if client:
            client.close()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
