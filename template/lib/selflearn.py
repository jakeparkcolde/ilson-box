"""Local, consent-based recurring-work proposals and lessons for Ilson Box."""
import argparse
import base64
import contextlib
import datetime as dt
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import unicodedata
import uuid

LIMIT = 24000
KINDS = {'document', 'research', 'summary'}
OUTPUTS = {'report', 'checklist', 'draft'}
WORKFLOWS = {'organize', 'verify', 'summarize'}
PROVIDERS = {'claude', 'codex', 'manual'}
LESSONS = {
    ('correction', 'unsupported_claim', 'check_evidence'): '주장을 작성할 때 근거를 확인하고 근거가 없으면 확인 필요로 표시합니다.',
    ('failure', 'missing_input', 'ask_before_work'): '필수 입력이 부족하면 추측하지 말고 확인한 뒤 작업합니다.',
    ('success', 'source_check', 'keep_sources'): '검증한 출처와 확인 날짜를 결과에 남깁니다.',
}
SENSITIVE = [
    re.compile(r'(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b'),
    re.compile(r'(?<!\d)(?:\+?82[ -]?)?0?1[016789][ .-]?\d{3,4}[ .-]?\d{4}(?!\d)'),
    re.compile(r'(?<!\d)\d{6}[ -]?[1-8]\d{6}(?!\d)'),
    re.compile(r'(?<!\d)(?:\d[ -]?){10,20}(?!\d)'),
    re.compile(r'(?i)(?:password|passwd|secret|api[ _-]?key|access[ _-]?token|비밀번호|주민등록번호|계좌번호|인증키)\s*[:=]\s*\S+'),
    re.compile(r'(?i)\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b'),
    re.compile(r'\b\d{5,15}:[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'\b\d{3}-\d{2}-\d{5}\b'),
    re.compile(r'(?i)/Users/[a-z0-9._-]+|/home/[a-z][a-z0-9_-]+|/Vol' + r'umes/[^\s]+'),
    re.compile(r'(?<![0-9.])(?:192\.168|10\.[0-9]{1,3}|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}(?!\.?[0-9])'),
    re.compile(r'(?i)\b(?:AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|(?:hf|npm|sbp|ntn|vercel)_[A-Za-z0-9]{20,})\b'),
    re.compile(r'(?i)\b(?:whsec_[A-Za-z0-9+/=_-]{16,}|GOCSPX-[A-Za-z0-9_-]{16,}|ya29\.[A-Za-z0-9_.-]{20,})\b'),
    re.compile(r'(?i)\b(?:[sr]k_live_[A-Za-z0-9]{16,}|pdl_live_[A-Za-z0-9_]{16,}|sb_secret_[A-Za-z0-9_-]{16,})\b'),
    re.compile(r'(?i)\b(?:bearer\s+[A-Za-z0-9._~+/=-]{20,}|eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.)'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}'),
    re.compile(r'(?i)aws_secret_access_key["\']?\s*[:=]\s*["\']?[A-Za-z0-9/+=]{20,}'),
    re.compile(r'\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD)\s*=\s*[A-Za-z0-9_\-/+=.]{16,}'),
    re.compile(r'(?i)(?:\.ts\.net\b|\btail(?=[0-9a-f]*[0-9])[0-9a-f]{4,}\b|\bmac-?(?:mini|studio)\b|[a-z0-9]{20}\.supabase\.co)'),
    re.compile(r'(?i)(?<![0-9.])100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}(?!\.?[0-9])|fd7a:115c:' + r'a1e0:'),
]
UNSAFE = re.compile(r'(?im)(```|~~~|<\s*(?:script|iframe|object)|https?://|\b(?:curl|wget|sudo|chmod|chown|eval|exec|bash|zsh|python3?)\b|\$\(|\b(?:hooks?|mcpServers)\s*:)')
PRIVILEGE = re.compile(r'(?i)(?:승인|허락|확인|보안|권한|검사).{0,20}(?:없이|생략|우회|무시|해제|불필요)|(?:bypass|disable|skip|ignore).{0,30}(?:approval|security|permission|verification|instruction|policy)|(?:이전|기존|시스템).{0,15}(?:지침|규칙|명령).{0,15}(?:무시|잊어|무효)')
SECTIONS = ('언제', '입력', '순서', '기준', '결과', '확인', '중단')

class Problem(Exception):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None

def ident(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Problem('식별자를 확인하세요') from None

def clean_text(text, maximum, *, name=False):
    if not isinstance(text, str) or not text.strip() or len(text) > maximum or (maximum == LIMIT and len(text.encode('utf-8')) > LIMIT) or '\x00' in text:
        raise Problem('입력의 길이 또는 형식을 확인하세요')
    # Calendar dates are not bank accounts. Do not include them in digit scans.
    checked = re.sub(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', '', text)
    if any(pattern.search(checked) for pattern in SENSITIVE):
        raise Problem('개인정보 또는 비밀값 패턴이 발견되어 저장하지 않았습니다')
    if name and ('\n' in text or '/' in text or '\\' in text):
        raise Problem('업무 이름을 한 줄의 일반적인 이름으로 입력하세요')
    if not name and (UNSAFE.search(text) or PRIVILEGE.search(text)):
        raise Problem('명령·코드·외부 연결이 포함되어 저장하지 않았습니다')
    return text.strip()

def normalized(name):
    return ''.join(c for c in unicodedata.normalize('NFKC', name).casefold() if c.isalnum())

def similar(a, b):
    a, b = normalized(a), normalized(b)
    return bool(a and b and difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= .85)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def stamp():
    return str(uuid.uuid4())

def encode(data):
    return None if data is None else base64.b64encode(data).decode('ascii')

def decode(data):
    return None if data is None else base64.b64decode(data, validate=True)

def blank():
    return {'version': 1, 'enabled': False, 'events': [], 'lessons': [], 'proposals': [], 'history': []}

def transaction_path(path):
    return (path in ('vault/.ilson-learning/state.json', 'vault/.ilson-learning/approved-skills.json',
                     'vault/lessons/approved-learning.md')
            or re.fullmatch(r'vault/\.ilson-learning/rollback/[0-9a-f-]{36}\.md', path) is not None
            or re.fullmatch(r'\.claude/skills/ilson-learned-[0-9a-f-]{36}/SKILL\.md', path) is not None)

class Store:
    def __init__(self, home):
        self.home = Path(home).absolute()
        if not self.home.is_dir() or self.home.is_symlink():
            raise Problem('Box 폴더를 확인하세요')
        self.base = self.home / 'vault/.ilson-learning'
        self.check(self.base, parents=True)
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.check(self.base)
        self.state_path = self.base / 'state.json'
        self.journal = self.base / 'transaction.json'

    def check(self, path, parents=False):
        path = Path(path)
        try:
            rel = path.relative_to(self.home)
        except ValueError:
            raise Problem('Box 밖 경로는 허용되지 않습니다') from None
        current = self.home
        for part in rel.parts:
            if part in ('', '.', '..'):
                raise Problem('잘못된 경로입니다')
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
                raise Problem('소유자 또는 연결 경로를 확인하세요')
            if current != path and not stat.S_ISDIR(info.st_mode):
                raise Problem('상위 폴더를 확인하세요')
        if path.exists() and not (path.is_file() or path.is_dir()):
            raise Problem('일반 파일 또는 폴더가 아닙니다')

    def read(self, path):
        self.check(path)
        try:
            if path.is_dir():
                raise Problem('파일 위치에 폴더가 있습니다')
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def write(self, path, body):
        self.check(path, parents=True)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.check(path)
        fd, temp = tempfile.mkstemp(prefix='.ilson-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            self.check(path)
            os.replace(temp, path)
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    @contextlib.contextmanager
    def locked(self):
        lock = self.base / 'lock'
        self.check(lock)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.recover()
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self):
        raw = self.read(self.state_path)
        if raw is None:
            return blank()
        state = json.loads(raw)
        if state.get('version') != 1:
            raise Problem('학습 기록 버전을 확인하세요')
        return state

    def dump(self, data):
        return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()

    def save(self, state):
        self.write(self.state_path, self.dump(state))

    def recover(self):
        raw = self.read(self.journal)
        if not raw:
            return
        journal = json.loads(raw)
        if journal.get('status') != 'pending':
            return
        changes = journal['changes']
        for change in changes:
            if not transaction_path(change['path']):
                raise Problem('중단된 변경의 대상 경로를 확인하세요')
            path = self.home / change['path']
            actual = digest(self.read(path))
            if actual not in (change['before_hash'], change['after_hash']):
                raise Problem('중단된 변경에 사용자 수정이 있어 복구를 멈췄습니다')
        # The journal is durable evidence of a previously confirmed transaction.
        # Finish it only if every touched file still has a known version.
        for change in changes:
            path = self.home / change['path']
            after = decode(change['after'])
            if digest(self.read(path)) != change['after_hash']:
                if after is None:
                    # This is only used after an approved, hash-checked rollback;
                    # the transaction also preserves the bytes in the vault.
                    self.check(path)
                    path.unlink()
                else:
                    self.write(path, after)
        self.write(self.journal, self.dump({'status': 'complete', 'id': journal['id']}))

    def transact(self, changes):
        rows = []
        for path, before, after in changes:
            self.check(path)
            if not transaction_path(path.relative_to(self.home).as_posix()):
                raise Problem('변경 대상 경로를 확인하세요')
            if self.read(path) != before:
                raise Problem('파일이 변경되어 적용을 중단했습니다')
            rows.append({'path': path.relative_to(self.home).as_posix(), 'before_hash': digest(before),
                         'after_hash': digest(after), 'after': encode(after)})
        self.write(self.journal, self.dump({'status': 'pending', 'id': stamp(), 'changes': rows}))
        self.recover()

    def enabled(self, state):
        if not state['enabled']:
            raise Problem('수집이 꺼져 있습니다. 사람이 ilson learn enable을 실행해야 합니다')

    def event(self, state, data):
        self.enabled(state)
        required = {'task_id', 'provider', 'kind', 'output', 'workflow', 'name'}
        if set(data) != required:
            raise Problem('기록 항목을 확인하세요')
        task = ident(data['task_id'])
        if data['provider'] not in PROVIDERS or data['kind'] not in KINDS or data['output'] not in OUTPUTS or data['workflow'] not in WORKFLOWS:
            raise Problem('지원하는 업무 분류를 선택하세요')
        name = clean_text(data['name'], 40, name=True)
        previous = next((e for e in state['events'] if e['task_id'] == task), None)
        if previous:
            return {'status': 'duplicate', 'event_id': previous['id']}
        if len(state['events']) >= 10000:
            raise Problem('기록 한도에 도달했습니다')
        event = {'id': stamp(), 'task_id': task, 'at': now(), 'provider': data['provider'],
                 'kind': data['kind'], 'output': data['output'], 'workflow': data['workflow'], 'name': name}
        comparable = [x for x in state['events'] if all(x[k] == event[k] for k in ('kind', 'output', 'workflow')) and similar(x['name'], name)]
        state['events'].append(event)
        result = {'status': 'recorded', 'event_id': event['id']}
        if comparable:
            older = comparable[-1]
            suppressed = any(
                p['type'] == 'skill' and p['status'] in ('pending', 'rejected', 'approved')
                and all(p['classification'][k] == event[k] for k in ('kind', 'output', 'workflow'))
                and (normalized(p['name']) in (normalized(event['name']), normalized(older['name']))
                     or (p['status'] != 'rejected' and (similar(p['name'], event['name']) or similar(p['name'], older['name']))))
                for p in state['proposals'])
            if not suppressed:
                result['match'] = older['id']
                result['message'] = '비슷한 업무가 두 번입니다. 이 작업을 스킬로 만들까요? 초안을 검토하세요.'
        self.save(state)
        return result

    def pair(self, state, first, second, confirmed=False):
        first, second = ident(first), ident(second)
        if first == second:
            raise Problem('서로 다른 업무 두 건을 선택하세요')
        events = {e['id']: e for e in state['events']}
        if first not in events or second not in events:
            raise Problem('업무 기록을 찾을 수 없습니다')
        a, b = events[first], events[second]
        confirmed = confirmed or b['id'] in a.get('confirmed_matches', []) or a['id'] in b.get('confirmed_matches', [])
        if not confirmed and any(a[k] != b[k] for k in ('kind', 'output', 'workflow')):
            raise Problem('업무 분류가 다릅니다. 사람이 동일 업무인지 직접 확인하세요')
        if not confirmed and not similar(a['name'], b['name']):
            raise Problem('업무 이름이 다릅니다. 사람이 동일 업무인지 직접 확인하세요')
        return a, b

    def draft(self, state, data, confirmed=False):
        self.enabled(state)
        if not {'first', 'second'} <= set(data) or set(data) - {'first', 'second', 'body'}:
            raise Problem('초안 입력 항목을 확인하세요')
        a, b = self.pair(state, data['first'], data['second'], confirmed)
        fallback = ('## 언제\n같은 업무를 요청받았을 때 사용합니다.\n\n## 입력\n필요한 자료를 확인합니다.\n\n'
                    '## 순서\n요청을 확인하고 자료를 정리합니다.\n\n## 기준\n정확성과 근거를 확인합니다.\n\n'
                    '## 결과\n요청한 결과물을 만듭니다.\n\n## 확인\n사람이 결과를 검토합니다.\n\n'
                    '## 중단\n필수 자료가 부족하면 확인을 요청합니다.')
        body = clean_text(data.get('body') or fallback, LIMIT)
        if any(not re.search(r'(?m)^#{1,3}\s*[^\n]*' + word, body) for word in SECTIONS):
            raise Problem('초안에 언제·입력·순서·기준·결과·확인·중단 항목이 필요합니다')
        for p in state['proposals']:
            if p['type'] == 'skill' and p['status'] in ('pending', 'rejected', 'approved') and all(p['classification'][k] == b[k] for k in ('kind', 'output', 'workflow')):
                same_key = normalized(p['name']) in (normalized(a['name']), normalized(b['name']))
                if same_key or (p['status'] != 'rejected' and (similar(p['name'], a['name']) or similar(p['name'], b['name']))):
                    raise Problem('이미 제안했거나 거절한 업무입니다')
        if sum(p['status'] == 'pending' for p in state['proposals']) >= 200:
            raise Problem('검토 대기 제안 한도에 도달했습니다')
        key = stamp()
        skill_name = 'ilson-learned-' + key
        description = clean_text(b['name'], 40, name=True).replace('"', '')
        content = f'---\nname: {skill_name}\ndescription: "{description} 업무에 사용합니다."\n---\n\n{body}\n'
        if len(content.encode('utf-8')) > LIMIT:
            raise Problem('스킬 초안이 너무 깁니다')
        path = '.claude/skills/' + skill_name + '/SKILL.md'
        proposal = {'id': key, 'type': 'skill', 'status': 'pending', 'at': now(), 'name': b['name'],
                    'classification': {k: b[k] for k in ('kind', 'output', 'workflow')},
                    'events': [a['id'], b['id']], 'path': path, 'before_hash': None, 'content': content}
        state['proposals'].append(proposal)
        self.save(state)
        return {'status': 'pending', 'id': key, 'path': path}

    def lesson(self, state, data):
        self.enabled(state)
        if not {'kind', 'issue', 'action'} <= set(data) or set(data) - {'kind', 'issue', 'action', 'rule'} or tuple(data.get(k) for k in ('kind', 'issue', 'action')) not in LESSONS:
            raise Problem('지원하는 배운 점 분류를 선택하세요')
        if len(state['lessons']) >= 10000:
            raise Problem('기록 한도에 도달했습니다')
        rule = data.get('rule')
        if rule:
            rule = clean_text(rule, 160)
            if '\n' in rule or len([x for x in re.split(r'(?<=[.!?。])\s*', rule) if x.strip()]) > 2:
                raise Problem('배운 점은 한 줄의 1~2문장으로 입력하세요')
        else:
            rule = LESSONS[tuple(data[k] for k in ('kind', 'issue', 'action'))]
        row = {'id': stamp(), 'at': now(), 'kind': data['kind'], 'issue': data['issue'], 'action': data['action'], 'rule': rule}
        state['lessons'].append(row)
        self.save(state)
        return {'status': 'recorded', 'id': row['id']}

    def review(self, state):
        self.enabled(state)
        path = self.home / 'vault/lessons/approved-learning.md'
        before = self.read(path)
        old = before.decode('utf-8') if before is not None else '# 승인한 배운 점\n'
        count = 0
        for lesson in state['lessons']:
            rule = lesson['rule']
            if rule in old or any(p['type'] == 'lesson' and p['rule'] == rule for p in state['proposals']):
                continue
            if sum(p['status'] == 'pending' for p in state['proposals']) >= 200:
                raise Problem('검토 대기 제안 한도에 도달했습니다')
            content = old.rstrip() + '\n\n- ' + rule + '\n'
            clean_text(content, LIMIT)
            pid = stamp()
            state['proposals'].append({'id': pid, 'type': 'lesson', 'status': 'pending', 'at': now(),
                'path': 'vault/lessons/approved-learning.md', 'before_hash': digest(before), 'content': content,
                'diff': ''.join(difflib.unified_diff((before or b'').decode().splitlines(True), content.splitlines(True), fromfile='현재', tofile='제안')),
                'rule': rule, 'lesson_id': lesson['id']})
            count += 1
        self.save(state)
        return {'created': count}

    def proposal(self, state, proposal_id):
        key = ident(proposal_id)
        p = next((p for p in state['proposals'] if p['id'] == key), None)
        if p is None:
            raise Problem('제안을 찾을 수 없습니다')
        return p

    def refresh_lesson(self, state, p):
        if p['status'] != 'pending' or p['type'] != 'lesson' or p['path'] != 'vault/lessons/approved-learning.md':
            raise Problem('대기 중인 배운 점 제안만 다시 만들 수 있습니다')
        clean_text(p['rule'], 160)
        before = self.read(self.home / p['path'])
        old = before.decode('utf-8') if before is not None else '# 승인한 배운 점\n'
        if p['rule'] in old:
            raise Problem('이미 기준에 반영되어 있습니다')
        content = clean_text(old.rstrip() + '\n\n- ' + p['rule'] + '\n', LIMIT) + '\n'
        p['before_hash'] = digest(before)
        p['content'] = content
        p['diff'] = ''.join(difflib.unified_diff((before or b'').decode().splitlines(True), content.splitlines(True), fromfile='현재', tofile='제안'))
        self.save(state)
        return {'status': 'pending', 'id': p['id'], 'diff': p['diff']}

    def approve(self, state, p):
        if p['status'] != 'pending':
            raise Problem('검토 대기 제안이 아닙니다')
        if p['type'] == 'lesson':
            if p['path'] != 'vault/lessons/approved-learning.md':
                raise Problem('배운 점의 대상 경로를 확인하세요')
        elif p['type'] == 'skill':
            if p['path'] != '.claude/skills/ilson-learned-' + ident(p['id']) + '/SKILL.md':
                raise Problem('스킬의 대상 경로를 확인하세요')
        else:
            raise Problem('제안 종류를 확인하세요')
        path = self.home / p['path']
        before = self.read(path)
        if digest(before) != p['before_hash']:
            raise Problem('사용자가 파일을 수정했거나 대상이 이미 있어 변경하지 않았습니다. 배운 점은 ilson learn refresh <ID>로 재검토하세요')
        if p['type'] == 'skill':
            skill_name = 'ilson-learned-' + ident(p['id'])
            description = clean_text(p['name'], 40, name=True).replace('"', '')
            header = f'---\nname: {skill_name}\ndescription: "{description} 업무에 사용합니다."\n---\n\n'
            if p['path'] != '.claude/skills/' + skill_name + '/SKILL.md' or not p['content'].startswith(header):
                raise Problem('스킬 초안이 변경되어 승인할 수 없습니다')
            body = clean_text(p['content'][len(header):], LIMIT)
            if any(not re.search(r'(?m)^#{1,3}\s*[^\n]*' + word, body) for word in SECTIONS):
                raise Problem('스킬 초안의 필수 항목을 확인하세요')
            content = (header + body + '\n').encode()
            if len(content) > LIMIT:
                raise Problem('스킬 초안이 너무 깁니다')
        else:
            rule = clean_text(p['rule'], 160)
            old = before.decode('utf-8') if before is not None else '# 승인한 배운 점\n'
            expected = old.rstrip() + '\n\n- ' + rule + '\n'
            if p['content'].strip() != expected.strip():
                raise Problem('배운 점 변경안이 달라져 승인할 수 없습니다')
            content = clean_text(expected, LIMIT).encode() + b'\n'
        changes = [(path, before, content)]
        registry = self.base / 'approved-skills.json'
        registry_before = self.read(registry)
        if p['type'] == 'skill':
            entries = json.loads(registry_before) if registry_before else []
            entries.append({'id': p['id'], 'path': p['path'], 'sha256': digest(content), 'name': p['name']})
            changes.append((registry, registry_before, self.dump(entries)))
        p['status'] = 'approved'
        history = {'id': stamp(), 'proposal_id': p['id'], 'at': now(), 'type': p['type'], 'path': p['path'],
                   'before': encode(before), 'before_hash': digest(before), 'after_hash': digest(content), 'status': 'applied'}
        state['history'].append(history)
        changes.append((self.state_path, self.read(self.state_path), self.dump(state)))
        self.transact(changes)
        return history

    def rollback(self, state, change_id):
        key = ident(change_id)
        h = next((h for h in state['history'] if h['id'] == key), None)
        if not h or h['status'] != 'applied':
            raise Problem('복구할 변경을 찾을 수 없습니다')
        expected = ('vault/lessons/approved-learning.md' if h['type'] == 'lesson' else
                    '.claude/skills/ilson-learned-' + ident(h['proposal_id']) + '/SKILL.md')
        if h['type'] not in ('lesson', 'skill') or h['path'] != expected:
            raise Problem('복구할 대상 경로를 확인하세요')
        path = self.home / h['path']
        current = self.read(path)
        if digest(current) != h['after_hash']:
            raise Problem('이후에 수정된 파일이라 복구하지 않았습니다')
        before = decode(h['before'])
        changes = []
        if before is None:
            archive = self.base / 'rollback' / (h['id'] + '.md')
            if self.read(archive) is not None:
                raise Problem('복구 보관 파일이 이미 있습니다')
            changes.extend([(archive, None, current), (path, current, None)])
        else:
            changes.append((path, current, before))
        if h['type'] == 'skill':
            registry = self.base / 'approved-skills.json'
            registry_before = self.read(registry)
            entries = json.loads(registry_before) if registry_before else []
            entry = next((e for e in entries if e['id'] == h['proposal_id']), None)
            if not entry or entry['sha256'] != h['after_hash']:
                raise Problem('스킬 목록이 변경되어 복구하지 않았습니다')
            changes.append((registry, registry_before, self.dump([e for e in entries if e['id'] != h['proposal_id']])))
        h['status'] = 'rolled_back'
        h['rolled_back_at'] = now()
        changes.append((self.state_path, self.read(self.state_path), self.dump(state)))
        self.transact(changes)
        return h

def require_human(prompt):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Problem('이 동작은 사람이 일반 터미널에서 직접 확인해야 합니다')
    print(prompt)
    if input('계속하려면 확인 이라고 입력하세요: ').strip() != '확인':
        raise Problem('취소했습니다')

def stdin_json():
    raw = sys.stdin.buffer.read(100000)
    if len(raw) >= 100000:
        raise Problem('입력이 너무 깁니다')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise Problem('입력 형식을 확인하세요')
    return data

def manual_event():
    print('업무 이름에 고객·회사·사람 이름이나 연락처를 넣지 마세요.')
    name = input('업무 이름(40자 이하): ')
    kind = input('업무 종류 (document/research/summary): ').strip()
    output = input('결과 종류 (report/checklist/draft): ').strip()
    workflow = input('방법 (organize/verify/summarize): ').strip()
    return {'task_id': stamp(), 'provider': 'manual', 'kind': kind, 'output': output,
            'workflow': workflow, 'name': name}

def main():
    parser = argparse.ArgumentParser(description='반복 업무 제안과 승인형 학습')
    parser.add_argument('--home', required=True)
    parser.add_argument('command', choices=['status', 'enable', 'disable', 'record', 'events', 'draft', 'lesson', 'review', 'proposals', 'show', 'approve', 'reject', 'reconsider', 'refresh', 'history', 'rollback', 'match', 'skills'])
    parser.add_argument('ids', nargs='*')
    args = parser.parse_args()
    store = Store(args.home)
    with store.locked():
        state = store.load()
        cmd = args.command
        if cmd == 'status':
            result = {'enabled': state['enabled'], 'pending': sum(p['status'] == 'pending' for p in state['proposals'])}
        elif cmd in ('enable', 'disable'):
            require_human('업무 이름·분류·제안은 이 Box의 vault와 로컬 Git 이력에 남을 수 있습니다. 대화는 외부 AI 공급자에게 처리될 수 있습니다.')
            state['enabled'] = cmd == 'enable'; store.save(state); result = {'enabled': state['enabled']}
        elif cmd == 'record': result = store.event(state, manual_event() if sys.stdin.isatty() else stdin_json())
        elif cmd == 'events': result = state['events']
        elif cmd == 'draft':
            if sys.stdin.isatty():
                if len(args.ids) != 2: raise Problem('기본 초안을 만들려면 업무 기록 ID 두 개가 필요합니다')
                data = {'first': args.ids[0], 'second': args.ids[1]}
            else:
                data = stdin_json()
            result = store.draft(state, data)
        elif cmd == 'lesson': result = store.lesson(state, stdin_json())
        elif cmd == 'review': result = store.review(state)
        elif cmd == 'proposals':
            result = [{**{k: p[k] for k in ('id', 'type', 'status', 'at')},
                       'title': p['name'] if p['type'] == 'skill' else p['rule']} for p in state['proposals']]
        elif cmd == 'history': result = [{k: h[k] for k in ('id', 'proposal_id', 'at', 'type', 'path', 'status')} for h in state['history']]
        elif cmd == 'skills':
            raw = store.read(store.base / 'approved-skills.json')
            entries = json.loads(raw) if raw else []
            result = []
            for entry in entries:
                if entry['path'] != '.claude/skills/ilson-learned-' + ident(entry['id']) + '/SKILL.md':
                    raise Problem('스킬 목록의 경로를 확인하세요')
                path = store.home / entry['path']
                result.append({'name': entry['name'], 'path': entry['path'],
                               'status': 'approved' if digest(store.read(path)) == entry['sha256'] else 'changed'})
        elif cmd == 'match':
            if len(args.ids) != 2: raise Problem('업무 기록 두 개가 필요합니다')
            a, b = store.pair(state, *args.ids, confirmed=True)
            require_human('두 업무가 같은 반복 업무인지 확인하세요: ' + a['name'] + ' / ' + b['name'])
            # A direct human match is retained on the events, not inferred by the AI.
            a.setdefault('confirmed_matches', [])
            if b['id'] not in a['confirmed_matches']: a['confirmed_matches'].append(b['id'])
            store.save(state); result = {'matched': [a['id'], b['id']]}
        else:
            if len(args.ids) != 1: raise Problem('식별자 하나가 필요합니다')
            if cmd == 'rollback':
                require_human('이 변경을 복구합니다. 현재 파일이 변경된 경우 중단합니다.')
                result = store.rollback(state, args.ids[0])
            else:
                p = store.proposal(state, args.ids[0])
                if cmd == 'show': result = p
                elif cmd == 'approve':
                    print(p.get('diff', p.get('content', '')))
                    require_human('위 내용을 승인하여 ' + p['path'] + '에 반영합니다.')
                    result = store.approve(state, p)
                elif cmd == 'reject':
                    require_human('이 제안을 거절하고 같은 제안을 자동으로 반복하지 않습니다.')
                    if p['status'] != 'pending': raise Problem('검토 대기 제안이 아닙니다')
                    p['status'] = 'rejected'; store.save(state); result = {'status': 'rejected'}
                elif cmd == 'reconsider':
                    require_human('거절한 제안을 다시 검토합니다.')
                    if p['status'] != 'rejected': raise Problem('거절된 제안이 아닙니다')
                    p['status'] = 'pending'; store.save(state); result = {'status': 'pending'}
                elif cmd == 'refresh':
                    require_human('현재 기준을 보존하며 변경안을 다시 만듭니다. 다시 살펴보고 별도로 승인해야 합니다.')
                    result = store.refresh_lesson(state, p)
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except (Problem, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as error:
        # Do not echo supplied text or paths; upstream exceptions can contain them.
        print(str(error) if isinstance(error, Problem) else '학습 기록을 처리하지 못했습니다. 입력과 Box 상태를 확인하세요.', file=sys.stderr)
        sys.exit(1)
