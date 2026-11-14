"""Exercise the real request guard and GET handler in memory, without networking."""
from contextlib import nullcontext, redirect_stderr
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from test_web_admin import admin
from opensource_catalog import Catalog
from opensource_fixtures import NOW, at, catalog, repo, raw

ROOT = Path(__file__).resolve().parents[1]
SESSION = 'FAKE_SESSION_ONLY_' + 'a'*32
TOKEN = 'FAKE_BOX_' + 'TOKEN_ONLY_' + 'b'*32


class OpenSourceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW
        self.document=raw(catalog(repo()))
        self.reader=Mock(side_effect=lambda path,limit:(self.document,None))
        self.redact=lambda value: json.loads(json.dumps(value).replace(TOKEN,'MASKED').replace(SESSION,'MASKED'))
        self.box=SimpleNamespace(home=ROOT/'.scratch',cookie_name='synthetic_cookie',
            clock=lambda:self.now,session_lock=threading.Lock(),
            sessions={hashlib.sha256(SESSION.encode()).hexdigest():NOW+3600},redact=self.redact)
        self.box.authenticated=lambda session:admin.Box.authenticated(self.box,session)
        self.box.opensource_catalog=Catalog(self.reader,clock=lambda:self.now,redact=self.redact)
        self.server=SimpleNamespace(box=self.box,hosts={'local.test'},origins={'http://local.test'})

    def request(self,path='/api/opensource/catalog',*,cookie=SESSION,host='local.test',origin=None,licensed=True,role=None,method='GET'):
        handler=admin.Handler.__new__(admin.Handler)
        handler.server=self.server;handler.path=path;handler.command=method
        handler.request_version='HTTP/1.1';handler.requestline=method+' '+path+' HTTP/1.1'
        handler.headers=Message();handler.headers['Host']=host
        if cookie:handler.headers['Cookie']='synthetic_cookie='+cookie
        if origin:handler.headers['Origin']=origin
        handler.wfile=io.BytesIO()
        stderr=io.StringIO()
        policy=None if role is None else SimpleNamespace(actor=SimpleNamespace(role=role))
        with patch('license.evaluate',return_value=(licensed,'SYNTHETIC')), \
             patch('runtime_gate.running',return_value=nullcontext()), \
             patch('access_policy.load',return_value=policy),redirect_stderr(stderr):
            handler.do_POST() if method=='POST' else handler.do_GET()
        response=handler.wfile.getvalue();header,body=response.split(b'\r\n\r\n',1)
        status=int(header.split()[1])
        return status,header.decode(),json.loads(body) if body else None,stderr.getvalue()

    def test_real_session_license_host_origin_and_employee_boundaries_for_both_apis(self):
        for path in ['/api/opensource/catalog','/api/opensource/repos/'+'a'*32]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0],200)
                for options,code in [({'cookie':None},401),({'cookie':'invalid'},401),
                    ({'origin':'https://evil.example'},403),({'host':'evil.example'},403),
                    ({'licensed':False},403),({'role':'staff'},403)]:
                    before=self.reader.call_count
                    response=self.request(path,**options)
                    self.assertEqual(response[0],code,response)
                    self.assertNotIn('ilson open',str(response))
                    self.assertNotIn('ilson license activate',str(response))
                    self.assertEqual(self.reader.call_count,before,'refused requests never read catalog')
                self.assertEqual(self.request(path,role='owner')[0],200)
                self.now+=3601
                self.assertEqual(self.request(path)[0],401)
                self.now=NOW;self.box.sessions[hashlib.sha256(SESSION.encode()).hexdigest()]=NOW+3600

    def test_no_raw_secret_or_source_error_in_response_headers_body_or_logs(self):
        for secret in [TOKEN,SESSION,'FAKE_GITBAP_KEY_ONLY']:
            row=repo();row['secret']=secret
            self.document=raw(catalog(row,version=self.box.opensource_catalog.good['catalog_version']+1 if self.box.opensource_catalog.good else 1))
            response=self.request()
            self.assertEqual(response[2]['repos'],[])
            self.assertNotIn(secret,str(response))
        row=repo();row['mild_md']='가짜 값 '+TOKEN
        self.document=raw(catalog(row,version=10))
        self.assertEqual(self.request()[2]['repos'],[])
        self.reader.side_effect=OSError(TOKEN)
        self.assertNotIn(TOKEN,str(self.request()))
        self.assertEqual(self.request()[3],'')

    def test_hidden_items_have_no_names_bodies_previews_or_links_at_either_endpoint(self):
        row=repo();row['catalog_approved']=False;self.document=raw(catalog(row))
        self.assertEqual(self.request()[2]['state'],'under_review')
        response=self.request('/api/opensource/repos/'+row['id'])
        self.assertEqual(response[0],404);self.assertIsNone(response[2]['repo'])
        for value in [row['id'],row['full_name'],row['gitbap_url'],row['preview']['result']]:
            self.assertNotIn(value,str(response))

    def test_expiry_revocation_load_error_and_valid_empty_use_status_only(self):
        self.document=raw(catalog())
        self.assertEqual(self.request()[2]['state'],'empty')
        self.document=raw(catalog(repo(),version=2,revocation=1,revoked=['a'*32]))
        self.assertEqual(self.request('/api/opensource/repos/'+'a'*32)[0],404)
        self.now+=72*3600
        self.box.sessions[hashlib.sha256(SESSION.encode()).hexdigest()]=self.now+3600
        result=self.request('/api/opensource/repos/'+'a'*32)
        self.assertEqual(result[2]['state'],'expired');self.assertNotIn('https:',str(result))
        self.box.opensource_catalog=Catalog(Mock(side_effect=OSError('FAKE_SECRET')),clock=lambda:self.now)
        result=self.request();self.assertEqual(result[2]['state'],'load_failed');self.assertNotIn('FAKE_SECRET',str(result))

    def test_opaque_id_only_no_query_paths_or_new_post_actions(self):
        for path in ['/api/opensource/repos/owner/fake','/api/opensource/repos/..%2Ffake',
                     '/api/opensource/repos/'+'a'*32+'?token=FAKE', '/api/opensource/catalog?url=https://evil.example',
                     '/api/opensource/repos/'+'a'*31]:
            self.assertEqual(self.request(path)[0],404)
        self.assertEqual(self.request(method='POST',origin='http://local.test')[0],404)

    def test_api_is_read_only_and_does_not_create_workspace_or_call_tools(self):
        self.box.workspace=Mock(side_effect=AssertionError('AI or documents'))
        with patch('subprocess.Popen',side_effect=AssertionError('shell')), \
             patch('socket.socket',side_effect=AssertionError('network')), \
             patch('pathlib.Path.read_text',side_effect=AssertionError('user read')), \
             patch('pathlib.Path.write_text',side_effect=AssertionError('user write')):
            self.assertEqual(self.request()[0],200)
            self.assertEqual(self.request('/api/opensource/repos/'+'a'*32)[0],200)
        self.box.workspace.assert_not_called()
        self.assertTrue(all(c.args==('web/current/opensource-catalog.json',1024*1024) for c in self.reader.call_args_list))

    def test_static_assets_registered_without_raw_catalog_access(self):
        page=(ROOT/'template/web/current/index.html').read_text()
        for name,kind in [('opensource.js','application/javascript'),('opensource.css','text/css')]:
            relative,mime=admin.STATIC['/current/'+name]
            self.assertEqual(relative,'web/current/'+name)
            self.assertTrue(mime.startswith(kind));self.assertTrue((ROOT/'template'/relative).is_file())
            self.assertIn(name,page)
        self.assertLess(page.index('src="opensource.js"'),page.index('src="shell.js"'))
        self.assertFalse(any('opensource-catalog.json' in k or 'opensource-catalog.json' in v[0] for k,v in admin.STATIC.items()))
        self.assertEqual(self.request('/current/opensource-catalog.json')[0],404)
        import importlib.util
        spec=importlib.util.spec_from_file_location('opensource_update_allowlist',ROOT/'tools/update.py')
        updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
        self.assertTrue(updater.allowed('cli','template/web/current/opensource-catalog.json'))
        self.assertTrue(updater.allowed('box','web/current/opensource-catalog.json'))
        installer=(ROOT/'ilson').read_text()
        self.assertIn('cp -R "$TEMPLATE/web/." "$ILSON_HOME/web/"',installer)
        response=self.request()
        self.assertIn("connect-src 'self'",response[1]);self.assertIn('Cache-Control: no-store',response[1])


if __name__=='__main__':unittest.main()
