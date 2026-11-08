"""Naver Commerce product Q&A. Documentation checked 2026-11-08, v2.91.0.

The supplied transport is injectable for isolated tests. Never log HTTP bodies,
credentials, or tokens. A PUT is never retried: it can have succeeded on timeout.
"""
import json
import hashlib
import os
from pathlib import Path
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://api.commerce.naver.com/external'

class APIError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('네이버 연결을 확인하지 못했습니다.' if status is None else f'네이버 요청 실패 ({status})')

class UnknownResult(APIError):
    def __init__(self):
        super().__init__(None)
        self.args = ('답변 등록 결과 확인 필요. 자동 재시도하지 마세요.',)


def secure_json_file(path):
    """Read only an owner's regular file with exactly 0600 and no symlink."""
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(os.fspath(path), flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('인증 파일 소유자와 권한(0600)을 확인하세요.')
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            fd = -1
            data = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    return data

def load_credentials(path):
    data = secure_json_file(path)
    if not isinstance(data, dict) or set(data) - {'client_id', 'client_secret', 'type', 'account_id'}:
        raise ValueError('인증 파일 형식을 확인하세요.')
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in ('client_id', 'client_secret')):
        raise ValueError('인증 파일을 확인하세요.')
    if data.get('type') not in ('SELF', 'SELLER') or not isinstance(data.get('account_id', ''), str) or (data['type'] == 'SELLER' and not data.get('account_id')):
        raise ValueError('계정 유형을 확인하세요.')
    return data


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def transport(method, url, headers, data):
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise APIError(None)
            return response.status, raw
    except HTTPError as exc:
        # Never propagate the upstream response body or request headers.
        return exc.code, b''
    except (URLError, TimeoutError, OSError):
        raise APIError(None) from None


class NaverQna:
    def __init__(self, credentials_path, *, home, send=transport, now=time.time):
        self.credentials_path = Path(credentials_path)
        self.home = Path(home)
        self.send = send
        self.now = now
        self.token = None

    def identity(self):
        creds = load_credentials(self.credentials_path)
        identity = [creds['client_id'], creds['type'], creds.get('account_id', '')]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    def _token(self):
        creds = load_credentials(self.credentials_path)
        from replies_runtime import sign
        timestamp = str(int(self.now() * 1000))
        signed = sign(self.home, creds['client_id'], creds['client_secret'], timestamp)
        fields = {'client_id': creds['client_id'], 'timestamp': timestamp,
                  'client_secret_sign': signed, 'grant_type': 'client_credentials', 'type': creds['type']}
        if creds['type'] == 'SELLER':
            fields['account_id'] = creds['account_id']
        status, raw = self.send('POST', BASE + '/v1/oauth2/token', {'Content-Type': 'application/x-www-form-urlencoded', 'Accept':'application/json'}, urlencode(fields).encode())
        if status != 200:
            raise APIError(status)
        try:
            result = json.loads(raw)
            token = result['access_token']
            if not isinstance(token, str) or not token:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise APIError(None) from None
        self.token = token

    def _request(self, method, path, params=None, body=None):
        if not self.token:
            self._token()
        url = BASE + path + (('?' + urlencode(params)) if params else '')
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept':'application/json'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        try:
            status, raw = self.send(method, url, headers, payload)
            # Only GET may be repeated after an expired token. PUT is never repeated.
            if method == 'GET' and status == 401:
                self.token = None
                self._token()
                headers['Authorization'] = 'Bearer ' + self.token
                status, raw = self.send(method, url, headers, payload)
        except APIError:
            if method == 'PUT':
                raise UnknownResult() from None
            raise
        if method == 'PUT' and (status >= 500 or status == 429):
            raise UnknownResult()
        if not 200 <= status < 300:
            raise APIError(status)
        if method == 'PUT':
            if status != 204:
                raise UnknownResult()
            return None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise APIError(None) from None

    def page(self, start, end, page):
        if type(page) is not int or page < 1:
            raise ValueError('페이지 번호 오류')
        return self._request('GET', '/v1/contents/qnas', {'fromDate': start, 'toDate': end, 'page': page, 'size': 100})

    def answer(self, question_id, body):
        if type(question_id) is not int or question_id <= 0 or not isinstance(body, str) or not body.strip():
            raise ValueError('답변 대상을 확인하세요.')
        return self._request('PUT', '/v1/contents/qnas/' + str(question_id), body={'commentContent': body})
