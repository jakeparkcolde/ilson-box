import importlib.util,json,tempfile,os,subprocess
from pathlib import Path
A=Path('/Users/koldeumaegmini/orca/workspaces/agents/ilson-box-safe-update')
spec=importlib.util.spec_from_file_location('u',A/'tools/update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
old=Path('/Users/koldeumaegmini/agents/webapp/ilson/downloads/box');new=Path('/tmp/ilson-motion-release-20261013-7')
with tempfile.TemporaryDirectory() as t:
 root=Path(t);roots={'box':root/'box','cli':root/'cli'}
 for folder,v in [(old,'2026.10.13.6'),(new,'2026.10.13.7')]:
  if v.endswith('.7'):
   preserved=roots['box']/'projects/motion/existing/source.html';preserved.parent.mkdir(parents=True);preserved.write_text('USER PROJECT')
  u.apply(roots,json.loads((folder/f'release-{v}.json').read_text()),(folder/f'ilson-box-{v}.zip').read_bytes())
 assert preserved.read_text()=='USER PROJECT'
 home=root/'user';bin=home/'.local/bin';bin.mkdir(parents=True)
 fake=bin/'claude';fake.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n');fake.chmod(0o755)
 env=dict(os.environ,HOME=str(home),ILSON_HOME=str(roots['box']))
 q=subprocess.run(['bash',str(roots['cli']/'ilson'),'motion','15초 영상 $(touch SHOULD_NOT_EXIST)'],env=env,text=True,capture_output=True)
 assert q.returncode==0,q.stderr
 assert str(roots['box']) in q.stdout and '15초 영상 $(touch SHOULD_NOT_EXIST)' in q.stdout
 assert not (roots['box']/'SHOULD_NOT_EXIST').exists()
 (roots['box']/'state').mkdir();(roots['box']/'state/sandbox').touch()
 q=subprocess.run(['bash',str(roots['cli']/'ilson'),'motion'],env=env,text=True,capture_output=True);assert q.returncode!=0
 print('PASS: .6→.7 적용 / 작품 보존 / CLI 전달·작업폴더 / 셸 주입 방지 / sandbox 차단')
