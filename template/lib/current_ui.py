"""기존 일손 화면의 요청을 미니의 로컬 업무 장부로 연결한다.

화면은 운영 소스를 재사용한다. 회사 데이터나 SNS 인증을 기존 맥에 의존하지
않으며, 승인 요청에는 화면이 열람한 리비전이 포함된 mid를 사용한다.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import parse_qs

from mini_workspace import WorkspaceError, now, text

CHANNELS = {'threads': 'Threads', 'instagram': 'Instagram', 'facebook': 'Facebook',
            'x': 'X', 'naverblog': '네이버 블로그', 'linkedin': 'LinkedIn',
            'qiita': 'Qiita', 'zenn': 'Zenn', 'youtube': 'YouTube'}
ROUTES = {'/api/motion/status', '/api/motion/install', '/api/motion/create', '/api/motion/render', '/api/research/image', '/api/research-capabilities', '/api/research/jobs', '/api/knowledge/collect',
          '/api/knowledge/learn', '/api/sns-operations', '/api/sns-internal',
          '/api/sns-internal/account', '/api/sns-internal/connect', '/api/sns-naver',
          '/api/sns-browser', '/api/sns-browser/check', '/api/sns-readiness', '/api/approve', '/api/reject',
          '/api/current/vault', '/api/current/document'}


def handles(path):
    return path in ROUTES or re.fullmatch(r'/api/motion/(?:jobs/[a-f0-9]{32}|projects/[a-f0-9]{32}/(?:preview|download))',path) is not None or re.fullmatch(r'/api/research/jobs/[a-f0-9]{32}', path) is not None


class CurrentUI:
    def __init__(self, work):
        self.work = work
        self.knowledge_lock = threading.Lock()
        with work.transaction():
            work.db.execute('CREATE TABLE IF NOT EXISTS account_registry(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            work.db.execute('CREATE TABLE IF NOT EXISTS post_feedback(post_id TEXT, revision INTEGER, note TEXT, at TEXT, PRIMARY KEY(post_id,revision))')
        from current_oauth import OAuth
        self.oauth = OAuth(work)
        from current_health import Health
        self.health = Health(self)

    def registry(self):
        with self.work.lock:
            rows = self.work.db.execute('SELECT key,value FROM account_registry').fetchall()
        return {r['key']: json.loads(r['value']) for r in rows}

    def save_account(self, data):
        import current_account_registry as registry
        try:
            key, account = registry.identity(data.get('platform'), data.get('account'))
            with self.work.transaction():
                old = self.registry()
                row = registry.details({'accounts': old}, data['platform'], account, data, now=now())
                self.work.db.execute('INSERT OR REPLACE INTO account_registry VALUES(?,?)',
                                     (key, json.dumps(row, ensure_ascii=False)))
                self.work.record('account_metadata', key)
        except ValueError as error:
            raise WorkspaceError(str(error)) from None
        return {'ok': True}

    def internal(self):
        accounts = []
        registry = self.registry()
        selected = {p['account_id'] for p in self.work.posts()['posts']}
        for row in self.work.accounts()['accounts']:
            connected = row['status'] == 'connected'
            meta = registry.get(row['platform'] + ':' + row['username'].casefold(), {})
            state = 'valid' if connected else 'missing'
            if meta.get('expires_at'):
                try:
                    remaining = datetime.fromisoformat(meta['expires_at']).timestamp() - self.work.clock()
                    state = 'expired' if remaining <= 0 else 'stale' if remaining <= 7 * 86400 else state
                except (TypeError, ValueError):
                    state = 'unknown'
            accounts.append(dict(row, health='ok' if connected else 'unknown',
                                 state=state, publishing=connected and row['id'] in selected,
                                 checked_at=row.get('checked_at'), expires_at=meta.get('expires_at')))
        return {'binding': 'matched', 'accounts': accounts, 'registry': registry,
                'connectable': ['threads', 'instagram', 'facebook'],
                'connections': self.oauth.connections(), 'worker': 'recent' if self.work.publish_thread and self.work.publish_thread.is_alive() else 'unknown',
                'last_cycle_at': None}

    def operations(self, week=None):
        from current_sns_common import iso
        registry = self.registry()
        accounts = []
        by_id = {}
        for a in self.work.accounts()['accounts']:
            by_id[a['id']] = a
            meta = registry.get(a['platform'] + ':' + a['username'].lower(), {})
            brands = meta.get('brands') or ['미분류']
            accounts.append({'platform': a['platform'], 'channel': CHANNELS[a['platform']],
                             'account': a['username'], 'brand': brands[0], 'brands': brands,
                             'state': 'ok' if a['status'] == 'connected' else 'unknown',
                             'label': '인증 확인됨' if a['status'] == 'connected' else '연결 확인 필요',
                             'route': 'internal', 'evidence': '이 미니의 계정 인증 결과'})
        known = {(a['platform'], a['account'].casefold()) for a in accounts}
        for meta in registry.values():
            if (meta['platform'], meta['account'].casefold()) in known or meta.get('management_status') == 'archived':
                continue
            brands = meta.get('brands') or ['미분류']
            accounts.append({'platform': meta['platform'], 'channel': CHANNELS[meta['platform']],
                             'account': meta['account'], 'brand': brands[0], 'brands': brands,
                             'state': 'unknown', 'label': '연결 확인 필요',
                             'route': 'browser' if meta['platform'] not in ('threads', 'instagram', 'facebook') else 'internal',
                             'evidence': '관리 정보만 등록되어 있습니다. 인증 결과를 확인하세요.'})
        records = []
        with self.work.lock:
            feedback = {(r['post_id'], r['revision']): r['note'] for r in self.work.db.execute('SELECT * FROM post_feedback')}
        states = {'draft': ('pending', '승인 대기'), 'approved': ('scheduled', '예약'),
                  'publishing': ('publishing', '발행 중'), 'published': ('published', '발행 완료'),
                  'rejected': ('cancelled', '반려'), 'unknown': ('unknown', '발행 확인 필요')}
        for p in self.work.posts()['posts']:
            a = by_id.get(p['account_id'])
            if not a:
                continue
            meta = registry.get(a['platform'] + ':' + a['username'].lower(), {})
            status, label = states[p['status']]
            records.append({'id': p['id'], 'mid': p['id'] + ':' + str(p['revision']),
                            'revision': p['revision'], 'platform': a['platform'], 'channel': CHANNELS[a['platform']],
                            'brand': (meta.get('brands') or ['미분류'])[0], 'account': a['username'],
                            'title': p['text'].splitlines()[0][:100], 'text': p['text'], 'body': p['text'],
                            'status': status, 'status_label': label, 'scheduled_at': iso(p['scheduled_at']),
                            'published_at': iso(p['updated_at']) if status == 'published' else '',
                            'created_at': iso(p['created_at']), 'prepared_at': iso(p['created_at']), 'updated_at': iso(p['updated_at']),
                            'manual_rejected': p['status'] == 'rejected', 'evidence': '이 미니의 실제 처리 장부',
                            'images': [{'url': p['image_url'], 'label': '첨부 이미지'}] if p['image_url'] else [],
                            'publish_evidence': bool(p['published_id']), 'post_id': p['published_id'],
                            'source': 'mini', 'source_label': '이 미니', 'error': p['error'], 'overdue': False})
            records[-1]['reason'] = feedback.get((p['id'], p['revision']), '')
        return {'records': records, 'accounts': accounts, 'generated_at': now(),
                'sources': [{'name': '이 미니의 발행 장부', 'status': 'ok', 'checked_at': now()}],
                'weekly': self.weekly(records, accounts, week), 'query_range': {'start': None, 'end': None}}

    @staticmethod
    def weekly(records, accounts, week):
        from current_sns_weekly import build
        try:
            return build(records, accounts, [], now=datetime.now(timezone.utc), week=week,
                         notes=('이 미니의 게시 장부입니다. 정기 콘텐츠 일정 연결 여부는 행별로 표시합니다.',))
        except (TypeError, ValueError):
            raise WorkspaceError('조회할 주를 확인하세요.') from None

    def vault(self):
        groups = {}
        listing = self.work.documents()
        for d in listing['documents']:
            parent = str(Path(d['path']).parent)
            names = {'workspace': '업무 기록', 'company': '회사 자료', 'research': '리서치',
                     'knowledge': '지식 훔치기', 'sns': 'SNS 운영', 'journal': '업무 일지',
                     'lessons': '배운 점', 'inbox': '받은 자료', 'vault': '서류함'}
            group_key = parent.split('/')[1] if '/' in parent else 'company'
            group = names.get(group_key, group_key)
            row = groups.setdefault(parent, {'rel': parent, 'base': 'box', 'group': group,
                                            'name': names.get(Path(parent).name, Path(parent).name), 'label': '회사 기록',
                                            'rule': '수정하면 원본과 연결된 새 기록을 만듭니다.',
                                            'writable': True, 'readers': [], 'n': 0, 'files': []})
            row['files'].append({'name': d['title'], 'id': d['id'], 'type': '기타'})
            row['n'] += 1
        return {'vault': list(groups.values()), 'vault_ok': True, 'limited': listing.get('limited', False)}

    def readiness(self):
        health = {(a['platform'], a['account']): a for a in self.health.snapshot()['accounts']}
        internal = {(a['platform'], a['username']): a for a in self.internal()['accounts']}
        operations = self.operations()
        rows = []
        for row in operations['accounts']:
            key = (row['platform'], row['account'])
            native, browser = internal.get(key), health.get(key)
            state, checked, detail = 'unknown', '', '인증·발행 권한을 아직 확인하지 않았습니다.'
            if native:
                state = 'error' if native['state'] in ('expired', 'missing') else 'warning' if native['state'] == 'stale' else 'ok' if native['health'] == 'ok' else 'unknown'
                checked = native['checked_at']
                detail = '이 미니에 저장한 계정의 마지막 인증 결과입니다.'
            elif browser:
                state, checked, detail = browser['state'], browser['checked_at'], browser['label']
            checks = [{'name':'계정 연결','state':state,'detail':detail}]
            if not native:
                checks.append({'name':'글쓰기 권한','state':'ok' if browser and browser['publish_access']=='confirmed' else 'unknown',
                               'detail':'로그인 확인과 글쓰기 권한은 별도로 확인합니다.'})
            if any(c['state']=='unknown' for c in checks) and state=='ok': state='unknown'
            published = [p['published_at'] for p in operations['records'] if (p['platform'],p['account'])==key and p['status']=='published']
            rows.append({**row,'state':state,'checked_at':checked,'checks':checks,'last_published_at':max(published,default='')})
        checked = max((r['checked_at'] or '' for r in rows),default='')
        return {'accounts':rows,'checked_at':checked,'stale':False,'message':'저장된 인증 결과와 최근 브라우저 관측 기준입니다.'}

    def reject(self, key, revision, note):
        note = text(note, 3000, '반려 사유') if note else ''
        with self.work.lock:
            post = self.work.post(key)
            if post['status'] == 'rejected':
                raise WorkspaceError('이미 반려한 게시물입니다. 다시 조회하세요.', 409)
            self.work.post_action(key, 'reject', {'revision':revision})
            with self.work.transaction():
                self.work.db.execute('INSERT INTO post_feedback VALUES(?,?,?,?)',(key,revision,note,now()))
            result = {'ok':True,'redraft':{'ok':False,'reason':'반려 상태와 사유를 기록했습니다.'}}
            if not note: return result
            # 생성된 이전 초안은 다시 입력하지 않는다. 저장된 사람의 요청만 찾는다.
            original = ''
            for row in self.work.db.execute("SELECT args,result FROM jobs WHERE kind='draft' AND status='done' ORDER BY created_at DESC"):
                if json.loads(row['result'] or '{}').get('post_id') == key:
                    original = json.loads(row['args']).get('brief','')
                    break
            brief = ('원래 요청:\n' + original[:900] + '\n\n' if original else '') + '수정 요청:\n' + note
            try:
                queued = self.work.queue('draft', {'account_id':post['account_id'],'brief':brief})
                result['redraft'].update(job_id=queued['id'],queued=True,reason='사유를 저장하고 재작성을 요청했습니다. 새 초안은 완료 후 승인 대기에 표시됩니다.')
            except WorkspaceError:
                result['redraft']['reason'] = '사유는 저장했지만 재작성 요청을 등록하지 못했습니다. 업무 대기열과 실행 설정을 확인하세요.'
            return result

    def dispatch(self, method, path, query='', data=None):
        data = data or {}
        if path.startswith('/api/motion/'):
            from motion_pack import status,asset
            if method=='GET' and path=='/api/motion/status':
                result=status(self.work.home)
                with self.work.lock:
                    rows=self.work.db.execute("SELECT id FROM jobs WHERE kind LIKE 'motion_%' ORDER BY created_at DESC LIMIT 10").fetchall()
                result['jobs']=[self.work.job(row['id']) for row in rows]
                return result
            if method=='GET' and '/jobs/' in path:
                row=self.work.job(path.rsplit('/',1)[1])
                if not row['kind'].startswith('motion_'): raise WorkspaceError('영상 작업을 찾을 수 없습니다.',404)
                return row
            if method=='GET' and path.endswith('/preview'):
                return {'html':asset(self.work.home,path.split('/')[-2],'preview.html').decode()}
            if method=='POST' and path in ('/api/motion/install','/api/motion/create','/api/motion/render'):
                return self.work.queue('motion_'+path.rsplit('/',1)[1],data)
            raise WorkspaceError('영상 요청을 찾을 수 없습니다.',404)
        if method == 'GET':
            if path == '/api/research-capabilities':
                from research.settings import load as llm_settings
                from research.image_input import available
                from research.image_normalize import heif_available
                return {'mode': 'internal', 'async': True, 'stream': False,
                        'provider': 'auto', 'llm': llm_settings(self.work.home), 'image_input': available(), 'heic_input': heif_available(), 'knowledge': bool(shutil.which('aside'))}
            if path.startswith('/api/research/jobs/'):
                row = self.work.job(path.rsplit('/', 1)[1])
                if row['kind'] != 'research':
                    raise WorkspaceError('조사 요청을 찾을 수 없습니다.', 404)
                return {'id': row['id'], 'stage': 'error' if row['status'] == 'failed' else row['stage'],
                        'result': row['result'] if row['status'] == 'done' else None,
                        'partial_answer': row['result'] if row['status'] == 'running' else None, 'error': row['error']}
            if path == '/api/sns-operations':
                return self.operations(parse_qs(query).get('week', [None])[0])
            if path == '/api/sns-internal':
                return self.internal()
            if path == '/api/sns-browser':
                return self.health.snapshot()
            if path == '/api/sns-readiness':
                return self.readiness()
            if path == '/api/sns-naver':
                return {'state':'unknown','message':'이 미니의 네이버 전용 브라우저 연결이 필요합니다.'}
            if path == '/api/current/vault':
                return self.vault()
        if method == 'POST':
            if path == '/api/research/image':
                from research.image_normalize import normalize
                return {'image':normalize(data)}
            if path == '/api/sns-browser/check':
                return self.health.request(data)
            if path in ('/api/knowledge/collect', '/api/knowledge/learn'):
                self.work.sandbox()
                if not self.knowledge_lock.acquire(blocking=False):
                    raise WorkspaceError('자료 수집·분석이 진행 중입니다. 완료 후 다시 요청하세요.', 409)
                try:
                    if path.endswith('/collect'):
                        from research.collect_aside import source_target
                        _, url = source_target(data.get('url'))
                        limit = data.get('limit', 5)
                        if type(limit) is not int or not 1 <= limit <= 10:
                            raise WorkspaceError('수집 범위는 1~10건입니다.')
                        return self.work.providers.collect(self.work.home, {'url': url, 'limit': limit})
                    from research.knowledge import validate_bundle, skill_markdown
                    bundle = data.get('bundle')
                    validate_bundle(bundle)
                    goal = text(data.get('goal'), 400, '배울 업무')
                    result = self.work.providers.learn(self.work.home, {'bundle': bundle, 'goal': goal})
                    document = self.work.save_document({'title': goal, 'category': 'knowledge',
                                                        'content': skill_markdown(result)})
                    result['document_id'] = document['id']
                    return result
                finally:
                    self.knowledge_lock.release()
            if path == '/api/research/jobs':
                options = data.get('options', {})
                return self.work.queue('research', dict(data, mode=options.get('mode', 'quick'),
                                                       context=options.get('context', []), videos=options.get('videos', False), image=options.get('image')))
            if path == '/api/sns-internal/account':
                return self.save_account(data)
            if path in ('/api/approve', '/api/reject'):
                match = re.fullmatch(r'([a-f0-9]{32}):([1-9][0-9]*)', str(data.get('mid', '')))
                if not match:
                    raise WorkspaceError('검토한 게시물 버전을 확인하세요.', 409)
                key, revision = match.groups()
                if path == '/api/reject':
                    return self.reject(key, int(revision), data.get('note', ''))
                payload = {'revision': int(revision)}
                if path == '/api/approve' and not data.get('immediate'):
                    scheduled = self.work.post(key)['scheduled_at']
                    if not scheduled:
                        raise WorkspaceError('예약 시각을 먼저 지정하거나 지금 발행을 선택하세요.')
                    payload['scheduled_at'] = scheduled
                self.work.post_action(key, 'approve' if path == '/api/approve' else 'reject', payload)
                return {'ok': True, 'when': payload.get('scheduled_at')}
            if path == '/api/current/document':
                return self.work.document(text(data.get('id'), 32, '서류'))
            if path == '/api/sns-internal/connect':
                return self.oauth.start(data)
        raise WorkspaceError('지원하지 않는 업무 요청입니다.', 404)
