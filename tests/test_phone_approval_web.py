import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_web_admin import BoxFixture, admin
import approval_store as store
from approval_actions import load_all


class ApprovalWebTests(BoxFixture):
    def setUp(self):
        super().setUp()
        load_all()
        self.server = admin.Server(self.box, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.cookie = self.box.cookie_name + '=' + self.box.login(self.token)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)
    def close_server(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()
    def call(self, method, path, data=None, cookie=True, origin=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {}
        if cookie: headers['Cookie'] = self.cookie
        if method == 'POST':
            headers['Content-Type'] = 'application/json'
            if origin: headers['Origin'] = self.origin
        connection.request(method, path, None if data is None else json.dumps(data), headers)
        response=connection.getresponse(); body=response.read(); status=response.status; connection.close()
        return status, json.loads(body)
    def test_local_approval_and_unlicensed_cancel(self):
        self.write('vault/reports/pending/a.md','text')
        status,created=self.call('POST','/api/approvals/create',{'name':'a.md'})
        self.assertEqual(status,200); req=created['id']
        self.assertEqual(self.call('GET','/api/approvals',cookie=False)[0],401)
        self.assertEqual(self.call('POST','/api/approvals/approve',{'id':req},origin=False)[0],403)
        with patch('license.evaluate',return_value=(False,'REVOKED')):
            self.assertEqual(self.call('GET','/api/approvals')[0],200)
            self.assertEqual(self.call('POST','/api/approvals/approve',{'id':req})[0],403)
            self.assertEqual(self.call('POST','/api/approvals/reject',{'id':req})[0],200)
        self.assertEqual(store.get(req,self.home)['state'],'rejected')
        self.assertTrue((self.home/'vault/reports/pending/a.md').exists())
    def test_customer_context_only_in_local_card(self):
        calls=[]
        def verify(req): pass
        def execute(req): return store.ActionResult()
        def context(req): calls.append(req.id); return '고객 문의 원문'
        name='test_web_local_context'; store._ACTIONS.pop(name,None); store.register_action(name,verify,execute,local_context=context)
        req=store.request_approval(name,{'channel':'naver_commerce','account':'shop','object_id':'1'},'title','reply',home=self.home)
        status,data=self.call('GET','/api/approvals')
        self.assertEqual(status,200)
        self.assertEqual(data['requests'][0]['local_context'],'고객 문의 원문')
        self.assertEqual(calls,[req])
    def test_redacted_body_cannot_be_approved_or_sent(self):
        self.write('vault/reports/pending/a.md','token 123456:'+('x'*30))
        status,created=self.call('POST','/api/approvals/create',{'name':'a.md'})
        self.assertEqual(status,200); req=created['id']
        status,rows=self.call('GET','/api/approvals')
        self.assertTrue(rows['requests'][0]['review_blocked'])
        self.assertNotIn('x'*30,json.dumps(rows))
        self.assertEqual(self.call('POST','/api/approvals/approve',{'id':req})[0],400)
        self.assertEqual(self.call('POST','/api/approvals/send',{'id':req,'consent':True})[0],400)
        self.assertEqual(store.get(req,self.home)['state'],'pending')
    def test_approved_but_unexecuted_can_be_cancelled(self):
        req=store.request_approval('local_note',{'channel':'local_note','account':'local','object_id':'a.md'},'title','body',home=self.home)
        self.assertTrue(store.decide(req,'approved','local',home=self.home))
        with patch('license.evaluate',return_value=(False,'REVOKED')):
            self.assertEqual(self.call('POST','/api/approvals/reject',{'id':req})[0],200)
        self.assertEqual(store.get(req,self.home)['state'],'rejected')

if __name__ == '__main__': unittest.main()
