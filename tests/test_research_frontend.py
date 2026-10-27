"""Research menu/iframe recovery using the real frontend scripts and synthetic APIs."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ResearchFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is required for frontend lifecycle checks')
    def test_research_lifecycle(self):
        result = subprocess.run(['node', str(ROOT / 'tests/fixtures/research_lifecycle.cjs')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('research lifecycle PASS', result.stdout)
        for regression in (
            'existing thread recovers and exports completion when every storage write fails',
            'optional thread pointer failure does not misreport a durable result save',
            'storage event for an empty different thread clears unrelated answers and sources',
            'storage event for the same thread preserves its prior answers',
        ):
            with self.subTest(regression=regression):
                self.assertIn('PASS ' + regression, result.stdout)


if __name__ == '__main__':
    unittest.main()
