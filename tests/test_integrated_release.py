import importlib.util,io,json,os,subprocess,tempfile,unittest,zipfile,sys
from contextlib import redirect_stderr,redirect_stdout
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'template/lib'))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
u=load('integrated_updater',ROOT/'tools/update.py')
FEED='https://feed.example/pack-library/downloads/box/latest-v2.json'
def research_pack(folder,changes=None,name='pack.zip'):
 # A pack built from the current template sources, as the release policy requires. changes: {pack path: bytes or None to drop}.
 files={p.name:p.read_bytes() for p in (ROOT/'template/lib/research').glob('*.py')}
 web=ROOT/'template/web/current/pack-library'
 files.update({'web/'+p.relative_to(web).as_posix():p.read_bytes() for p in sorted(web.rglob('*')) if p.is_file()})
 files.update(changes or {})
 files={k:v for k,v in files.items() if v is not None}
 pack=Path(folder)/name
 with zipfile.ZipFile(pack,'w') as z:
  z.writestr('manifest.json',json.dumps({'version':'0.15.0'}))
  for key,data in files.items():z.writestr(key,data)
 return pack
class IntegratedReleaseTests(unittest.TestCase):
 def test_관리자중첩코드와아이콘은_설정제외하고허용(self):
  for area,p in [('box','lib/research/engine.py'),('box','lib/social/http.py'),('box','lib/current_browser_check.js'),('box','web/current/assets/sns/threads.svg')]:self.assertTrue(u.allowed(area,p),p)
  for p in ['lib/research/.env','lib/social/settings.json','lib/research/secret.txt','vault/user.py']:self.assertFalse(u.allowed('box',p))
 def test_활성업무가있으면_배포전중단(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);p=home/'.workspace';p.mkdir();db=sqlite3.connect(p/'work.sqlite3');db.executescript("CREATE TABLE jobs(status TEXT); CREATE TABLE posts(status TEXT); INSERT INTO jobs VALUES('running');");db.commit();db.close()
   with self.assertRaisesRegex(ValueError,'실행'):u.ensure_idle(home)
 def test_관리자와팩엔진의배포정본일치(self):
  b=load('integrated_builder',ROOT/'tools/build_release.py')
  with tempfile.TemporaryDirectory() as tmp:
   pack=research_pack(tmp)
   r=b.build(Path(tmp),'9999.1',pack,FEED)
   with zipfile.ZipFile(Path(tmp)/r['archive']) as z:
    self.assertEqual(z.read('box/lib/research/engine.py'),z.read('box/packs/research/0.15.0/engine.py'))
    self.assertEqual(z.read('box/web/current/pack-library/research.js'),z.read('box/packs/research/0.15.0/web/research.js'))
if __name__=='__main__':unittest.main()

class RuntimeGateTests(unittest.TestCase):
 def test_실행중업무가잠금중이면_업데이트진입거부(self):
  from runtime_gate import running
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp)
   with running(home):
    with self.assertRaisesRegex(ValueError,'실행'): 
     with u.runtime_lock(home):pass
   with u.runtime_lock(home):
    with self.assertRaises(BlockingIOError):
     with running(home):pass
 def test_이미지첨부는_실행에전달하지만_업무장부에저장하지않음(self):
  import base64,io
  from PIL import Image
  from test_mini_workspace import FakeProviders,admin
  from mini_workspace import Workspace
  from current_ui import CurrentUI
  class Provider(FakeProviders):
   def research(self,home,args,progress):
    self.received=args.get('image');return super().research(home,args,progress)
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);(home/'state').mkdir();(home/'vault').mkdir();provider=Provider()
   buf=io.BytesIO();Image.new('RGB',(4,4),'red').save(buf,format='JPEG');data=base64.b64encode(buf.getvalue()).decode();attachment={'media_type':'image/jpeg','data':data}
   w=Workspace(home,admin.Files(home),providers=provider)
   try:
    ui=CurrentUI(w);q=ui.dispatch('POST','/api/research/jobs',data={'question':'이 제품 구매처','period':'all','options':{'image':attachment}})
    self.assertNotIn(data,(home/'.workspace/work.sqlite3').read_bytes().decode(errors='ignore'))
    w.run_next_job();self.assertEqual(provider.received,attachment);self.assertEqual(w.job(q['id'])['status'],'done')
    self.assertNotIn(data,(home/'.workspace/work.sqlite3').read_bytes().decode(errors='ignore'))
    self.assertEqual(w.research_images,{})
   finally:w.close()

class StampedReleaseTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.b=load('stamped_builder',ROOT/'tools/build_release.py')
  cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)/'stage'
  cls.release=cls.b.build(cls.out,'9999.3',research_pack(cls.tmp.name),FEED)
  with zipfile.ZipFile(cls.out/cls.release['archive']) as z:cls.members={i.filename:z.read(i) for i in z.infolist()}
  cls.archive=(cls.out/cls.release['archive']).read_bytes()
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def test_배포updater에_주소를기록하고_manifest해시도_기록본(self):
  body=self.members['cli/tools/update.py'];source=(ROOT/'tools/update.py').read_bytes()
  self.assertEqual(u.feed_of(body),FEED);self.assertEqual(u.feed_of(source),'')
  self.assertEqual(u.unstamp(body),source);compile(body,'update.py','exec')
  entry=[f for f in self.release['files'] if f['area']=='cli' and f['path']=='tools/update.py']
  self.assertEqual(len(entry),1);self.assertEqual(entry[0]['sha256'],u.digest(body))
  # History hashes are of plain git versions, never of the stamped body.
  self.assertNotIn(u.digest(body),entry[0]['previous_sha256'])
  head=subprocess.run(['git','show','HEAD:tools/update.py'],cwd=ROOT,capture_output=True)
  if head.returncode==0:self.assertIn(u.digest(head.stdout),entry[0]['previous_sha256'])
 def test_주소없이_또는_http주소로는_빌드거부(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ):
   os.environ.pop('ILSON_RELEASE_FEED',None);pack=research_pack(tmp)
   for feed in (None,'','http://feed.example/latest-v2.json'):
    with self.subTest(feed=feed),self.assertRaises(ValueError):self.b.build(Path(tmp)/'out','9999.4',pack,feed)
   self.assertFalse((Path(tmp)/'out').exists())
   os.environ['ILSON_RELEASE_FEED']=FEED;r=self.b.build(Path(tmp)/'env','9999.4',pack)
   with zipfile.ZipFile(Path(tmp)/'env'/r['archive']) as z:self.assertEqual(u.feed_of(z.read('cli/tools/update.py')),FEED)
 def test_저장소와_다른_리서치팩은_빌드거부(self):
  knowledge=(ROOT/'template/web/current/pack-library/knowledge.js').read_bytes()
  cases={'template/web/current/pack-library/knowledge.js':{'web/knowledge.js':knowledge.replace(b'mode',b'mode/*stale*/',1)+b'\n// stale pack copy\n'},
         'template/web/current/pack-library/extra.js':{'web/extra.js':b'const extra=1;'},
         'template/lib/research/engine.py':{'engine.py':b'MARKER=123'},
         'template/web/current/pack-library/research.js':{'web/research.js':None},
         'template/lib/research/run.py':{'run.py':None}}
  with tempfile.TemporaryDirectory() as tmp:
   for path,changes in cases.items():
    with self.subTest(path):
     pack=research_pack(tmp,changes,'stale.zip')
     with self.assertRaisesRegex(ValueError,'리서치 팩이 저장소와 다릅니다') as refused:self.b.build(Path(tmp)/'out','9999.6',pack,FEED)
     self.assertIn(path,str(refused.exception));self.assertFalse((Path(tmp)/'out').exists())
 def test_저장소와_같은_리서치팩은_같은바이트로_배포(self):
  for rel,data in self.members.items():
   if rel.startswith('box/packs/research/0.15.0/web/'):
    self.assertEqual(data,(ROOT/'template/web/current/pack-library'/rel.split('/web/',1)[1]).read_bytes())
    self.assertEqual(data,self.members['box/web/current/pack-library/'+rel.split('/web/',1)[1]])
  self.assertEqual(self.members['box/lib/research/engine.py'],(ROOT/'template/lib/research/engine.py').read_bytes())
 def test_구버전updater가_브리지배포를_받아_주소기록본을_설치(self):
  legacy=load('legacy_update_v2',ROOT/'tests/fixtures/legacy_update_v2.py')
  m=self.release
  rejected=[f['area']+'/'+f['path'] for f in m['files'] if not legacy.allowed(f['area'],f['path'])]
  self.assertEqual(rejected,[])
  with tempfile.TemporaryDirectory() as tmp:
   roots={'box':Path(tmp)/'box','cli':Path(tmp)/'cli'}
   for p in roots.values():p.mkdir()
   old=(ROOT/'tests/fixtures/legacy_update_v2.py').read_bytes();(roots['cli']/'tools').mkdir();(roots['cli']/'tools/update.py').write_bytes(old)
   legacy.save(roots['box']/'.updates/installed.json',{'version':'2026.10.13.6','files':{'cli/tools/update.py':legacy.digest(old)}})
   with redirect_stdout(io.StringIO()):legacy.apply(roots,m,self.archive)
   installed=(roots['cli']/'tools/update.py').read_bytes()
   self.assertEqual(installed,self.members['cli/tools/update.py']);self.assertEqual(u.feed_of(installed),FEED)
   self.assertEqual(legacy.read(roots['box']/'.updates/installed.json')['files']['cli/tools/update.py'],u.digest(installed))
   fresh=load('installed_updater',roots['cli']/'tools/update.py');self.assertEqual(fresh.FEED,FEED)
   self.assertEqual(fresh.resolve_feed(roots['box']),FEED)

