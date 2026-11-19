"""Installer exit handling in isolated homes; never perform an installation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerExitTests(unittest.TestCase):
    def test_dry_run_and_early_failure_preserve_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, HOME=temp, TMPDIR=temp)
            for args, expected in [(['--dry-run'], 0), (['–bad'], 2)]:
                with self.subTest(args=args):
                    result = subprocess.run(['sh', str(ROOT / 'install.sh'), *args], env=env,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_cleanup_preserves_status_and_removes_existing_directory(self):
        source = (ROOT / 'install.sh').read_text()
        cleanup = source.split('cleanup() {', 1)[1].split('\n', 1)[0]
        cleanup = 'cleanup() {' + cleanup + '\n'
        handler = source.split('install_interrupted=0\n', 1)[1].split("trap 'install_interrupted=1; exit 3' INT TERM", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for kind, exit_code in [('empty', 37), ('missing', 37), ('existing', 37),
                                    ('failure', 37), ('failure', 0)]:
                with self.subTest(kind=kind, exit_code=exit_code):
                    target = root / (kind + str(exit_code))
                    if kind in ('existing', 'failure'):
                        target.mkdir()
                        (target / 'file').write_text('test')
                    code = 'set -e\nTMP="$1"\ndiag_finish() { return "$1"; }\ndiag_next() { :; }\n'
                    if kind == 'failure':
                        code += 'rm() { return 9; }\n'
                    code += cleanup + 'install_interrupted=0\n' + handler + '\nexit ' + str(exit_code) + '\n'
                    result = subprocess.run(['sh', '-c', code, 'test', '' if kind == 'empty' else str(target)],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, exit_code, result.stderr)
                    self.assertEqual(target.exists(), kind == 'failure')


if __name__ == '__main__':
    unittest.main()
