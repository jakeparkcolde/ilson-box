"""미니에 등록한 SNS만 관측한다. 로그인 관측은 발행 권한이나 성공을 대신하지 않는다."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from mini_workspace import WorkspaceError, now

LABELS = {'ok':'로그인 정상', 'login_required':'재로그인 필요',
          'account_mismatch':'다른 계정으로 로그인됨', 'unknown':'확인 불가'}
PLATFORMS = {'x', 'qiita', 'zenn', 'linkedin'}


def target(platform, account):
    if platform == 'linkedin':
        if not re.fullmatch(r'company/[0-9]{1,30}', account):
            raise WorkspaceError('LinkedIn 회사 계정은 company/회사번호 형식으로 등록하세요.')
        url = 'https://www.linkedin.com/' + account + '/admin/feed/posts?share=true'
    elif platform in {'x','qiita','zenn'}:
        if not re.fullmatch(r'[A-Za-z0-9_\-]{1,80}', account):
            raise WorkspaceError('SNS 사용자 이름을 확인하세요.')
        url = {'x':'https://x.com/home','qiita':'https://qiita.com','zenn':'https://zenn.dev'}[platform]
    else:
        raise WorkspaceError('해당 SNS의 전용 연결 경로에서 확인하세요.')
    return {'platform':platform,'account':account,'url':url}


def probe(platform, account):
    config = target(platform, account)
    executable = shutil.which('aside')
    if not executable:
        return {'login_state':'unknown','publish_access':'unknown','reason':'브라우저 연결 도구를 설치해야 합니다.'}
    script = 'const C=' + json.dumps(config) + ';\n' + Path(__file__).with_name('current_browser_check.js').read_text()
    try:
        result = subprocess.run([executable, '--account', 'u0', 'repl', script],
                                text=True,capture_output=True,timeout=90)
        for line in reversed(result.stdout.splitlines()):
            if line.startswith('ILSON_HEALTH:'):
                data = json.loads(line.partition(':')[2])
                if data.get('login_state') in LABELS:
                    return {k:data.get(k) for k in ('login_state','publish_access')}
    except (OSError,ValueError,subprocess.TimeoutExpired):
        pass
    return {'login_state':'unknown','publish_access':'unknown','reason':'브라우저 점검을 완료하지 못했습니다.'}


class Health:
    def __init__(self, ui):
        self.ui, self.work = ui, ui.work
        with self.work.transaction():
            self.work.db.execute('CREATE TABLE IF NOT EXISTS browser_health(key TEXT PRIMARY KEY, value TEXT)')
            rows = self.work.db.execute('SELECT key,value FROM browser_health').fetchall()
            for row in rows:
                data = json.loads(row['value'])
                if data.get('checking'):
                    data.update(checking=False,login_state='unknown',reason='관리자 재시작으로 점검이 중단됐습니다.')
                    self.put(row['key'], data)

    def put(self, key, data):
        self.work.db.execute('INSERT OR REPLACE INTO browser_health VALUES(?,?)',(key,json.dumps(data,ensure_ascii=False)))

    def snapshot(self):
        with self.work.lock:
            raw = {r['key']:json.loads(r['value']) for r in self.work.db.execute('SELECT key,value FROM browser_health')}
        rows = []
        for key, meta in self.ui.registry().items():
            if meta['platform'] not in PLATFORMS or meta.get('management_status') == 'archived': continue
            got = raw.get(key, {})
            checked = got.get('checked_at', '')
            try: fresh = 0 <= self.work.clock() - datetime.fromisoformat(checked).timestamp() < 2700
            except (ValueError,TypeError): fresh = False
            code = got.get('login_state','unknown') if fresh else 'unknown'
            rows.append({'platform':meta['platform'],'account':meta['account'],'provider':'aside',
                         'login_state':code,'state':{'ok':'ok','login_required':'error','account_mismatch':'warning','unknown':'unknown'}[code],
                         'label':LABELS[code], 'checked_at':checked, 'stale':not fresh,
                         'checking':bool(got.get('checking')), 'reason':got.get('reason',''),
                         'publish_access':'confirmed' if fresh and code=='ok' and got.get('publish_access')=='confirmed' else 'unknown'})
        return {'accounts':rows,'interval_minutes':30}

    def request(self, data):
        self.work.sandbox()
        platform, account = data.get('platform'), data.get('account')
        target(platform, account)
        key = platform + ':' + account
        if key not in self.ui.registry(): raise WorkspaceError('등록한 계정만 확인할 수 있습니다.')
        with self.work.transaction():
            old = self.work.db.execute('SELECT value FROM browser_health WHERE key=?',(key,)).fetchone()
            got = json.loads(old['value']) if old else {}
            if got.get('checking'): return {'ok':True,'message':'이미 점검하고 있습니다.'}
            got.update(checking=True,checked_at=now(),login_state='unknown',publish_access='unknown')
            self.put(key,got)
        return {'ok':True,'message':'로그인 점검을 요청했습니다. 결과는 자동으로 갱신됩니다.'}

    def tick(self):
        if self.work.files.marker('state/sandbox') is not False: return
        for row in self.snapshot()['accounts']:
            if self.work.stop_event.is_set(): return
            try: due = self.work.clock() - datetime.fromisoformat(row['checked_at']).timestamp() >= 1800
            except (ValueError,TypeError): due = True
            if not row['checking'] and not due: continue
            key = row['platform'] + ':' + row['account']
            with self.work.transaction():
                self.put(key,dict(row,checking=True))
            # 시험용 공급자는 브라우저를 열지 않는다. 실제 공급자만 read-only 관측을 수행한다.
            result = {'login_state':'unknown','publish_access':'unknown'}
            try:
                callback = getattr(self.work.providers,'browser_health',None)
                if callback: result = callback(row['platform'],row['account'])
            except Exception:
                result['reason'] = '브라우저 점검을 완료하지 못했습니다.'
            if result.get('login_state') not in LABELS: result['login_state'] = 'unknown'
            with self.work.transaction():
                self.put(key,{**result,'checked_at':now(),'checking':False})
