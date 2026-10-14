"""브라우저 관측은 등록한 계정만 대상으로 삼고 실패를 정상 로그인으로 바꾸지 않는다."""
from datetime import datetime, timezone
import unittest
import shutil
import test_current_ui as fixtures
from current_health import target
from mini_workspace import WorkspaceError


class HealthTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.CurrentUITests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.work, self.ui, self.provider = fixture.work, fixture.ui, fixture.provider
        self.ui.save_account({'platform':'x','account':'sample','brands':['사업부']})

    @unittest.skipUnless(shutil.which('node'), 'JS 실행기는 로컬 브라우저 검증 환경에서 사용합니다.')
    def test_Zenn_표시이름이_바뀌어도_프로필주소로_계정을_대조한다(self):
        import json, subprocess
        from pathlib import Path
        script = (Path(__file__).resolve().parents[1]/'template/lib/current_browser_check.js').read_text()
        fixture = r"""
const C={platform:'zenn',account:'sample',url:'https://zenn.dev'};
let n=0;const page={locator:()=>({click:async()=>{},getAttribute:async()=>'/sample'})};
const openTab=async()=>page,closeTab=async()=>{},sleep=async()=>{};
const snapshot=async()=>({tree:++n===1?'- button "メニューを開く" [ref=a]':'- link "회사이름@sample" [ref=b]'});
"""
        result=subprocess.run(['node','--input-type=module','-'],input=fixture+script,text=True,capture_output=True,check=True)
        observed=json.loads(result.stdout.split('ILSON_HEALTH:')[1])
        self.assertEqual(observed['login_state'],'ok')

    def test_등록한계정만_관측하고_발행하지않는다(self):
        calls=[]
        def probe(platform, account):
            calls.append((platform,account))
            return {'login_state':'ok','publish_access':'unknown'}
        self.provider.browser_health=probe
        self.ui.health.request({'platform':'x','account':'sample'})
        self.ui.health.tick()
        self.assertEqual(calls,[('x','sample')])
        self.assertEqual(self.ui.health.snapshot()['accounts'][0]['login_state'],'ok')
        self.assertEqual(self.ui.readiness()['accounts'][0]['state'],'unknown')
        self.assertEqual(self.provider.sent,[])
        self.ui.health.tick(); self.assertEqual(len(calls),1)
        with self.assertRaises(WorkspaceError): self.ui.health.request({'platform':'x','account':'other'})

    def test_관측실패나_오래된관측은_정상으로_표시하지않는다(self):
        def broken(*args): raise TimeoutError('비밀이 섞인 브라우저 출력')
        self.provider.browser_health=broken
        self.ui.health.tick()
        row=self.ui.health.snapshot()['accounts'][0]
        self.assertEqual(row['state'],'unknown')
        self.assertNotIn('비밀',row['reason'])
        self.provider.browser_health=lambda *args:{'login_state':'ok','publish_access':'confirmed'}
        self.ui.health.request({'platform':'x','account':'sample'});self.ui.health.tick()
        self.assertEqual(self.ui.readiness()['accounts'][0]['state'],'ok')
        self.work.clock=lambda:datetime.now(timezone.utc).timestamp()+2701
        self.assertEqual(self.ui.health.snapshot()['accounts'][0]['state'],'unknown')

    def test_회사회원_경로는_계정에서_만들고_외부주소를_거부한다(self):
        self.assertIn('/company/7654321/admin/',target('linkedin','company/7654321')['url'])
        for platform,account in [('linkedin','company/../evil'),('x','a/b'),('x','https://evil.example')]:
            with self.assertRaises(WorkspaceError): target(platform,account)
