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
