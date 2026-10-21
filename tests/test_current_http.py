"""기존 화면의 API와 OAuth 콜백이 관리자 인증 경계를 우회하지 못하게 한다."""
from http.client import HTTPConnection
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock
import test_mini_workspace as fixtures
from mini_workspace import safe_private


class CurrentHTTPTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.WorkspaceHTTPTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.server=fixture.server;self.home=fixture.home
        shutil.copytree(fixtures.ROOT/'template/web',self.home/'web',dirs_exist_ok=True)
        self.work=self.server.box.workspace();self.work.providers=fixtures.FakeProviders()
        from current_ui import CurrentUI
        self.work.current_ui=CurrentUI(self.work)
        safe_private(self.work.credentials/'oauth-apps.json',{'threads':{'app_id':'123456','app_secret':'only-test-fixture',
            'redirect_uri':'https://mini.example/api/oauth/callback/threads'}})

    def call(self,method,path,*,cookie=True,host=None,data=None,origin=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={}
        if cookie:headers['Cookie']=self.fixture.cookie
        if host:headers['Host']=host
        if method=='POST':headers.update({'Content-Type':'application/json','Origin':origin or self.fixture.origin})
        c.request(method,path,json.dumps(data) if data is not None else None,headers)
        r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result

    def test_기존화면의_API도_세션과_동일출처를_확인한다(self):
        for path in ('/api/sns-operations?week=2026-10-05','/api/current/vault','/api/sns-readiness','/api/research-capabilities'):
            self.assertEqual(self.call('GET',path,cookie=False)[0],401)
            self.assertEqual(self.call('GET',path)[0],200)
        self.assertEqual(self.call('POST','/api/sns-internal/account',data={},origin='https://evil.example')[0],403)

    def test_임베드화면만_동일출처프레임을_허용하고_정적파일만_열어준다(self):
        for path in ('/current/index.html?tab=sns','/current/pack-library/research.html','/current/assets/sns/threads.svg'):
            status,headers,_=self.call('GET',path)
            self.assertEqual(status,200,path)
            self.assertEqual(headers['X-Frame-Options'],'SAMEORIGIN' if 'pack-library' in path else 'DENY')
        self.assertEqual(self.call('GET','/current/../../.credentials/oauth-apps.json')[0],404)
        self.assertEqual(self.call('GET','/api/session?token=anything')[0],404)

    def test_외부콜백호스트는_콜백이외_화면이나_API를_열지못한다(self):
        self.work.current_ui.oauth.finish=Mock(return_value={'ok':True})
        path='/api/oauth/callback/threads?state=fixture&code=fixture'
        self.assertEqual(self.call('GET',path,cookie=False,host='mini.example')[0],200)
        self.work.current_ui.oauth.finish.assert_called_once()
        for other in ('/api/current/vault','/api/health','/current/index.html'):
            self.assertEqual(self.call('GET',other,host='mini.example')[0],403)
        self.assertEqual(self.call('GET',path,host='evil.example')[0],403)

    def test_지식훔치기_API는_내부모드에서_세션만으로_수집과_능력생성을_처리한다(self):
        status,_,raw=self.call('GET','/api/research-capabilities')
        caps=json.loads(raw)
        self.assertEqual((status,caps['mode']),(200,'internal'))
        self.assertIn('knowledge',caps)
        source={'url':'https://www.youtube.com/watch?v=abcdefghijk','limit':3}
        self.assertEqual(self.call('POST','/api/knowledge/collect',cookie=False,data=source)[0],401)
        # 화면은 내부 모드에서 별도 실행 토큰 헤더 없이 세션 쿠키로만 호출한다.
        status,_,raw=self.call('POST','/api/knowledge/collect',data=source)
        self.assertEqual(status,200,raw)
        bundle=json.loads(raw)
        status,_,raw=self.call('POST','/api/knowledge/learn',data={'bundle':bundle,'goal':'점검 방법'})
        self.assertEqual(status,200,raw)
        ability=json.loads(raw)
        self.assertEqual((ability['state'],ability['tested']),('draft',False))
        self.assertIn('시험 능력',self.work.document(ability['document_id'])['content'])

    def test_Aside가_없으면_수집은_정직한_안내로_거절한다(self):
        from mini_workspace import Providers
        from unittest.mock import patch
        self.work.providers=Providers()
        with patch('shutil.which',return_value=None):
            caps=json.loads(self.call('GET','/api/research-capabilities')[2])
            status,_,raw=self.call('POST','/api/knowledge/collect',data={'url':'https://www.youtube.com/watch?v=abcdefghijk','limit':3})
        self.assertFalse(caps['knowledge'])
        self.assertEqual(status,409)
        self.assertIn('Aside',json.loads(raw)['error'])

    def test_중복파라미터와_HEAD는_인증교환하지않는다(self):
        self.work.current_ui.oauth.finish=Mock()
        self.assertEqual(self.call('GET','/api/oauth/callback/threads?state=a&state=b&code=c')[0],400)
        self.assertEqual(self.call('HEAD','/api/oauth/callback/threads?state=a&code=c')[0],405)
        self.work.current_ui.oauth.finish.assert_not_called()


# 지식 훔치기 화면 스크립트를 가짜 DOM에서 실행한다. 실제 브라우저·Aside·LLM은 쓰지 않는다.
KNOWLEDGE_HARNESS = r'''
const vm=require('vm'),fs=require('fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const els={},calls=[];
function el(id){return els[id]||(els[id]={id,textContent:'',hidden:false,disabled:false,value:'',children:[],handlers:{},
  classList:{toggle(){},add(){}},addEventListener(type,fn){this.handlers[type]=fn},
  replaceChildren(...c){this.children=c},append(...c){this.children.push(...c)}})}
for(const id of ['localGuide','collectionCommand','copyCommand','bundlePanel','abilityPanel'])el(id).hidden=true;
el('collectButton').textContent='자료 수집하기 ↗';
let made=0;
const stages=['stageCollect','stageLearn','stageSave'].map(id=>({id,classList:{toggle(){}}}));
const replies={'/api/research-capabilities':input.capabilities,'/api/knowledge/collect':input.bundle,'/api/knowledge/learn':input.ability};
const ctx={console,URL,Date,JSON,Number,Error,AbortSignal,URLSearchParams,setTimeout,crypto:globalThis.crypto,
  document:{getElementById:el,querySelectorAll:()=>stages,createElement:()=>el('made-'+(made++)),body:{classList:{add(){}}}},
  location:{search:''},localStorage:{getItem:()=>null,setItem(){}},navigator:{},Blob:class{},
  fetch:async(path,options={})=>{calls.push({path,headers:options.headers||{}});const body=replies[path];
    return {ok:body!==undefined,json:async()=>body===undefined?{error:'없는 요청'}:body}}};
ctx.window=ctx;vm.createContext(ctx);
for(const file of ['ability-format.js','knowledge.js'])vm.runInContext(fs.readFileSync(input.dir+'/'+file,'utf8'),ctx,{filename:file});
const settle=()=>new Promise(resolve=>setTimeout(resolve,30));
(async()=>{
  await settle();
  const out={init:{status:el('knowledgeStatus').textContent,collect:el('collectButton').textContent,guide:el('localGuide').hidden}};
  el('sourceUrl').value='https://www.youtube.com/watch?v=abcdefghijk';el('collectLimit').value='3';
  el('collectForm').handlers.submit({preventDefault(){}});await settle();
  out.collect={status:el('knowledgeStatus').textContent,command:el('collectionCommand').hidden,bundle:el('bundlePanel').hidden,learn:el('learnButton').textContent};
  el('abilityGoal').value='점검 방법';el('learnForm').handlers.submit({preventDefault(){}});await settle();
  out.learn={status:el('knowledgeStatus').textContent,ability:el('abilityPanel').hidden,title:el('abilityTitle').textContent};
  out.calls=calls;console.log(JSON.stringify(out));
})();
'''


@unittest.skipUnless(shutil.which('node'), 'JS 실행기는 로컬 브라우저 검증 환경에서 사용합니다.')
class KnowledgePageTests(unittest.TestCase):
    def run_page(self, capabilities):
        import subprocess
        providers = fixtures.FakeProviders()
        bundle = providers.collect(None, {'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'limit': 3})
        ability = dict(providers.learn(None, {'goal': '점검 방법'}), document_id='a' * 32)
        payload = json.dumps({'dir': str(fixtures.ROOT / 'template/web/current/pack-library'),
                              'capabilities': capabilities, 'bundle': bundle, 'ability': ability})
        result = subprocess.run(['node', '-e', KNOWLEDGE_HARNESS], input=payload, text=True,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_현재화면의_내부모드에서도_직접실행으로_연결한다(self):
        out = self.run_page({'mode': 'internal', 'async': True, 'knowledge': True})
        self.assertNotIn('직접 실행 연결이 없습니다', out['init']['status'])
        self.assertEqual(out['init']['collect'], '자료 수집하기 ↗')
        self.assertTrue(out['init']['guide'])
        self.assertTrue(out['collect']['command'])
        self.assertFalse(out['collect']['bundle'])
        self.assertEqual(out['collect']['learn'], '능력 초안 만들기 ↗')
        self.assertFalse(out['learn']['ability'])
        self.assertEqual(out['learn']['title'], '시험 능력')
        posted = [c for c in out['calls'] if c['path'].startswith('/api/knowledge/')]
        self.assertEqual([c['path'] for c in posted], ['/api/knowledge/collect', '/api/knowledge/learn'])
        # 내부 모드는 세션 쿠키로 인증하므로 별도 실행 토큰 헤더를 보내지 않는다.
        self.assertTrue(all('X-Ilson-Research' not in c['headers'] for c in posted))

    def test_Aside가_없으면_수집전에_정직하게_알린다(self):
        out = self.run_page({'mode': 'internal', 'async': True, 'knowledge': False})
        self.assertIn('Aside', out['init']['status'])
        self.assertNotIn('직접 실행 연결이 없습니다', out['init']['status'])

    def test_기기_리서치팩_토큰모드는_그대로_토큰을_보낸다(self):
        out = self.run_page({'mode': 'box', 'token': 'fixture-token'})
        posted = [c for c in out['calls'] if c['path'].startswith('/api/knowledge/')]
        self.assertEqual(posted[0]['headers'].get('X-Ilson-Research'), 'fixture-token')

    def test_연결이_없으면_명령준비_모드를_유지한다(self):
        out = self.run_page({'mode': 'static'})
        self.assertIn('직접 실행 연결이 없습니다', out['init']['status'])
        self.assertEqual(out['init']['collect'], '수집 명령 준비 ↗')
        self.assertFalse(out['collect']['command'])
