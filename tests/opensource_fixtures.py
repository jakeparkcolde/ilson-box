"""Synthetic data only. These fake tools are not shipped or recommendations."""
import copy
import json
from datetime import datetime, timezone

NOW = 1794614400.0  # 2026-11-14T00:00:00Z


def at(offset=0):
    return datetime.fromtimestamp(NOW + offset, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def repo(ident='a' * 32, number=1):
    name = 'synthetic-fixture/fake-tool-' + str(number)
    return dict(id=ident, github_id=number, full_name=name, category='documents', curated_order=number,
        one_liner='합성 검증용 가짜 도구 소개', mild_md='실제 제품이 아닌 한국어 합성 설명입니다.',
        use_cases=['가상 문서를 살펴보는 상황'], prerequisites=['가상 준비물'], limitations=['실제 동작은 검증하지 않았습니다.'],
        difficulty=2, box_burden='browse', preparation='설명 확인용 기기', cost='가상 검토: 필수 유료 API 없음',
        data_processing='L0는 입력 자료를 받거나 전송하지 않습니다.',
        license=dict(spdx='MIT', conditions='원문 조건 확인이 필요합니다.',
            url='https://github.com/' + name + '/blob/' + 'b'*40 + '/LICENSE', reviewed=True),
        gitbap_url='https://www.gitbap.com/r/' + name, official_url='https://github.com/' + name,
        source=dict(summary_id='synthetic-summary', summary_revision=1, lang='ko',
            readme_hash='c'*64, summary_readme_hash='c'*64, model='synthetic-model',
            summary_created_at=at(-86400), synced_at=at(-3600), status_checked_at=at(), commit='b'*40),
        review=dict(hidden=False, review_status='approved', metadata_verdict='ok', content_scan='ok',
            policy='approved', rights='approved', maintenance='active', archived=False, prohibited=False,
            requirements_confirmed=True, key_required=False, paid_api_required=False, reviewed_at=at(),
            valid_until=at(7*86400), target_commit='b'*40, policy_version='box-l0-v1',
            past_safety_pass=True, past_alive_pass=True, past_evaluated_at=at(-864000), metadata_checked_at=at()),
        catalog_approved=True, runnable=False,
        preview=dict(approved=True, input='가상 입력 예', result='검토한 가상 결과 예', placement='가상 업무 자리', source='합성 샘플 기록'),
        video=dict(public_approved=True, lang='ko', made_at=at(-86400), duration_s=35,
            gitbap_url='https://www.gitbap.com/r/' + name, approval_basis='가상 공개 승인 근거', valid_until=at(86400)))


def catalog(*rows, version=1, revocation=0, revoked=()):
    return dict(schema_version=1, catalog_version=version, generated_at=at(), valid_until=at(72*3600),
        policy_version='box-l0-v1', revocation_version=revocation, revoked_repo_ids=list(revoked),
        signature=dict(kind='bundled', key_id=None, value=None), source_commit='d'*40, repos=copy.deepcopy(list(rows)))


def raw(document):
    return json.dumps(document, ensure_ascii=False).encode()
