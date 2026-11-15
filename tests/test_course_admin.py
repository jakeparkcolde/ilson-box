"""Course admin uses the student's flat vault and private course state."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_web_admin import BoxFixture, admin, ROOT
import approval_store as store
import approval_dispatch as dispatch


class FlatVaultTests(BoxFixture):
    def setUp(self):
        super().setUp()
        self.vault = self.home.parent / 'Documents/일손강의-1기'
        (self.vault/'reports/pending').mkdir(parents=True)
        (self.vault/'reports/weekly').mkdir()
        (self.vault/'CONTEXT.md').write_text('- 회사명: 강의 회사\n')
        self.box = admin.Box(self.home, profile='course', vault=self.vault,
                             probe=self.probe, user_home=self.user_home)

    def test_flat_reports_use_vault_and_classification(self):
        (self.vault/'reports/weekly/2026-11-15.md').write_text('# 주간 리포트\nhello')
        (self.vault/'reports/pending/draft.md').write_text('# 대기 초안')
        rows = self.box.reports()['reports']
        self.assertEqual({r['category'] for r in rows}, {'주간 보고','승인 대기 초안'})
        weekly = next(row for row in rows if row['category']=='주간 보고')
        self.assertIn('hello',self.box.report(weekly['id'])['text'])
        self.assertEqual(self.box.company()[0], '강의 회사')

    def test_flat_approval_moves_and_logs_in_same_vault(self):
        dispatch.register()
        draft=self.vault/'reports/pending/draft.md'; body='# 합성 초안\n검토할 내용'
        draft.write_text(body)
        identity=store.request_approval('local_note', {'channel':'local_note','account':'local','object_id':'draft.md'},'합성 초안',body,home=self.home)
        self.assertTrue(store.decide(identity,'approved','local',home=self.home))
        self.assertEqual(dispatch.dispatch(identity,self.home,vault=self.vault,license_check=lambda:True),'success')
        self.assertFalse(draft.exists())
        self.assertEqual((self.vault/'reports/approved/draft.md').read_text(),body)
        self.assertTrue(list((self.vault/'journal').glob('*.md')))
        self.assertFalse((self.home/'vault/reports/approved').exists())

    def test_course_cli_passes_private_home_to_weekly_child_and_restores_caller(self):
        spec=importlib.util.spec_from_file_location('course_cli_admin',ROOT/'course/ilson.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        observed=[]
        def call(args):
            observed.append((args,os.environ.get('ILSON_HOME'),os.environ.get('ILSON_PROFILE')))
            return 0
        with patch.dict(os.environ,{'ILSON_COURSE_STATE':str(self.home),'ILSON_COURSE_VAULT':str(self.vault),'ILSON_HOME':'caller-home'}),patch.object(cli.subprocess,'call',side_effect=call):
            self.assertEqual(cli.main(['report','weekly']),0)
            self.assertEqual(os.environ['ILSON_HOME'],'caller-home')
        self.assertEqual(len(observed),2)
        self.assertTrue(all(home==str(self.home) and profile=='course' for _,home,profile in observed))
        self.assertIn('--flat-vault',observed[-1][0])


if __name__=='__main__':unittest.main()


class CourseHTTPTests(FlatVaultTests):
    # Reuse only HTTP helpers, without inheriting the full Box HTTP test suite.
    from test_web_admin import HTTP시험 as _HTTP
    request=_HTTP.request
    login=_HTTP.login
    stop=_HTTP.stop

    def setUp(self):
        super().setUp()
        import threading
        self.server=admin.Server(self.box,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.stop)

    def test_course_allowlist_prevents_optional_imports_and_returns_only_five_features(self):
        import builtins
        original=builtins.__import__
        forbidden={'mini_workspace','current_ui','resource_dashboard','inbox_files','approval_telegram','replies_naver_qna','replies_dispatch'}
        def checked(name,*args,**kwargs):
            if name in forbidden: raise AssertionError('course imported '+name)
            return original(name,*args,**kwargs)
        with patch.object(builtins,'__import__',side_effect=checked):
            cookie,_=self.login();headers={'Cookie':cookie}
            status,_,session=self.request('GET','/api/session',headers=headers)
            self.assertEqual(status,200)
            self.assertEqual(set(session['features']),{'home','approvals','reports','usage-history','replies'})
            self.assertEqual(self.request('GET','/api/approvals',headers=headers)[0],200)
            for method,path in [('GET','/api/dashboard'),('GET','/current/'),('GET','/api/workspace/people'),('GET','/api/inbox-files'),('GET','/api/oauth/callback/threads'),('GET','/api/sns-operations'),('POST','/api/approvals/send'),('POST','/api/replies/collect'),('POST','/api/usage')]:
                with self.subTest(path=path): self.assertEqual(self.request(method,path,{} if method=='POST' else None,headers=headers)[0],404)
            with patch('replies_draft.draft',return_value={'status':'draft','text':'합성 초안'}) as draft:
                self.assertEqual(self.request('POST','/api/replies/draft',{'text':'안녕','consent':True},headers=headers)[0],200)
                draft.assert_called_once()

    def test_course_keeps_token_host_origin_and_read_only_reports_boundary(self):
        self.assertEqual(self.request('GET','/api/overview')[0],401)
        self.assertEqual(self.request('GET','/api/overview',headers={'Host':'attacker.test'})[0],403)
        cookie,_=self.login();headers={'Cookie':cookie}
        self.assertEqual(self.request('POST','/api/approvals/create',{'name':'draft.md'},headers={**headers,'Origin':'https://attacker.test'})[0],403)
        self.assertEqual(self.request('POST','/api/reports',{},headers=headers)[0],404)
        self.assertEqual(self.request('POST','/api/replies/draft',{'text':'안녕','consent':False},headers=headers)[0],400)

    def test_course_licenses_are_cached_for_sixty_seconds(self):
        self.box.license_cache=None;clock=[10.0];self.box.license_clock=lambda:clock[0]
        with patch('license.evaluate',return_value=(True,'ACTIVE')) as evaluate:
            self.assertTrue(self.box.licensed());self.assertTrue(self.box.licensed())
            evaluate.assert_called_once()
            clock[0]+=60
            self.assertTrue(self.box.licensed());self.assertEqual(evaluate.call_count,2)
