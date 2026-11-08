import dataclasses
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
import replies_ingest as ingest
import replies_draft as draft
import replies_dispatch as dispatch
from replies_naver_qna import APIError, UnknownResult, NaverQna
import replies_service as service
import replies_runtime as runtime
import replies_scheduled as scheduled
from datetime import datetime, timezone
import threading
import test_web_admin as admin_fixture
import test_scheduled_jobs as job_fixture

START = '2026-11-01T00:00:00+09:00'
END = '2026-11-08T00:00:00+09:00'
def question(qid=7, answered=False):
    return {'questionId':qid, 'question':'사용 방법을 알려주세요', 'createDate':'2026-11-02T12:00:00+09:00', 'productId':1, 'productName':'제품', 'answered':answered, 'answer':None, 'answers':[]}

class FakeAPI:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [question()]
        self.puts = []
        self.error = None
        self.identity_value = 'a' * 64
    def identity(self): return self.identity_value
    def page(self, start, end, page):
        if self.error: raise self.error
        return {'contents':self.rows[(page-1)*100:page*100], 'totalElements':len(self.rows), 'totalPages':(len(self.rows)+99)//100}
    def answer(self, qid, body):
        self.puts.append((qid, body))
        if self.error: raise self.error

class Stale(Exception): pass
class Failed(Exception): pass
class Unknown(Exception): pass
@dataclasses.dataclass(frozen=True)
class Result:
    status: str
    external_ref: object
    detail: str
contract = SimpleNamespace(ApprovalStale=Stale, ActionFailed=Failed, ActionUnknown=Unknown, ActionResult=Result)

@dataclasses.dataclass(frozen=True)
class Request:
    id: str
    action_type: str
    target: dict
    title: str
    body: str
    body_sha256: str
    meta: dict
    version: int = 1
    state: str = 'pending'
    created_at: str = '2026-11-08T00:00:00Z'
    expires_at: str = '2026-11-09T00:00:00Z'

class FakeStore:
    def __init__(self): self.actions, self.requests, self.states, self.contexts = {}, {}, {}, {}
    def register_action(self, kind, verify, execute, local_context=None):
        self.actions[kind] = (verify, execute)
        self.contexts[kind] = local_context
    def request_approval(self, action_type, target, title, body, meta=None, ttl_hours=24):
        if action_type not in self.actions: raise ValueError()
        key = str(len(self.requests)+1)
        self.requests[key] = Request(key, action_type, target, title, body, hashlib.sha256(body.encode()).hexdigest(), meta)
        self.states[key] = 'pending'
        return key
    def approve_and_execute(self, key, approved=False):
        if not approved or self.states[key] != 'pending': raise ValueError('승인 필요')
        self.states[key] = 'executing'
        req = self.requests[key]
        try:
            if hashlib.sha256(req.body.encode()).hexdigest() != req.body_sha256: raise Stale()
            verify, execute = self.actions[req.action_type]
            verify(req)
            result = execute(req)
            self.states[key] = result.status
        except Stale: self.states[key] = 'changed'
        except Failed: self.states[key] = 'failed'
        except Exception: self.states[key] = 'result_unknown'
        return self.states[key]

class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.api = FakeAPI()
        ingest.save(self.home, 'naver_commerce', 'shop', ingest.collect(self.api, START, END), START, END)
        self.store = FakeStore()
        self.adapter = dispatch.Adapter(self.home, self.store, lambda account:self.api, contract)
        self.adapter.register()
    def make(self): return self.adapter.request('shop', 7, '안녕하세요. 감사합니다.')
    def test_approval_required_and_no_duplicate_execution(self):
        key = self.make()
        with self.assertRaises(ValueError): self.store.approve_and_execute(key)
        self.assertEqual(self.api.puts, [])
        self.assertEqual(self.store.approve_and_execute(key, True), 'success')
        with self.assertRaises(ValueError): self.store.approve_and_execute(key, True)
        self.assertEqual(len(self.api.puts), 1)
    def test_already_answered_or_changed(self):
        for change in ('answered', 'question'):
            key = self.make()
            self.api.rows = [question()]
            if change == 'answered': self.api.rows[0]['answered'] = True
            else: self.api.rows[0]['question'] = '다른 문의'
            self.assertEqual(self.store.approve_and_execute(key, True), 'changed')
        self.assertEqual(self.api.puts, [])
    def test_forged_target_and_changed_body(self):
        key = self.make()
        self.store.requests[key] = dataclasses.replace(self.store.requests[key], body='위조')
        self.assertEqual(self.store.approve_and_execute(key, True), 'changed')
        key = self.make()
        self.store.requests[key] = dataclasses.replace(self.store.requests[key], target={'channel':'naver_commerce','account':'shop','object_id':'8'})
        self.assertEqual(self.store.approve_and_execute(key, True), 'changed')
        self.assertEqual(self.api.puts, [])
    def test_register_rejects_different_box_home(self):
        fake_module = SimpleNamespace(register_action=self.store.register_action, ApprovalStale=Stale,
                                      ActionFailed=Failed, ActionUnknown=Unknown, ActionResult=Result)
        with mock.patch.dict(sys.modules, {'approval_store':fake_module}), mock.patch.dict(os.environ, {'ILSON_HOME':str(Path(self.home)/'other')}):
            dispatch.register()
            verify, execute = self.store.actions[dispatch.ACTION]
            with self.assertRaises(Failed): verify(object())
            with self.assertRaises(Failed): execute(object())
            self.assertIsNone(self.store.contexts[dispatch.ACTION](object()))
    def test_local_context_uses_only_matching_saved_question(self):
        key = self.make()
        request = self.store.requests[key]
        self.assertEqual(self.store.contexts[dispatch.ACTION](request), question()['question'])
        row = question(); row['question'] = '변경된 원문'
        ingest.save(self.home, 'naver_commerce', 'shop', {7:row}, START, END)
        self.assertIsNone(self.store.contexts[dispatch.ACTION](request))
    def test_account_changed(self):
        key = self.make()
        self.api.identity_value = 'b'*64
        self.assertEqual(self.store.approve_and_execute(key, True), 'changed')
    def test_http_errors_during_verify(self):
        for code in (429, 403, 401):
            key = self.make()
            self.api.error = APIError(code)
            self.assertEqual(self.store.approve_and_execute(key, True), 'failed')
            self.api.error = None
        self.assertFalse(self.api.puts)
    def test_uncertain_put_no_retry_even_after_restart(self):
        key = self.make()
        def answer(qid, body): self.api.puts.append((qid, body)); raise UnknownResult()
        self.api.answer = answer
        self.assertEqual(self.store.approve_and_execute(key, True), 'result_unknown')
        self.adapter = dispatch.Adapter(self.home, self.store, lambda account:self.api, contract)
        self.adapter.register()
        with self.assertRaises(ValueError): self.store.approve_and_execute(key, True)
        self.assertEqual(len(self.api.puts), 1)
    def test_pages_and_duplicates(self):
        self.api.rows = [question(i) for i in range(1, 206)]
        self.assertEqual(len(ingest.collect(self.api, START, END)), 205)
        self.api.rows.append(question(1))
        with self.assertRaises(ValueError): ingest.collect(self.api, START, END)
    def test_dedup_across_runs(self):
        rows = ingest.collect(self.api, START, END)
        ingest.save(self.home, 'naver_commerce', 'shop', rows, START, END)
        record, digest = ingest.get(self.home, 'shop', 7)
        self.assertEqual(record['question']['questionId'], 7)
        self.assertEqual(digest, ingest.fingerprint(question()))
        later = '2026-11-09T00:00:00+09:00'
        ingest.save(self.home, 'naver_commerce', 'shop', rows, START, later)
        self.assertEqual(ingest.get(self.home, 'shop', 7)[0]['end'], END)
    def test_manual_sensitive_input_never_calls_model(self):
        def no_call(*a, **k): raise AssertionError()
        self.assertEqual(draft.draft('환불해주세요', consent=True, home=self.home, runner=no_call)['status'], 'review')
        with self.assertRaises(ValueError): draft.draft('안녕하세요', consent=False, home=self.home, runner=no_call)
    def test_model_promise_is_held(self):
        fake = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({'result':'내일 배송해드립니다.'}))
        self.assertEqual(draft.draft('안녕하세요', consent=True, home=self.home, runner=fake)['status'], 'review')

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        service.save_connection(self.home, {'account':'test','client_id':'synthetic-id','client_secret':'synthetic-secret','type':'SELF','account_id':''})
        self.path = service.path_for(self.home, 'test')
    def test_credentials_are_private_and_overwrite_without_disclosure(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('synthetic-secret', json.dumps(service.save_connection(self.home, {'account':'test','client_id':'synthetic-id','client_secret':'synthetic-secret','type':'SELF','account_id':''})))
    def test_get_token_expiration_is_retried_once(self):
        calls = []
        def send(method, url, headers, body):
            calls.append((method,url))
            if url.endswith('/oauth2/token'): return 200, b'{"access_token":"synthetic-token"}'
            if sum('/contents/qnas' in u for _,u in calls) == 1: return 401, b''
            return 200, b'{"contents":[],"totalPages":0,"totalElements":0}'
        client = NaverQna(self.path, home=self.home, send=send)
        with mock.patch.object(runtime,'sign',return_value='signed-fixture'):
            self.assertEqual(client.page(START, END, 1)['contents'], [])
        self.assertEqual([x[0] for x in calls], ['POST','GET','POST','GET'])
    def test_put_ambiguous_failure_never_retries(self):
        calls = []
        def send(method, url, headers, body):
            calls.append(method)
            if method == 'POST': return 200, b'{"access_token":"synthetic-token"}'
            return 500, b''
        client = NaverQna(self.path, home=self.home, send=send)
        with mock.patch.object(runtime,'sign',return_value='signed-fixture'):
            with self.assertRaises(UnknownResult): client.answer(7, '안녕하세요')
        self.assertEqual(calls, ['POST','PUT'])
    def test_runtime_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError): runtime.install(self.home, consent=False, platform='darwin')
        self.assertFalse((Path(self.home)/'.runtime').exists())

