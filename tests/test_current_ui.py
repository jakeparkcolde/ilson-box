"""기존 화면의 요청이 실제 로컬 장부와 승인 경계를 지키는지 검증한다."""
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/lib'))
from current_ui import CurrentUI
from mini_workspace import Workspace, WorkspaceError
from test_mini_workspace import FakeProviders, admin


class CurrentUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        (self.home / 'vault').mkdir()
        self.provider = FakeProviders()
        self.work = Workspace(self.home, admin.Files(self.home), providers=self.provider)
        self.addCleanup(self.work.close)
        self.ui = CurrentUI(self.work)

    def test_등록계정도_운영화면에서_미확인상태로_보이고_연결가능채널을_돌려준다(self):
        self.ui.save_account({'platform':'x','account':'sample','brands':['사업부']})
        row = self.ui.operations()['accounts'][0]
        self.assertEqual(row['platform'], 'x')
        self.assertEqual(row['state'], 'unknown')
        self.assertEqual(set(self.ui.internal()['connectable']), {'threads','instagram','facebook'})

    def test_서류함_그룹과_폴더는_사용자용_이름을_쓴다(self):
        self.work.save_document({'title':'조사','content':'자료','category':'research'})
        row = self.ui.vault()['vault'][0]
        self.assertEqual(row['group'], '업무 기록')
        self.assertEqual(row['name'], '리서치')

    def test_반려사유를_저장하고_사람의요청만_재작성입력으로_쓴다(self):
        account=self.work.connect({'platform':'threads','token':secrets.token_urlsafe(40)})
        queued=self.work.queue('draft',{'account_id':account['id'],'brief':'원래 사람이 요청한 상품 안내'})
        self.work.run_next_job()
        post=self.work.post(self.work.job(queued['id'])['result']['post_id'])
        result=self.ui.dispatch('POST','/api/reject',data={'mid':post['id']+':1','note':'할인 조건을 먼저 설명해 주세요.'})
        job=self.work.job(result['redraft']['job_id'])
        self.assertIn('원래 사람이 요청한 상품 안내',job['args']['brief'])
        self.assertIn('할인 조건을 먼저',job['args']['brief'])
        self.assertNotIn(post['text'],job['args']['brief'])
        self.assertEqual(self.work.post(post['id'])['status'],'rejected')
        self.assertIn('할인 조건을 먼저',self.ui.operations()['records'][0]['reason'])
        self.work.run_next_job();self.work.publish_due()
        self.assertEqual(self.provider.sent,[])

    def test_초안예약편집은_승인을_취소하고_그시각으로만_재승인한다(self):
        account=self.work.connect({'platform':'threads','token':secrets.token_urlsafe(40)})
        post=self.work.create_post({'account_id':account['id'],'text':'예약 초안','scheduled_at':'2099-01-02T10:00:00+09:00'})
        self.assertEqual(post['scheduled_at'],'2099-01-02T01:00:00+00:00')
        self.ui.dispatch('POST','/api/approve',data={'mid':post['id']+':1','immediate':False})
        changed=self.work.post_action(post['id'],'edit',{'revision':1,'text':'수정 초안','scheduled_at':'2099-01-03T10:00:00+09:00'})
        self.assertEqual(changed['status'],'draft')
        self.assertEqual(changed['scheduled_at'],'2099-01-03T01:00:00+00:00')
        self.assertIsNone(changed['approved_digest'])
        self.work.publish_due();self.assertEqual(self.provider.sent,[])

    def test_브라우저의_ISO_Z예약시각을_파이썬39에서도_읽는다(self):
        account=self.work.connect({'platform':'threads','token':secrets.token_urlsafe(40)})
        post=self.work.create_post({'account_id':account['id'],'text':'브라우저 예약','scheduled_at':'2099-01-02T01:00:00.000Z'})
        self.assertEqual(post['scheduled_at'],'2099-01-02T01:00:00+00:00')

    def test_계정분류는_인증이나_발행으로_취급하지않는다(self):
        result = self.ui.dispatch('POST', '/api/sns-internal/account', data={
            'platform': 'youtube', 'account': 'sample', 'brands': ['시험 사업부'], 'owner': '담당자'})
        self.assertTrue(result['ok'])
        self.assertEqual(self.ui.internal()['accounts'], [])
        self.assertEqual(self.ui.registry()['youtube:sample']['owner'], '담당자')
        self.assertEqual(self.provider.sent, [])
        self.assertEqual(self.ui.operations()['records'], [])

    def test_기존_링크드인회사_계정형식과_분류이력을_보존한다(self):
        self.ui.save_account({'platform': 'linkedin', 'account': 'company/123456',
                              'brands': ['영업'], 'owner': '담당자'})
        row = self.ui.registry()['linkedin:company/123456']
        self.assertEqual(row['account'], 'company/123456')
        self.assertIn('updated_at', row)

    def test_기존SNS화면의_승인은_열람한_리비전에만_유효하다(self):
        account = self.work.connect({'platform': 'threads', 'token': secrets.token_urlsafe(40)})
        post = self.work.create_post({'account_id': account['id'], 'text': '첫 본문'})
        viewed = self.ui.operations()['records'][0]['mid']
        self.work.post_action(post['id'], 'edit', {'revision': 1, 'text': '바뀐 본문'})
        with self.assertRaises(WorkspaceError):
            self.ui.dispatch('POST', '/api/approve', data={'mid': viewed, 'immediate': True})
        self.work.publish_due()
        self.assertEqual(self.provider.sent, [])
        latest = self.ui.operations()['records'][0]['mid']
        self.ui.dispatch('POST', '/api/approve', data={'mid': latest, 'immediate': True})
        self.work.publish_due()
        self.assertEqual(len(self.provider.sent), 1)

    def test_예약시간없이_예약승인하면_즉시발행으로_바뀌지않는다(self):
        account = self.work.connect({'platform': 'threads', 'token': secrets.token_urlsafe(40)})
        post = self.work.create_post({'account_id': account['id'], 'text': '예약 검토'})
        with self.assertRaises(WorkspaceError):
            self.ui.dispatch('POST', '/api/approve', data={'mid': post['id'] + ':1', 'immediate': False})
        self.assertEqual(self.work.post(post['id'])['status'], 'draft')

    def test_주간표는_UTC날짜가아닌_한국날짜에_예약을_표시한다(self):
        account = self.work.connect({'platform':'threads','token':secrets.token_urlsafe(40)})
        post = self.work.create_post({'account_id':account['id'],'text':'자정 이후 예약'})
        with self.work.transaction():
            self.work.db.execute('UPDATE posts SET scheduled_at=? WHERE id=?',
                                 ('2026-10-07T16:00:00+00:00',post['id']))
        week = self.ui.operations('2026-10-05')['weekly']
        cells = [c for row in week['rows'] for c in row['cells'] if any(i['id']==post['id'] for i in c['items'])]
        self.assertEqual([c['day'] for c in cells], ['2026-10-08'])

    def test_조사화면의_깊이_영상_이전질문을_실행기로_전달한다(self):
        queued = self.ui.dispatch('POST', '/api/research/jobs', data={
            'question': '후속 질문', 'period': 'all',
            'options': {'mode': 'deep', 'videos': True, 'context': ['이전 사용자 질문']}})
        job = self.work.job(queued['id'])
        self.assertTrue(job['args']['videos'])
        self.assertEqual(job['args']['mode'], 'deep')
        self.assertEqual(job['args']['context'], ['이전 사용자 질문'])
        self.work.run_next_job()
        result = self.ui.dispatch('GET', '/api/research/jobs/' + job['id'])
        self.assertEqual(result['stage'], 'done')
        self.assertIn('document_id', result['result'])

    def test_서류함은_실제문서를_그룹화하고_원본을_보존한다(self):
        original = self.work.save_document({'title': '원본', 'content': '보존할 내용', 'category': 'company'})
        tree = self.ui.vault()['vault']
        self.assertEqual(tree[0]['files'][0]['id'], original['id'])
        self.assertEqual(self.ui.dispatch('POST', '/api/current/document', data={'id': original['id']})['title'], '원본')
        saved = self.work.save_document({'title': '수정본', 'content': '새 내용', 'category': 'company', 'previous_id': original['id']})
        self.assertIn('보존할 내용', self.work.document(original['id'])['content'])
        self.assertIn('이전 기록:', self.work.document(saved['id'])['content'])

    def test_지식화면의_수집후검토후생성을_분리한다(self):
        bundle = self.ui.dispatch('POST', '/api/knowledge/collect', data={
            'url':'https://www.youtube.com/watch?v=abcdefghijk','limit':3})
        self.assertEqual(self.work.documents()['documents'], [])
        ability = self.ui.dispatch('POST', '/api/knowledge/learn', data={'bundle':bundle,'goal':'점검 방법'})
        self.assertEqual(ability['state'], 'draft')
        self.assertFalse(ability['tested'])
        self.assertIn('시험 능력', self.work.document(ability['document_id'])['content'])


if __name__ == '__main__':
    unittest.main()
