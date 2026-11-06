"""Real-browser regression for the unified manager's iframe navigation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CORE=os.environ.get('PLAYWRIGHT_CORE')

@unittest.skipUnless(shutil.which('node') and CORE and Path(CORE).is_dir(),
                     'set PLAYWRIGHT_CORE to an installed playwright-core with WebKit')
class AdminNavigationBrowserTests(unittest.TestCase):
    def test_sidebar_switches_visible_iframe_content_at_desktop_and_mobile_sizes(self):
        with tempfile.TemporaryDirectory(prefix='ilson-browser-test-') as folder:
            proc=subprocess.Popen([sys.executable,str(ROOT/'tests/fixtures/admin_navigation_server.py'),folder],
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                port=proc.stdout.readline().strip()
                self.assertTrue(port.isdigit(),'isolated manager did not start')
                token=Path(folder)/'box/state/web-admin/token'
                result=subprocess.run(['node',str(ROOT/'tests/fixtures/admin_navigation_browser.cjs'),
                                       'http://127.0.0.1:'+port,str(token)],
                                      env=os.environ.copy(),capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('desktop: sidebar and in-frame transitions PASS',result.stdout)
                self.assertIn('mobile: sidebar and in-frame transitions PASS',result.stdout)
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                proc.stdout.close();proc.stderr.close()

if __name__=='__main__': unittest.main()
