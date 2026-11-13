"""Installer dry runs and failure handling use only temporary homes and mocked tools."""
import os
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_BASE64 = re.compile(
    r"(?<=K ')[A-Za-z0-9+/=]+(?=')|"
    r"(?<=FromBase64String\(')[A-Za-z0-9+/=]+(?=')|"
    r"(?<=        ')[A-Za-z0-9+/=]+(?='$)", re.M)


class EmbeddedTextTests(unittest.TestCase):
    def test_all_windows_embedded_text_matches_original(self):
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        expected = json.loads((ROOT / 'tests/course_windows_base64_text.json').read_text(encoding='utf-8'))
        expected = [(ROOT / item['file']).read_text(encoding='utf-8') if isinstance(item, dict) else item
                    for item in expected]
        encoded = WINDOWS_BASE64.findall(source)
        self.assertEqual(len(encoded), len(expected))
        for index, (value, original) in enumerate(zip(encoded, expected)):
            with self.subTest(index=index):
                self.assertEqual(base64.b64decode(value, validate=True).decode('utf-8'), original)
        for key, name in (('Guide', '00_강의_시작.md'), ('Rules', 'CLAUDE.md')):
            value = re.search(r"\$Course" + key + r"='([A-Za-z0-9+/=]+)'", source).group(1)
            self.assertEqual(base64.b64decode(value, validate=True).decode('utf-8'),
                             (ROOT / 'course' / name).read_text(encoding='utf-8'))

    def test_all_mac_embedded_text_matches_original(self):
        source = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        for key, name in (('GUIDE', '00_강의_시작.md'), ('RULES', 'CLAUDE.md')):
            value = re.search(r"COURSE_" + key + r"='([A-Za-z0-9+/=]+)'", source).group(1)
            self.assertEqual(base64.b64decode(value, validate=True).decode('utf-8'),
                             (ROOT / 'course' / name).read_text(encoding='utf-8'))


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
    def test_python_bootstrap_and_existing_environment_are_preserved(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for mocked PowerShell tests')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        source = source.replace('New-Object Net.WebClient', 'New-TestClient')
        source = source.replace('[IO.Path]::GetPathRoot($env:USERPROFILE).Substring(0,1)', "'T'")
        mocks = r'''
function Get-CimInstance { param($ClassName) if ($ClassName -eq 'Win32_OperatingSystem') { [pscustomobject]@{ BuildNumber='26300'; ProductType=1; Caption='test Windows' } } else { [pscustomobject]@{ SystemType='x64-based PC' } } }
function Get-PSDrive { param($Name) [pscustomobject]@{Free=10GB} }
function Find-Claude { [pscustomobject]@{ Source='/usr/bin/true' } }
function Find-Orca { '/fake/Orca.exe' }
function Get-Command {
    [CmdletBinding()] param([string]$Name)
    if ($Name -eq 'python.exe') { return [pscustomobject]@{Source=$env:ILSON_TEST_PYTHON} }
    return $null
}
function New-TestClient {
    $client = [pscustomobject]@{}
    $client | Add-Member ScriptMethod DownloadData { param($url) return ,([Text.Encoding]::UTF8.GetBytes('fixture')) }
    $client | Add-Member ScriptMethod Dispose { }
    return $client
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); kit = home / 'kit'; kit.mkdir()
            obs = home / 'Programs/obsidian/Obsidian.exe'
            obs.parent.mkdir(parents=True); obs.write_text('fixture')
            runner = home / 'runner.ps1'
            runner.write_text(source[:-5] + '\n' + mocks + '''
Main
Write-Output ('ENV_PAYLOAD=' + $env:ILSON_COURSE_PAYLOAD)
Write-Output ('ENV_BOOTSTRAP=' + $env:ILSON_COURSE_BOOTSTRAP)
''', encoding='ascii')
            env = dict(os.environ, USERPROFILE=tmp, LOCALAPPDATA=tmp, ProgramFiles=tmp,
                       ILSON_COURSE_DRY_RUN='0', ILSON_TEST_PYTHON=sys.executable,
                       ILSON_COURSE_PAYLOAD='existing-payload', ILSON_COURSE_BOOTSTRAP='existing-bootstrap')
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(runner), '-KitPath', str(kit)],
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Learn: 준비됨', result.stdout)
            self.assertIn('ENV_PAYLOAD=existing-payload', result.stdout)
            self.assertIn('ENV_BOOTSTRAP=existing-bootstrap', result.stdout)
            self.assertEqual((home / 'ilson-course/lib/ilson.py').read_text(encoding='utf-8'),
                             (ROOT / 'course/ilson.py').read_text(encoding='utf-8'))

    def test_dry_run_and_failures_preserve_existing_files(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for mocked PowerShell tests')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        self.assertTrue(source.endswith('Main\n'))
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
                patched = patched[:-5].replace('param([switch]$DryRun, [string]$KitPath)', 'param([switch]$DryRun, [string]$KitPath)\n' + prefix)
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

    def test_empty_kit_creation_and_second_run_preserves_every_file(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for mocked PowerShell tests')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        self.assertEqual(source.count('New-Object Net.WebClient'), 1)
        source = source.replace('New-Object Net.WebClient', 'New-TestClient')
        source = source.replace('[IO.Path]::GetPathRoot($env:USERPROFILE).Substring(0,1)', "'T'")
        mocks = r'''
function Get-CimInstance { param($ClassName) if ($ClassName -eq 'Win32_OperatingSystem') { [pscustomobject]@{ BuildNumber='26300'; ProductType=1; Caption='test Windows' } } else { [pscustomobject]@{ SystemType='x64-based PC' } } }
function Get-PSDrive { param($Name) [pscustomobject]@{Free=10GB} }
function Find-Claude { [pscustomobject]@{ Source='/usr/bin/true' } }
function Find-Orca { '/fake/Orca.exe' }
function New-TestClient {
    $client = [pscustomobject]@{}
    $client | Add-Member ScriptMethod DownloadData {
        param($url)
        [IO.File]::AppendAllText($env:ILSON_DOWNLOAD_LOG, "download`n")
        return ,([Text.Encoding]::UTF8.GetBytes('fixture body'))
    }
    $client | Add-Member ScriptMethod Dispose { }
    return $client
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            kit = home / 'empty kit'
            kit.mkdir()
            obs = home / 'Programs/obsidian/Obsidian.exe'
            obs.parent.mkdir(parents=True)
            obs.write_text('fixture')
            runner = home / 'runner.ps1'
            runner.write_text(source[:-5] + '\n' + mocks + '\nMain\n', encoding='ascii')
            env = dict(os.environ, USERPROFILE=tmp, LOCALAPPDATA=tmp, ProgramFiles=tmp,
                       ILSON_COURSE_DRY_RUN='0', ILSON_DOWNLOAD_LOG=str(home / 'downloads'))
            def run():
                return subprocess.run([pwsh, '-NoProfile', '-File', str(runner), '-KitPath', str(kit)],
                                      text=True, capture_output=True, timeout=30, env=env)
            first = run()
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn('Kit: 완료', first.stdout)
            self.assertIn('Vault: 준비됨', first.stdout)
            names = [p.name for p in (ROOT / 'template/claude/skills/course-kit-20261109').glob('*.md')]
            self.assertEqual(len(names), 11)
            expected = set(names + ['00_강의_시작.md', 'CLAUDE.md', 'CONTEXT.md',
                                   'company/_index.md', 'journal/.gitkeep', 'lessons/.gitkeep',
                                   'reports/briefing/.gitkeep', 'reports/weekly/.gitkeep',
                                   'reports/pending/.gitkeep'])
            actual = {str(p.relative_to(kit)) for p in kit.rglob('*') if p.is_file()}
            self.assertEqual(actual, expected)
            self.assertEqual((kit / '시작과_막힘_복구.md').read_text(encoding='utf-8'),
                             '> Windows와 Intel 맥은 먼저 00_강의_시작.md를 따르세요.\n\nfixture body')
            before = {name: ((kit / name).read_bytes(), (kit / name).stat().st_mtime_ns) for name in expected}
            self.assertEqual((home / 'downloads').read_text().count('download'), 18)
            second = run()
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn('Kit: 완료', second.stdout)
            self.assertEqual({str(p.relative_to(kit)) for p in kit.rglob('*') if p.is_file()}, expected)
            self.assertEqual({name: ((kit / name).read_bytes(), (kit / name).stat().st_mtime_ns)
                              for name in expected}, before)
            self.assertEqual((home / 'downloads').read_text().count('download'), 18)


    def test_upgrade_replaces_old_suggested_rules_and_keeps_a_dated_backup(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for mocked PowerShell tests')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        source = source.replace('New-Object Net.WebClient', 'New-TestClient')
        source = source.replace('[IO.Path]::GetPathRoot($env:USERPROFILE).Substring(0,1)', "'T'")
        mocks = r"""
function Get-CimInstance { param($ClassName) if ($ClassName -eq 'Win32_OperatingSystem') { [pscustomobject]@{ BuildNumber='26300'; ProductType=1; Caption='test Windows' } } else { [pscustomobject]@{ SystemType='x64-based PC' } } }
function Get-PSDrive { param($Name) [pscustomobject]@{Free=10GB} }
function Find-Claude { [pscustomobject]@{ Source='/usr/bin/true' } }
function Find-Orca { '/fake/Orca.exe' }
function Get-Command {
    [CmdletBinding()] param([string]$Name)
    if ($Name -eq 'python.exe') { return [pscustomobject]@{Source=$env:ILSON_TEST_PYTHON} }
    return $null
}
function New-TestClient {
    $client = [pscustomobject]@{}
    $client | Add-Member ScriptMethod DownloadData { param($url) return ,([Text.Encoding]::UTF8.GetBytes('fixture')) }
    $client | Add-Member ScriptMethod Dispose { }
    return $client
}
"""
        rules = (ROOT / 'course/CLAUDE.md').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); kit = home / 'kit'; kit.mkdir()
            (kit / 'CLAUDE.md').write_bytes(b'user rules\n')
            obs = home / 'Programs/obsidian/Obsidian.exe'
            obs.parent.mkdir(parents=True); obs.write_text('fixture')
            course = home / 'ilson-course'; course.mkdir()
            suggested = course / 'CLAUDE-course-suggested.md'
            suggested.write_bytes(b'old suggested rules\n')
            runner = home / 'runner.ps1'
            runner.write_text(source[:-5] + '\n' + mocks + '\nMain\n', encoding='ascii')
            env = dict(os.environ, USERPROFILE=tmp, LOCALAPPDATA=tmp, ProgramFiles=tmp,
                       ILSON_COURSE_DRY_RUN='0', ILSON_TEST_PYTHON=sys.executable)
            def run():
                result = subprocess.run([pwsh, '-NoProfile', '-File', str(runner), '-KitPath', str(kit)],
                                        text=True, capture_output=True, timeout=30, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            first = run()
            self.assertEqual(suggested.read_bytes(), rules)
            backups = sorted(course.glob('CLAUDE-course-suggested.*.bak.md'))
            self.assertEqual(len(backups), 1)
            self.assertRegex(backups[0].name, r'^CLAUDE-course-suggested\.\d{8}-\d{6}\.bak\.md$')
            self.assertEqual(backups[0].read_bytes(), b'old suggested rules\n')
            self.assertIn(str(backups[0]), first.stdout)
            self.assertEqual((kit / 'CLAUDE.md').read_bytes(), b'user rules\n')
            run()
            self.assertEqual(sorted(course.glob('CLAUDE-course-suggested.*.bak.md')), backups)
            self.assertEqual(suggested.read_bytes(), rules)


def intel_path_writer():
    source = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
    return re.search(r"<<'PYWRAP'\n(.*?)\nPYWRAP\n", source, re.S).group(1)


class IntelPathTests(unittest.TestCase):
    """Runs the installer's own PATH writer (the PYWRAP block) against a temporary HOME."""
    LINE = 'export PATH="$HOME/.local/bin:$PATH"'

    def run_writer(self, home, shell):
        notes = home / 'path-notes.txt'
        proc = subprocess.run([sys.executable, '-', sys.executable, str(home / 'lib'), str(home), shell, str(notes)],
                              input=intel_path_writer(), text=True, capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((home / '.local/bin/ilson').is_file())
        proc.manual = notes.read_text(encoding='utf-8').splitlines()
        return proc

    def path_lines(self, path):
        known = (self.LINE, 'export PATH="' + str(path.parent / '.local/bin') + ':$PATH"')
        return sum(l.strip() in known for l in path.read_text(encoding='utf-8').splitlines())

    def test_zsh_user_gets_zprofile_and_zshrc_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.zshrc').write_text('alias ll="ls -l"\n', encoding='utf-8')
            for _ in range(2):
                self.run_writer(home, '/bin/zsh')
            for name in ('.zprofile', '.zshrc'):
                text = (home / name).read_text(encoding='utf-8')
                self.assertEqual(text.count('# ilson course user bin'), 1, name)
                self.assertEqual(text.count(self.LINE), 1, name)
            self.assertTrue((home / '.zshrc').read_text(encoding='utf-8').startswith('alias ll="ls -l"\n'))
            for name in ('.bash_profile', '.bashrc', '.profile'):
                self.assertFalse((home / name).exists(), name)
            self.assertTrue((home / '.local/bin/ilson').is_file())

    def test_bash_user_gets_bash_startup_files_without_hiding_profile(self):
        for existing in (None, '.profile', '.bash_profile'):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                if existing:
                    (home / existing).write_text('# mine\n', encoding='utf-8')
                for _ in range(2):
                    self.run_writer(home, '/bin/bash')
                login = existing or '.bash_profile'
                for name in ('.zprofile', '.zshrc', login, '.bashrc'):
                    self.assertEqual((home / name).read_text(encoding='utf-8').count(self.LINE), 1, name)
                if existing == '.profile':
                    self.assertFalse((home / '.bash_profile').exists())

    def test_linked_zshrc_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / 'dotfiles-zshrc'
            target.write_text('# managed\n', encoding='utf-8')
            (home / '.zshrc').symlink_to(target)
            proc = self.run_writer(home, '/bin/zsh')
            self.assertEqual(target.read_text(encoding='utf-8'), '# managed\n')
            self.assertIn(self.LINE, proc.stdout)
            self.assertIn(self.LINE, (home / '.zprofile').read_text(encoding='utf-8'))
            self.assertEqual(proc.manual, [str(home / '.zshrc')])

    def test_linked_zprofile_and_zshrc_are_left_alone_and_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for name in ('.zprofile', '.zshrc'):
                (home / ('dotfiles' + name)).write_text('# managed\n', encoding='utf-8')
                (home / name).symlink_to(home / ('dotfiles' + name))
            (home / '.bashrc').symlink_to(home / 'missing-bashrc')
            for _ in range(2):
                proc = self.run_writer(home, '/bin/bash')
            for name in ('.zprofile', '.zshrc'):
                self.assertTrue((home / name).is_symlink())
                self.assertEqual((home / ('dotfiles' + name)).read_text(encoding='utf-8'), '# managed\n')
            self.assertFalse((home / 'missing-bashrc').exists())
            self.assertEqual(proc.manual, [str(home / n) for n in ('.zprofile', '.zshrc', '.bashrc')])
            self.assertEqual(self.path_lines(home / '.bash_profile'), 1)

    @unittest.skipIf(os.geteuid() == 0, 'root ignores file modes')
    def test_read_only_zprofile_is_reported_and_zshrc_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.zprofile').write_text('# mine\n', encoding='utf-8')
            os.chmod(home / '.zprofile', 0o400)
            proc = self.run_writer(home, '/bin/zsh')
            self.assertEqual((home / '.zprofile').read_text(encoding='utf-8'), '# mine\n')
            self.assertEqual(self.path_lines(home / '.zshrc'), 1)
            self.assertEqual(proc.manual, [str(home / '.zprofile')])
            self.assertIn(self.LINE, proc.stdout)

    def test_lines_from_older_installers_are_recognized(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            box = 'export PATH="' + str(home / '.local/bin') + ':$PATH"'
            (home / '.zprofile').write_text('# mine\n\n# ilson\n' + box + '\n', encoding='utf-8')
            (home / '.zshrc').write_text('  ' + self.LINE + '  \n', encoding='utf-8')
            for _ in range(2):
                proc = self.run_writer(home, '/bin/zsh')
            self.assertEqual((home / '.zprofile').read_text(encoding='utf-8'), '# mine\n\n# ilson\n' + box + '\n')
            self.assertEqual((home / '.zshrc').read_text(encoding='utf-8'), '  ' + self.LINE + '  \n')
            self.assertEqual(proc.manual, [])

    def test_unwritable_zshrc_does_not_fail_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.zshrc').mkdir()
            proc = self.run_writer(home, '/bin/zsh')
            self.assertIn(self.LINE, proc.stdout)
            self.assertIn(self.LINE, (home / '.zprofile').read_text(encoding='utf-8'))
            self.assertEqual(proc.manual, [str(home / '.zshrc')])
            self.assertEqual(list((home / '.zshrc').iterdir()), [])

    def test_result_tells_how_to_reach_ilson_in_open_windows(self):
        source = (ROOT / 'course/install-intel-mac.sh').read_text(encoding='utf-8')
        self.assertIn('"${SHELL:-}" "$path_notes" <<\'PYWRAP\'', source)
        self.assertIn('새 터미널을 열거나 source ~/.zshrc', source)
        self.assertIn('PATH 직접 추가 필요', source)


@unittest.skipUnless(sys.platform == 'darwin', 'install.sh supports macOS only')
class BoxInstallerPathTests(unittest.TestCase):
    """install.sh --cli-only with a temporary HOME, CLI and bin directory."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='ilson-path-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home, self.box, self.cli, self.bin = (self.base / n for n in ('home', 'box', 'cli', 'bin'))
        self.home.mkdir()
        self.src = self.base / 'src'
        (self.src / 'template').mkdir(parents=True)
        (self.src / 'tools').mkdir()
        (self.src / 'ilson').write_text('#!/bin/sh\necho "ilson full-mac ILSON-DIAG-1"\n')
        (self.src / 'template/CLAUDE.md').write_text('# test\n')
        (self.src / 'tools/update.py').write_bytes((ROOT / 'tools/update.py').read_bytes())
        self.line = 'export PATH="' + str(self.bin) + ':$PATH"'

    def use_home_bin(self):
        self.bin = self.home / '.local/bin'
        self.line = 'export PATH="' + str(self.bin) + ':$PATH"'

    def install(self, shell, on_path=False):
        environ = {k: v for k, v in os.environ.items() if not k.startswith('ILSON_')}
        path = os.environ['PATH']
        environ.update(HOME=str(self.home), SHELL=shell, ILSON_SRC=str(self.src), ILSON_CLI_DIR=str(self.cli),
                       ILSON_BIN_DIR=str(self.bin), ILSON_HOME=str(self.box),
                       PATH=(str(self.bin) + ':' + path) if on_path else path)
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--cli-only'], env=environ,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def count(self, name):
        path = self.home / name
        return path.read_text(encoding='utf-8').count(self.line) if path.exists() else 0

    def test_zsh_install_writes_zprofile_and_zshrc_once(self):
        first = self.install('/bin/zsh')
        self.assertIn('source ~/.zshrc', first.stdout)
        self.install('/bin/zsh')
        self.assertEqual((self.count('.zprofile'), self.count('.zshrc')), (1, 1))
        self.assertFalse((self.home / '.bash_profile').exists())
        self.assertFalse((self.home / '.bashrc').exists())

    def test_bash_install_also_writes_bash_startup_files(self):
        self.install('/bin/bash')
        self.install('/bin/bash')
        self.assertEqual([self.count(n) for n in ('.zprofile', '.zshrc', '.bash_profile', '.bashrc')], [1, 1, 1, 1])

    def test_reinstall_repairs_zprofile_only_install(self):
        (self.home / '.zprofile').write_text('\n# ilson\n' + self.line + '\n', encoding='utf-8')
        self.install('/bin/zsh', on_path=True)
        self.assertEqual((self.count('.zprofile'), self.count('.zshrc')), (1, 1))

    def manual_list(self, result):
        lines = result.stdout.splitlines()
        if not any(l.startswith('  PATH 직접 추가 필요') for l in lines):
            return []
        start = next(i for i, l in enumerate(lines) if l.startswith('  PATH 직접 추가 필요'))
        self.assertIn(self.line, lines[start])
        return [l.strip()[2:] for l in lines[start + 1:] if l.startswith('    · ')]

    def test_unwritable_zshrc_is_reported_not_fatal(self):
        (self.home / '.zshrc').mkdir()
        result = self.install('/bin/zsh')
        self.assertIn('PATH 줄을 쓰지 못함', result.stdout)
        self.assertEqual(self.count('.zprofile'), 1)
        self.assertEqual(self.manual_list(result), [str(self.home / '.zshrc')])
        self.assertEqual(list((self.home / '.zshrc').iterdir()), [])

    def test_linked_zprofile_and_zshrc_are_left_alone_and_listed(self):
        for name in ('.zprofile', '.zshrc'):
            (self.base / ('dotfiles' + name)).write_text('# managed\n', encoding='utf-8')
            (self.home / name).symlink_to(self.base / ('dotfiles' + name))
        (self.home / '.bashrc').symlink_to(self.base / 'missing-bashrc')
        for _ in range(2):
            result = self.install('/bin/bash')
        for name in ('.zprofile', '.zshrc'):
            self.assertTrue((self.home / name).is_symlink())
            self.assertEqual((self.base / ('dotfiles' + name)).read_text(encoding='utf-8'), '# managed\n')
        self.assertFalse((self.base / 'missing-bashrc').exists())
        self.assertEqual(self.manual_list(result), [str(self.home / n) for n in ('.zprofile', '.zshrc', '.bashrc')])
        self.assertEqual(self.count('.bash_profile'), 1)

    @unittest.skipIf(os.geteuid() == 0, 'root ignores file modes')
    def test_read_only_zprofile_is_reported_and_zshrc_still_written(self):
        (self.home / '.zprofile').write_text('# mine\n', encoding='utf-8')
        os.chmod(self.home / '.zprofile', 0o400)
        self.addCleanup(os.chmod, self.home / '.zprofile', 0o600)
        result = self.install('/bin/zsh')
        self.assertEqual((self.home / '.zprofile').read_text(encoding='utf-8'), '# mine\n')
        self.assertEqual(self.count('.zshrc'), 1)
        self.assertEqual(self.manual_list(result), [str(self.home / '.zprofile')])

    def test_already_on_path_still_fills_missing_files(self):
        self.install('/bin/zsh', on_path=True)
        self.install('/bin/zsh', on_path=True)
        self.assertEqual((self.count('.zprofile'), self.count('.zshrc')), (1, 1))

    def test_home_form_from_lecture_workaround_or_intel_is_recognized(self):
        self.use_home_bin()
        home_line = 'export PATH="$HOME/.local/bin:$PATH"'
        (self.home / '.zprofile').write_text('# mine\n' + home_line + '\n', encoding='utf-8')
        (self.home / '.zshrc').write_text('\n# ilson course user bin\n' + home_line + '\n', encoding='utf-8')
        for _ in range(2):
            result = self.install('/bin/zsh', on_path=True)
        self.assertEqual((self.home / '.zprofile').read_text(encoding='utf-8'), '# mine\n' + home_line + '\n')
        self.assertEqual((self.home / '.zshrc').read_text(encoding='utf-8'),
                         '\n# ilson course user bin\n' + home_line + '\n')
        self.assertEqual(self.manual_list(result), [])

    def test_intel_then_box_leaves_one_path_line_per_file(self):
        # The other direction (Box lines seen by the Intel writer) is IntelPathTests.test_lines_from_older_installers_are_recognized.
        self.use_home_bin()
        intel = IntelPathTests()
        intel.run_writer(self.home, '/bin/bash')
        self.install('/bin/bash')
        self.install('/bin/bash', on_path=True)
        for name in ('.zprofile', '.zshrc', '.bash_profile', '.bashrc'):
            self.assertEqual(intel.path_lines(self.home / name), 1, name)


if __name__ == '__main__':
    unittest.main()
