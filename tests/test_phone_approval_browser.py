"""Isolated approval flow in headless WebKit; no Chrome or external APIs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CORE=os.environ.get('PLAYWRIGHT_CORE')

@unittest.skipUnless(shutil.which('node') and CORE and Path(CORE).is_dir(), 'set PLAYWRIGHT_CORE to playwright-core with WebKit')
class ApprovalBrowserTest(unittest.TestCase):
    def test_local_approval_flow(self):
        with tempfile.TemporaryDirectory(prefix='approval-browser-') as folder:
            proc=subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/admin_navigation_server.py'),folder],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,ILSON_TEST_APPROVAL_CONTEXT='1'))
            try:
                port=proc.stdout.readline().strip()
                self.assertTrue(port.isdigit(),'isolated manager did not start')
                home=Path(folder)/'box'; pending=home/'vault/reports/pending'; pending.mkdir(parents=True)
                (pending/'draft.md').write_text('확인할 초안 내용',encoding='utf-8')
                token=home/'state/web-admin/token'
                result=subprocess.run(['node',str(ROOT/'tests/fixtures/approval_browser.cjs'),'http://127.0.0.1:'+port,str(token)],env=os.environ.copy(),capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual((home/'vault/reports/approved/draft.md').read_text(encoding='utf-8'),'확인할 초안 내용')
            finally:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
                proc.stdout.close(); proc.stderr.close()

if __name__=='__main__': unittest.main()
