"""직원·조직·명시적으로 설치한 텍스트 스킬. 기존 업무 장부의 트랜잭션을 공유한다."""
import json
import re
from mini_workspace import WorkspaceError, identity, text

CATALOG = {
    'meeting-notes': {'name': '회의 정리', 'description': '회의 내용을 결정·담당·기한으로 정리합니다.',
                      'body': '제공된 회의 기록만 근거로 요약하세요. 결정 사항, 할 일, 담당자, 기한을 구분하세요. 명시되지 않은 담당자나 기한은 미정으로 표시하세요.'},
    'report-review': {'name': '보고서 점검', 'description': '근거와 미확인 내용을 구분합니다.',
                      'body': '핵심 결론을 먼저 쓰세요. 제공된 근거와 추정을 구분하고 빠진 정보와 다음 확인 사항을 적으세요. 수치·출처를 만들지 마세요.'},
}


def markdown(value):
    """단일 SKILL.md 텍스트만 수용한다. 확장 지시·쉘 치환·지원 파일은 실행하지 않는다."""
    value = text(value, 24000, '스킬 본문')
    if value.startswith('---\n') or value.startswith('---\r\n'):
        lines = value.splitlines()
        try:
            end = lines.index('---', 1)
        except ValueError:
            raise WorkspaceError('SKILL.md 머리말을 닫아주세요.') from None
        for line in lines[1:end]:
            if not re.fullmatch(r'(name|description):[^\r\n]*', line):
                raise WorkspaceError('머리말은 한 줄 name·description만 지원합니다. hooks·도구 설정은 가져오지 않습니다.')
        value = text('\n'.join(lines[end + 1:]), 24000, '스킬 본문')
    if '!`' in value:
        raise WorkspaceError('쉘 동적 치환은 지원하지 않습니다. 실행 결과 대신 순수 지침을 입력하세요.')
    return value