class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / 'launchd').mkdir()
        (self.home / 'launchd/jobs.conf').write_text('briefing | run-job.sh | briefing | daily 08:00\n')
        service.save_connection(self.home, {'account':'shop','client_id':'id','client_secret':'synthetic','type':'SELF','account_id':''})
        self.settings = {'enabled':True,'account':'shop','start':'2026-01-01T00:00:00+00:00','collection_consent':True,'model_consent':True}
    def test_opt_in_and_resume_after_interrupted_collection(self):
        service.schedule(self.home, self.settings)
        periods=[]
        def scan(client, start, end):
            periods.append((start,end))
            if len(periods) == 2: raise APIError(429)
            return {7:question()}
        with mock.patch.object(scheduled,'client_for',return_value=object()), mock.patch.object(scheduled,'collect',side_effect=scan), mock.patch.object(scheduled,'draft',return_value={'status':'draft','text':'감사합니다.'}) as model:
            with self.assertRaises(APIError): scheduled.run(self.home, datetime(2026,1,17,tzinfo=timezone.utc))
            scheduled.run(self.home, datetime(2026,1,17,tzinfo=timezone.utc))
            self.assertLessEqual(datetime.fromisoformat(periods[2][0]), datetime.fromisoformat(periods[1][0]))
            self.assertEqual(model.call_count, 1)
        self.assertEqual(len(service.list_drafts(self.home, {'account':'shop'})['drafts']), 1)
        self.assertEqual(sum(line.startswith('reply-drafts |') for line in (self.home/'launchd/jobs.conf').read_text().splitlines()), 1)
    def test_disabled_never_collects_and_optin_required(self):
        denied = dict(self.settings, model_consent=False)
        with self.assertRaises(ValueError): service.schedule(self.home, denied)
        with mock.patch.object(scheduled,'collect',side_effect=AssertionError):
            scheduled.run(self.home)
            service.schedule(self.home, self.settings)
            service.schedule(self.home, dict(self.settings, enabled=False))
            scheduled.run(self.home)
    def test_disconnect_prevents_further_collection(self):
        service.schedule(self.home, self.settings)
        service.disconnect(self.home, {'account':'shop'})
        self.assertFalse(service.path_for(self.home, 'shop').exists())
        with mock.patch.object(scheduled,'collect',side_effect=AssertionError): scheduled.run(self.home)

