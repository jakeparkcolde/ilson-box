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