class ReleaseCommandTests(unittest.TestCase):
 def setUp(self):
  self.b=load('command_builder',ROOT/'tools/build_release.py')
 def test_작업트리가_깨끗하지않으면_명령행빌드를_거부(self):
  args=['--output','out','--version','9999.7','--pack','pack.zip','--feed',FEED,'--no-preserve-from']
  with patch.object(self.b,'dirty_files',return_value=[' M tools/update.py']),patch.object(self.b,'build') as build:
   with self.assertRaises(SystemExit) as stop:self.b.main(args)
   build.assert_not_called();self.assertIn('--allow-dirty',str(stop.exception.code))
   build.return_value={'version':'9999.7','files':[]}
   with redirect_stdout(io.StringIO()):self.b.main(args+['--allow-dirty'])
   build.assert_called_once()
  with patch.object(self.b,'dirty_files',return_value=[]),patch.object(self.b,'build',return_value={'version':'9999.7','files':[]}) as build:
   with redirect_stdout(io.StringIO()):self.b.main(args)
   self.assertEqual(build.call_args.args[3],FEED)
 def test_git_status로_수정과_추적안된파일을_찾는다(self):
  with tempfile.TemporaryDirectory() as tmp:
   repo=Path(tmp);git=lambda *a:subprocess.run(['git',*a],cwd=repo,capture_output=True,check=True)
   git('init','-q');(repo/'a.txt').write_text('1');git('add','a.txt')
   git('-c','user.name=t','-c','user.email=t@example.invalid','commit','-qm','init')
   self.assertEqual(self.b.dirty_files(repo),[])
   (repo/'a.txt').write_text('2');(repo/'new.txt').write_text('x')
   self.assertEqual(sorted(line[3:] for line in self.b.dirty_files(repo)),['a.txt','new.txt'])