class ScheduledRunnerTests(unittest.TestCase):
    def test_disabled_job_uses_no_model_and_sends_no_notification(self):
        fixture = job_fixture.RunJobNotifyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.run_job('reply-drafts')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((fixture.box/'state/last-run.reply-drafts').exists())
        self.assertEqual(fixture.sent(), '')

class ReplyHTTPTests(admin_fixture.BoxFixture):
    request = admin_fixture.HTTP시험.request
    login = admin_fixture.HTTP시험.login
    def setUp(self):
        super().setUp()
        self.server = admin_fixture.admin.Server(self.box, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3)
    def test_session_origin_and_input_gate_before_reply_service(self):
        payload={'text':'합성 글', 'consent':True}
        with mock.patch.object(service,'manual_draft',return_value={'status':'draft','text':'감사합니다.'}) as model:
            self.assertEqual(self.request('POST','/api/replies/draft',payload)[0], 401)
            cookie,_ = self.login()
            self.assertEqual(self.request('POST','/api/replies/draft',payload,headers={'Cookie':cookie, 'Origin':'https://invalid.example'})[0],403)
            status,_,body=self.request('POST','/api/replies/draft',payload,headers={'Cookie':cookie})
            self.assertEqual(status,200)
            self.assertEqual(body['status'],'draft')
            self.assertEqual(model.call_count,1)

if __name__ == '__main__': unittest.main()
