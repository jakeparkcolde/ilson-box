"""가상 파일과 가짜 Claude만 사용하는 격리 WebKit 화면 시험."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_inbox_files import make_pdf

ROOT=Path(__file__).resolve().parents[1]
CORE=os.environ.get('PLAYWRIGHT_CORE')
@unittest.skipUnless(shutil.which('node') and CORE and Path(CORE).is_dir(),'set PLAYWRIGHT_CORE with WebKit')
class InboxBrowserTests(unittest.TestCase):
    def test_pdf_review_consent_and_separate_approval(self):
        with tempfile.TemporaryDirectory(prefix='ilson-inbox-browser-') as temp:
            proc=subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/inbox_browser_server.py'),temp],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                port=proc.stdout.readline().strip();self.assertTrue(port.isdigit())
                box=Path(temp)/'box';folder=box/'vault/inbox';folder.mkdir();(box/'vault/company').mkdir()
                source=folder/'synthetic.pdf';source.write_bytes(make_pdf(2))
                r=subprocess.run(['node',str(ROOT/'tests/fixtures/inbox_browser.cjs'),'http://127.0.0.1:'+port,str(box/'state/web-admin/token')],capture_output=True,text=True,timeout=90,env=os.environ.copy())
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertTrue(source.is_file())
                self.assertIn('사람이 확인한 가상 금액',next((box/'vault/company').glob('*.md')).read_text())
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                output=proc.stdout.read()+proc.stderr.read()
                proc.stdout.close();proc.stderr.close()
                self.assertNotIn('가상 금액',output)
                self.assertNotIn('확인한 가상 금액',output)
