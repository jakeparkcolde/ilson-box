"""Adapter for approval_store's naver_qna_answer contract.

Only the approval store may call these callbacks. The store owns the atomic
approved->executing transition, content hash and non-retryable result ledger.
"""
import hashlib
import re
from replies_ingest import collect, get
from replies_naver_qna import APIError, UnknownResult

ACTION = 'naver_qna_answer'

class Adapter:
    def __init__(self, home, store, client_for_account, contract):
        self.home, self.store = home, store
        self.client_for_account, self.contract = client_for_account, contract

    def register(self):
        self.store.register_action(ACTION, self.verify, self.execute, local_context=self.local_context)

    def request(self, account, question_id, body):
        if not isinstance(account, str) or not account or len(account) > 128 or type(question_id) is not int or question_id <= 0:
            raise ValueError('문의 대상을 확인하세요.')
        if not isinstance(body, str) or not body.strip() or len(body) > 2000:
            raise ValueError('답변 내용을 확인하세요.')
        record, digest = get(self.home, account, question_id)
        q = record['question']
        if q.get('answered') is not False or q.get('answer') or q.get('answers'):
            raise ValueError('이미 답변된 문의입니다.')
        target = {'channel':'naver_commerce', 'account':account, 'object_id':str(question_id)}
        return self.store.request_approval(ACTION, target, '네이버 상품 문의 답변', body,
                                           {'question_sha256':digest, 'from_date':record['start'], 'to_date':record['end'], 'connection_sha256':self.client_for_account(account).identity()})

    def verify(self, req):
        stale, failed = self.contract.ApprovalStale, self.contract.ActionFailed
        try:
            target, meta = req.target, req.meta
            if req.action_type != ACTION or not isinstance(target, dict) or set(target) != {'channel','account','object_id'} or target['channel'] != 'naver_commerce':
                raise ValueError()
            account, qid = target['account'], target['object_id']
            if not isinstance(account, str) or not account or not isinstance(qid, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', qid):
                raise ValueError()
            if not isinstance(meta, dict) or set(meta) != {'question_sha256','from_date','to_date','connection_sha256'}:
                raise ValueError()
            if hashlib.sha256(req.body.encode()).hexdigest() != req.body_sha256:
                raise ValueError()
            record, digest = get(self.home, account, int(qid))
            if digest != meta['question_sha256'] or record['start'] != meta['from_date'] or record['end'] != meta['to_date']:
                raise ValueError()
            local = record['question']
            if local['answered'] is not False or local.get('answer') or local.get('answers'):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise stale('저장된 문의 또는 승인 내용이 달라졌습니다.') from None
        try:
            client = self.client_for_account(account)
            if client.identity() != meta['connection_sha256']:
                raise stale('연결 계정이 바뀌었습니다.')
            remote = collect(client, record['start'], record['end'])
        except (APIError, ValueError, OSError):
            raise failed('네이버 문의 상태를 확인하지 못했습니다.') from None
        current = remote.get(int(qid))
        from replies_ingest import fingerprint
        if not current or current.get('answered') is not False or current.get('answer') or current.get('answers') or fingerprint(current) != digest:
            raise stale('문의가 바뀌었거나 이미 답변되었습니다.')

    def local_context(self, req):
        # Do not show a newer question as if it were the one originally approved.
        try:
            target = req.target
            if req.action_type != ACTION or set(target) != {'channel','account','object_id'} or target['channel'] != 'naver_commerce': return None
            qid = target['object_id']
            if not isinstance(qid, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', qid): return None
            record, digest = get(self.home, target['account'], int(qid))
            if digest != req.meta.get('question_sha256'): return None
            return record['question']['question']
        except Exception:
            return None

    def execute(self, req):
        try:
            client = self.client_for_account(req.target['account'])
            if client.identity() != req.meta['connection_sha256']:
                raise self.contract.ApprovalStale('연결 계정이 바뀌었습니다.')
            client.answer(int(req.target['object_id']), req.body)
        except UnknownResult:
            raise self.contract.ActionUnknown('등록 결과 확인 필요. 자동 재시도하지 마세요.') from None
        except APIError:
            raise self.contract.ActionFailed('답변 등록 요청이 거절되었습니다.') from None
        return self.contract.ActionResult(status='success', external_ref=None, detail='상품 문의 답변 등록 요청 완료')


def register():
    """Called by approval_actions.load_all() in each executing process."""
    import os
    from pathlib import Path
    import approval_store as contract
    from replies_service import client_for
    home = Path(__file__).resolve().parent.parent
    adapter = Adapter(home, contract, lambda account:client_for(home, account), contract)
    def check_home():
        configured = os.environ.get('ILSON_HOME')
        if configured and Path(configured).expanduser().resolve() != home:
            raise contract.ActionFailed('Box 폴더가 일치하지 않습니다.')
    def verify(req):
        check_home()
        return adapter.verify(req)
    def execute(req):
        check_home()
        return adapter.execute(req)
    def local_context(req):
        try: check_home()
        except contract.ActionFailed: return None
        return adapter.local_context(req)
    contract.register_action(ACTION, verify, execute, local_context=local_context)
