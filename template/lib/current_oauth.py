"""기존 SNS 연결 흐름의 로컬 OAuth. 코드 교환과 토큰 보관은 이 미니에서만 한다."""
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from mini_workspace import WorkspaceError, safe_private
from social.http import NoRedirect

GRAPH = 'https://graph.facebook.com/v21.0'
SCOPES = {'pages_show_list', 'pages_read_engagement', 'pages_manage_posts'}
AUTH = {'threads': 'https://threads.net/oauth/authorize',
        'instagram': 'https://www.instagram.com/oauth/authorize',
        'facebook': 'https://www.facebook.com/v21.0/dialog/oauth'}
SCOPE = {'threads': 'threads_basic,threads_content_publish',
         'instagram': 'instagram_business_basic,instagram_business_content_publish',
         'facebook': ','.join(sorted(SCOPES))}
TOKEN = {'threads': 'https://graph.threads.net/oauth/access_token',
         'instagram': 'https://api.instagram.com/oauth/access_token'}
BASE = {'threads': 'https://graph.threads.net', 'instagram': 'https://graph.instagram.com'}
HOSTS = {'graph.facebook.com', 'graph.threads.net', 'graph.instagram.com', 'api.instagram.com'}


def request(method, url, fields=None, bearer=''):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        raise WorkspaceError('인증 서버 주소를 확인하세요.')
    headers = {'Authorization': 'Bearer ' + bearer} if bearer else {}
    body = None
    if method == 'GET' and fields:
        url += ('&' if '?' in url else '?') + urlencode(fields)
    elif fields:
        body = urlencode(fields).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('error'):
            raise ValueError()
        return result
    except Exception:
        # URL이나 API 오류에 시크릿·토큰이 실릴 수 있어 원문은 전파하지 않는다.
        raise WorkspaceError('SNS 인증 응답을 확인하지 못했습니다. 다시 연결하세요.', 502) from None


