import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('skill_admin', ROOT/'server/license/skill_admin.py')
admin=importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)

class AdminTest(unittest.TestCase):
    def setUp(self):
        self.server=admin.ReviewServer('synthetic-test-secret')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, headers=None, body=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request(method,path,body,headers or {})
        response=connection.getresponse()
        result=response.status,response.read(),dict(response.getheaders())
        connection.close()
        return result

    def test_local_screen_and_authorized_actions(self):
        code,page,headers=self.request('GET','/')
        self.assertEqual(code,200)
        self.assertNotIn(b'synthetic-test-secret',page)
        self.assertIn(b'.textContent=',page)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        with mock.patch.object(admin,'remote',return_value={'status':'ok','items':[]}) as remote:
            valid={'Origin':self.server.origin,'X-Ilson-Session':self.server.token,'Content-Type':'application/json'}
            self.assertEqual(self.request('POST','/api/list',valid,'{}')[0],200)
            remote.assert_called_once_with('list','synthetic-test-secret',None,0)
            self.assertEqual(self.request('POST','/api/list',{'Origin':'https://attacker.invalid','X-Ilson-Session':self.server.token},'{}')[0],403)
            self.assertEqual(self.request('POST','/api/list',{'Origin':self.server.origin,'X-Ilson-Session':'bad'},'{}')[0],403)
            self.assertEqual(self.request('GET','/',{'Host':'attacker.invalid'})[0],404)

if __name__=='__main__': unittest.main()
