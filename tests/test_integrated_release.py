import importlib.util,json,tempfile,unittest,zipfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'template/lib'))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
u=load('integrated_updater',ROOT/'tools/update.py')
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
   pack=Path(tmp)/'pack.zip'
   with zipfile.ZipFile(pack,'w') as z:
    z.writestr('manifest.json',json.dumps({'version':'0.15.0'}));z.writestr('engine.py','MARKER=123');z.writestr('web/research.js','const marker=123;')
   r=b.build(Path(tmp),'9999.1',pack)
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
