"""미니 실업무 경로. 네트워크·LLM·고객 계정은 주입한 가짜 공급자로 대체한다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPConnection
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'template/lib'))
from mini_workspace import Workspace, WorkspaceError, Providers
spec=importlib.util.spec_from_file_location('mini_admin_test',ROOT/'template/lib/web-admin-server.py')
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)


class FakeProviders:
    def __init__(self):self.sent=[];self.calls=[];self.fail=False
    def collect(self,home,args):
        return {'version':1,'type':'ilson-source-bundle','coverage':'partial','target':args['url'],
                'checked_at':'2026-10-07T00:00:00+00:00','requested':args['limit'],'collected':1,
                'sources':[{'id':1,'title':'시험 영상','url':'https://www.youtube.com/watch?v=abcdefghijk',
                            'content':'원문을 읽고 점검 목록을 만듭니다.','method':'aside-youtube-transcript',
                            'published_at':None,'truncated':False}],
                'failures':[],'limitations':'외부 호출 없는 시험 자료입니다.'}
    def learn(self,home,args):
        return self.knowledge(home,args,lambda **_:None)['ability']
    def verify(self,platform,token,expected=''):
        self.calls.append(('verify',platform))
        return {'user_id':'123456','username':'시험 계정'}
    def publish(self,account,token,post):
        self.sent.append((account['id'],post['text']))
        if self.fail:raise TimeoutError('외부 서비스의 비밀 원문')
        return 'published-123'
    def research(self,home,args,progress):
        self.calls.append(('research',args));progress(stage='reading')
        return {'version':1,'question':args['question'],'claims':[{'kind':'fact','text':'자료에 근거한 시험 답변','source_ids':[1]}],
                'sources':[{'id':1,'title':'시험 출처','url':'https://example.com/source'}],
                'limitations':'시험 자료만 사용','checked_at':'2026-10-07T00:00:00+00:00'}
    def draft(self,home,args,progress):return {'text':'검토할 시험 초안'}
    def knowledge(self,home,args,progress):
        return {'bundle':{'sources':[]},'ability':{'version':1,'type':'ilson-ability','state':'draft','tested':False,
            'goal':args['goal'],'checked_at':'2026-10-07T00:00:00+00:00',
            'claims':[{'kind':'fact','text':'원문에서 확인한 절차','source_ids':[1]}],'limitations':'미시험 초안',
            'sources':[{'id':1,'title':'시험 영상','url':'https://www.youtube.com/watch?v=abcdefghijk','published_at':None,'method':'transcript','truncated':False}],
            'skill':{'name':'sample-skill','title':'시험 능력','description':'시험 설명','when_to_use':'시험 시',
                     'inputs':['질문'],'steps':[{'text':'원문 읽기','source_ids':[1]}],
                     'checks':['출처 대조'],'test_cases':['표본 시험']}}}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mini-work-test-');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'box';self.home.mkdir();(self.home/'state').mkdir();(self.home/'vault').mkdir()
        self.providers=FakeProviders();self.clock=[datetime(2026,10,7,tzinfo=timezone.utc).timestamp()]
        self.work=Workspace(self.home,admin.Files(self.home),providers=self.providers,clock=lambda:self.clock[0])
        self.addCleanup(lambda:self.work.close())
        self.token=secrets.token_urlsafe(40)
        self.account=self.work.connect({'platform':'threads','token':self.token})

    def post(self,**extra):return self.work.create_post({'account_id':self.account['id'],'text':'승인할 내용',**extra})
    def approve(self,post,**extra):return self.work.post_action(post['id'],'approve',{'revision':post['revision'],**extra})

    def test_계정비밀은_장부와_응답에_남지않고_로컬_0600파일만_쓴다(self):
        self.assertNotIn(self.token,json.dumps(self.work.accounts()))
        self.assertNotIn(self.token,(self.home/'.workspace/work.sqlite3').read_bytes().decode(errors='ignore'))
        file=next((self.home/'.credentials').glob('*.json'))
        self.assertEqual(file.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(file.read_text())['token'],self.token)
        self.work.account_action(self.account['id'],'disconnect')
        self.assertFalse(file.exists())
        self.assertEqual(self.work.accounts()['accounts'][0]['status'],'disconnected')

    def test_미승인과_반려초안은_발행하지않는다(self):
        post=self.post();self.work.tick();self.assertEqual(self.providers.sent,[])
        self.work.post_action(post['id'],'reject',{'revision':1});self.work.tick()
        self.assertEqual(self.providers.sent,[])

    def test_승인한_내용만_한번_발행한다(self):
        post=self.post();self.approve(post)
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:self.work.publish_due(),range(8)))
        self.assertEqual(self.providers.sent,[(self.account['id'],'승인할 내용')])
        self.assertEqual(self.work.post(post['id'])['status'],'published')
        with self.assertRaises(WorkspaceError):self.approve(post)

    def test_수정하면_승인취소_이전리비전승인거절(self):
        post=self.post();self.approve(post)
        changed=self.work.post_action(post['id'],'edit',{'revision':1,'text':'바뀐 내용'})
        self.assertEqual(changed['status'],'draft');self.assertIsNone(changed['approved_digest'])
        with self.assertRaises(WorkspaceError):self.approve(post)
        self.work.tick();self.assertEqual(self.providers.sent,[])
        self.approve(changed);self.work.tick();self.assertEqual(self.providers.sent[0][1],'바뀐 내용')

    def test_승인후_장부변조도_digest가_차단한다(self):
        post=self.post();self.approve(post)
        with self.work.transaction():self.work.db.execute('UPDATE posts SET text=? WHERE id=?',('변조',post['id']))
        self.work.tick();self.assertEqual(self.providers.sent,[])
        self.assertEqual(self.work.post(post['id'])['status'],'draft')

    def test_KST예약이_UTC로_비교되고_시간대없는_입력은_거절한다(self):
        post=self.post()
        with self.assertRaises(WorkspaceError):self.approve(post,scheduled_at='2026-10-07T10:00:00')
        self.approve(post,scheduled_at='2026-10-07T10:00:00+09:00')
        self.work.tick();self.assertEqual(self.providers.sent,[])
        self.clock[0]+=3600;self.work.tick();self.assertEqual(len(self.providers.sent),1)

    def test_통신실패와_재시작은_자동재발행하지않는다(self):
        post=self.post();self.approve(post);self.providers.fail=True
        self.work.tick();self.work.tick();self.assertEqual(len(self.providers.sent),1)
        row=self.work.post(post['id']);self.assertEqual(row['status'],'unknown')
        self.assertNotIn('비밀 원문',row['error'])
        self.work.close();self.work=Workspace(self.home,admin.Files(self.home),providers=self.providers)
        self.work.tick();self.assertEqual(len(self.providers.sent),1)

    def test_발행중_강제종료는_확인필요로_복구한다(self):
        post=self.post();self.approve(post)
        with self.work.transaction():self.work.db.execute("UPDATE posts SET status='publishing' WHERE id=?",(post['id'],))
        self.work.close();self.work=Workspace(self.home,admin.Files(self.home),providers=self.providers)
        self.assertEqual(self.work.post(post['id'])['status'],'unknown');self.work.tick();self.assertEqual(self.providers.sent,[])

    def test_계정해제가_대기발행도_취소한다(self):
        post=self.post();self.approve(post);self.work.account_action(self.account['id'],'disconnect');self.work.tick()
        self.assertEqual(self.providers.sent,[]);self.assertEqual(self.work.post(post['id'])['status'],'draft')

    def test_인스타_이미지없이_승인하지않는다(self):
        account=self.work.connect({'platform':'instagram','token':self.token})
        post=self.work.create_post({'account_id':account['id'],'text':'이미지 필요'})
        with self.assertRaises(WorkspaceError):self.approve(post)

    def test_연습설치는_외부업무와_발행을_차단한다(self):
        post=self.post();self.approve(post);(self.home/'state/sandbox').touch()
        with self.assertRaises(WorkspaceError):self.work.queue('research',{'question':'질문'})
        with self.assertRaises(WorkspaceError):self.work.connect({'platform':'threads','token':self.token})
        self.work.tick();self.assertEqual(self.providers.sent,[])

    def test_재시작뒤에도_대기업무를_처리하고_출처서류를_남긴다(self):
        job=self.work.queue('research',{'question':'새 시장 조사'})
        self.work.close();self.work=Workspace(self.home,admin.Files(self.home),providers=self.providers)
        self.work.tick();result=self.work.job(job['id']);self.assertEqual(result['status'],'done')
        doc=self.work.document(result['result']['document_id'])
        self.assertIn('https://example.com/source',doc['content']);self.assertIn('자료에 근거한 시험 답변',doc['content'])

    def test_지식추출은_출처와_미시험상태를_서류로_보존한다(self):
        job=self.work.queue('knowledge',{'url':'https://www.youtube.com/watch?v=abcdefghijk','goal':'절차 배우기'})
        self.work.tick();row=self.work.job(job['id']);self.assertEqual(row['status'],'done',row)
        doc=self.work.document(row['result']['document_id'])
        self.assertIn('https://www.youtube.com/watch?v=abcdefghijk',doc['content'])
        self.assertIn('시험',doc['content'])

    def test_초안생성은_발행없이_검토초안만_만든다(self):
        job=self.work.queue('draft',{'account_id':self.account['id'],'brief':'상품 소개'})
        self.work.tick();row=self.work.job(job['id']);self.assertEqual(row['status'],'done')
        self.assertEqual(self.work.post(row['result']['post_id'])['status'],'draft');self.assertEqual(self.providers.sent,[])

    def test_후속조사는_이전질문만_전달하고_모델답변은_재주입하지않는다(self):
        first=self.work.queue('research',{'question':'첫 조사 질문'})
        self.work.tick()
        second=self.work.queue('research',{'question':'후속 질문','previous_job':first['id']})
        self.work.tick()
        args=self.work.job(second['id'])['args']
        self.assertEqual(args['context'],['첫 조사 질문'])
        self.assertNotIn('자료에 근거한 시험 답변',json.dumps(args,ensure_ascii=False))

    def test_지식파일은_완료된_출처포함초안만_내보낸다(self):
        import base64,io,zipfile
        job=self.work.queue('knowledge',{'url':'https://www.youtube.com/watch?v=abcdefghijk','goal':'절차 배우기'})
        with self.assertRaises(WorkspaceError):self.work.handle('GET','/jobs/'+job['id']+'/export')
        self.work.tick()
        data=self.work.handle('GET','/jobs/'+job['id']+'/export')
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['base64']))) as archive:
            self.assertTrue(any(name.endswith('SKILL.md') for name in archive.namelist()))
            self.assertTrue(any(name.endswith('sources.json') for name in archive.namelist()))

    def test_긴조사가_예약발행을_막지않는다(self):
        ready,release=threading.Event(),threading.Event()
        original=self.providers.research
        def slow(*args):
            ready.set();release.wait(5);return original(*args)
        self.providers.research=slow
        self.work.queue('research',{'question':'긴 조사'})
        self.work.start()
        self.assertTrue(ready.wait(2))
        post=self.post();self.approve(post)
        import time
        try:
            end=time.monotonic()+3
            while not self.providers.sent and time.monotonic()<end:time.sleep(0.03)
            self.assertEqual(len(self.providers.sent),1)
        finally:
            release.set()

    def test_서류수정본이_원본을_덮지않고_백링크를_남긴다(self):
        first=self.work.save_document({'title':'회사','content':'보존할 내용'})
        original=(self.home/first['path']).read_bytes()
        second=self.work.save_document({'title':'회사 수정','content':'새 내용','previous_id':first['id']})
        self.assertNotEqual(first['id'],second['id']);self.assertEqual((self.home/first['path']).read_bytes(),original)
        self.assertIn(first['path'].removeprefix('vault/'),self.work.document(second['id'])['content'])
        self.assertEqual(len(self.work.documents('새 내용')['documents']),1)

    def test_서류탐색은_비밀폴더와_심볼릭링크를_읽지않는다(self):
        (self.home/'vault/link.md').symlink_to(next((self.home/'.credentials').glob('*.json')))
        self.assertEqual(self.work.documents()['documents'],[])
        with self.assertRaises(WorkspaceError):self.work.document('../../.credentials')
        (self.home/'vault/workspace').symlink_to(self.home/'.credentials')
        with self.assertRaises(OSError):self.work.save_document({'title':'공격','content':'기록'})

    def test_한_미니의_실행기를_중복시작하지않는다(self):
        with self.assertRaises(WorkspaceError):Workspace(self.home,admin.Files(self.home))

    def test_기존노트와_비밀은_스냅샷에서_분리한다(self):
        shutil.copytree(ROOT/'template/lib',self.home/'lib')
        note=self.work.save_document({'title':'보존','content':'원문'})
        import subprocess
        result=subprocess.run(['bash',str(self.home/'lib/snapshot.sh')],env={**os.environ,'ILSON_HOME':str(self.home)},capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        names=subprocess.check_output(['git','-C',str(self.home),'ls-files'],text=True)
        self.assertIn(note['path'],names);self.assertNotIn('.credentials/',names);self.assertNotIn('.workspace/',names)


class WorkspaceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mini-http-');self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);private=self.home/'state/web-admin';private.mkdir(parents=True)
        self.token=secrets.token_urlsafe(32)
        for name,value in [('token',self.token),('instance',secrets.token_urlsafe(24))]:
            path=private/name;path.write_text(value);path.chmod(0o600)
        box=admin.Box(self.home);self.server=admin.Server(box,0)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.addCleanup(self.stop)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        status,headers,_=self.call('POST','/api/session',{'token':self.token})
        self.assertEqual(status,200);self.cookie=dict(headers)['Set-Cookie'].split(';')[0]

    def stop(self):
        self.server.shutdown();self.server.server_close()
        if self.server.box._workspace:self.server.box._workspace.close()

    def call(self,method,path,data=None,headers=None):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        body=json.dumps(data) if data is not None else None
        headers={'Content-Type':'application/json','Origin':self.origin,**(headers or {})}
        connection.request(method,path,body,headers);response=connection.getresponse()
        raw=response.read();result=(response.status,response.getheaders(),json.loads(raw));connection.close();return result

    def test_실행_조회_모두_세션과_동일출처가_필요하다(self):
        for method,path,data in [('POST','/api/workspace/research',{'question':'질문'}),('GET','/api/workspace/accounts',None)]:
            self.assertEqual(self.call(method,path,data)[0],401)
            self.assertEqual(self.call(method,path,data,{'Cookie':self.cookie,'Origin':'https://evil.example'})[0],403)
        self.assertIsNone(self.server.box._workspace)

    def test_서류_실행API가_실제장부와_연결된다(self):
        headers={'Cookie':self.cookie}
        status,_,doc=self.call('POST','/api/workspace/documents',{'title':'회사의 자료','content':'실제 저장 시험'},headers)
        self.assertEqual(status,200,doc)
        status,_,body=self.call('GET','/api/workspace/documents/'+doc['id'],headers=headers)
        self.assertEqual(status,200);self.assertIn('실제 저장 시험',body['content'])
        self.server.box.workspace().providers=FakeProviders()
        status,_,job=self.call('POST','/api/workspace/research',{'question':'조사 시험'},headers)
        self.assertEqual(status,200,job);self.server.box.workspace().tick()
        status,_,job=self.call('GET','/api/workspace/jobs/'+job['id'],headers=headers)
        self.assertEqual(job['status'],'done')



class ProviderContractTests(unittest.TestCase):
    def test_전체기간검색은_지원하지않는_all필터를_검색CLI로_보내지않는다(self):
        import subprocess
        with tempfile.TemporaryDirectory(prefix='mini-search-') as directory:
            base=Path(directory);capture=base/'arguments.json'
            timer=base/'gtimeout';timer.write_text('#!/bin/sh\nshift 3\nexec "$@"\n');timer.chmod(0o700)
            search=base/'tvly'
            search.write_text('#!'+sys.executable+'\nimport json,sys\nfrom pathlib import Path\n'+
                              f'Path({str(capture)!r}).write_text(json.dumps(sys.argv[1:]))\n'+
                              'print(json.dumps({"results":[]}))\n')
            search.chmod(0o700)
            result=subprocess.run(['bash',str(ROOT/'template/lib/search.sh'),'공개 질문','general','all'],
                                  env={**os.environ,'ILSON_HOME':str(base),'PATH':str(base)+':'+os.environ['PATH']},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            args=json.loads(capture.read_text())
            self.assertNotIn('--time-range',args);self.assertEqual(args[:2],['search','공개 질문'])

    def test_Meta_실제발행경로의_계정확인과_요청본문(self):
        from social.http import Client,Response
        token=secrets.token_urlsafe(32)
        for platform in ('threads','instagram','facebook'):
            with self.subTest(platform=platform):
                calls=[]
                def request(client,method,url,**kwargs):
                    calls.append((method,url,kwargs))
                    if url.endswith('/me'):
                        data={'id':'123456','user_id':'123456','username':'example','name':'Page','category':'Brand'}
                    elif method=='GET': data={'status':'FINISHED','status_code':'FINISHED'}
                    elif url.endswith(('threads_publish','media_publish','/feed','/photos')):data={'id':'published-actual-contract'}
                    else:data={'id':'container-one'}
                    return Response(200,json.dumps(data).encode())
                account={'platform':platform,'user_id':'123456'}
                with patch.object(Client,'request',request):
                    result=Providers().publish(account,token,{'text':'승인된 게시 본문','image_url':'https://example.com/image.jpg' if platform=='instagram' else ''})
                self.assertEqual(result,'published-actual-contract')
                self.assertTrue(calls[0][1].endswith('/me'))
                posts=[row for row in calls if row[0]=='POST']
                self.assertTrue(posts)
                self.assertTrue(all('/123456/' in row[1] for row in posts))
                self.assertTrue(any('승인된 게시 본문' in json.dumps(row[2],ensure_ascii=False) for row in posts))

    def test_다른계정이면_발행요청전에_중단한다(self):
        from social.http import Client,Response
        calls=[]
        def request(client,method,url,**kwargs):
            calls.append(method);return Response(200,json.dumps({'id':'999','username':'other'}).encode())
        with patch.object(Client,'request',request):
            with self.assertRaises(WorkspaceError):
                Providers().publish({'platform':'threads','user_id':'123'},secrets.token_urlsafe(32),{'text':'본문','image_url':''})
        self.assertEqual(calls,['GET'])

    def test_새설치에_업무모듈과_화면이_함께_포함된다(self):
        import subprocess
        with tempfile.TemporaryDirectory(prefix='mini-install-') as directory:
            base=Path(directory);(base/'bin').mkdir()
            env={**os.environ,'ILSON_HOME':str(base/'box'),'ILSON_SRC':str(ROOT),
                 'ILSON_CLI_DIR':str(base/'cli'),'ILSON_BIN_DIR':str(base/'bin'),
                 'PATH':str(base/'bin')+':'+os.environ['PATH']}
            result=subprocess.run(['sh',str(ROOT/'install.sh'),'--sandbox'],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            for name in ('lib/mini_workspace.py','lib/research/engine.py','lib/research/knowledge.py',
                         'lib/social/meta_publish.py','lib/social/http.py','web/workspace.js','web/workspace.css'):
                self.assertEqual((base/'box'/name).read_bytes(),(ROOT/'template'/name).read_bytes())
            code='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/lib')
from mini_workspace import Workspace
import importlib.util
spec=importlib.util.spec_from_file_location('admin',sys.argv[1]+'/lib/web-admin-server.py')
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)
home=Path(sys.argv[1]);work=Workspace(home,admin.Files(home))
print(work.handle('GET','/status')['sandbox']);work.close()
'''
            result=subprocess.run([sys.executable,'-c',code,str(base/'box')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'True')

if __name__=='__main__':unittest.main()
