# coding: utf-8
"""Dedicated usage API: owner/session/origin boundaries and offline privacy controls."""
import base64
import gzip
from http.client import HTTPConnection
import json
from pathlib import Path
import re
import threading
from unittest.mock import patch
from test_web_admin import BoxFixture, admin
import usage_timeline

ROOT = Path(__file__).resolve().parents[1]


class UsageWebTests(BoxFixture):
    def setUp(self):
        super().setUp()
        self.server = admin.Server(self.box, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start(); self.addCleanup(self.stop)
        for relative in ('current/index.html','current/base.css','current/shell.js','fonts.css'):
            self.write('web/'+relative,(ROOT/'template/web'/relative).read_text())
        for name in ('usage-history.html','usage-history.js','usage-history.css'):
            self.write('web/'+name,(ROOT/'template/web'/name).read_text())

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)

    def request(self, method, path, payload=None, *, cookie=None, origin=None):
        conn = HTTPConnection('127.0.0.1', self.server.server_port, timeout=6)
        headers={}
        if cookie: headers['Cookie']=cookie
        if method=='POST': headers['Origin']=origin or 'http://127.0.0.1:'+str(self.server.server_port)
        raw=None
        if payload is not None:
            raw=json.dumps(payload).encode();headers['Content-Type']='application/json'
        try:
            conn.request(method,path,raw,headers)
            response=conn.getresponse(); data=response.read(); meta=dict(response.getheaders())
            if response.getheader('Content-Type','').startswith('application/json'): data=json.loads(data)
            return response.status,meta,data
        finally: conn.close()

    def login(self):
        status,headers,data=self.request('POST','/api/session',{'token':self.token})
        self.assertEqual(status,200,data)
        return headers['Set-Cookie'].split(';',1)[0]

    def test_session_owner_origin_unknown_fields(self):
        self.assertEqual(self.request('GET','/api/usage-history/summary')[0],401)
        cookie=self.login()
        self.assertEqual(self.request('GET','/api/usage-history/summary',cookie=cookie)[2]['state'],'off')
        self.assertEqual(self.request('POST','/api/usage-history/off',{},cookie=cookie,origin='https://foreign.invalid')[0],403)
        self.assertEqual(self.request('POST','/api/usage-history/off',{'prompt':'PRIVATE'},cookie=cookie)[0],400)
        with patch('access_policy.require_owner', side_effect=__import__('access_policy').AccessDenied()):
            self.assertEqual(self.request('GET','/api/usage-history/summary',cookie=cookie)[0],403)

    def test_expired_offline_page_and_privacy_controls_skip_license_network(self):
        with patch('license.evaluate',side_effect=AssertionError('license network forbidden')):
            cookie=self.login()
            for path in ('/usage-history','/usage-history.js','/usage-history.css','/api/usage-history/summary','/current/base.css','/current/shell.js','/fonts.css'):
                status,headers,body=self.request('GET',path,cookie=cookie)
                self.assertEqual(status,200,body);self.assertEqual(headers['Cache-Control'],'no-store')
            for action in ('off','delete-local','unlink','export'):
                status,_,body=self.request('POST','/api/usage-history/'+action,{},cookie=cookie)
                self.assertEqual(status,200,body)
        with patch('license.evaluate',return_value=(False,'EXPIRED')):
            self.assertEqual(self.request('POST','/api/usage-history/on',{},cookie=cookie)[0],403)
            self.assertEqual(self.request('GET','/api/dashboard',cookie=cookie)[0],403)

    def test_optin_and_export_exactly_matches_preview_without_paths(self):
        workspace=self.user_home/'실습';workspace.mkdir()
        cookie=self.login()
        body=dict(workspace=str(workspace),timezone='Asia/Seoul',backfill_from=None,consent=True)
        status,_,result=self.request('POST','/api/usage-history/on',body,cookie=cookie)
        self.assertEqual(status,200,result)
        self.assertTrue(result['enabled'])
        status,_,payload=self.request('POST','/api/usage-history/export',{},cookie=cookie)
        self.assertEqual(status,200,payload);self.assertEqual(payload,result['preview'])
        self.assertNotIn(str(workspace),json.dumps(result))
        self.assertEqual(self.request('POST','/api/usage-history/link',dict(base_url='http://external.invalid',code='ABC',consent=True,preview_revision=-1),cookie=cookie)[0],400)

    def test_usage_page_reuses_admin_shell_components_and_theme_tokens(self):
        cookie=self.login()
        status,_,body=self.request('GET','/usage-history',cookie=cookie)
        self.assertEqual(status,200)
        page=body.decode()
        current=(ROOT/'template/web/current/index.html').read_text()
        normalized=re.sub(r'(href|src)="/current/([^"]+)"',r'\1="\2"',page)
        self.assertEqual(normalized.replace('내 AI 사용 기록 · 일손','일손 · 업무 공간'),current)
        for part in ('class="sidebar"','id="main"','src="/current/shell.js"','href="/current/base.css"'):
            self.assertIn(part,page)
        script=(ROOT/'template/web/usage-history.js').read_text()
        css=(ROOT/'template/web/usage-history.css').read_text()
        for source in (page,script,css):
            self.assertNotRegex(source,r'#[0-9a-fA-F]{3,8}\b')
        self.assertNotIn('dataset.theme',script)
        self.assertNotIn('prefers-color-scheme',css)
        for component in ('btn btn-primary','btn btn-danger','seg uh-tabs','card metric-card','callout','data-table'):
            self.assertIn(component,script)
        for level in range(5):
            self.assertIn('var(--activity-'+str(level)+')',css)
        self.assertIn('border:1px dashed',css)
        self.assertIn('날짜별 숫자 표',script)
        shell=(ROOT/'template/web/current/shell.js').read_text()
        self.assertIn("id:'usage-history'",shell)
        self.assertIn("if(!main.querySelector('.usage-history'))IlsonUsage.mount(main)",shell)

    def test_course_payload_and_pricing_manifest_match_runtime(self):
        for name in ('usage_timeline.py','usage_sync.py'):
            self.assertEqual((ROOT/'template/lib'/name).read_bytes(),(ROOT/'course/lib'/name).read_bytes())
        manifest=json.loads((ROOT/'docs/usage-timeline/PRICING-MANIFEST.json').read_text())
        for name,price in usage_timeline.PRICES.items():
            self.assertEqual(manifest['models'][name]['input'],price[0])
            self.assertEqual(manifest['models'][name]['cache_creation_1h'],price[0]*2)
        for name in ('install-intel-mac.sh','install-windows.ps1'):
            source=(ROOT/'course'/name).read_text()
            encoded=re.search(r"(?:COURSE_PAYLOAD|\$CoursePayload)='([^']+)'",source).group(1)
            files=json.loads(gzip.decompress(base64.b64decode(encoded)))
            self.assertEqual(files['usage_timeline.py'],(ROOT/'course/lib/usage_timeline.py').read_text())
            self.assertIn('web-admin-server.py',files)
            self.assertFalse(any('instructor' in p for p in files))