class People:
    def __init__(self, work):
        self.work, self.db = work, work.db
        # 기존 설치에도 가산 이행만 적용한다. 사용자 장부는 배포 자산 밖에 있다.
        with work.transaction():
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS people_departments(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS people_employees(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, department_id TEXT NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS people_skills(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL, body TEXT NOT NULL, active INTEGER NOT NULL, source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS people_assignments(employee_id TEXT NOT NULL, skill_id TEXT NOT NULL, PRIMARY KEY(employee_id,skill_id));
            ''')

    def row(self, table, key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):
            raise WorkspaceError('항목 식별자를 확인하세요.')
        row = self.db.execute('SELECT * FROM people_' + table + ' WHERE id=?', (key,)).fetchone()
        if row is None:
            raise WorkspaceError('항목이 없거나 삭제되었습니다. 목록을 새로 고쳐주세요.', 404)
        return dict(row)

    def state(self):
        with self.work.lock:
            result = {name: [dict(r) for r in self.db.execute('SELECT * FROM people_' + name + ' ORDER BY rowid')]
                      for name in ('departments', 'employees', 'skills', 'assignments')}
        result['catalog'] = [{'id': key, **value} for key, value in CATALOG.items()]
        return result

    def save(self, kind, data):
        if kind not in ('departments', 'employees', 'skills'):
            raise WorkspaceError('항목 종류를 확인하세요.')
        with self.work.transaction():
            key = data.get('id') or identity()
            if data.get('id'):
                self.row(kind, key)
            name = text(data.get('name'), 80, '이름')
            if kind in ('departments', 'skills') and self.db.execute(
                    'SELECT id FROM people_' + kind + ' WHERE name=? AND id!=?', (name, key)).fetchone():
                raise WorkspaceError('같은 이름이 이미 있습니다.', 409)
            active = data.get('active', True)
            if type(active) is not bool:
                raise WorkspaceError('활성 상태를 확인하세요.')
            if kind == 'departments':
                parent = data.get('parent_id', '')
                if not isinstance(parent, str):
                    raise WorkspaceError('상위 부서를 확인하세요.')
                visited = {key}
                cursor = parent
                while cursor:
                    if cursor in visited:
                        raise WorkspaceError('부서가 자신 또는 하위 부서에 속할 수 없습니다.')
                    visited.add(cursor)
                    cursor = self.row(kind, cursor)['parent_id']
                values = (key, name, parent)
            elif kind == 'employees':
                department = data.get('department_id', '')
                if department:
                    self.row('departments', department)
                if not isinstance(department, str):
                    raise WorkspaceError('부서를 확인하세요.')
                values = (key, name, text(data.get('role'), 2000, '역할'), department, int(active))
            else:
                values = (key, name, text(data.get('description'), 400, '설명'), markdown(data.get('body')), int(active), 'local')
            if self.db.execute('SELECT count(*) FROM people_' + kind).fetchone()[0] >= 200 and not data.get('id'):
                raise WorkspaceError('종류별 최대 200개까지 저장할 수 있습니다.', 409)
            columns = {'departments': ('name', 'parent_id'), 'employees': ('name', 'role', 'department_id', 'active'),
                       'skills': ('name', 'description', 'body', 'active', 'source')}[kind]
            self.db.execute('INSERT INTO people_' + kind + ' VALUES(' + ','.join('?' for _ in values) +
                            ') ON CONFLICT(id) DO UPDATE SET ' + ','.join(c + '=excluded.' + c for c in columns), values)
            self.work.record('people_saved', key)
        return {'id': key}

    def delete(self, kind, key):
        if kind not in ('departments', 'employees', 'skills'):
            raise WorkspaceError('항목 종류를 확인하세요.')
        with self.work.transaction():
            self.row(kind, key)
            if kind == 'departments':
                if self.db.execute('SELECT id FROM people_departments WHERE parent_id=?', (key,)).fetchone() or self.db.execute(
                        'SELECT id FROM people_employees WHERE department_id=?', (key,)).fetchone():
                    raise WorkspaceError('직원과 하위 부서를 먼저 다른 곳으로 옮겨주세요.', 409)
            if kind == 'employees':
                for row in self.db.execute("SELECT args FROM jobs WHERE kind='employee' AND status IN ('queued','running')"):
                    if json.loads(row['args']).get('employee_id') == key:
                        raise WorkspaceError('직원의 진행 중 업무가 끝난 뒤 삭제하세요.', 409)
                self.db.execute('DELETE FROM people_assignments WHERE employee_id=?', (key,))
            if kind == 'skills':
                self.db.execute('DELETE FROM people_assignments WHERE skill_id=?', (key,))
            self.db.execute('DELETE FROM people_' + kind + ' WHERE id=?', (key,))
            self.work.record('people_deleted', key)
        return {'ok': True}

    def assign(self, data):
        with self.work.transaction():
            employee = self.row('employees', data.get('employee_id'))
            skills = data.get('skill_ids')
            if not isinstance(skills, list) or len(skills) > 10 or any(not isinstance(k, str) for k in skills) or len(set(skills)) != len(skills):
                raise WorkspaceError('중복 없이 최대 10개 스킬을 선택하세요.')
            for key in skills:
                self.row('skills', key)
            self.db.execute('DELETE FROM people_assignments WHERE employee_id=?', (employee['id'],))
            self.db.executemany('INSERT INTO people_assignments VALUES(?,?)', [(employee['id'], key) for key in skills])
            self.work.record('people_assigned', employee['id'])
        return {'ok': True}

    def context(self, key):
        # 요청 시점이 아니라 실행 직전 선택: 대기 중 해제·비활성화도 반영한다.
        with self.work.lock:
            employee = self.row('employees', key)
            if not employee['active']:
                raise WorkspaceError('비활성 직원은 업무를 실행할 수 없습니다.', 409)
            skills = [dict(r) for r in self.db.execute('''SELECT s.* FROM people_skills s
                JOIN people_assignments a ON a.skill_id=s.id WHERE a.employee_id=? AND s.active=1 ORDER BY s.id''', (key,))]
        return {'name': employee['name'], 'role': employee['role'],
                'skills': [{'id': s['id'], 'name': s['name'], 'body': s['body']} for s in skills]}

    def handle(self, method, path, data):
        if method == 'GET' and path == '/people':
            return self.state()
        if method != 'POST' or not isinstance(data, dict):
            raise WorkspaceError('지원하지 않는 직원 요청입니다.', 404)
        if path == '/people/assign':
            return self.assign(data)
        if path == '/people/run':
            return self.work.queue('employee', data)
        if path == '/people/install':
            source = CATALOG.get(data.get('catalog_id')) if isinstance(data.get('catalog_id'), str) else None
            if not source:
                raise WorkspaceError('제공 스킬을 선택하세요.')
            return self.save('skills', source)
        match = re.fullmatch(r'/people/(departments|employees|skills)/(save|delete)', path)
        if match:
            kind, action = match.groups()
            return self.save(kind, data) if action == 'save' else self.delete(kind, data.get('id'))
        raise WorkspaceError('지원하지 않는 직원 요청입니다.', 404)
