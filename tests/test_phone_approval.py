import concurrent.futures
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
import approval_store as store
import approval_dispatch as dispatch
import approval_telegram as telegram
from approval_actions import load_all
load_all()


class FakeTelegram(BaseHTTPRequestHandler):
    calls = []
    updates = []
    conflict = False
    def log_message(self, *args):
        pass
    def do_POST(self):
        method = self.path.rsplit('/', 1)[-1]
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append((method, data))
        if method == 'getUpdates' and self.conflict:
            self.send_response(409); self.send_header('Content-Length','0'); self.end_headers(); return
        result = {'message_id': 123} if method == 'sendMessage' else (list(self.updates) if method == 'getUpdates' else True)
        raw = json.dumps({'ok': True, 'result': result}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeTelegram)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.pending = self.home / 'vault/reports/pending'
        self.pending.mkdir(parents=True)
        self.draft = self.pending / 'draft.md'
        self.draft.write_text('synthetic body', encoding='utf-8')
        telegram.save_config(self.home, 'synthetic-token', 222, 222)
        FakeTelegram.calls = []
        FakeTelegram.updates = []
        FakeTelegram.conflict = False
    def tearDown(self):
        self.tmp.cleanup()
    def transport(self, token, method, data):
        return telegram.api(token, method, data, endpoint='http://127.0.0.1:' + str(self.server.server_port))
    def make(self, ttl=24):
        return store.request_approval('local_note', {'channel':'local_note','account':'local','object_id':'draft.md'}, 'draft', 'synthetic body', ttl_hours=ttl, home=self.home)
    def card(self, req):
        telegram.send_card(self.home, req, consent=True, transport=self.transport, license_check=lambda: True)
        sent = [data for method,data in FakeTelegram.calls if method == 'sendMessage'][-1]
        return sent['reply_markup']['inline_keyboard'][0]
    def update(self, token, *, chat=222, user=222, kind='private', message=123, forward=None):
        msg = {'chat': {'id':chat,'type':kind}, 'message_id':message}
        if forward: msg['forward_origin'] = {'type':'user'}
        return {'update_id':1,'callback_query': {'id':'callback', 'data':token, 'from':{'id':user,'is_bot':False}, 'message':msg}}
    def click(self, update, license_check=lambda:True):
        telegram.process_update(self.home, update, transport=self.transport, license_check=license_check)
    def test_end_to_end_and_reclick(self):
        req = self.make(); token = self.card(req)[0]['callback_data']
        self.click(self.update(token)); self.click(self.update(token))
        self.assertEqual(store.get(req, self.home)['state'], 'success')
        self.assertFalse(self.draft.exists())
        self.assertEqual((self.home/'vault/reports/approved/draft.md').read_text(), 'synthetic body')
        self.assertEqual(len(list((self.home/'vault/journal').glob('*.md'))),1)
        self.assertEqual(sum(method == 'answerCallbackQuery' for method,_ in FakeTelegram.calls), 2)
    def test_parallel_callbacks_one_transition(self):
        req=self.make(); token=self.card(req)[0]['callback_data']; update=self.update(token)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.click(update), range(8)))
        self.assertEqual(store.get(req,self.home)['state'], 'success')
        with store.connect(self.home) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE event='approved'").fetchone()[0],1)
    def test_forged_group_forward_sender_and_message(self):
        req=self.make(); token=self.card(req)[0]['callback_data']
        for update in (self.update('forged'),self.update(token,chat=333),self.update(token,user=333),self.update(token,kind='group'),self.update(token,message=124),self.update(token,forward=True)):
            self.click(update)
        self.assertEqual(store.get(req,self.home)['state'],'pending')
        self.assertTrue(self.draft.exists())
    def test_stale_expiry_and_reconnect(self):
        req=self.make(); token=self.card(req)[0]['callback_data']
        self.draft.write_text('modified',encoding='utf-8'); self.click(self.update(token))
        self.assertEqual(store.get(req,self.home)['state'],'changed')
        self.draft.write_text('synthetic body',encoding='utf-8')
        req=self.make(); token=self.card(req)[0]['callback_data']
        with store.connect(self.home) as db: db.execute('UPDATE requests SET expires=? WHERE id=?',(time.time()-1,req))
        self.click(self.update(token))
        self.assertEqual(store.get(req,self.home)['state'],'expired')
        req=self.make(); token=self.card(req)[0]['callback_data']; telegram.save_config(self.home,'new-synthetic',222,222); self.click(self.update(token))
        self.assertEqual(store.get(req,self.home)['state'],'pending')
    def test_poll_offset_and_lock(self):
        req=self.make(); token=self.card(req)[2]['callback_data']; FakeTelegram.updates=[self.update(token)]
        telegram.poll_once(self.home,transport=self.transport,license_check=lambda:True)
        self.assertEqual(store.get(req,self.home)['state'],'rejected')
        self.assertEqual(store.setting('offset:'+telegram.read_config(self.home)['generation'],home=self.home),'2')
        lock=telegram.receiver_lock(self.home)
        try:
            with self.assertRaises(telegram.TelegramError): telegram.receiver_lock(self.home)
        finally: os.close(lock)
    def test_unknown_is_never_retried_and_recovery(self):
        calls=[]
        def verify(req): self.assertIsInstance(req,store.ApprovalRequest)
        def execute(req): calls.append(req.id); raise store.ActionUnknown('synthetic')
        name='test_unknown'; store._ACTIONS.pop(name,None); store.register_action(name,verify,execute)
        req=store.request_approval(name,{'channel':'test','account':'a','object_id':'1'},'title','body',home=self.home)
        self.assertTrue(store.decide(req,'approved','local',home=self.home))
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'result_unknown')
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'not_ready')
        self.assertEqual(calls,[req])
        req=self.make()
        with store.connect(self.home) as db: db.execute("UPDATE requests SET state='executing' WHERE id=?",(req,))
        dispatch.recover(self.home)
        self.assertEqual(store.get(req,self.home)['state'],'result_unknown')
    def test_stopped_license_blocks_send_and_execution_but_allows_cancel(self):
        req=self.make()
        with self.assertRaises(telegram.TelegramError): telegram.send_card(self.home,req,consent=True,transport=self.transport,license_check=lambda:False)
        self.assertTrue(store.decide(req,'approved','local',home=self.home))
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:False),'license_required')
        self.assertTrue(self.draft.exists())
        req=self.make(); self.assertTrue(store.decide(req,'rejected','local',home=self.home))
    def test_read_only_reports_and_no_secret_in_events(self):
        empty=self.home/'empty'
        now=datetime.now(timezone.utc); start=now-timedelta(minutes=1); end=now+timedelta(minutes=1)
        self.assertEqual(store.weekly_counts(start,end,home=empty),{})
        self.assertEqual(store.list_titles(['pending'],start,end,home=empty),[])
        req=self.make()
        counts=store.weekly_counts(start,end,home=self.home)
        self.assertEqual(counts['pending'],1)
        rows=store.list_titles(['pending'],start,end,home=self.home)
        self.assertEqual(set(rows[0]),{'id','action_type','title','state','updated_at'})
        with store.connect(self.home) as db: events=str([tuple(row) for row in db.execute('SELECT * FROM events')])
        self.assertNotIn('synthetic-token',events); self.assertNotIn('synthetic body',events)
    def test_local_customer_context_never_enters_telegram_card(self):
        calls=[]
        def verify(req): pass
        def execute(req): return store.ActionResult()
        def context(req): calls.append(req.id); return 'PRIVATE_CUSTOMER_QUESTION'
        name='test_local_context'; store._ACTIONS.pop(name,None); store.register_action(name,verify,execute,local_context=context)
        req=store.request_approval(name,{'channel':'naver_commerce','account':'shop','object_id':'1'},'PRIVATE_CUSTOMER_QUESTION','synthetic reply',home=self.home)
        self.card(req)
        sent=[data for method,data in FakeTelegram.calls if method=='sendMessage'][-1]
        self.assertNotIn('PRIVATE_CUSTOMER_QUESTION',json.dumps(sent,ensure_ascii=False))
        self.assertIn('synthetic reply',sent['text'])
        self.assertIn('문의 원문은 일손 화면에서 확인',sent['text'])
        self.assertEqual(calls,[])
    def test_poll_conflict_and_sensitive_content(self):
        FakeTelegram.conflict=True
        with self.assertRaises(telegram.TelegramError) as error:
            telegram.poll_once(self.home,transport=self.transport,license_check=lambda:True)
        self.assertNotIn('synthetic-token',str(error.exception))
        self.assertIsNone(store.setting('offset:'+telegram.read_config(self.home)['generation'],home=self.home))
        req=store.request_approval('local_note',{'channel':'local_note','account':'local','object_id':'draft.md'},'title','123456:'+('x'*30),home=self.home)
        with self.assertRaises(telegram.TelegramError):
            telegram.send_card(self.home,req,consent=True,transport=self.transport,license_check=lambda:True)
    def test_approved_action_interrupted_after_side_effect_is_unknown(self):
        req=self.make()
        self.assertTrue(store.decide(req,'approved','local',home=self.home))
        with patch.object(dispatch.os,'unlink',side_effect=OSError('synthetic')):
            self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'result_unknown')
        self.assertTrue((self.home/'vault/reports/approved/draft.md').exists())
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'not_ready')
    def test_sandbox_and_definite_failure(self):
        req=self.make()
        (self.home/'state').mkdir()
        (self.home/'state/sandbox').touch()
        with self.assertRaises(telegram.TelegramError):
            telegram.send_card(self.home,req,consent=True,transport=self.transport,license_check=lambda:True)
        calls=[]
        def verify(req): calls.append('verify')
        def execute(req): calls.append('execute'); raise store.ActionFailed('synthetic')
        name='test_definite_failure'; store._ACTIONS.pop(name,None); store.register_action(name,verify,execute)
        req=store.request_approval(name,{'channel':'test','account':'a','object_id':'1'},'title','body',home=self.home)
        store.decide(req,'approved','local',home=self.home)
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'failed')
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'not_ready')
        self.assertEqual(calls,['verify','execute'])
    def test_generic_verify_error_is_unknown(self):
        calls=[]
        def verify(req): raise ValueError('synthetic')
        def execute(req): calls.append('execute')
        name='test_verify_unknown'; store._ACTIONS.pop(name,None); store.register_action(name,verify,execute)
        req=store.request_approval(name,{'channel':'test','account':'a','object_id':'1'},'title','body',home=self.home)
        store.decide(req,'approved','local',home=self.home)
        self.assertEqual(dispatch.dispatch(req,self.home,license_check=lambda:True),'result_unknown')
        self.assertEqual(calls,[])
    def test_approval_is_immutable_and_only_registered_actions(self):
        with self.assertRaises(ValueError): store.request_approval('not_registered',{},'a','b',home=self.home)
        req=self.make(); obj=store.approval_request(store.get(req,self.home))
        with self.assertRaises(TypeError): obj.target['object_id']='another.md'
        with self.assertRaises(Exception): obj.body='other'

if __name__ == '__main__': unittest.main()
