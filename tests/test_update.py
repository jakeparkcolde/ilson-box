from contextlib import redirect_stdout
import http.client
import importlib.util
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('update',ROOT/'tools/update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.roots={a:self.root/a for a in ['box','cli']}
        for p in self.roots.values():p.mkdir()
        self.target=self.roots['box']/'lib/search.sh';self.target.parent.mkdir();self.target.write_bytes(b'old')
        self.protected={}
        for name in ['vault/company.md','state/pairing.json','state/web_sessions.json','logs/job.log','lib/job-settings.json','.claude/settings.json','launchd/jobs.conf']:
            p=self.roots['box']/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'customer '+name.encode());self.protected[name]=p.read_bytes()
    def bundle(self,rows=None):
        rows=rows or [('box','lib/search.sh',b'new',b'old')]
        buf=io.BytesIO();files=[]
        with zipfile.ZipFile(buf,'w') as z:
            for area,name,data,old in rows:
                z.writestr(area+'/'+name,data)
                files.append(dict(area=area,path=name,sha256=u.digest(data),previous_sha256=u.digest(old) if old else None))
        data=buf.getvalue()
        return dict(schema=1,version='1.0',files=files,archive_sha256=u.digest(data),research_version='0.14.0'),data
    def test_운영데이터를_보존하고_코드만_교체와_복구(self):
        m,a=self.bundle();u.apply(self.roots,m,a)
        self.assertEqual(self.target.read_bytes(),b'new')
        for n,body in self.protected.items():self.assertEqual((self.roots['box']/n).read_bytes(),body)
        store=self.roots['box']/'.updates';u.rollback(self.roots,store,u.read(store/'journal.json'))
        self.assertEqual(self.target.read_bytes(),b'old')
        for n,body in self.protected.items():self.assertEqual((self.roots['box']/n).read_bytes(),body)
    def test_검토한_확장본은_보존하고_새파일만_적용(self):
        self.target.write_bytes(b'advanced')
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old'),('cli','ilson',b'newcli',None)])
        m['files'][0]['preserve_sha256']=[u.digest(b'advanced')]
        u.apply(self.roots,m,a)
        self.assertEqual(self.target.read_bytes(),b'advanced')
        self.assertEqual((self.roots['cli']/'ilson').read_bytes(),b'newcli')
        self.assertNotIn('box/lib/search.sh',u.read(self.roots['box']/'.updates/installed.json')['files'])
        for n,body in self.protected.items():self.assertEqual((self.roots['box']/n).read_bytes(),body)
        self.target.write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'보존'):u.apply(self.roots,m,a)

    def test_중간실패는_앞서적용한_코드도_원복(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old'),('cli','ilson',b'newcli',None)])
        original=u.atomic;failed=[]
        def atomic(path,data):
            if path==self.roots['cli']/'ilson' and not failed:failed.append(1);raise OSError('disk error')
            original(path,data)
        with patch.object(u,'atomic',side_effect=atomic),self.assertRaises(OSError):u.apply(self.roots,m,a)
        self.assertEqual(self.target.read_bytes(),b'old');self.assertFalse((self.roots['cli']/'ilson').exists())
        self.assertEqual(u.read(self.roots['box']/'.updates/journal.json')['status'],'recovered')
    def test_사용자수정이_있으면_다른파일도_미적용(self):
        self.target.write_bytes(b'custom')
        m,a=self.bundle([('cli','ilson',b'newcli',None),('box','lib/search.sh',b'new',b'old')])
        with self.assertRaisesRegex(ValueError,'보존'):u.apply(self.roots,m,a)
        self.assertFalse((self.roots['cli']/'ilson').exists());self.assertEqual(self.target.read_bytes(),b'custom')
    def test_설정_경로탈출_심볼릭링크_해시변조_차단(self):
        for path in ['state/pairing.json','lib/job-settings.json','../outside','.claude/settings.json','vault/secret.py']:
            m,a=self.bundle([('box',path,b'bad',None)])
            with self.subTest(path=path),self.assertRaises(ValueError):u.apply(self.roots,m,a)
        m,a=self.bundle()
        with self.assertRaises(ValueError):u.apply(self.roots,m,a+b'tampered')
        self.target.unlink();self.target.symlink_to(self.roots['box']/'state/pairing.json')
        with self.assertRaises(ValueError):u.apply(self.roots,m,a)
    def test_반복실행은_원복백업을_유지(self):
        m,a=self.bundle();u.apply(self.roots,m,a)
        journal=(self.roots['box']/'.updates/journal.json').read_bytes()
        u.apply(self.roots,m,a)
        self.assertEqual((self.roots['box']/'.updates/journal.json').read_bytes(),journal)
    def test_확인만_할때_코드변경없음_원복후수정도보존(self):
        m,a=self.bundle();u.apply(self.roots,m,a,check=True);self.assertEqual(self.target.read_bytes(),b'old')
        u.apply(self.roots,m,a);self.target.write_bytes(b'user modified after update')
        store=self.roots['box']/'.updates'
        with self.assertRaises(ValueError):u.rollback(self.roots,store,u.read(store/'journal.json'))
        self.assertEqual(self.target.read_bytes(),b'user modified after update')
    def test_파이썬구문오류는_적용전에_거부(self):
        m,a=self.bundle([('box','lib/tool.py',b'def broken(',None)])
        with self.assertRaises(SyntaxError):u.apply(self.roots,m,a)
        self.assertFalse((self.roots['box']/'lib/tool.py').exists())

if __name__=='__main__':unittest.main()

class RunningUpdateTests(UpdateTests):
    def test_관리자중지_적용_재기동_순서와_운영정보보존(self):
        m,a=self.bundle();home=self.roots['box'];(home/'state/web-admin').mkdir();(home/'state/web-admin/enabled').write_text('1')
        calls=[]
        def activate(h,command):
            calls.append((command,self.target.read_bytes()))
        with patch.object(u,'activate_command',side_effect=activate):u.apply_running(self.roots,m,a)
        self.assertEqual(calls,[('stop',b'old'),('install',b'new')])
        self.assertEqual(u.read(home/'.updates/activation.json')['status'],'active')
        for n,body in self.protected.items():self.assertEqual((home/n).read_bytes(),body)
    def test_꺼진관리자는_업데이트가_임의로켜지않음(self):
        m,a=self.bundle()
        with patch.object(u,'activate_command') as activate:u.apply_running(self.roots,m,a)
        activate.assert_not_called()
    def test_활성화실패는_성공으로숨기지않고_재실행으로복구(self):
        m,a=self.bundle();home=self.roots['box'];(home/'state/web-admin').mkdir();(home/'state/web-admin/enabled').write_text('1')
        def activate(h,command):
            if command=='install':raise ValueError('activation failed')
        with patch.object(u,'activate_command',side_effect=activate),self.assertRaises(ValueError):u.apply_running(self.roots,m,a)
        self.assertEqual(u.read(home/'.updates/activation.json')['status'],'pending')
        with patch.object(u,'activate_command') as activate:u.apply_running(self.roots,m,a)
        self.assertEqual(activate.call_count,2);self.assertEqual(u.read(home/'.updates/activation.json')['status'],'active')

class PackRuntimeUpdateTests(UpdateTests):
    def test_최신코드여도_팩프로그램을_다시점검(self):
        m,a=self.bundle();home=self.roots['box'];u.apply(self.roots,m,a)
        u.save(home/'.updates/activation.json',{'version':m['version'],'status':'active'})
        with patch.object(u,'ensure_pack_runtime') as check:
            u.apply_running(self.roots,m,a);check.assert_called_once_with(home)
        with patch.object(u,'ensure_pack_runtime') as check:
            u.apply_running(self.roots,m,a,check=True);check.assert_not_called()
    def test_프로그램실패를_성공처리하지않고_다음업데이트에서재시도(self):
        m,a=self.bundle();home=self.roots['box'];u.apply(self.roots,m,a)
        u.save(home/'.updates/activation.json',{'version':m['version'],'status':'active'})
        with patch.object(u,'ensure_pack_runtime',side_effect=ValueError('dependency failed')):
            with self.assertRaises(ValueError):u.apply_running(self.roots,m,a)
        with patch.object(u,'ensure_pack_runtime') as check:
            u.apply_running(self.roots,m,a);check.assert_called_once()
    def test_선택하지않은팩은_자동설치하지않음(self):
        with patch.object(u.subprocess,'run') as run:u.ensure_pack_runtime(self.roots['box'])
        run.assert_not_called()

KILL_DRIVER='''
import importlib.util,json,os,sys
from pathlib import Path
source,box,cli,manifest,archive=sys.argv[1:6]
spec=importlib.util.spec_from_file_location('killed_updater',source);u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
real=os.replace;seen=[]
def replace(src,dst):
    if '/.updates/' not in str(dst):
        seen.append(dst)
        if len(seen)==2:os._exit(137)
    return real(src,dst)
os.replace=replace
u.apply({'box':Path(box),'cli':Path(cli)},json.loads(Path(manifest).read_text()),Path(archive).read_bytes())
'''

class FeedTests(unittest.TestCase):
    FEED='https://feed.example/box/latest-v2.json'
    def setUp(self):
        env=patch.dict(u.os.environ);env.start();self.addCleanup(env.stop)
        u.os.environ.pop('ILSON_UPDATE_FEED',None)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.box=self.root/'box';self.cli=self.root/'cli';self.roots={'box':self.box,'cli':self.cli}
        (self.box/'lib').mkdir(parents=True);(self.box/'lib/common.sh').write_text('#');(self.box/'lib/search.sh').write_bytes(b'old')
        self.cli.mkdir();(self.cli/'ilson').write_text('#')
    def bundle(self,rows,version='1.0'):
        buf=io.BytesIO();files=[]
        with zipfile.ZipFile(buf,'w') as z:
            for area,name,data,old in rows:
                z.writestr(area+'/'+name,data);files.append(dict(area=area,path=name,sha256=u.digest(data),previous_sha256=u.digest(old) if old else None))
        data=buf.getvalue()
        return dict(schema=1,version=version,files=files,archive='box.zip',archive_sha256=u.digest(data),research_version='0.14.0'),data
    def saved(self):
        path=self.box/'.updates/feed'
        return path.read_text() if path.exists() else None
    def run_main(self,*args,feed=FEED,rows=None,version='1.0'):
        m,a=self.bundle(rows or [('box','lib/search.sh',b'new',b'old')],version)
        served={feed:json.dumps(m).encode(),feed.rsplit('/',1)[0]+'/box.zip':a}
        argv=['update.py','--home',str(self.box),'--cli',str(self.cli),*args]
        with patch.object(u,'fetch',side_effect=lambda url:served[url]) as fetch,patch.object(u.sys,'argv',argv):u.main()
        return fetch

    def test_주소_우선순위는_인자_환경_내장_저장파일_기본주소(self):
        (self.box/'.updates').mkdir();(self.box/'.updates/feed').write_text(' https://saved.example/latest-v2.json \n')
        with patch.object(u,'FEED','https://stamped.example/latest-v2.json'),patch.dict(u.os.environ,ILSON_UPDATE_FEED='https://env.example/latest-v2.json'):
            self.assertEqual(u.resolve_feed(self.box,'https://arg.example/latest-v2.json'),'https://arg.example/latest-v2.json')
            self.assertEqual(u.resolve_feed(self.box),'https://env.example/latest-v2.json')
        with patch.object(u,'FEED','https://stamped.example/latest-v2.json'):self.assertEqual(u.resolve_feed(self.box),'https://stamped.example/latest-v2.json')
        self.assertEqual(u.resolve_feed(self.box),'https://saved.example/latest-v2.json')
        (self.box/'.updates/feed').unlink();self.assertEqual(u.resolve_feed(self.box),u.DEFAULT_FEED)
    def test_기본주소는_FEED_줄과_별개이고_올바른_주소다(self):
        self.assertTrue(u.valid_feed(u.DEFAULT_FEED))
        self.assertEqual(u.FEED,'')
        source=(Path(u.__file__)).read_bytes()
        self.assertEqual(u.feed_of(source),'')
        stamped=u.stamp_feed(source,self.FEED)
        self.assertEqual(u.feed_of(stamped),self.FEED);self.assertEqual(u.unstamp(stamped),source)
        self.assertIn(b"DEFAULT_FEED='"+u.DEFAULT_FEED.encode()+b"'",stamped)
    def test_저장파일이_없거나_비면_기본주소(self):
        self.assertEqual(u.resolve_feed(self.box),u.DEFAULT_FEED)
        store=self.box/'.updates';store.mkdir()
        self.assertEqual(u.resolve_feed(self.box),u.DEFAULT_FEED)
        for empty in ('',' \n\n'):
            with self.subTest(empty=empty):
                (store/'feed').write_text(empty);self.assertEqual(u.resolve_feed(self.box),u.DEFAULT_FEED)
    def test_링크_http_빈주소는_거부한다(self):
        for bad in ['http://feed.example/latest-v2.json','','https://','https://feed.example/a b']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):u.resolve_feed(self.box,bad)
        with patch.dict(u.os.environ,ILSON_UPDATE_FEED='http://feed.example/x'),self.assertRaises(ValueError):u.resolve_feed(self.box)
        store=self.box/'.updates';store.mkdir();real=self.root/'real-feed';real.write_text(self.FEED)
        (store/'feed').symlink_to(real)
        with self.assertRaisesRegex(ValueError,'링크'):u.resolve_feed(self.box)
        with self.assertRaisesRegex(ValueError,'링크'):u.remember_feed(self.box,self.FEED)
        self.assertEqual(real.read_text(),self.FEED)
        (store/'feed').unlink();(store/'feed').write_text('http://feed.example/latest-v2.json\n')
        with self.assertRaisesRegex(ValueError,'ilson update --feed'):u.resolve_feed(self.box)
        (store/'feed').unlink();(store/'feed').symlink_to(self.root/'missing')
        with self.assertRaisesRegex(ValueError,'링크'):u.resolve_feed(self.box)
    def test_링크된_업데이트폴더의_주소는_읽지않음(self):
        elsewhere=self.root/'elsewhere';elsewhere.mkdir();(elsewhere/'feed').write_text(self.FEED)
        (self.box/'.updates').symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError,'링크'):u.resolve_feed(self.box)

    def test_성공한_실제실행만_주소를_기억(self):
        self.run_main('--feed',self.FEED,'--check');self.assertIsNone(self.saved())
        self.assertEqual((self.box/'lib/search.sh').read_bytes(),b'old')
        self.run_main('--feed',self.FEED);self.assertEqual(self.saved(),self.FEED+'\n')
        self.assertEqual((self.box/'lib/search.sh').read_bytes(),b'new')
        # Already up to date: the address is still remembered.
        (self.box/'.updates/feed').unlink()
        self.run_main('--feed',self.FEED);self.assertEqual(self.saved(),self.FEED+'\n')
        # The remembered address is used without --feed.
        fetch=self.run_main();self.assertEqual(fetch.call_args_list[0].args[0],self.FEED)
    def test_수동묶음과_복구는_주소를_기억하지않음(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')]);(self.root/'m.json').write_text(json.dumps(m));(self.root/'a.zip').write_bytes(a)
        argv=['update.py','--home',str(self.box),'--cli',str(self.cli),'--feed',self.FEED,'--manifest',str(self.root/'m.json'),'--archive',str(self.root/'a.zip')]
        with patch.object(u,'fetch') as fetch,patch.object(u.sys,'argv',argv):u.main()
        fetch.assert_not_called();self.assertIsNone(self.saved())
        with patch.object(u,'fetch') as fetch,patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli),'--feed',self.FEED,'--rollback']):u.main()
        fetch.assert_not_called();self.assertIsNone(self.saved());self.assertEqual((self.box/'lib/search.sh').read_bytes(),b'old')
    def test_검증실패한_배포의_주소는_기억하지않음(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        served={self.FEED:json.dumps(m).encode(),'https://feed.example/box/box.zip':a+b'tampered'}
        with patch.object(u,'fetch',side_effect=lambda url:served[url]),patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli),'--feed',self.FEED]):
            with self.assertRaises(ValueError):u.main()
        self.assertIsNone(self.saved())
    def test_기본주소는_정확히_이_값이다(self):
        self.assertEqual(u.DEFAULT_FEED,'https://github.com/jakeparkcolde/ilson-box/releases/latest/download/latest-v2.json')
    def failing_run(self,fetch):
        out=io.StringIO()
        with patch.object(u,'fetch',side_effect=fetch),patch('sys.stdout',out),patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli),'--feed',self.FEED]):
            with self.assertRaises(SystemExit) as stop:u.run()
        self.assertEqual(stop.exception.code,1)
        self.assertEqual((self.box/'lib/search.sh').read_bytes(),b'old');self.assertIsNone(self.saved())
        return out.getvalue()
    def test_서버에_닿지_못하면_박스가_그대로라고_알린다(self):
        broken=[urllib.error.HTTPError(self.FEED,500,'Server Error',None,None),urllib.error.HTTPError(self.FEED,403,'Forbidden',None,None),urllib.error.URLError('no route'),socket.timeout('timed out'),ConnectionResetError('reset'),OSError('down'),http.client.IncompleteRead(b'')]
        for error in broken:
            with self.subTest(error=type(error).__name__):
                def fail(url):raise error
                out=self.failing_run(fail)
                self.assertIn('업데이트 서버에 연결하지 못했습니다',out);self.assertIn('일손 박스는 그대로입니다',out);self.assertNotIn(type(error).__name__,out)
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        def archive_fails(url):
            if url==self.FEED:return json.dumps(m).encode()
            raise urllib.error.HTTPError(url,503,'Unavailable',None,None)
        self.assertIn('연결하지 못했습니다',self.failing_run(archive_fails))
    def test_배포가_없으면_404를_따로_알린다(self):
        def fail(url):raise urllib.error.HTTPError(url,404,'Not Found',None,None)
        out=self.failing_run(fail)
        self.assertIn('업데이트 서버에 아직 배포가 없습니다',out);self.assertIn('일손 박스는 그대로입니다',out);self.assertNotIn('연결하지 못했습니다',out)
    def test_업데이트_정보를_못읽으면_박스가_그대로라고_알린다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        def without(*keys):return json.dumps({k:v for k,v in m.items() if k not in keys}).encode()
        cases={'not json':b'not json','bad bytes':b'\xff\xfe\xff','list':b'[]','text':b'"x"','no archive':without('archive'),
               'archive empty':json.dumps(dict(m,archive='')).encode(),'archive null':json.dumps(dict(m,archive=None)).encode(),'archive number':json.dumps(dict(m,archive=7)).encode(),
               'archive bad url':json.dumps(dict(m,archive='https://[bad/x.zip')).encode(),'archive not ascii':json.dumps(dict(m,archive='한글.zip')).encode(),'no version':without('version'),
               'no hash':without('archive_sha256'),'no files':without('files'),'files not list':json.dumps(dict(m,files=7)).encode(),'file not dict':json.dumps(dict(m,files=[1])).encode(),
               'file no sha':json.dumps(dict(m,files=[{'area':'box','path':'lib/x.sh'}])).encode(),'version number':json.dumps(dict(m,version=1)).encode()}
        for name,body in cases.items():
            with self.subTest(name):
                out=self.failing_run(lambda url:body if url==self.FEED else a)
                self.assertIn('업데이트 정보를 읽지 못했습니다',out);self.assertIn('일손 박스는 그대로입니다',out)
    def test_ValueError는_그대로_알린다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        body=json.dumps(dict(m,archive='https://other.example/box.zip')).encode()
        out=self.failing_run(lambda url:body)
        self.assertIn('배포 서버가 다른 묶음입니다',out);self.assertNotIn('그대로입니다',out)
    def test_다른_업데이트가_실행중이면_알린다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        served={self.FEED:json.dumps(m).encode(),'https://feed.example/box/box.zip':a}
        with patch.object(u.fcntl,'flock',side_effect=BlockingIOError()):
            out=self.failing_run(lambda url:served[url])
        self.assertIn('다른 업데이트가 실행 중입니다',out);self.assertNotIn('BlockingIOError',out)
    def test_주소로_쓸수없는_묶음이름은_읽기_실패로_알린다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        body=json.dumps(dict(m,archive='a b.zip')).encode()
        def fetch(url):
            if url==self.FEED:return body
            raise http.client.InvalidURL('control characters')
        self.assertIn('업데이트 정보를 읽지 못했습니다',self.failing_run(fetch))
    def test_잠금이_아닌_BlockingIOError는_업데이트_충돌이_아니다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        served={self.FEED:json.dumps(m).encode(),'https://feed.example/box/box.zip':a}
        with patch.object(u,'apply_running',side_effect=BlockingIOError(35,'Resource temporarily unavailable')):
            out=self.failing_run(lambda url:served[url])
        self.assertIn('예상하지 못한 오류',out);self.assertNotIn('다른 업데이트',out)
    def test_적용_단계의_오류에는_그대로라고_쓰지_않는다(self):
        m,a=self.bundle([('box','lib/search.sh',b'new',b'old')])
        served={self.FEED:json.dumps(m).encode(),'https://feed.example/box/box.zip':a}
        for error in (OSError('disk full'),KeyError('x'),RuntimeError('boom')):
            with self.subTest(error=type(error).__name__),patch.object(u,'apply_running',side_effect=error):
                out=self.failing_run(lambda url:served[url])
                self.assertIn('예상하지 못한 오류',out);self.assertIn(type(error).__name__,out);self.assertNotIn('그대로',out)
    ROWS=[('box','lib/search.sh',b'new1',b'old'),('box','lib/two.sh',b'new2',b'old2'),('box','lib/three.sh',b'new3',b'old3')]
    def killed_box(self):
        # A real process dies on its second code write, so nothing in this one gets to clean up.
        (self.box/'lib/two.sh').write_bytes(b'old2');(self.box/'lib/three.sh').write_bytes(b'old3')
        m,a=self.bundle(self.ROWS,'2.0');(self.root/'m.json').write_text(json.dumps(m));(self.root/'a.zip').write_bytes(a)
        driver=self.root/'kill.py'
        driver.write_text(KILL_DRIVER)
        result=subprocess.run([sys.executable,'-B',str(driver),str(Path(u.__file__)),str(self.box),str(self.cli),str(self.root/'m.json'),str(self.root/'a.zip')],capture_output=True,text=True)
        self.assertEqual(result.returncode,137,result.stdout+result.stderr)
        self.assertEqual(self.journal(),'applying')
        self.assertEqual(self.code(),(b'new1',b'old2',b'old3'))
        return m,a
    def journal(self):return json.loads((self.box/'.updates/journal.json').read_text())['status']
    def code(self):return tuple((self.box/'lib'/n).read_bytes() for n in ('search.sh','two.sh','three.sh'))
    def served(self,m,a):return {self.FEED:json.dumps(m).encode(),'https://feed.example/box/box.zip':a}
    def rerun(self,*args,fetch=None):
        out=io.StringIO()
        with patch.object(u,'fetch',side_effect=fetch) as called,patch('sys.stdout',out),patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli),'--feed',self.FEED,*args]):
            try:u.run()
            except SystemExit as stop:self.assertEqual(stop.code,1);return out.getvalue(),1,called
        return out.getvalue(),0,called
    def test_죽은_업데이트를_다음_실행이_복구하고_마친다_apply_running(self):
        m,a=self.killed_box()
        with redirect_stdout(io.StringIO()) as out:u.apply_running(self.roots,m,a)
        self.assertIn('중단됐던 업데이트를 복구했습니다',out.getvalue())
        self.assertEqual(self.code(),(b'new1',b'new2',b'new3'));self.assertEqual(self.journal(),'applied')
    def test_죽은_업데이트를_다음_실행이_복구하고_마친다_main(self):
        m,a=self.killed_box();served=self.served(m,a)
        def fetch(url):
            # Recovery has already happened by the time the network is touched.
            self.assertEqual(self.journal(),'recovered');return served[url]
        out,code,called=self.rerun(fetch=fetch)
        self.assertEqual(code,0,out);self.assertEqual(called.call_count,2)
        self.assertIn('중단됐던 업데이트를 복구했습니다',out)
        self.assertEqual(self.code(),(b'new1',b'new2',b'new3'));self.assertEqual(self.journal(),'applied')
        self.assertEqual(self.saved(),self.FEED+'\n')
    def test_네트워크가_없어도_먼저_복구하고_사실대로_알린다(self):
        self.killed_box()
        def down(url):raise urllib.error.URLError('down')
        out,code,_=self.rerun(fetch=down)
        self.assertEqual(code,1);self.assertIn('중단됐던 업데이트를 복구했습니다',out);self.assertIn('연결하지 못했습니다',out)
        self.assertEqual(self.code(),(b'old',b'old2',b'old3'));self.assertEqual(self.journal(),'recovered')
    def test_복구한_실행의_읽기_실패는_그대로라고_하지_않는다(self):
        m,a=self.bundle(self.ROWS,'2.0')
        def no_release(url):raise urllib.error.HTTPError(url,404,'Not Found',None,None)
        def timeout(url):raise socket.timeout('timed out')
        for name,fetch,word in (('down',self.down,'연결하지 못했습니다'),('404',no_release,'아직 배포가 없습니다'),('timeout',timeout,'연결하지 못했습니다'),('bad json',lambda url:b'not json','정보를 읽지 못했습니다')):
            with self.subTest(name):
                self.tearDownBox()
                self.killed_box()
                out,code,_=self.rerun(fetch=fetch)
                self.assertEqual(code,1);self.assertIn(word,out);self.assertIn('중단됐던 업데이트는 되돌렸고',out);self.assertIn('나중에 다시 진행됩니다',out)
                self.assertNotIn('그대로',out);self.assertNotIn('ilson open',out)
        # The next plain failure changed nothing, so the promise is true again.
        out,code,_=self.rerun(fetch=self.down)
        self.assertIn('일손 박스는 그대로입니다',out);self.assertNotIn('되돌렸고',out)
    def test_복구한_실행에서_관리자가_꺼져_있으면_알린다(self):
        self.admin_box()
        with patch.object(u,'activate_command',side_effect=ValueError('관리자 install 미완료')):out,code,_=self.rerun(fetch=self.down)
        self.assertEqual(code,1);self.assertIn('되돌렸고',out);self.assertIn('ilson open',out);self.assertNotIn('그대로',out)
        self.tearDownBox();self.admin_box()
        with patch.object(u,'activate_command'):out,code,_=self.rerun(fetch=self.down)
        self.assertIn('되돌렸고',out);self.assertNotIn('ilson open',out)
    def test_복구한_실행의_다른_거부는_문구를_바꾸지_않는다(self):
        m,a=self.killed_box()
        body=json.dumps(dict(m,archive='https://other.example/box.zip')).encode()
        out,code,_=self.rerun(fetch=lambda url:body)
        self.assertEqual(code,1);self.assertIn('배포 서버가 다른 묶음입니다',out);self.assertNotIn('되돌렸고',out)
    def test_임시파일_정리는_폴더를_건너뛰고_링크는_지운다(self):
        self.killed_box()
        folder=self.box/'lib'/(u.TEMP_PREFIX+'folder');folder.mkdir();(folder/'inside.txt').write_text('keep')
        target=self.root/'target';target.write_text('keep');link=self.box/'lib'/(u.TEMP_PREFIX+'link');link.symlink_to(target)
        dangling=self.box/'lib'/(u.TEMP_PREFIX+'dangling');dangling.symlink_to(self.root/'missing')
        out,code,_=self.rerun(fetch=self.down)
        self.assertNotIn('복구하지 못했습니다',out);self.assertIn('중단됐던 업데이트를 복구했습니다',out)
        self.assertEqual(self.journal(),'recovered');self.assertEqual(self.code(),(b'old',b'old2',b'old3'))
        self.assertEqual((folder/'inside.txt').read_text(),'keep');self.assertEqual(target.read_text(),'keep')
        self.assertFalse(link.is_symlink());self.assertFalse(dangling.is_symlink())
    def test_임시파일을_못지워도_복구는_성공이다(self):
        self.killed_box()
        real=Path.unlink
        def refuse(path,*args,**kwargs):
            if path.name.startswith(u.TEMP_PREFIX):raise PermissionError('locked')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',refuse):out,code,_=self.rerun(fetch=self.down)
        self.assertNotIn('복구하지 못했습니다',out);self.assertNotIn('일부가 새 버전',out);self.assertIn('중단됐던 업데이트를 복구했습니다',out)
        self.assertEqual(self.journal(),'recovered');self.assertEqual(self.code(),(b'old',b'old2',b'old3'))
    def test_임시파일_목록을_못읽어도_복구는_성공이다(self):
        self.killed_box()
        with patch.object(Path,'glob',side_effect=PermissionError('locked')):out,code,_=self.rerun(fetch=self.down)
        self.assertNotIn('복구하지 못했습니다',out);self.assertEqual(self.journal(),'recovered');self.assertEqual(self.code(),(b'old',b'old2',b'old3'))
    def test_복구는_죽은_쓰기의_임시파일만_지운다(self):
        self.killed_box()
        left=list((self.box/'lib').glob(u.TEMP_PREFIX+'*'))
        self.assertEqual(len(left),1,'the kill happens between the temp file and the rename')
        (self.box/'lib/tmpkeep').write_text('not ours');(self.box/'keep').mkdir();(self.box/'keep'/(u.TEMP_PREFIX+'x')).write_text('other folder')
        self.rerun(fetch=lambda url:(_ for _ in ()).throw(urllib.error.URLError('down')))
        self.assertEqual(list((self.box/'lib').glob(u.TEMP_PREFIX+'*')),[])
        self.assertEqual((self.box/'lib/tmpkeep').read_text(),'not ours');self.assertTrue((self.box/'keep'/(u.TEMP_PREFIX+'x')).exists())
    def test_복구가_실패하면_네트워크로_가지_않고_그대로라고_하지_않는다(self):
        self.killed_box()
        (self.box/'lib/two.sh').write_bytes(b'edited by a person')
        out,code,called=self.rerun()
        self.assertEqual(code,1);called.assert_not_called()
        self.assertIn('복구하지 못했습니다',out);self.assertIn('일부가 새 버전',out);self.assertNotIn('그대로',out)
        self.assertEqual(self.journal(),'applying')
    def test_check는_중단을_알리고_네트워크와_코드를_건드리지_않는다(self):
        self.killed_box();before=self.code()
        out,code,called=self.rerun('--check')
        self.assertEqual(code,1);called.assert_not_called();self.assertIn('ilson update 로 복구하세요',out);self.assertNotIn('그대로',out)
        self.assertEqual(self.code(),before);self.assertEqual(self.journal(),'applying')
    def test_rollback도_중단된_업데이트를_ilson_update로_안내한다(self):
        self.killed_box();before=self.code()
        out=io.StringIO()
        with patch('sys.stdout',out),patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli),'--rollback']),self.assertRaises(SystemExit):u.run()
        self.assertIn('ilson update 로 복구하세요',out.getvalue());self.assertEqual(self.code(),before)
    def test_다른_실행이_잠금을_쥐면_복구를_미루고_알린다(self):
        self.killed_box();before=self.code()
        with (self.box/'.updates/runtime.lock').open('a') as held:
            u.fcntl.flock(held,u.fcntl.LOCK_EX)
            real=u.fcntl.flock
            def refuse(stream,flags):
                if stream is not held:raise BlockingIOError()
                return real(stream,flags)
            with patch.object(u.fcntl,'flock',side_effect=refuse):out,code,called=self.rerun()
        self.assertEqual(code,1);called.assert_not_called();self.assertIn('완료 후 다시',out);self.assertEqual(self.code(),before)
    def admin_box(self,installed='1.0'):
        # What a kill after the admin stop leaves: pending, and no enabled marker, because stop removes it.
        if installed:u.save(self.box/'.updates/installed.json',dict(version=installed,files={}))
        m,a=self.killed_box()
        u.save(self.box/'.updates/activation.json',dict(version='2.0',status='pending'))
        self.assertFalse((self.box/'state/web-admin/enabled').exists())
        return m,a
    def activation(self):return u.read(self.box/'.updates/activation.json')
    def down(self,url):raise urllib.error.URLError('down')
    def test_네트워크가_없어도_복구한_코드로_관리자를_켠다(self):
        self.admin_box()
        with patch.object(u,'activate_command') as admin:out,code,_=self.rerun(fetch=self.down)
        self.assertEqual(code,1);self.assertEqual(self.code(),(b'old',b'old2',b'old3'))
        self.assertEqual([c.args[1] for c in admin.call_args_list],['install'])
        self.assertEqual(self.activation(),dict(version='1.0',status='active'))
        self.assertIn('복구한 코드로 관리자를 다시 켰습니다',out);self.assertIn('연결하지 못했습니다',out)
    def test_첫_업데이트가_죽은_박스는_버전없이_활성으로_둔다(self):
        self.admin_box(installed=None)
        with patch.object(u,'activate_command'):self.rerun(fetch=self.down)
        self.assertFalse((self.box/'.updates/installed.json').exists())
        self.assertEqual(self.activation(),dict(version=None,status='active'))
    def test_관리자를_못켜면_그렇게_알리고_다음_실행이_다시_시도한다(self):
        m,a=self.admin_box();served=self.served(m,a)
        with patch.object(u,'activate_command',side_effect=ValueError('관리자 install 미완료')):out,code,_=self.rerun(fetch=self.down)
        self.assertEqual(code,1);self.assertEqual(self.activation()['status'],'pending')
        self.assertIn('중단됐던 업데이트를 복구했습니다',out);self.assertIn('다시 켜지 못했습니다',out);self.assertNotIn('복구한 코드로 관리자를',out)
        self.assertIn('지금 ilson open 으로 켤 수 있고',out);self.assertIn('인터넷이 연결된 ilson update 도 다시 켭니다',out);self.assertNotIn('다음 ilson update 가 다시 시도합니다',out)
        self.assertEqual(self.code(),(b'old',b'old2',b'old3'));self.assertEqual(self.journal(),'recovered')
        with patch.object(u,'activate_command') as admin:out,code,_=self.rerun(fetch=lambda url:served[url])
        self.assertEqual(code,0,out);self.assertEqual([c.args[1] for c in admin.call_args_list],['stop','install'])
        self.assertEqual(self.activation(),dict(version='2.0',status='active'))
    def test_깨진_관리자_상태_파일도_복구를_막지_않고_사실대로_알린다(self):
        cases={'not json':b'not json','bad bytes':b'\xff\xfe\xff','list':b'[]','text':b'"x"','number':b'7'}
        for name,body in cases.items():
            with self.subTest(name):
                self.tearDownBox();self.killed_box()
                (self.box/'.updates/activation.json').write_bytes(body)
                with patch.object(u,'activate_command') as admin:out,code,_=self.rerun(fetch=self.down)
                self.assertEqual(code,1);admin.assert_not_called()
                self.assertEqual(self.journal(),'recovered');self.assertEqual(self.code(),(b'old',b'old2',b'old3'))
                self.assertIn('중단됐던 업데이트를 복구했습니다',out);self.assertIn('관리자 상태를 읽지 못했습니다',out);self.assertIn('ilson open',out)
                self.assertNotIn('Expecting',out);self.assertNotIn('codec',out);self.assertNotIn('예상하지 못한',out)
    def test_깨진_관리자_상태_파일이_있어도_온라인이면_업데이트를_마친다(self):
        m,a=self.killed_box();served=self.served(m,a)
        (self.box/'.updates/activation.json').write_bytes(b'not json')
        with patch.object(u,'activate_command') as admin:out,code,_=self.rerun(fetch=lambda url:served[url])
        self.assertEqual(code,0,out);admin.assert_not_called();self.assertNotIn('Expecting',out)
        self.assertEqual(self.code(),(b'new1',b'new2',b'new3'));self.assertEqual(u.read(self.box/'.updates/activation.json')['status'],'installed')
    def test_어떤_재시작_실패도_복구를_되돌리지_않는다(self):
        for error in (subprocess.TimeoutExpired('x',35),OSError('fork')):
            with self.subTest(error=type(error).__name__):
                self.tearDownBox()
                self.admin_box()
                with patch.object(u,'activate_command',side_effect=error):out,code,_=self.rerun(fetch=self.down)
                self.assertIn('다시 켜지 못했습니다',out);self.assertEqual(self.journal(),'recovered');self.assertEqual(self.activation()['status'],'pending')
    def tearDownBox(self):
        shutil.rmtree(self.box/'.updates',ignore_errors=True)
        (self.box/'lib/search.sh').write_bytes(b'old')
    def test_복구_뒤_관리자를_켜고_이어서_정상_업데이트한다(self):
        m,a=self.admin_box();served=self.served(m,a)
        marker=self.box/'state/web-admin/enabled';marker.parent.mkdir(parents=True)
        def like_the_real_admin(home,command):
            if command=='install':marker.write_text('1')
            else:marker.unlink()
        with patch.object(u,'activate_command',side_effect=like_the_real_admin) as admin:out,code,_=self.rerun(fetch=lambda url:served[url])
        self.assertEqual(code,0,out);self.assertEqual([c.args[1] for c in admin.call_args_list],['install','stop','install'])
        self.assertEqual(self.code(),(b'new1',b'new2',b'new3'));self.assertEqual(self.activation(),dict(version='2.0',status='active'))
    def test_대기표시가_없으면_관리자를_건드리지_않는다(self):
        for activation in (None,dict(version='1.0',status='active'),dict(version='1.0',status='installed')):
            with self.subTest(activation=activation):
                self.tearDownBox()
                self.killed_box()
                if activation:u.save(self.box/'.updates/activation.json',activation)
                with patch.object(u,'activate_command') as admin:self.rerun(fetch=self.down)
                admin.assert_not_called()
    def test_실행_잠금이_잡혀있으면_관리자도_켜지_않는다(self):
        self.admin_box();before=self.code()
        with (self.box/'.updates/runtime.lock').open('a') as held:
            real=u.fcntl.flock
            def refuse(stream,flags):
                if stream is not held and Path(stream.name).name=='runtime.lock':raise BlockingIOError()
                return real(stream,flags)
            with patch.object(u.fcntl,'flock',side_effect=refuse),patch.object(u,'activate_command') as admin:out,code,called=self.rerun()
        self.assertEqual(code,1);admin.assert_not_called();called.assert_not_called()
        self.assertEqual(self.code(),before);self.assertEqual(self.activation()['status'],'pending')
    def test_주소없는_새설치는_수동과_예약_모두_기본주소에서_받는다(self):
        for env in ({},{'ILSON_UPDATE_SKIP_IF_NO_FEED':'1'}):
            with self.subTest(env=env),patch.dict(u.os.environ,env):
                (self.box/'lib/search.sh').write_bytes(b'old')
                updates=self.box/'.updates'
                if updates.exists():shutil.rmtree(updates)
                fetch=self.run_main(feed=u.DEFAULT_FEED)
                self.assertEqual(fetch.call_args_list[0].args[0],u.DEFAULT_FEED)
                self.assertEqual(fetch.call_args_list[1].args[0],u.DEFAULT_FEED.rsplit('/',1)[0]+'/box.zip')
                self.assertEqual((self.box/'lib/search.sh').read_bytes(),b'new');self.assertEqual(self.saved(),u.DEFAULT_FEED+'\n')

    def owned_box(self,disk,owned,key='cli/tools/update.py'):
        target=self.roots[key.split('/',1)[0]]/key.split('/',1)[1];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(disk)
        u.save(self.box/'.updates/installed.json',{'version':'1.0','files':{key:u.digest(owned)}})
        return target
    def test_소스재설치한_빈주소_updater는_주소기록본_소유해시와_일치(self):
        v1=b"X=1\nFEED=''\nY=2\n";v2=b"X=1\nFEED=''\nY=3\n";new=u.stamp_feed(v2,self.FEED)
        cases={'plain reinstall':v1,'other stamped feed':u.stamp_feed(v1,'https://other.example/latest-v2.json')}
        for name,disk in cases.items():
            with self.subTest(name):
                target=self.owned_box(disk,u.stamp_feed(v1,self.FEED))
                m,a=self.bundle([('cli','tools/update.py',new,None)],'1.1');u.apply(self.roots,m,a)
                self.assertEqual(target.read_bytes(),new)
                self.assertEqual(u.read(self.box/'.updates/installed.json')['files']['cli/tools/update.py'],u.digest(new))
    def test_updater의_주소외_수정과_다른파일은_계속차단(self):
        v1=b"X=1\nFEED=''\nY=2\n";new=u.stamp_feed(b"X=1\nFEED=''\nY=3\n",self.FEED)
        for name,disk in {'code edit':v1+b'Z=9\n','plain code edit':b"X=2\nFEED=''\nY=2\n",'second FEED line':v1+b"FEED=''\n",'no FEED line':b'X=1\nY=2\n'}.items():
            with self.subTest(name):
                target=self.owned_box(disk,u.stamp_feed(v1,self.FEED))
                m,a=self.bundle([('cli','tools/update.py',new,None)],'1.1')
                with self.assertRaisesRegex(ValueError,'보존'):u.apply(self.roots,m,a)
                self.assertEqual(target.read_bytes(),disk)
        # The FEED tolerance belongs to the updater only.
        target=self.owned_box(v1,u.stamp_feed(v1,self.FEED),'box/lib/tool.py')
        m,a=self.bundle([('box','lib/tool.py',new,None)],'1.1')
        with self.assertRaisesRegex(ValueError,'보존'):u.apply(self.roots,m,a)
        self.assertEqual(target.read_bytes(),v1)

    def test_하위버전_주소나_충돌로_실패한_실행은_주소를_기억하지않음(self):
        u.save(self.box/'.updates/installed.json',{'version':'2.0','files':{}})
        with self.assertRaisesRegex(ValueError,'이전 버전'):self.run_main('--feed',self.FEED)
        self.assertIsNone(self.saved())
        (self.box/'.updates/installed.json').unlink();(self.box/'lib/search.sh').write_bytes(b'user edit')
        with self.assertRaisesRegex(ValueError,'보존'):self.run_main('--feed',self.FEED)
        self.assertIsNone(self.saved())

    def reinstalled_box(self,disk,owned,previous='2026.10.16.3'):
        (self.cli/'tools').mkdir(exist_ok=True);(self.cli/'tools/update.py').write_bytes(disk)
        u.save(self.box/'.updates/installed.json',{'version':previous,'files':{'cli/tools/update.py':u.digest(owned)}})
        (self.box/'.updates/feed').write_text(self.FEED+'\n')
    def test_C_구버전박스를_새설치기로_재설치해도_브리지배포를_받는다(self):
        # The box owns the legacy hard-coded updater; install.sh replaced it with this source (FEED='') and carried the address.
        legacy=(ROOT/'tests/fixtures/legacy_update_v2.py').read_bytes();plain=(ROOT/'tools/update.py').read_bytes()
        bridge=u.stamp_feed(plain,self.FEED);self.reinstalled_box(plain,legacy)
        self.run_main(rows=[('cli','tools/update.py',bridge,legacy),('cli','ilson',b'#',None)],version='2026.10.21.1')
        self.assertEqual((self.cli/'tools/update.py').read_bytes(),bridge)
        state=u.read(self.box/'.updates/installed.json')
        self.assertEqual((state['version'],state['files']['cli/tools/update.py']),('2026.10.21.1',u.digest(bridge)))
    def test_D_새main으로_재설치한_박스가_그_main의_배포를_받는다(self):
        older=b"X=1\nFEED=''\n";newer=b"X=2\nFEED=''\n";release=u.stamp_feed(newer,self.FEED)
        self.reinstalled_box(newer,u.stamp_feed(older,self.FEED))
        self.run_main(rows=[('cli','tools/update.py',release,None)],version='2026.10.21.1')
        self.assertEqual((self.cli/'tools/update.py').read_bytes(),release)
    def test_배포본과_코드가_다른_재설치_updater는_차단(self):
        older=b"X=1\nFEED=''\n";newer=b"X=2\nFEED=''\n";release=u.stamp_feed(newer,self.FEED)
        tricks={'code edit':newer+b'Z=9\n','second FEED line':newer+b"FEED=''\n",'CRLF copy':newer.replace(b'\n',b'\r\n'),
                'CR hidden assignment':b"X=2\nFEED=''\rFEED='https://evil.example/latest-v2.json'\n"}
        for name,disk in tricks.items():
            with self.subTest(name):
                self.reinstalled_box(disk,u.stamp_feed(older,self.FEED))
                with self.assertRaisesRegex(ValueError,'보존'):self.run_main(rows=[('cli','tools/update.py',release,None)],version='2026.10.21.1')
                self.assertEqual((self.cli/'tools/update.py').read_bytes(),disk)
    def test_CR이_섞인_소스에는_주소를_기록하거나_읽지않음(self):
        for source in (b"X=1\r\nFEED=''\n",b"FEED=''\rFEED='https://evil.example/x'\n"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):u.stamp_feed(source,self.FEED)
                with self.assertRaises(ValueError):u.feed_of(source)
