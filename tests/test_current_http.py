"""기존 화면의 API와 OAuth 콜백이 관리자 인증 경계를 우회하지 못하게 한다."""
from http.client import HTTPConnection
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock
import test_mini_workspace as fixtures
from mini_workspace import safe_private


class CurrentHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.WorkspaceHTTPTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.server=fixture.server;self.home=fixture.home
        shutil.copytree(fixtures.ROOT/'template/web',self.home/'web',dirs_exist_ok=True)
        self.work=self.server.box.workspace();self.work.providers=fixtures.FakeProviders()
        from current_ui import CurrentUI
        self.work.current_ui=CurrentUI(self.work)
        safe_private(self.work.credentials/'oauth-apps.json',{'threads':{'app_id':'123456','app_secret':'only-test-fixture',
            'redirect_uri':'https://mini.example/api/oauth/callback/threads'}})

    def call(self,method,path,*,cookie=True,host=None,data=None,origin=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={}
        if cookie:headers['Cookie']=self.fixture.cookie
        if host:headers['Host']=host
        if method=='POST':headers.update({'Content-Type':'application/json','Origin':origin or self.fixture.origin})
        c.request(method,path,json.dumps(data) if data is not None else None,headers)
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result

    def test_기존화면의_API도_세션과_동일출처를_확인한다(self):
        for path in ('/api/sns-operations?week=2026-10-05','/api/current/vault','/api/sns-readiness','/api/research-capabilities'):
            self.assertEqual(self.call('GET',path,cookie=False)[0],401)
            self.assertEqual(self.call('GET',path)[0],200)
        self.assertEqual(self.call('POST','/api/sns-internal/account',data={},origin='https://evil.example')[0],403)

    def test_임베드화면만_동일출처프레임을_허용하고_정적파일만_열어준다(self):
        for path in ('/current/index.html?tab=sns','/current/pack-library/research.html','/current/assets/sns/threads.svg'):
            status,headers,_=self.call('GET',path)
            self.assertEqual(status,200,path)
            self.assertEqual(headers['X-Frame-Options'],'SAMEORIGIN' if 'pack-library' in path else 'DENY')
        self.assertEqual(self.call('GET','/current/../../.credentials/oauth-apps.json')[0],404)
        self.assertEqual(self.call('GET','/api/session?token=anything')[0],404)

    def test_외부콜백호스트는_콜백이외_화면이나_API를_열지못한다(self):
        self.work.current_ui.oauth.finish=Mock(return_value={'ok':True})
        path='/api/oauth/callback/threads?state=fixture&code=fixture'
        self.assertEqual(self.call('GET',path,cookie=False,host='mini.example')[0],200)
        self.work.current_ui.oauth.finish.assert_called_once()
        for other in ('/api/current/vault','/api/health','/current/index.html'):
            self.assertEqual(self.call('GET',other,host='mini.example')[0],403)
        self.assertEqual(self.call('GET',path,host='evil.example')[0],403)

    def test_중복파라미터와_HEAD는_인증교환하지않는다(self):
        self.work.current_ui.oauth.finish=Mock()
        self.assertEqual(self.call('GET','/api/oauth/callback/threads?state=a&state=b&code=c')[0],400)
        self.assertEqual(self.call('HEAD','/api/oauth/callback/threads?state=a&code=c')[0],405)
        self.work.current_ui.oauth.finish.assert_not_called()
