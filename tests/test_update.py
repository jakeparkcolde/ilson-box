import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
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

class FeedTests(unittest.TestCase):
    FEED='https://feed.example/box/latest-v2.json'
    def setUp(self):
        env=patch.dict(u.os.environ);env.start();self.addCleanup(env.stop)
        for name in ('ILSON_UPDATE_FEED','ILSON_UPDATE_SKIP_IF_NO_FEED'):u.os.environ.pop(name,None)
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

    def test_주소_우선순위는_인자_환경_내장_저장파일(self):
        (self.box/'.updates').mkdir();(self.box/'.updates/feed').write_text(' https://saved.example/latest-v2.json \n')
        with patch.object(u,'FEED','https://stamped.example/latest-v2.json'),patch.dict(u.os.environ,ILSON_UPDATE_FEED='https://env.example/latest-v2.json'):
            self.assertEqual(u.resolve_feed(self.box,'https://arg.example/latest-v2.json'),'https://arg.example/latest-v2.json')
            self.assertEqual(u.resolve_feed(self.box),'https://env.example/latest-v2.json')
        with patch.object(u,'FEED','https://stamped.example/latest-v2.json'):self.assertEqual(u.resolve_feed(self.box),'https://stamped.example/latest-v2.json')
        self.assertEqual(u.resolve_feed(self.box),'https://saved.example/latest-v2.json')
    def test_링크_http_빈주소는_거부하고_없으면_안내(self):
        with self.assertRaises(u.MissingFeed) as missing:u.resolve_feed(self.box)
        self.assertIn('ilson update --feed',str(missing.exception))
        for bad in ['http://feed.example/latest-v2.json','','https://','https://feed.example/a b']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):u.resolve_feed(self.box,bad)
        with patch.dict(u.os.environ,ILSON_UPDATE_FEED='http://feed.example/x'),self.assertRaises(ValueError):u.resolve_feed(self.box)
        store=self.box/'.updates';store.mkdir();real=self.root/'real-feed';real.write_text(self.FEED)
        (store/'feed').symlink_to(real)
        with self.assertRaisesRegex(ValueError,'링크') as linked:u.resolve_feed(self.box)
        self.assertNotIsInstance(linked.exception,u.MissingFeed)
        with self.assertRaisesRegex(ValueError,'링크'):u.remember_feed(self.box,self.FEED)
        self.assertEqual(real.read_text(),self.FEED)
        (store/'feed').unlink();(store/'feed').write_text('http://feed.example/latest-v2.json\n')
        with self.assertRaises(ValueError) as plain:u.resolve_feed(self.box)
        self.assertNotIsInstance(plain.exception,u.MissingFeed)
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
    def test_주소없음_예약실행은_건너뛰고_수동실행은_안내후_실패(self):
        out=io.StringIO();err=io.StringIO()
        with patch.dict(u.os.environ,ILSON_UPDATE_SKIP_IF_NO_FEED='1'),patch.object(u,'fetch') as fetch,patch('sys.stdout',out):
            with patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli)]):u.main()
        fetch.assert_not_called();self.assertIn('건너뜁니다',out.getvalue())
        with patch.object(u,'fetch') as fetch,patch('sys.stderr',err),patch.object(u.sys,'argv',['update.py','--home',str(self.box),'--cli',str(self.cli)]):
            with self.assertRaises(SystemExit) as stop:u.main()
        self.assertEqual(stop.exception.code,1);fetch.assert_not_called();self.assertIn('ilson update --feed',err.getvalue())

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