class OAuth:
    def __init__(self, work, *, send=request, clock=time.time):
        self.work, self.send, self.clock = work, send, clock
        with work.transaction():
            work.db.execute('''CREATE TABLE IF NOT EXISTS oauth_requests(
                digest TEXT PRIMARY KEY, platform TEXT, account TEXT, page_id TEXT,
                expires REAL, status TEXT, message TEXT)''')
            # 인증 코드는 일회용이다. 중단된 교환을 자동 재시도하지 않는다.
            work.db.execute("UPDATE oauth_requests SET status='failed',message='인증 확인 중 관리자가 재시작됐습니다. 연결 상태를 확인하고 다시 요청하세요.' WHERE status='exchanging'")

    def config(self, platform):
        if platform not in AUTH:
            raise WorkspaceError('해당 SNS는 기존 브라우저 연결 경로를 사용하세요.')
        try:
            data = safe_private(self.work.credentials / 'oauth-apps.json')[platform]
            uri = urlsplit(data['redirect_uri'])
            if (not re.fullmatch(r'[0-9]{3,40}', str(data['app_id'])) or not data.get('app_secret')
                    or uri.scheme != 'https' or not uri.hostname or uri.username or uri.password
                    or uri.path != '/api/oauth/callback/' + platform or uri.query or uri.fragment):
                raise ValueError()
            return data
        except (OSError, KeyError, TypeError, ValueError):
            raise WorkspaceError('이 미니의 SNS 인증 앱과 HTTPS 콜백 주소를 먼저 설정하세요.', 409) from None

    def callback_host(self, host, path):
        platform = path.rsplit('/', 1)[-1]
        try:
            uri = urlsplit(self.config(platform)['redirect_uri'])
            return uri.netloc.lower() == host.lower() and uri.path == path
        except WorkspaceError:
            return False

    def start(self, data):
        self.work.sandbox()
        platform = data.get('platform')
        cfg = self.config(platform)
        from current_account_registry import identity
        try:
            _, account = identity(platform, data.get('account'))
        except ValueError as error:
            raise WorkspaceError(str(error)) from None
        page_id = str(data.get('page_id') or '')
        if platform == 'facebook' and not re.fullmatch(r'[0-9]{5,30}', page_id):
            raise WorkspaceError('연결할 Facebook 페이지 ID를 확인하세요.')
        state = secrets.token_urlsafe(32)
        digest = hashlib.sha256(state.encode()).hexdigest()
        with self.work.transaction():
            self.work.db.execute("UPDATE oauth_requests SET status='expired',message='새 연결 요청으로 대체되었습니다.' WHERE platform=? AND account=? AND status='waiting'", (platform, account))
            self.work.db.execute('INSERT INTO oauth_requests VALUES(?,?,?,?,?,?,?)',
                                 (digest, platform, account, page_id, self.clock() + 600, 'waiting', 'SNS 인증 창에서 연결을 승인하세요.'))
        return {'ok': True, 'authorize_url': AUTH[platform] + '?' + urlencode({
            'client_id': cfg['app_id'], 'redirect_uri': cfg['redirect_uri'],
            'response_type': 'code', 'scope': SCOPE[platform], 'state': state})}

    def connections(self):
        with self.work.lock:
            rows = self.work.db.execute('SELECT platform,account,status,message,expires FROM oauth_requests ORDER BY expires DESC LIMIT 10').fetchall()
        return [{'platform': r['platform'], 'expected_account': r['account'],
                 'status': 'expired' if r['status'] == 'waiting' and r['expires'] < self.clock() else r['status'],
                 'message': '인증 요청이 만료되었습니다.' if r['status'] == 'waiting' and r['expires'] < self.clock() else r['message']} for r in rows]

    def finish(self, platform, params):
        state = params.get('state', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', state):
            raise WorkspaceError('인증 요청을 확인할 수 없습니다.', 403)
        digest = hashlib.sha256(state.encode()).hexdigest()
        with self.work.transaction():
            row = self.work.db.execute('SELECT * FROM oauth_requests WHERE digest=?', (digest,)).fetchone()
            if not row or row['platform'] != platform or row['status'] != 'waiting' or row['expires'] < self.clock():
                raise WorkspaceError('인증 요청이 만료되었거나 이미 처리됐습니다.', 403)
            self.work.db.execute("UPDATE oauth_requests SET status='exchanging',message='인증 결과를 확인하고 있습니다.' WHERE digest=?", (digest,))
        try:
            code = params.get('code', '')
            if params.get('error') or not isinstance(code, str) or not 1 <= len(code) <= 8000:
                raise WorkspaceError('SNS 인증이 취소되었거나 코드가 없습니다.')
            cfg = self.config(platform)
            if platform == 'facebook':
                got = facebook_exchange(code, row['page_id'], cfg, now=datetime.fromtimestamp(self.clock(), timezone.utc),
                                        get=lambda path, fields=None, token='': self.send('GET', GRAPH + path, fields, token))
                token = got['access_token']
            else:
                short = self.send('POST', TOKEN[platform], {'client_id': cfg['app_id'], 'client_secret': cfg['app_secret'],
                                  'grant_type': 'authorization_code', 'redirect_uri': cfg['redirect_uri'], 'code': code})
                if not short.get('access_token'):
                    raise WorkspaceError('단기 인증 교환을 확인하지 못했습니다.')
                got = self.send('GET', BASE[platform] + '/access_token', {
                    'grant_type': 'th_exchange_token' if platform == 'threads' else 'ig_exchange_token',
                    'client_secret': cfg['app_secret'], 'access_token': short['access_token']})
                if not got.get('access_token') or int(got.get('expires_in') or 0) <= 0:
                    raise WorkspaceError('장기 인증을 확인하지 못했습니다. 다시 연결하세요.')
                token = got['access_token']
                got['expires_at'] = datetime.fromtimestamp(self.clock() + int(got['expires_in']), timezone.utc).isoformat()
            profile = self.work.providers.verify(platform, token, row['page_id'] if platform == 'facebook' else '')
            if platform != 'facebook' and profile['username'].lstrip('@').casefold() != row['account'].casefold():
                raise WorkspaceError('요청한 계정과 SNS에서 로그인한 계정이 다릅니다.')
            account = self.work.connect({'platform': platform, 'token': token, 'expected_user_id':profile['user_id']})
            with self.work.transaction():
                self.work.db.execute("UPDATE oauth_requests SET status='connected',message='계정 인증과 연결을 확인했습니다.' WHERE digest=?", (digest,))
                key = platform + ':' + account['username'].casefold()
                meta = self.work.db.execute('SELECT value FROM account_registry WHERE key=?', (key,)).fetchone()
                requested_key = platform + ':' + row['account'].casefold()
                if not meta:
                    meta = self.work.db.execute('SELECT value FROM account_registry WHERE key=?', (requested_key,)).fetchone()
                public = json.loads(meta['value']) if meta else {'platform': platform, 'account': account['username']}
                public.update(account=account['username'], expires_at=got['expires_at'], linked_at=datetime.now(timezone.utc).isoformat(), origin='internal')
                if platform == 'facebook': public['page_id'] = row['page_id']
                self.work.db.execute('INSERT OR REPLACE INTO account_registry VALUES(?,?)', (key, json.dumps(public, ensure_ascii=False)))
                if requested_key != key:
                    self.work.db.execute('DELETE FROM account_registry WHERE key=?', (requested_key,))
            return {'ok': True}
        except Exception:
            with self.work.transaction():
                self.work.db.execute("UPDATE oauth_requests SET status='failed',message='SNS 인증을 완료하지 못했습니다. 계정·권한·연결 설정을 확인하세요.' WHERE digest=?", (digest,))
            raise WorkspaceError('SNS 인증을 완료하지 못했습니다. 계정·권한·연결 설정을 확인하세요.', 400) from None


def facebook_exchange(code, page_id, cfg, *, now, get):
    short = get('/oauth/access_token', {'client_id':cfg['app_id'], 'client_secret':cfg['app_secret'],
                'redirect_uri':cfg['redirect_uri'], 'code':code})
    if not short.get('access_token'):
        raise WorkspaceError('Facebook 인증 교환을 완료하지 못했습니다.')
    long = get('/oauth/access_token', {'client_id':cfg['app_id'], 'client_secret':cfg['app_secret'],
               'grant_type':'fb_exchange_token', 'fb_exchange_token':short['access_token']})
    token = long.get('access_token')
    if not token:
        raise WorkspaceError('Facebook 장기 인증을 확인하지 못했습니다.')
    debug = get('/debug_token', {'input_token':token}, cfg['app_id']+'|'+cfg['app_secret']).get('data') or {}
    if (not debug.get('is_valid') or str(debug.get('app_id')) != str(cfg['app_id'])
            or not SCOPES.issubset(set(debug.get('scopes') or []))):
        raise WorkspaceError('페이지 조회·게시 권한을 모두 허용한 뒤 다시 연결해 주세요.')
    # Page 토큰이 무기한이어도 사용자 인증/데이터 접근의 확인된 기한 안에서만 정상 취급한다.
    expiries = [int(debug.get(k) or 0) for k in ('expires_at', 'data_access_expires_at')]
    expiry = min((v for v in expiries if v > 0), default=0)
    if expiry <= now.timestamp():
        raise WorkspaceError('Facebook 인증 유효기간을 확인하지 못했습니다.')
    after = ''
    for _ in range(20):
        params = {'fields':'id,name,access_token,tasks', 'limit':100}
        if after:
            params['after'] = after
        pages = get('/me/accounts', params, token)
        for page in pages.get('data', []):
            if str(page.get('id')) != page_id:
                continue
            if (not page.get('access_token') or not page.get('name')
                    or not {'CREATE_CONTENT', 'MANAGE', 'PROFILE_PLUS_CREATE_CONTENT'}.intersection(page.get('tasks') or [])):
                raise WorkspaceError('선택한 페이지의 게시 권한을 확인하지 못했습니다.')
            profile = get('/me', {'fields':'id,name'}, page['access_token'])
            if str(profile.get('id')) != page_id:
                raise WorkspaceError('인증된 페이지가 선택한 페이지와 다릅니다.')
            return {'access_token':page['access_token'], 'user_id':page_id, 'page_name':str(profile.get('name') or page['name']),
                    'expires_at':datetime.fromtimestamp(expiry, timezone.utc).isoformat()}
        paging = pages.get('paging') or {}
        cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('next') or not cursor or cursor == after:
            break
        after = cursor  # 응답의 next URL을 따라가며 인증값을 다른 호스트에 보내지 않는다.
    raise WorkspaceError('선택한 페이지가 인증 목록에 없습니다. Facebook에서 해당 페이지 접근을 허용해 주세요.')
