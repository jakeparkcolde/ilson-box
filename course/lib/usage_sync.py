# coding: utf-8
"""Daily-number-only client. No default URL, redirects, ambient proxy or raw errors."""
from datetime import date, datetime, timedelta
import json
import random
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import uuid
from zoneinfo import ZoneInfo

from usage_timeline import UsageError, COUNTERS, MODELS, MAX_INT, safe, stamp, write_json


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def canonical_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value, version=4)) == value and uuid.UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


def validate_payload(payload, today=None, *, linked=True):
    keys = {'schema_version', 'aggregation_version', 'device_id', 'enrollment_id', 'consent_id', 'timezone', 'revision', 'daily'}
    row_keys = {'date', 'tool', 'model', 'sessions', 'turns', 'quality', *COUNTERS}
    if not isinstance(payload, dict) or set(payload) != keys or type(payload['schema_version']) is not int or payload['schema_version'] != 1 or payload['aggregation_version'] != 'usage-v1':
        raise UsageError('허용되지 않은 전송 형식입니다.')
    if not canonical_uuid(payload['device_id']) or any(not canonical_uuid(payload[k]) and (linked or payload[k] is not None) for k in ('enrollment_id', 'consent_id')):
        raise UsageError('연결 정보를 확인하세요.')
    zone = payload['timezone']
    if not isinstance(zone, str) or len(zone) > 64:
        raise UsageError('시간대를 확인하세요.')
    zone = ZoneInfo(zone)
    today = today or datetime.now(zone).date()
    if type(payload['revision']) is not int or not 1 <= payload['revision'] <= MAX_INT or not isinstance(payload['daily'], list) or len(payload['daily']) > 4096:
        raise UsageError('전송 범위를 확인하세요.')
    seen = set()
    for row in payload['daily']:
        if not isinstance(row, dict) or set(row) != row_keys:
            raise UsageError('허용되지 않은 전송 필드입니다.')
        day = date.fromisoformat(row['date'])
        if day.isoformat() != row['date'] or not today - timedelta(days=366) <= day <= today:
            raise UsageError('전송 날짜를 확인하세요.')
        if row['tool'] not in ('claude_code', 'codex') or row['model'] not in (None, *MODELS) or row['quality'] not in ('observed', 'partial'):
            raise UsageError('지원하지 않는 집계 형식입니다.')
        if any(type(row[k]) is not int or not 0 <= row[k] <= MAX_INT for k in ('sessions', 'turns')):
            raise UsageError('건수 형식을 확인하세요.')
        if row['model'] is not None and (row['sessions'] or row['turns']):
            raise UsageError('모델별 세션 중복을 허용하지 않습니다.')
        if any(row[k] is not None and (type(row[k]) is not int or not 0 <= row[k] <= MAX_INT) for k in COUNTERS):
            raise UsageError('토큰 형식을 확인하세요.')
        key = (row['date'], row['tool'], row['model'])
        if key in seen:
            raise UsageError('중복된 일별 행입니다.')
        seen.add(key)
    if len(json.dumps(payload).encode()) > 1024 * 1024:
        raise UsageError('전송 범위가 너무 큽니다.')
    return payload


def base_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise UsageError('사이트 주소를 확인하세요.')
    u = urlsplit(value)
    if u.username or u.password or u.query or u.fragment or not u.hostname or u.scheme not in ('https', 'http'):
        raise UsageError('HTTPS 사이트 주소를 확인하세요.')
    if u.scheme != 'https' and u.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise UsageError('HTTPS가 필요합니다.')
    if any(ord(c) < 33 for c in value) or '%' in u.path or '..' in u.path.split('/') or '\\' in value:
        raise UsageError('사이트 주소를 확인하세요.')
    return value.rstrip('/')


