"""Keyboard/list/detail lifecycle using local Node and a synthetic DOM."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class OpenSourceFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'node required for synthetic DOM checks')
    def test_navigation_search_filters_back_scroll_stale_responses_expiry_and_states(self):
        result=subprocess.run(['node',str(ROOT/'tests/fixtures/opensource_lifecycle.cjs')],
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('opensource component + shell lifecycle PASS',result.stdout)

    def test_styles_are_scoped_and_mobile_is_one_column(self):
        css=(ROOT/'template/web/current/opensource.css').read_text()
        self.assertIn('@media(max-width:720px)',css)
        self.assertIn('grid-template-columns:1fr',css)
        self.assertIn(':focus-visible',css)
        for line in css.splitlines():
            if line and not line.startswith(('@','}')):
                self.assertTrue(line.lstrip().startswith('.ilson-opensource'),line)
        js=(ROOT/'template/web/current/opensource.js').read_text()
        for forbidden in ['<iframe','<video','navigator.clipboard','type="file"','localStorage','innerHTML=r.mild_md']:
            self.assertNotIn(forbidden,js)
        self.assertIn("credentials:'same-origin'",js)
        self.assertIn("cache:'no-store'",js)


if __name__=='__main__':unittest.main()
