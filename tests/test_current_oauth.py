"""SNS 로그인 콜백은 선택한 계정과 일회 상태를 검증하고 비밀을 장부에 남기지 않는다."""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
from current_oauth import OAuth
from current_ui import CurrentUI
from mini_workspace import Workspace, WorkspaceError, safe_private
from test_mini_workspace import FakeProviders, admin


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.provider = FakeProviders()
        self.provider.verify = lambda platform, token, expected='': {'user_id': '123456', 'username': 'sample'}
        self.work = Workspace(self.home, admin.Files(self.home), providers=self.provider)
        self.addCleanup(self.work.close)
        self.ui = CurrentUI(self.work)
        self.clock = [1800000000]
        self.secret, self.token, self.code = [secrets.token_urlsafe(32) for _ in range(3)]
        safe_private(self.work.credentials / 'oauth-apps.json', {'threads': {
            'app_id': '123456', 'app_secret': self.secret,
            'redirect_uri': 'https://mini.example/api/oauth/callback/threads'}})
        self.calls = []
        def send(method, url, fields=None, bearer=''):
            self.calls.append((method, url, fields, bearer))
            return {'access_token': self.token, 'expires_in': 5184000}
        self.oauth = OAuth(self.work, send=send, clock=lambda: self.clock[0])

    def begin(self):
        result = self.oauth.start({'platform': 'threads', 'account': 'sample'})
        self.assertNotIn(self.secret, result['authorize_url'])
        return parse_qs(urlsplit(result['authorize_url']).query)['state'][0]

    def test_페이스북_페이지실명으로_연결해도_기존사업부와담당자를_보존한다(self):
        from unittest.mock import patch
        from datetime import datetime, timezone
        (self.work.credentials/'oauth-apps.json').unlink()
        safe_private(self.work.credentials/'oauth-apps.json',{'facebook':{'app_id':'123456','app_secret':self.secret,
            'redirect_uri':'https://mini.example/api/oauth/callback/facebook'}})
        self.ui.save_account({'platform':'facebook','account':'sample-page','brands':['사업부'],'owner':'담당자'})
        result=self.oauth.start({'platform':'facebook','account':'sample-page','page_id':'123456'})
        state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        self.provider.verify=lambda platform,token,expected='':{'user_id':'123456','username':'실제 페이지 이름'}
        with patch('current_oauth.facebook_exchange',return_value={'access_token':self.token,'expires_at':datetime.fromtimestamp(self.clock[0]+3600,timezone.utc).isoformat()}):
            self.oauth.finish('facebook',{'state':state,'code':self.code})
        metadata=self.ui.registry()['facebook:실제 페이지 이름']
        self.assertEqual(metadata['owner'],'담당자')
        self.assertEqual(metadata['brands'],['사업부'])
        self.assertEqual(metadata['account'],'실제 페이지 이름')
        self.assertNotIn('facebook:sample-page',self.ui.registry())

    def test_인증결과는_선택한계정으로_한번만_연결하고_토큰은_금고에만_둔다(self):
        self.ui.save_account({'platform':'threads','account':'sample','brands':['사업부'],'owner':'담당자'})
        state = self.begin()
        self.oauth.finish('threads', {'state': state, 'code': self.code})
        self.assertEqual(len(self.work.accounts()['accounts']), 1)
        self.assertEqual(self.ui.registry()['threads:sample']['owner'], '담당자')
        self.assertIn('expires_at', self.ui.registry()['threads:sample'])
        with self.assertRaises(WorkspaceError):
            self.oauth.finish('threads', {'state': state, 'code': self.code})
        self.assertEqual(len(self.calls), 2)
        dump = '\n'.join(self.work.db.iterdump())
        for private in (state, self.secret, self.code, self.token):
            self.assertNotIn(private, dump)
            self.assertNotIn(private, json.dumps(self.oauth.connections()))
        credential = next(p for p in self.work.credentials.glob('*.json') if p.name != 'oauth-apps.json')
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(credential.read_text())['token'], self.token)

    def test_만료된요청과_다른채널과_위조상태는_인증교환을_하지않는다(self):
        state = self.begin()
        for platform, value in [('instagram', state), ('threads', secrets.token_urlsafe(32))]:
            with self.assertRaises(WorkspaceError): self.oauth.finish(platform, {'state':value,'code':self.code})
        self.clock[0] += 601
        with self.assertRaises(WorkspaceError): self.oauth.finish('threads', {'state':state,'code':self.code})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.work.accounts()['accounts'], [])

    def test_다른계정로그인은_보관하지않고_에러에_비밀을_반환하지않는다(self):
        state = self.begin()
        self.provider.verify = lambda *args: {'user_id':'789','username':'another'}
        with self.assertRaises(WorkspaceError) as error:
            self.oauth.finish('threads', {'state':state,'code':self.code})
        self.assertNotIn(self.code, str(error.exception))
        self.assertEqual(self.work.accounts()['accounts'], [])
        self.assertEqual(len(list(self.work.credentials.glob('*.json'))), 1)
        self.assertEqual(self.oauth.connections()[0]['status'], 'failed')

    def test_새요청이_이전상태를_무효화하고_콜백호스트는_정확히_일치한다(self):
        first = self.begin(); second = self.begin()
        with self.assertRaises(WorkspaceError): self.oauth.finish('threads', {'state':first,'code':self.code})
        self.assertTrue(self.oauth.callback_host('mini.example', '/api/oauth/callback/threads'))
        for host, path in [('evil.example','/api/oauth/callback/threads'),('mini.example','/api/oauth/callback/instagram'),('mini.example:80','/api/oauth/callback/threads')]:
            self.assertFalse(self.oauth.callback_host(host, path))
        self.oauth.finish('threads', {'state':second,'code':self.code})

    def test_인증교환중_재시작은_재사용하지않고_확인필요로_표시한다(self):
        state = self.begin()
        with self.work.transaction(): self.work.db.execute("UPDATE oauth_requests SET status='exchanging'")
        OAuth(self.work, clock=lambda:self.clock[0])
        self.assertEqual(self.oauth.connections()[0]['status'], 'failed')
        with self.assertRaises(WorkspaceError): self.oauth.finish('threads', {'state':state,'code':self.code})


if __name__ == '__main__': unittest.main()
