"""기존 관리자 흐름의 조직 원자성·실제 실행·이전 코드 호환 경계."""
import copy
import json
import subprocess
from unittest.mock import patch
import unittest
import test_people_skills as baseline
import test_mini_workspace as fixtures
from mini_workspace import WorkspaceError, Providers
from research import native, settings
import test_native_research as native_fixture


class ParityTests(unittest.TestCase):
    setUp=baseline.PeopleTests.setUp
    employee=baseline.PeopleTests.employee
    skill=baseline.PeopleTests.skill
    def test_mixed_hierarchy_browser_sibling_order(self):
        result=subprocess.run(['node',str(fixtures.ROOT/'tests/people_org_order_check.js'),str(fixtures.ROOT/'template/web/current/people.js')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_org_atomic_conflict_cycle_missing_reorder(self):
        a=self.people.save('departments',{'name':'기획'})['id']
        b=self.people.save('departments',{'name':'운영'})['id']
        staff=self.employee(department_id=a)
        before=self.people.state()
        payload={'expected':before['org_version'],'departments':list(reversed(before['departments'])),'placements':{staff:b}}
        self.people.organization(payload)
        after=self.people.state()
        self.assertEqual(after['employees'][0]['department_id'],b)
        self.assertEqual(after['departments'][0]['id'],b)
        with self.assertRaises(WorkspaceError):self.people.organization(payload)
        for change in ('cycle','missing','remove','duplicate','bad_employee'):
            bad=copy.deepcopy(payload);bad['expected']=after['org_version']
            if change=='cycle':
                bad['departments'][0]['parent_id']=a;bad['departments'][1]['parent_id']=b
            elif change=='missing':bad['departments'][0]['parent_id']='f'*32
            elif change=='remove':bad['departments'].pop()
            elif change=='duplicate':bad['departments'][0]['name']=bad['departments'][1]['name']
            else:bad['placements'][staff]='f'*32
            with self.assertRaises(WorkspaceError):self.people.organization(bad)
            self.assertEqual(self.people.state(),after)

    def test_duty_crud_validation_live_context_and_history(self):
        staff,skill=self.employee(),self.skill()
        self.people.assign({'employee_id':staff,'skill_ids':[skill]})
        duty=self.people.duty({'employee_id':staff,'title':'주제 조사','kind':'research','args':{'question':'시험 질문'}})['id']
        with self.assertRaises(WorkspaceError):self.work.queue('employee',{'employee_id':staff,'duty_id':duty,'brief':'다른 종류'})
        job=self.people.run({'duty_id':duty})
        self.work.providers=fixtures.FakeProviders()
        self.work.run_next_job()
        result=self.work.job(job['id'])
        self.assertEqual(result['status'],'done',result['error'])
        self.assertEqual(self.work.providers.calls[0][1]['employee_context']['skills'][0]['id'],skill)
        self.assertEqual(result['result']['employee_id'],staff)
        self.assertEqual(result['result']['applied_stage'],'조사·답변 작성')
        self.assertIn('시험 답변',self.work.document(result['result']['document_id'])['content'])
        self.people.assign({'employee_id':staff,'skill_ids':[]})
        self.assertEqual(self.people.state()['activity'][0]['applied_skills'][0]['id'],skill)
        row=self.people.state()['duties'][0]
        with self.assertRaises(WorkspaceError):self.people.duty({**row,'active':False,'expected':{}})
        self.people.duty({**row,'active':False,'expected':row})
        with self.assertRaises(WorkspaceError):self.people.run({'duty_id':duty})
        row=self.people.state()['duties'][0]
        self.people.duty({**row,'expected':row},True)
        self.assertEqual(len(self.people.state()['activity']),1)
        for kind,args in [('shell',{'brief':'echo x'}),('knowledge',{'url':'file:///etc/passwd','goal':'x'}),('research',{'question':'x','period':'bad'})]:
            with self.assertRaises(WorkspaceError):self.people.duty({'employee_id':staff,'title':'bad','kind':kind,'args':args})

    def test_pending_native_employee_disable_delete_and_duty_delete(self):
        staff=self.employee()
        duty=self.people.duty({'employee_id':staff,'title':'조사','kind':'research','args':{'question':'질문'}})['id']
        job=self.people.run({'duty_id':duty})
        with self.assertRaises(WorkspaceError):self.people.delete('employees',staff)
        self.employee(id=staff,active=False)
        with patch.object(self.work.providers,'research') as run:self.work.run_next_job()
        run.assert_not_called();self.assertEqual(self.work.job(job['id'])['status'],'failed')
        self.employee(id=staff,active=True)
        job=self.people.run({'duty_id':duty})
        row=self.people.state()['duties'][0];self.people.duty({**row,'expected':row},True)
        with patch.object(self.work.providers,'research') as run:self.work.run_next_job()
        run.assert_not_called();self.assertEqual(self.work.job(job['id'])['status'],'failed')

    def test_actual_research_prompt_contains_role_skill_and_source_checks_still_run(self):
        staff,skill=self.employee(),self.skill();self.people.assign({'employee_id':staff,'skill_ids':[skill]})
        settings.save(self.home,'codex')
        job=self.people.run({'employee_id':staff,'kind':'research','question':'조건 조사'})
        with patch.object(native,'execute',return_value=(native_fixture.candidate(),native_fixture.events())) as execute:
            self.work.run_next_job()
        prompt=execute.call_args.args[2]
        self.assertIn('정확한 문서 작성',prompt);self.assertIn('확인된 근거만 작성',prompt)
        self.assertEqual(self.work.job(job['id'])['status'],'done')
        bad=native_fixture.candidate();bad['sources'][0]['url']='https://example.org/unobserved'
        job=self.people.run({'employee_id':staff,'kind':'research','question':'조건 조사'})
        with patch.object(native,'execute',return_value=(bad,native_fixture.events())):
            self.work.run_next_job()
        self.assertEqual(self.work.job(job['id'])['status'],'failed')

    def test_actual_knowledge_prompt_preserves_empty_tools(self):
        from research import knowledge
        staff,skill=self.employee(),self.skill();self.people.assign({'employee_id':staff,'skill_ids':[skill]})
        bundle=fixtures.FakeProviders().collect(self.home,{'url':'https://www.youtube.com/watch?v=abcdefghijk','limit':1})
        args={'url':bundle['target'],'goal':'점검 방법','limit':1,'employee_context':self.people.context(staff)}
        captured=[]
        def run(argv,**kw):captured.append(argv);raise RuntimeError('stop before network')
        with patch('research.collect_aside.collect',return_value=bundle),patch.object(knowledge.shutil,'which',return_value='/test/claude'),patch.object(knowledge,'call',run):
            # learn의 기본 run 인수는 정의 시 묶이므로 명시적으로 실제 learn 경로를 호출한다.
            with self.assertRaises(RuntimeError):knowledge.learn(bundle,args['goal'],self.home,run=run,employee_context=args['employee_context'])
        self.assertIn('확인된 근거만 작성',captured[0][2]);self.assertEqual(captured[0][captured[0].index('--tools')+1],'')
        with patch('research.collect_aside.collect',return_value=bundle),patch.object(knowledge,'learn',return_value={}) as learn:
            Providers().knowledge(self.home,args,lambda **_:None)
        self.assertEqual(learn.call_args.kwargs['employee_context'],args['employee_context'])

    def test_previous_release_can_insert_edit_without_erasing_new_metadata(self):
        staff=self.employee(bio='새 소개')
        raw=subprocess.check_output(['git','show','27bdb897655c46ded3893d7d6076f1f7fc375f3b:template/lib/people_skills.py'],cwd=fixtures.ROOT,text=True)
        scope={};exec(compile(raw,'previous_people.py','exec'),scope)
        old=scope['People'](self.work)
        old.save('employees',{'id':staff,'name':'변경 담당','role':'기존 버전 편집'})
        added=old.save('employees',{'name':'기존 버전 신규','role':'검토'})['id']
        self.assertEqual(self.people.row('employees',added)['role'],'검토')
        self.assertEqual(self.people.state()['profiles'][0]['bio'],'새 소개')

    def test_profile_conflict_and_cli_request_replay(self):
        staff=self.employee(bio='첫 소개');row=self.people.row('employees',staff)
        self.people.save('employees',{**row,'active':True,'bio':'다른 소개','expected_bio':'첫 소개'})
        with self.assertRaises(WorkspaceError):self.people.save('employees',{**row,'active':True,'bio':'충돌','expected_bio':'첫 소개'})
        self.assertEqual(self.people.state()['profiles'][0]['bio'],'다른 소개')

class ParityHTTPTests(unittest.TestCase):
    def test_registry_auth_validation_and_same_shell_assets(self):
        import test_current_http
        f=test_current_http.CurrentHTTPTests();f.setUp();self.addCleanup(f.doCleanups)
        (f.home/'launchd').mkdir(exist_ok=True);(f.home/'launchd/jobs.conf').write_text('briefing|run-job.sh|briefing|daily 09:00\n')
        report=f.home/'vault/reports/briefing/sample.md';report.parent.mkdir(parents=True,exist_ok=True);report.write_text('# 시험 브리핑\n검증된 시험 결과')
        registry=json.loads(f.call('GET','/api/workspace/people/registry')[2])
        self.assertEqual(registry['jobs'][0]['reports'][0]['title'],'시험 브리핑')
        self.assertEqual(f.call('GET','/api/workspace/people/registry',cookie=False)[0],401)
        staff=f.work.people.save('employees',{'name':'담당','role':'검토'})['id']
        self.assertEqual(f.call('POST','/api/workspace/people/schedules',data={'employee_id':staff,'schedule_ids':['unregistered']})[0],400)
        self.assertEqual(f.call('POST','/api/workspace/people/schedules',data={'employee_id':staff,'schedule_ids':['briefing']})[0],200)
        for path in ('/current/people.js','/current/people.css','/people'):
            status,headers,body=f.call('GET',path);self.assertEqual(status,200)
            self.assertIn('Content-Security-Policy',headers)
        self.assertIn(b'/current/?tab=staff',f.call('GET','/people')[2])

class RollbackTests(unittest.TestCase):
    def test_rollback_refuses_pending_work_before_restoring_any_file(self):
        import test_update
        f=test_update.UpdateTests();f.setUp();self.addCleanup(f.doCleanups)
        w=fixtures.Workspace(f.roots['box'],fixtures.admin.Files(f.roots['box']));self.addCleanup(w.close)
        staff=w.people.save('employees',{'name':'담당','role':'조사'})['id']
        w.people.run({'employee_id':staff,'kind':'research','question':'질문'})
        with patch.object(test_update.u,'restore_previous') as restore:
            with self.assertRaisesRegex(ValueError,'대기 중'):test_update.u.rollback(f.roots,f.roots['box']/'.updates',{})
        restore.assert_not_called()
