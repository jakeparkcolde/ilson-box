"""새 코드 배포 경로에서 관리자 화면과 운영 파일의 보존을 검증한다."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('updater',ROOT/'tools/update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class WebAdminUpdateTests(unittest.TestCase):
    def test_관리자전체갱신에도_보고서_토큰_설정_활성상태는_그대로(self):
        with tempfile.TemporaryDirectory() as folder:
            roots={area:Path(folder)/area for area in ['box','cli']}
            for root in roots.values():root.mkdir()
            preserved={}
            for name in ['vault/report.md','state/web-admin/token','state/web-admin/config.json','state/web-admin/enabled','state/pairing.json','launchd/jobs.conf']:
                p=roots['box']/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('user data: '+name);preserved[p]=p.read_bytes()
            files=[];buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w') as z:
                for area,name in [('box','web/index.html'),('box','lib/web-admin-server.py'),('cli','ilson')]:
                    body=b'# new version\n' if name.endswith('.py') else b'new'
                    z.writestr(area+'/'+name,body)
                    files.append(dict(area=area,path=name,sha256=u.digest(body),previous_sha256=[]))
            data=buf.getvalue();m=dict(schema=1,version='1.0',files=files,archive_sha256=u.digest(data))
            u.apply(roots,m,data)
            for p,b in preserved.items():self.assertEqual(p.read_bytes(),b)
            self.assertEqual((roots['box']/'web/index.html').read_bytes(),b'new')
            store=roots['box']/'.updates';u.rollback(roots,store,u.read(store/'journal.json'))
            self.assertFalse((roots['box']/'web/index.html').exists())
            for p,b in preserved.items():self.assertEqual(p.read_bytes(),b)
    def test_업데이트_명령이_확인옵션을_새도구로_전달(self):
        with tempfile.TemporaryDirectory() as folder:
            cli=Path(folder);(cli/'tools').mkdir();(cli/'ilson').write_bytes((ROOT/'ilson').read_bytes())
            (cli/'tools/update.py').write_text('import sys; assert "--check" in sys.argv; print("safe updater")')
            result=subprocess.run(['bash',str(cli/'ilson'),'update','--check'],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('safe updater',result.stdout)

if __name__=='__main__':unittest.main()
