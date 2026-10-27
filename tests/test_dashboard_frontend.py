"""Native shell integration and dashboard request/timer lifecycle without a browser."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DashboardFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is required for frontend lifecycle checks')
    def test_mount_leave_cached_refresh_stale_requests_and_shell_navigation(self):
        result = subprocess.run(['node', str(ROOT/'tests/fixtures/dashboard_lifecycle.cjs')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('component + shell lifecycle PASS', result.stdout)

    def test_shared_assets_and_legacy_entry_do_not_add_another_shell(self):
        current = (ROOT/'template/web/current/index.html').read_text()
        for asset in ['/dashboard.css', '/dashboard.js']:
            self.assertIn(asset, current)
        self.assertLess(current.index('/dashboard.js'), current.index('src="shell.js"'))
        legacy = (ROOT/'template/web/dashboard.html').read_text()
        self.assertIn("location.replace('/current/index.html?tab=dashboard')", legacy)
        self.assertNotIn('<header', legacy)
        self.assertNotIn('/dashboard.js', legacy)
        css = (ROOT/'template/web/dashboard.css').read_text()
        # Dashboard styles have no unscoped body/root/theme rules.
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        for selector in re.findall(r'(?:^|[{}])\s*([^{}]+)\{', css):
            if selector.startswith('@media'):
                continue
            self.assertTrue(all(s.strip().startswith('.ilson-dashboard') for s in selector.split(',')), selector)
        self.assertNotIn('dataset.theme', (ROOT/'template/web/dashboard.js').read_text())


if __name__ == '__main__':
    unittest.main()
