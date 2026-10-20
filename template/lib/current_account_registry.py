"""내부 SNS 계정 분류와 연결 이력. 인증 정보·발행 설정을 저장하지 않는다.

파일 IO/동시 쓰기 락은 sns_internal이 담당한다. 여기서는 허용한 공개 필드만
검증하고 합친다. 사업부 수정이 발행 계정이나 승인 경로를 바꾸면 안 된다.
"""
from __future__ import annotations

PLATFORMS = {'threads', 'instagram', 'facebook', 'naverblog', 'x', 'linkedin', 'qiita', 'zenn', 'youtube'}
PUBLIC_FIELDS = ('platform', 'account', 'display_name', 'brands', 'owner', 'origin',
                 'linked_at', 'imported_at', 'updated_at', 'history', 'management_status', 'page_id')


def text(value, limit):
    if not isinstance(value, str) or len(value.strip()) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('입력 길이와 형식을 확인해 주세요.')
    return value.strip()


def identity(platform, account):
    if platform not in PLATFORMS:
        raise ValueError('지원하는 SNS를 선택해 주세요.')
    account = text(account, 160).lstrip('@').lower()
    if not account:
        raise ValueError('계정 이름을 입력해 주세요.')
    return platform + ':' + account, account


def read(data, company_id):
    if data and data.get('company_id') != company_id:
        raise ValueError('계정 관리 자료의 사무소가 다릅니다.')
    return data or {'company_id': company_id, 'accounts': {}}


def details(data, platform, account, changes, *, now):
    key, account = identity(platform, account)
    row = data['accounts'].setdefault(key, {'platform': platform, 'account': account})
    brands = changes.get('brands')
    if not isinstance(brands, list) or len(brands) > 8:
        raise ValueError('사업부는 최대 8개까지 선택해 주세요.')
    clean = list(dict.fromkeys(text(b, 40) for b in brands if b))
    management = changes.get('management_status', row.get('management_status', 'active'))
    if management not in ('active', 'archived'):
        raise ValueError('관리 중 또는 보관을 선택해 주세요.')
    # 모든 검증이 끝난 뒤에만 기존 값을 바꾼다.
    patch = {'brands': clean, 'display_name': text(changes.get('display_name', ''), 80),
             'owner': text(changes.get('owner', ''), 80), 'updated_at': now,
             'management_status': management}
    row.update(patch)
    return row


def connected(data, platform, account, *, now):
    key, account = identity(platform, account)
    row = data['accounts'].setdefault(key, {'platform': platform, 'account': account})
    # 같은 인계의 저장/소각 재시도는 같은 시각을 넘기므로 이력을 중복시키지 않는다.
    if row.get('linked_at') != now:
        event = {'at': now, 'kind': 'reconnected' if row.get('linked_at') or row.get('origin') else 'connected'}
        row['history'] = [*(row.get('history') or []), event][-10:]
    row.update(origin='internal', linked_at=now)


def public(data):
    return {key: {k: row[k] for k in PUBLIC_FIELDS if k in row}
            for key, row in data['accounts'].items()}
