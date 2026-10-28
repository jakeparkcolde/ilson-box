"""직원 업무의 실입력·참조 무결성·장부 이행. 실제 모델/계정은 호출하지 않는다."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_mini_workspace as fixtures
from mini_workspace import Workspace, WorkspaceError, Providers
from people_skills import People, markdown


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ilson-people-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'box'
        self.home.mkdir()
        (self.home / 'state').mkdir()
        (self.home / 'vault').mkdir()
        self.work = Workspace(self.home, fixtures.admin.Files(self.home))
        self.addCleanup(lambda: self.work.close())
        self.people = self.work.people

    def employee(self, **extra):
        return self.people.save('employees', {'name': '문서 담당', 'role': '정확한 문서 작성', **extra})['id']

    def skill(self, **extra):
        return self.people.save('skills', {'name': '근거 점검', 'description': '문서 점검', 'body': '확인된 근거만 작성', **extra})['id']

    def test_화면렌더링은_XSS본문과속성을_이스케이프한다(self):
        script = r"""
const fs=require('fs'), vm=require('vm');
const nodes={};
const node=id=>nodes[id]||(nodes[id]={innerHTML:'',textContent:'',replaceChildren(){},append(){}});
const bad='<img src=x onerror=alert(1)>"&';
const data={departments:[{id:'a'.repeat(32),name:bad,parent_id:''}],employees:[{id:'b'.repeat(32),name:bad,role:bad,active:1,department_id:'a'.repeat(32)}],skills:[{id:'c'.repeat(32),name:bad,description:bad,body:bad,active:1}],assignments:[],catalog:[]};
const context={document:{getElementById:node,querySelectorAll:()=>[],addEventListener(){}},fetch:async path=>({ok:true,json:async()=>path.endsWith('/jobs')?{jobs:[{id:'d'.repeat(32),kind:'employee',title:bad,status:'done'}]}:data}),location:{assign(){}},console};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{for(const tab of ['employees','departments','skills','jobs']){
 await vm.runInContext(`state=${JSON.stringify(data)};tab='${tab}';render()`,context);
 if(node('view').innerHTML.includes('<img')||!node('view').innerHTML.includes('&lt;img'))throw Error('unsafe '+tab);
}})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run(['node', '-e', script, str(fixtures.ROOT/'template/web/people.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_빈상태_부서직원CRUD_재배치_순환삭제참조(self):
        self.assertEqual(self.people.state()['employees'], [])
        a = self.people.save('departments', {'name': '운영'})['id']
        b = self.people.save('departments', {'name': '문서', 'parent_id': a})['id']
        e = self.employee(department_id=b)
        with self.assertRaises(WorkspaceError):
            self.people.save('departments', {'id': a, 'name': '운영', 'parent_id': b})
        for key in (a, b):
            with self.assertRaises(WorkspaceError): self.people.delete('departments', key)
        with self.assertRaises(WorkspaceError): self.people.save('departments', {'name': '운영'})
        self.people.save('employees', {'id': e, 'name': '편집 담당', 'role': '검토', 'department_id': a})
        self.people.delete('departments', b)
        self.people.delete('employees', e)
        self.people.delete('departments', a)
        self.assertEqual(self.people.state()['departments'], [])

    def test_없는스킬_중복_과다할당은_기존할당을_보존한다(self):
        e, s = self.employee(), self.skill()
        self.people.assign({'employee_id': e, 'skill_ids': [s]})
        for ids in ([s, 'f'*32], [s, s], [s]*11, None, [{}]):
            with self.assertRaises(WorkspaceError): self.people.assign({'employee_id': e, 'skill_ids': ids})
            self.assertEqual(self.people.context(e)['skills'][0]['id'], s)
        self.people.delete('skills', s)
        self.assertEqual(self.people.state()['assignments'], [])
        self.assertEqual(self.people.context(e)['skills'], [])

    def test_실행직전_활성할당만_실제CLI입력에_전달하고_결과를_보존한다(self):
        e = self.employee()
        first, second = self.skill(), self.skill(name='회의 정리', body='결정과 미정을 구분')
        self.people.assign({'employee_id': e, 'skill_ids': [first, second]})
        queued = self.work.queue('employee', {'employee_id': e, 'brief': '회의 기록 정리'})
        self.skill(id=first, active=False)
        with patch('mini_workspace.subprocess.run', return_value=Mock(returncode=0, stdout=json.dumps({'result': '작성한 결과'}))) as run:
            self.work.run_next_job()
        prompt = json.loads(run.call_args.kwargs['input'].split('\n', 1)[1])
        self.assertEqual([s['id'] for s in prompt['employee']['skills']], [second])
        self.assertNotIn('확인된 근거만 작성', run.call_args.kwargs['input'])
        argv = run.call_args.args[0]
        self.assertIn('--safe-mode', argv)
        self.assertEqual(argv[argv.index('--tools')+1], '')
        self.assertIn('--disable-slash-commands', argv)
        job = self.work.job(queued['id'])
        self.assertEqual(job['status'], 'done', job['error'])
        self.assertEqual(job['result']['applied_skills'], [{'id': second, 'name': '회의 정리'}])
        self.assertIn('작성한 결과', self.work.document(job['result']['document_id'])['content'])

    def test_대기중해제와_제거는_실행에_반영한다(self):
        e, s = self.employee(), self.skill()
        self.people.assign({'employee_id': e, 'skill_ids': [s]})
        for change in ('unassign', 'delete'):
            if change == 'delete': self.people.assign({'employee_id': e, 'skill_ids': [s]})
            job = self.work.queue('employee', {'employee_id': e, 'brief': '작성'})
            if change == 'unassign': self.people.assign({'employee_id': e, 'skill_ids': []})
            else: self.people.delete('skills', s)
            with patch.object(self.work.providers, 'employee', return_value={'text': '결과', 'employee_name': '담당', 'applied_skills': []}) as execute:
                self.work.run_next_job()
            self.assertEqual(execute.call_args.args[1]['employee_context']['skills'], [])
            self.assertEqual(self.work.job(job['id'])['status'], 'done')

    def test_대기직원삭제제한과_비활성화는_모델호출을_막는다(self):
        e = self.employee()
        job = self.work.queue('employee', {'employee_id': e, 'brief': '작성'})
        with self.assertRaises(WorkspaceError): self.people.delete('employees', e)
        self.employee(id=e, active=False)
        with patch.object(self.work.providers, 'employee') as run: self.work.run_next_job()
        run.assert_not_called()
        self.assertEqual(self.work.job(job['id'])['status'], 'failed')
        self.people.delete('employees', e)
        self.assertEqual(self.work.job(job['id'])['status'], 'failed')

    def test_진행중삭제는_막고_시작한스킬스냅샷은_유지한다(self):
        e, s = self.employee(), self.skill()
        self.people.assign({'employee_id': e, 'skill_ids': [s]})
        job = self.work.queue('employee', {'employee_id': e, 'brief': '작성'})
        def running(home, args, progress):
            with self.assertRaises(WorkspaceError): self.people.delete('employees', e)
            self.people.delete('skills', s)
            self.employee(id=e, active=False)
            self.assertEqual(args['employee_context']['skills'][0]['id'], s)
            return {'text': '진행한 결과', 'applied_skills': [{'id': s, 'name': '근거 점검'}], 'employee_name': '문서 담당'}
        with patch.object(self.work.providers, 'employee', side_effect=running): self.work.run_next_job()
        self.assertEqual(self.work.job(job['id'])['status'], 'done')
        self.assertEqual(self.people.state()['assignments'], [])

    def test_재시작_반복이행_사용자장부보존(self):
        e, s = self.employee(), self.skill()
        self.people.assign({'employee_id': e, 'skill_ids': [s]})
        before = self.people.state()
        People(self.work)
        self.assertEqual(before, self.people.state())
        self.work.close()
        self.work = Workspace(self.home, fixtures.admin.Files(self.home))
        self.assertEqual(before, self.work.people.state())

    def test_오래된장부_테이블추가가_기존업무를_보존한다(self):
        with self.work.transaction():
            for table in ('assignments','skills','employees','departments'):
                self.work.db.execute('DROP TABLE people_' + table)
            self.work.db.execute("INSERT INTO jobs VALUES('old-job','research','{}','done','done','before','before','{}',NULL)")
        self.work.close()
        self.work = Workspace(self.home, fixtures.admin.Files(self.home))
        self.assertEqual(self.work.job('old-job')['status'], 'done')
        self.assertEqual(self.work.people.state()['employees'], [])

    def test_트랜잭션_실패는_할당과_저장을_되돌린다(self):
        e, s = self.employee(), self.skill()
        self.people.assign({'employee_id': e, 'skill_ids': [s]})
        with patch.object(self.work, 'record', side_effect=RuntimeError('쓰기 실패')):
            with self.assertRaises(RuntimeError): self.people.assign({'employee_id': e, 'skill_ids': []})
            with self.assertRaises(RuntimeError): self.skill(id=s, active=False)
        self.assertEqual(self.people.context(e)['skills'][0]['id'], s)

    def test_동시삭제와할당은_고아참조를_남기지않는다(self):
        e, s = self.employee(), self.skill()
        def assign():
            try: self.people.assign({'employee_id': e, 'skill_ids': [s]})
            except WorkspaceError: pass
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda fn: fn(), [assign, lambda: self.people.delete('skills', s)]))
        self.assertEqual(self.people.state()['assignments'], [])

    def test_경로_입력은_파일접근을_만들지않고_원격설치는_거절한다(self):
        for key in ('../outside', '/tmp/item', 'https://example.com/a', '<img src=x onerror=alert(1)>'):
            with self.assertRaises(WorkspaceError): self.people.row('employees', key)
            with self.assertRaises(WorkspaceError): self.people.handle('POST', '/people/install', {'catalog_id': key})
        key = self.skill(name='../../outside', body='<script>danger()</script>')
        self.assertEqual(self.people.row('skills', key)['body'], '<script>danger()</script>')
        self.assertFalse((Path(self.temp.name) / 'outside').exists())
        self.assertFalse((self.home / '.claude').exists())

    def test_동적치환_후크_빈본문_과다입력_잘못된자료형(self):
        for body in ('', '!`touch /tmp/no`', '---\nhooks: run\n---\n본문', '---\nname: skill\n', 'x'*24001):
            with self.assertRaises(WorkspaceError): markdown(body)
        self.assertEqual(markdown('---\nname: sample\ndescription: summary\n---\n확인'), '확인')
        for data in ({'name': '부서', 'parent_id': []}, {'name': '부서', 'parent_id': None}):
            with self.assertRaises(WorkspaceError): self.people.save('departments', data)
        with self.assertRaises(WorkspaceError): self.employee(active='yes')

    def test_장부와_부모심볼릭링크는_거절한다(self):
        self.work.close()
        original = self.home / '.workspace'
        relocated = self.home / 'elsewhere'
        original.rename(relocated)
        original.symlink_to(relocated, target_is_directory=True)
        with self.assertRaises(WorkspaceError): Workspace(self.home, fixtures.admin.Files(self.home))
        original.unlink()
        relocated.rename(original)
        db = original / 'work.sqlite3'
        saved = original / 'saved.sqlite3'
        db.rename(saved)
        db.symlink_to(saved)
        with self.assertRaises(WorkspaceError): Workspace(self.home, fixtures.admin.Files(self.home))

    def test_실패_권한거절_빈결과는_성공으로_저장하지않는다(self):
        e = self.employee()
        for response in (Mock(returncode=1, stdout=''), Mock(returncode=0, stdout='{"is_error":true}'), Mock(returncode=0, stdout='{"result":""}')):
            job = self.work.queue('employee', {'employee_id': e, 'brief': '작성'})
            with patch('mini_workspace.subprocess.run', return_value=response): self.work.run_next_job()
            self.assertEqual(self.work.job(job['id'])['status'], 'failed')


class PeopleInstallTests(unittest.TestCase):
    def test_격리HOME_설치와_재설치가_직원장부를_보존한다(self):
        import test_setup
        fixture = test_setup.SetupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        isolated = fixture.base / 'home'
        isolated.mkdir()
        fixture.env['HOME'] = str(isolated)
        script = 'TEMPLATE="' + str(fixtures.ROOT / 'template') + '"; SANDBOX=1; init_step_box'
        first = fixture.shell(script, timeout=30)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        for name in ('lib/people_skills.py', 'web/people.html', 'web/people.js', 'web/people.css'):
            self.assertTrue((fixture.box / name).is_file(), name)
        work = Workspace(fixture.box, fixtures.admin.Files(fixture.box))
        work.people.save('employees', {'name': '설치 시험 담당', 'role': '문서 작성'})
        before = work.people.state()
        work.close()
        second = fixture.shell(script, timeout=30)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        work = Workspace(fixture.box, fixtures.admin.Files(fixture.box))
        try: self.assertEqual(work.people.state(), before)
        finally: work.close()
        self.assertFalse((isolated / 'Library/LaunchAgents').exists())
        self.assertFalse((isolated / '.claude').exists())

    def test_업데이트와_코드원복은_직원장부를_건드리지않는다(self):
        import test_update
        fixture = test_update.UpdateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        home = fixture.roots['box']
        work = Workspace(home, fixtures.admin.Files(home))
        work.people.save('employees', {'name': '보존 시험 담당', 'role': '문서 작성'})
        before = work.people.state()
        work.close()
        db = home / '.workspace/work.sqlite3'
        raw = db.read_bytes()
        rows = [('box', name, (fixtures.ROOT/'template'/name).read_bytes(), None)
                for name in ('lib/people_skills.py','web/people.html','web/people.js','web/people.css')]
        manifest, archive = fixture.bundle(rows)
        test_update.u.apply(fixture.roots, manifest, archive)
        self.assertEqual(db.read_bytes(), raw)
        store = home / '.updates'
        test_update.u.rollback(fixture.roots, store, test_update.u.read(store/'journal.json'))
        self.assertEqual(db.read_bytes(), raw)
        work = Workspace(home, fixtures.admin.Files(home))
        try: self.assertEqual(work.people.state(), before)
        finally: work.close()


class PeopleHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.WorkspaceHTTPTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.home = fixture.home
        shutil.copytree(fixtures.ROOT/'template/web', self.home/'web', dirs_exist_ok=True)

    def call(self, method, path, body=None, cookie=True, origin=None):
        from http.client import HTTPConnection
        client = HTTPConnection('127.0.0.1', self.fixture.server.server_port, timeout=5)
        headers = {'Content-Type': 'application/json', 'Origin': origin or self.fixture.origin}
        if cookie: headers['Cookie'] = self.fixture.cookie
        client.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        client.close()
        return result

    def test_API세션_출처_CSP와_XSS문자열_보존(self):
        path = '/api/workspace/people'
        self.assertEqual(self.call('GET', path, cookie=False)[0], 401)
        self.assertEqual(self.call('GET', path)[0], 200)
        data = {'name': '<img src=x onerror=alert(1)>', 'role': '문서'}
        self.assertEqual(self.call('POST', path+'/employees/save', data, origin='https://evil.example')[0], 403)
        self.assertEqual(self.call('POST', path+'/employees/save', data)[0], 200)
        result = json.loads(self.call('GET', path)[2])
        self.assertEqual(result['employees'][0]['name'], data['name'])
        status, headers, html = self.call('GET', '/people')
        self.assertEqual(status, 200)
        self.assertIn('Content-Security-Policy', headers)
        self.assertNotIn(data['name'].encode(), html)
        for asset in ('/people.js', '/people.css'):
            self.assertEqual(self.call('GET', asset)[0], 200)
        self.assertEqual(self.call('GET', '/people/../../.workspace/work.sqlite3')[0], 404)

    def test_제공설치_할당_삭제_API(self):
        prefix = '/api/workspace/people'
        def post(path, data):
            status, _, raw = self.call('POST', prefix + path, data)
            self.assertEqual(status, 200, raw)
            return json.loads(raw)
        skill = post('/install', {'catalog_id': 'meeting-notes'})['id']
        employee = post('/employees/save', {'name': '시험 직원', 'role': '회의 정리'})['id']
        post('/assign', {'employee_id': employee, 'skill_ids': [skill]})
        post('/skills/delete', {'id': skill})
        self.assertEqual(json.loads(self.call('GET', prefix)[2])['assignments'], [])


if __name__ == '__main__': unittest.main()