class PreserveCarryTests(unittest.TestCase):
 # Reviewed owner edits (preserve_sha256) ride from the previous release manifest into every new one.
 KEY='box/lib/job-rules.md'
 @classmethod
 def setUpClass(cls):
  cls.b=load('preserve_builder',ROOT/'tools/build_release.py')
  cls.tmp=tempfile.TemporaryDirectory();base=Path(cls.tmp.name)
  cls.edited=(ROOT/'template/lib/job-rules.md').read_bytes()+'\n- 소유자 수정: 예약 검색은 WebSearch\n'.encode()
  cls.edit_hash=u.digest(cls.edited)
  (base/'prev').mkdir();cls.previous=base/'prev/release-9999.8.json'
  cls.previous.write_text(json.dumps({'schema':1,'version':'9999.8','files':[
   {'area':'box','path':'lib/job-rules.md','sha256':'1'*64,'previous_sha256':['2'*64],'preserve_sha256':[cls.edit_hash]},
   {'area':'box','path':'lib/retired-rules.md','sha256':'3'*64,'previous_sha256':[],'preserve_sha256':['4'*64]},
   {'area':'cli','path':'ilson','sha256':'5'*64,'previous_sha256':[]}]}))
  cls.stage=base/'stage';log=io.StringIO()
  with redirect_stdout(log):cls.release=cls.b.build(cls.stage,'9999.9',research_pack(cls.tmp.name),FEED,preserve_from=cls.previous)
  cls.log=log.getvalue();cls.archive=(cls.stage/cls.release['archive']).read_bytes()
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def previous_with(self,folder,values):
  prev=Path(folder)/'release-bad.json'
  prev.write_text(json.dumps({'files':[{'area':'box','path':'lib/job-rules.md','sha256':'1'*64,'previous_sha256':[],'preserve_sha256':values}]}))
  return prev
 def test_이전manifest의_보존해시를_같은자리로_이월(self):
  written=json.loads((self.stage/'release-9999.9.json').read_text())
  for manifest in (self.release,written):
   entries={f['area']+'/'+f['path']:f for f in manifest['files']}
   self.assertEqual(entries[self.KEY]['preserve_sha256'],[self.edit_hash])
   # Same key order as the hand-edited 2026.10.16.3 manifest.
   self.assertEqual(list(entries[self.KEY]),['area','path','sha256','previous_sha256','preserve_sha256'])
   self.assertEqual([k for k,f in entries.items() if 'preserve_sha256' in f],[self.KEY])
  self.assertEqual([line for line in self.log.splitlines() if self.KEY in line],['보존 해시 이월: '+self.KEY+' (1개)'])
 def test_새배포에없는경로는_메모만남기고_건너뜀(self):
  self.assertNotIn('box/lib/retired-rules.md',[f['area']+'/'+f['path'] for f in self.release['files']])
  self.assertIn('보존 해시 이월 건너뜀(새 배포에 없는 파일): box/lib/retired-rules.md',self.log.splitlines())
 def test_잘못된_보존해시는_빌드거부(self):
  bad={'uppercase':[self.edit_hash.upper()],'short':[self.edit_hash[:63]],'long':[self.edit_hash+'0'],'not hex':['g'*64],
       'newline':[self.edit_hash+'\n'],'not a list':self.edit_hash,'empty':[],'not text':[123]}
  with tempfile.TemporaryDirectory() as tmp:
   pack=research_pack(tmp)
   for name,values in bad.items():
    with self.subTest(name):
     with self.assertRaisesRegex(ValueError,'preserve_sha256'):self.b.build(Path(tmp)/'out','9999.10',pack,FEED,preserve_from=self.previous_with(tmp,values))
     self.assertFalse((Path(tmp)/'out').exists())
 def test_새배포_자기해시와_같은_보존해시는_빌드거부(self):
  own=u.digest((ROOT/'template/lib/job-rules.md').read_bytes())
  with tempfile.TemporaryDirectory() as tmp:
   with redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,self.KEY):
    self.b.build(Path(tmp)/'out','9999.11',research_pack(tmp),FEED,preserve_from=self.previous_with(tmp,[self.edit_hash,own]))
   self.assertFalse((Path(tmp)/'out').exists())
 def test_명령행은_보존이월_선택없이_빌드거부(self):
  args=['--output','out','--version','9999.7','--pack','pack.zip','--feed',FEED]
  with patch.object(self.b,'dirty_files',return_value=[]),patch.object(self.b,'build',return_value={'version':'9999.7','files':[]}) as build:
   with self.assertRaises(SystemExit) as stop:self.b.main(args)
   build.assert_not_called()
   for flag in ('--preserve-from','--no-preserve-from'):self.assertIn(flag,str(stop.exception.code))
   with redirect_stdout(io.StringIO()):self.b.main(args+['--no-preserve-from'])
   self.assertIsNone(build.call_args.kwargs['preserve_from'])
   with redirect_stdout(io.StringIO()):self.b.main(args+['--preserve-from','prev/release-9999.6.json'])
   self.assertEqual(build.call_args.kwargs['preserve_from'],Path('prev/release-9999.6.json'))
   with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):self.b.main(args+['--no-preserve-from','--preserve-from','x.json'])
   self.assertEqual(build.call_count,2)
 def test_게시검증을_통과하고_최신포인터에_보존해시가_남는다(self):
  publisher=load('preserve_publisher',ROOT/'tools/publish_release.py');base=FEED.rsplit('/',1)[0]
  with tempfile.TemporaryDirectory() as tmp:
   server=Path(tmp)/'box';server.mkdir()
   (server/'install-updater.sh').write_text("#!/bin/bash\nUPDATER='updater-2026.10.13.6.py'\nSHA='"+'0'*64+"'\n")
   urlopen=lambda url,timeout=None:io.BytesIO((server/url[len(base)+1:]).read_bytes())
   with patch.object(publisher.urllib.request,'urlopen',side_effect=urlopen),redirect_stdout(io.StringIO()):publisher.publish(self.stage,server,base)
   for name in ('latest-v2.json','release-9999.9.json'):
    self.assertEqual((server/name).read_bytes(),(self.stage/'release-9999.9.json').read_bytes())
    entry=[f for f in json.loads((server/name).read_text())['files'] if f['area']+'/'+f['path']==self.KEY]
    self.assertEqual(entry[0]['preserve_sha256'],[self.edit_hash])
 def test_구버전과_현재updater가_보존해시와_같은_소유자수정을_지킨다(self):
  legacy=load('preserve_legacy_update',ROOT/'tests/fixtures/legacy_update_v2.py')
  for name,module in (('legacy v2',legacy),('current',u)):
   with self.subTest(name),tempfile.TemporaryDirectory() as tmp:
    roots={'box':Path(tmp)/'box','cli':Path(tmp)/'cli'}
    for p in roots.values():p.mkdir()
    rules=roots['box']/'lib/job-rules.md';rules.parent.mkdir();rules.write_bytes(self.edited)
    log=io.StringIO()
    with redirect_stdout(log):module.apply(roots,self.release,self.archive)
    self.assertEqual(rules.read_bytes(),self.edited)
    self.assertIn('기존 확장 기능 보존: '+self.KEY,log.getvalue())
    self.assertNotIn(self.KEY,module.read(roots['box']/'.updates/installed.json')['files'])
    # An edit nobody reviewed still stops the update.
    rules.write_bytes(self.edited+b'unreviewed\n')
    with redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,self.KEY):module.apply(roots,self.release,self.archive)
    self.assertEqual(rules.read_bytes(),self.edited+b'unreviewed\n')
