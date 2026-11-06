"""Installer dry runs and failure handling use only temporary homes and mocked tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MacDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_write_for_missing_or_existing_apps(self):
        for installed in (False, True):
            with self.subTest(installed=installed), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                if installed:
                    (home / 'Applications/Orca.app').mkdir(parents=True)
                    (home / 'Applications/Obsidian.app').mkdir()
                before = {str(p.relative_to(home)) for p in home.rglob('*')}
                hook = home / 'mock-bash-env'
                hook.write_text('''
uname() { case "$1" in -s) echo Darwin;; -m) echo x86_64;; esac; }
sysctl() { return 1; }
sw_vers() { echo 13.6; }
command() { if [[ "$*" == "-v claude" ]]; then return REPLACE; fi; builtin command "$@"; }
claude() { echo "Claude mock"; }
'''.replace('REPLACE', '0' if installed else '1'))
                env = dict(os.environ, HOME=tmp, BASH_ENV=str(hook), ILSON_COURSE_DRY_RUN='1')
                proc = subprocess.run(['bash', str(ROOT / 'course/install-intel-mac.sh')], env=env,
                                      text=True, capture_output=True, timeout=20)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn('모의 실행', proc.stdout)
                self.assertIn('이미 있음' if installed else '설치 예정', proc.stdout)
                after = {str(p.relative_to(home)) for p in home.rglob('*')}
                self.assertEqual(after, before | {'mock-bash-env'})


class PowerShellTests(unittest.TestCase):
    def test_dry_run_and_failures_preserve_existing_files(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for mocked PowerShell tests')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        self.assertTrue(source.endswith('Main\n'))
        import base64
        import re
        for mode in ('installed', 'missing', 'failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                prefix = "$env:USERPROFILE = '{0}'\n$env:LOCALAPPDATA = '{0}'\n$env:ProgramFiles = '{0}'\n$env:ILSON_COURSE_DRY_RUN = '{1}'".format(tmp.replace("'", "''"), '0' if mode == 'failure' else '1')
                mocks = '''
function Get-CimInstance { param($ClassName) if ($ClassName -eq 'Win32_OperatingSystem') { [pscustomobject]@{ BuildNumber='26300'; ProductType=1; Caption='test Windows' } } else { [pscustomobject]@{ SystemType='x64-based PC' } } }
function Get-PSDrive { param($Name) [pscustomobject]@{Free=10GB} }
function Find-Claude { CLAUDE_MOCK }
function Find-Orca { ORCA_MOCK }
function Invoke-RestMethod { throw 'simulated Claude failure' }
function Invoke-WebRequest { throw 'simulated download failure' }
'''.replace('CLAUDE_MOCK', "[pscustomobject]@{ Source='/usr/bin/true' }" if mode == 'installed' else '$null').replace('ORCA_MOCK', "'/fake/Orca.exe'" if mode == 'installed' else '$null')
                kit = home / 'Documents/일손강의-1기'
                if mode == 'failure':
                    kit.mkdir(parents=True)
                    names = [base64.b64decode(e).decode() for e in re.findall(r"^        '([^']+)'$", source, re.M)]
                    names += ['00_강의_시작.md', 'CONTEXT.md', 'CLAUDE.md', 'company/_index.md', 'journal/.gitkeep', 'lessons/.gitkeep', 'reports/briefing/.gitkeep', 'reports/weekly/.gitkeep', 'reports/pending/.gitkeep']
                    for name in names:
                        target = kit / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text('preserved')
                patched = source.replace("[IO.Path]::GetPathRoot($env:USERPROFILE).Substring(0,1)", "'T'")
                patched = patched[:-5].replace('param([switch]$DryRun)', 'param([switch]$DryRun)\n' + prefix)
                runner = home / 'test.ps1'
                runner.write_text(patched + '\n' + mocks + '\nMain\n')
                proc = subprocess.run([pwsh, '-NoProfile', '-File', str(runner)], text=True, capture_output=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                for word in {'installed': ['이미 있음', '모의 실행'], 'missing': ['설치 예정', '모의 실행'], 'failure': ['실패', '준비됨']}[mode]:
                    self.assertIn(word, proc.stdout)
                if mode == 'failure':
                    self.assertTrue(all(p.read_text() == 'preserved' for p in kit.rglob('*') if p.is_file()))
                else:
                    self.assertFalse(kit.exists())


if __name__ == '__main__':
    unittest.main()