class Client:
    def __init__(self, ledger):
        self.ledger = ledger
        self.credential = ledger.root / 'device-token.json'

    def token(self):
        safe(self.credential, private=True)
        if self.credential.stat().st_size > 4096:
            raise UsageError('기기 자격을 확인하세요.')
        with self.credential.open(encoding='utf-8') as stream:
            token = json.load(stream)['token']
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token):
            raise UsageError('기기 자격을 확인하세요.')
        return token

    def request(self, method, base, route, body=None, token=None):
        raw = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() if body is not None else None
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = Request(base_url(base) + '/api/activity/' + route, data=raw, headers=headers, method=method)
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3) as response:
                raw_response = response.read(65537)
                if len(raw_response) > 65536:
                    return 502, {}, None
                return response.status, json.loads(raw_response), None
        except HTTPError as error:
            # Do not read or expose untrusted error bodies.
            return error.code, {}, error.headers.get('Retry-After')
        except (OSError, URLError, ValueError):
            return 503, {}, None

    def link(self, base, code):
        cfg = self.ledger.config()
        if not cfg.get('enabled') or cfg.get('consent_id') or cfg.get('revoke_pending'):
            raise UsageError('기록을 켜고 기존 연결을 해제한 뒤 연결하세요.')
        base = base_url(base)
        if not re.fullmatch(r'[A-Z0-9]{12}', code):
            raise UsageError('일회 연결 코드 형식을 확인하세요.')
        validate_payload(self.ledger.payload(), date.fromisoformat(self.ledger.summary()['today']), linked=False)
        status, reply, _ = self.request('POST', base, 'link', dict(schema_version=1, code=code, device_id=cfg['device_id'], consent_version='usage-v1'))
        expected = {'device_token', 'device_id', 'enrollment_id', 'consent_id', 'expires_at', 'retention_days'}
        if status != 201 or not isinstance(reply, dict) or set(reply) != expected or reply.get('device_id') != cfg['device_id'] or reply.get('retention_days') != 60:
            raise UsageError('연결하지 못했습니다. 사이트에서 코드를 확인하세요.')
        if not all(canonical_uuid(reply[k]) for k in ('enrollment_id', 'consent_id')) or not isinstance(reply['device_token'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', reply['device_token']) or stamp(reply['expires_at']) <= self.ledger.clock():
            raise UsageError('기기 자격 응답을 확인하세요.')
        with self.ledger.locked():
            current = self.ledger.config()
            if not current.get('enabled') or current.get('device_id') != cfg['device_id'] or current.get('consent_id'):
                raise UsageError('설정이 바뀌었습니다. 사이트에서 연결을 해제하세요.')
            write_json(self.credential, {'token': reply['device_token']})
            current.update(base_url=base, enrollment_id=reply['enrollment_id'], consent_id=reply['consent_id'],
                           expires_at=reply['expires_at'], sync_enabled=True, sync_state='ready', attempts=0, next_sync_at=0)
            self.ledger.save(current)
        return self.ledger.summary()

    def unlink(self):
        cfg = self.ledger.config()
        if not cfg.get('consent_id'):
            return self.ledger.summary()
        with self.ledger.locked(wait=True):
            cfg = self.ledger.config()
            cfg.update(sync_enabled=False, revoke_pending=True, sync_state='revoke_pending', next_sync_at=0)
            self.ledger.save(cfg)
        return self.sync()

    def sync(self):
        cfg = self.ledger.config()
        deleting = cfg.get('revoke_pending', False)
        if not deleting and (self.ledger.home / 'state/company.json').exists():
            return self.ledger.summary()
        if not deleting and not (cfg.get('enabled') and cfg.get('sync_enabled') and cfg.get('base_url') and cfg.get('consent_id')):
            return self.ledger.summary()
        if cfg.get('next_sync_at', 0) > self.ledger.clock():
            return self.ledger.summary()
        if deleting:
            method, route, payload = 'POST', 'revoke', {'device_id': cfg['device_id'], 'delete_data': True}
        else:
            payload = validate_payload(self.ledger.payload(), date.fromisoformat(self.ledger.summary()['today']))
            method, route = 'PUT', 'batches'
        status, reply, retry_after = self.request(method, cfg['base_url'], route, payload, self.token())
        with self.ledger.locked():
            current = self.ledger.config()
            if current.get('device_id') != cfg['device_id']:
                return self.ledger.summary()
            if deleting and status == 200 and reply == {'revoked': True, 'deleted': True}:
                safe(self.credential, private=True)
                self.credential.unlink(missing_ok=True)
                for key in ('enrollment_id', 'consent_id', 'expires_at', 'base_url', 'next_sync_at', 'attempts'):
                    current.pop(key, None)
                current.update(device_id=str(uuid.uuid4()), sync_enabled=False, revoke_pending=False, sync_state='deleted')
            elif not deleting and status == 200 and isinstance(reply, dict) and set(reply) == {'accepted_revision', 'accepted_rows', 'delete_after'} and type(reply['accepted_revision']) is int and reply['accepted_revision'] == payload['revision'] and type(reply['accepted_rows']) is int and reply['accepted_rows'] == len(payload['daily']):
                stamp(reply['delete_after'])
                current.update(last_sync_at=self.ledger.clock(), attempts=0, next_sync_at=self.ledger.clock() + 600, sync_state='synced')
            elif not deleting and status in (400, 401, 403, 404, 409, 410, 422):
                current.update(sync_enabled=False, sync_state='needs_attention')
            else:
                attempt = min(current.get('attempts', 0) + 1, 10)
                delay = min(21600, 60 * 2 ** (attempt - 1) + random.uniform(0, 30))
                if retry_after and retry_after.isdigit():
                    delay = max(delay, min(21600, int(retry_after)))
                current.update(attempts=attempt, next_sync_at=self.ledger.clock() + delay,
                               sync_state='revoke_pending' if deleting else 'retry_pending')
            self.ledger.save(current)
        return self.ledger.summary()
