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

    def test_missing_research_archive_is_not_probed_or_advertised(self):
        page = (ROOT/'template/web/current/pack-library/packs.html').read_text()
        script = (ROOT/'template/web/current/pack-library/packs.js').read_text()
        self.assertNotIn('리서치 팩 다운로드', page)
        self.assertNotIn('research-pack-0.15.3.zip', script)
        self.assertRegex(page, r'id="downloadPack"[^>]*hidden')
        self.assertRegex(page, r'id="downloadHelp" hidden')

    def test_mobile_account_workspace_does_not_force_empty_height(self):
        css = (ROOT/'template/web/current/sns_operations.css').read_text()
        mobile = css.split('@media(max-width:1200px)', 1)[1].split('@media(max-width:700px)', 1)[0]
        self.assertRegex(mobile, r'\.sns-account-workspace\{[^}]*min-height:0')
        self.assertNotIn('min-height:420px', mobile)

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
