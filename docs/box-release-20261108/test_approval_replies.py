"""Run standalone after 1+6 merge: real modules, fake loopback services, no external calls."""
import json
import importlib.util
import secrets
import subprocess
import threading
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_services import fake_services

# load_all binds its adapter to the directory containing replies_dispatch.py, just as an installed Box does.
TEMP = tempfile.TemporaryDirectory(prefix='ilson-integration-')
HOME = Path(TEMP.name)
shutil.copytree(ROOT / 'template/lib', HOME / 'lib', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
os.environ['ILSON_HOME'] = str(HOME)
sys.path.insert(0, str(HOME / 'lib'))
import approval_store as store
import approval_actions
import approval_dispatch
import approval_telegram as telegram
import replies_service as service
import replies_draft
from replies_naver_qna import NaverQna, transport, APIError, BASE

START = '2026-11-01T00:00:00+09:00'
END = '2026-11-08T00:00:00+09:00'

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service.save_connection(HOME, {'account':'shop', 'client_id':'synthetic-id', 'client_secret':'synthetic-secret', 'type':'SELF', 'account_id':''})
        telegram.save_config(HOME, 'synthetic-token', 222, 222)
        # The callable resolves this factory at execution time; load_all must register it, not the test.
        cls.client_patch = patch.object(service, 'client_for', lambda home, account: cls.client)
        cls.client_patch.start()
        approval_actions.load_all()
        assert 'naver_qna_answer' in store._ACTIONS
    @classmethod
    def tearDownClass(cls):
        cls.client_patch.stop()
        TEMP.cleanup()
    def setUp(self):
        self.manager = fake_services()
        self.state, self.base = self.manager.__enter__()
        self.addCleanup(self.manager.__exit__, None, None, None)
        self.timeout_put = False
        def send(method, url, headers, data):
            if not url.startswith(BASE + '/'):
                raise AssertionError('unexpected outbound destination')
            if method == 'PUT' and self.timeout_put:
                raise APIError(None)  # same transport failure classification as a timeout
            return transport(method, self.base + url[len('https://api.commerce.naver.com'):], headers, data)
        client = NaverQna(service.path_for(HOME, 'shop'), home=HOME, send=send)
        client.token = 'synthetic-access-token'
        type(self).client = client
        self.telegram_transport = lambda token, method, data: telegram.api(token, method, data, endpoint=self.base)
    def create(self):
        before_put = sum(c[0] == 'PUT' for c in self.state.calls)
        result = service.fetch_questions(HOME, {'account':'shop','start':START,'end':END,'consent':True})
        self.assertEqual(result['count'], 1)
        fake_runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({'result':'안녕하세요. 감사합니다.'}))
        drafted = replies_draft.draft(result['questions'][0]['question'], consent=True, home=HOME, runner=fake_runner)
        self.assertEqual(drafted['status'], 'draft')
        req = service.request_answer(HOME, {'account':'shop', 'question_id':'7', 'body':drafted['text']})['request_id']
        self.assertEqual(store.get(req, HOME)['state'], 'pending')
        self.assertEqual(sum(c[0] == 'PUT' for c in self.state.calls), before_put)
        telegram.send_card(HOME, req, consent=True, transport=self.telegram_transport, license_check=lambda:True)
        card = [c[2] for c in self.state.calls if c[1] == 'sendMessage'][-1]
        self.assertIn(drafted['text'], card['text'])
        self.assertIn('문의 원문은 일손 화면', card['text'])
        self.assertNotIn(self.state.question['question'], card['text'])
        token = card['reply_markup']['inline_keyboard'][0][0]['callback_data']
        update = {'update_id':1,'callback_query':{'id':'callback','data':token,'from':{'id':222,'is_bot':False},'message':{'chat':{'id':222,'type':'private'},'message_id':123}}}
        return req, update
    def approve(self, update):
        telegram.process_update(HOME, update, transport=self.telegram_transport, license_check=lambda:True)
    def test_success_verify_before_single_put_and_reclick(self):
        req, update = self.create()
        action = store._ACTIONS['naver_qna_answer']
        row = store.get(req, HOME)
        self.assertEqual(action[2](store.approval_request(row)), self.state.question['question'])
        self.approve(update); self.approve(update)
        self.assertEqual(store.get(req, HOME)['state'], 'success')
        calls = [x[0] for x in self.state.calls if x[0] in ('GET','PUT')]
        self.assertEqual(calls, ['GET','GET','GET','GET','PUT'])
        self.assertEqual(approval_dispatch.dispatch(req, HOME, license_check=lambda:True), 'not_ready')
    def test_answered_or_changed_no_put(self):
        for mode in ('answered','changed'):
            with self.subTest(mode=mode):
                self.state.question.update(question='합성 문의 원문', answered=False)
                req, update = self.create()
                if mode == 'answered': self.state.question['answered'] = True
                else: self.state.question['question'] = '변경된 합성 문의'
                self.approve(update)
                self.assertEqual(store.get(req, HOME)['state'], 'changed')
                self.assertFalse([c for c in self.state.calls if c[0] == 'PUT'])
    @unittest.skipUnless(os.environ.get('PLAYWRIGHT_CORE'), 'PLAYWRIGHT_CORE with WebKit required')
    def test_real_adapter_context_in_local_webkit(self):
        self.state.question['question'] = '<img src=x onerror="window.__unsafe=1"> 고객 문의'
        self.create()
        shutil.copytree(ROOT / 'template/web', HOME / 'web', dirs_exist_ok=True)
        folder = HOME / 'state/web-admin'
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('token', 'instance'):
            path = folder / name
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as out:
                out.write(secrets.token_urlsafe(32))
        import license as lic
        spec = importlib.util.spec_from_file_location('isolated_admin', HOME / 'lib/web-admin-server.py')
        admin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(admin)
        probe = admin.Probe(HOME, run=lambda _: (1, ''), which=lambda _:None)
        probe.jobs = lambda:set()
        with patch.object(lic, 'evaluate', return_value=(True, 'ACTIVE')):
            server = admin.Server(admin.Box(HOME, user_home=HOME, probe=probe), 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run(['node', str(ROOT/'docs/box-release-20261108/check_context_webkit.cjs'),
                    'http://127.0.0.1:' + str(server.server_port), str(folder/'token')],
                    env=os.environ.copy(), capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            finally:
                server.shutdown(); server.server_close(); thread.join()
                if server.box._workspace is not None: server.box._workspace.close()

    def test_ambiguous_put_never_retried(self):
        for mode in ('disconnect','server_error','timeout'):
            with self.subTest(mode=mode):
                self.state.question.update(question='합성 문의 원문', answered=False)
                self.state.put_mode = mode
                self.timeout_put = mode == 'timeout'
                req, update = self.create()
                before = sum(c[0] == 'PUT' for c in self.state.calls)
                self.approve(update); self.approve(update)
                self.assertEqual(store.get(req, HOME)['state'], 'result_unknown')
                self.assertEqual(approval_dispatch.dispatch(req, HOME, license_check=lambda:True), 'not_ready')
                after = sum(c[0] == 'PUT' for c in self.state.calls)
                self.assertEqual(after-before, 0 if mode == 'timeout' else 1)
                self.timeout_put = False

if __name__ == '__main__': unittest.main(verbosity=2)
