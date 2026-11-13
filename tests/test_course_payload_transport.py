"""Stream large course bundles through the same bootstrap used by both installers."""
import base64
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT = 'import base64,sys;exec(base64.b64decode(sys.stdin.buffer.readline()))'
spec = importlib.util.spec_from_file_location('transport_diagnostics', ROOT / 'template/lib/install_diagnostics.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class PayloadTransportTests(unittest.TestCase):
    def test_large_bundle_streams_installs_upgrades_and_rolls_back_under_windows_environment_limit(self):
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        bootstrap = re.search(r"\$CourseBootstrap='([^']+)'", source).group(1)
        payload = re.search(r"\$CoursePayload='([^']+)'", source).group(1)
        self.assertEqual(base64.b64decode(bootstrap), (ROOT / 'course/install_payload.py').read_bytes())
        files = json.loads(gzip.decompress(base64.b64decode(payload)))
        # Incompressible, valid Python adds ample headroom for later curator bundles.
        files['ilson.py'] += '\n# ' + base64.b64encode(os.urandom(512 * 1024)).decode() + '\n'
        payload = base64.b64encode(gzip.compress(json.dumps(files).encode())).decode()
        self.assertGreater(len(payload), 512 * 1024)
        env = dict(os.environ, ILSON_COURSE_PAYLOAD='untouched', ILSON_COURSE_BOOTSTRAP='untouched')
        def run_with_windows_limit(command, environment, data):
            if any(len(value) >= 32767 for value in environment.values()):
                raise OSError('simulated Windows environment variable limit')
            return subprocess.run(command, input=data, env=environment, capture_output=True, timeout=20)
        with tempfile.TemporaryDirectory(prefix="course stream 한글 ' ") as temp:
            root = Path(temp).resolve() / 'lib'
            root.mkdir()
            for name in files:
                if name == 'install_diagnostics.py':
                    continue
                old = subprocess.check_output(['git', 'show', '6002abb:course/' + ('' if name == 'ilson.py' else 'lib/') + name], cwd=ROOT)
                (root / name).write_bytes(old)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            cmd = [sys.executable, '-X', 'utf8', '-c', BOOT, str(root)]
            # CRLF is also how Windows PowerShell 5.1 terminates native pipeline input.
            data = (bootstrap + '\r\n' + payload + '\r\n').encode('ascii')
            with self.assertRaises(OSError):
                run_with_windows_limit(cmd, dict(env, ILSON_COURSE_PAYLOAD=payload), data)
            result = run_with_windows_limit(cmd, env, data)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name, content in files.items():
                self.assertEqual((root / name).read_text(), content)
            self.assertEqual(run_with_windows_limit(cmd, env, data).returncode, 0)
            backup = next((root / '.install-backups').iterdir())
            rollback = subprocess.run([sys.executable, str(ROOT / 'course/install_payload.py'), str(root), '--rollback', backup.name],
                                      env=env, capture_output=True, timeout=10)
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}, before)

    def test_installers_stream_bootstrap_and_payload_without_environment_or_argument_transport(self):
        windows = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        intel = (ROOT / 'course/install-intel-mac.sh').read_text()
        for source in (windows, intel):
            self.assertNotIn('ILSON_COURSE_PAYLOAD', source)
            self.assertNotIn('ILSON_COURSE_BOOTSTRAP', source)
            self.assertIn(BOOT, source)
        self.assertIn('"$CourseBootstrap`n$CoursePayload" | & $python -X utf8 -c $boot $lib', windows)
        self.assertIn('printf \'%s\\n%s\\n\' "$COURSE_BOOTSTRAP" "$COURSE_PAYLOAD" |', intel)


class HelperFailureTests(unittest.TestCase):
    def test_windows_helper_failure_records_native_code_or_sanitized_exception_without_message(self):
        pwsh = os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')
        if not pwsh:
            self.skipTest('pwsh required for isolated Windows helper stage')
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        recorder = source.split('# DIAGNOSTICS_BEGIN\n', 1)[1].split('# DIAGNOSTICS_END', 1)[0]
        stage = "    Start-IlsonStep 'helper.install'\n" + source.split("    Start-IlsonStep 'helper.install'\n", 1)[1].split("    Start-IlsonStep 'verify.current'", 1)[0]
        for mode in ('native', 'exception', 'missing-runtime'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                home = Path(temp).resolve()
                script = recorder + '''
$ErrorActionPreference='Stop'
function K([string]$s) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s)) }
function Get-Command { $null }
$DryRun=$false; $statuses=@{}; $python=$env:ILSON_TEST_PYTHON
Start-IlsonDiagnostics 'windows-course'
'''
                if mode == 'native':
                    script += "$CourseBootstrap='" + base64.b64encode(b"import sys;sys.stderr.write('SECRET-token username@example.com');sys.exit(37)").decode() + "'\n$CoursePayload='test'\n"
                elif mode == 'exception':
                    script += "function Get-Command { throw (New-Object IO.IOException('SECRET-token username@example.com')) }\n"
                else:
                    script += '$python=$null\n'
                # The real installer invokes this stage inside Main, so test a
                # function scope too (especially the LASTEXITCODE automatic variable).
                script += 'function Invoke-TestHelper {\n' + stage + '\n}\nInvoke-TestHelper\nComplete-IlsonDiagnostics 0\n'
                runner = home / 'stage.ps1'
                runner.write_text(script, encoding='ascii')
                env = dict(os.environ, LOCALAPPDATA=str(home), USERPROFILE=str(home), ILSON_TEST_PYTHON=sys.executable,
                           ILSON_DIAGNOSTICS_DIR=str(home / 'diagnostics'))
                result = subprocess.run([pwsh, '-NoProfile', '-File', str(runner)], env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('INSTALL_RESULT=1', result.stdout)
                folder = next((home / 'diagnostics/runs').iterdir())
                events, damaged = diag.read_run(folder)
                self.assertFalse(damaged)
                end = next(e for e in events if e['step_id'] == 'helper.install' and e['event'] == 'step-end')
                if mode == 'missing-runtime':
                    self.assertEqual((end['result'], end['reason_code']), ('skipped-with-reason', 'DEPENDENCY_FAILED'))
                else:
                    self.assertEqual((end['result'], end['reason_code']), ('failed', 'EXECUTE_FAILED'))
                    self.assertEqual(end['exit_code'], 37 if mode == 'native' else None)
                    self.assertEqual(end['exit_source'], 'native' if mode == 'native' else 'exception')
                    if mode == 'exception':
                        self.assertEqual(end['exception_class'], 'IOException')
                raw = (folder / 'events.jsonl').read_text()
                self.assertNotIn('SECRET-token', raw)
                self.assertNotIn('username@example.com', raw)

    def test_intel_bootstrap_and_wrapper_failures_keep_native_exit_codes(self):
        source = (ROOT / 'course/install-intel-mac.sh').read_text()
        # Exercise the actual helper stage; app downloads and runtime discovery are unrelated.
        stage = source.split('  diag_step_end runtime.python ok REUSED_VERIFIED true 0\n', 1)[1]
        stage = stage.split('diag_skip verify.current', 1)[0]
        stage = stage.replace('\nfi\nif [[ "$DRY_RUN"', '\nif [[ "$DRY_RUN"', 1)
        for failure in ('bootstrap', 'wrapper'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                home = Path(temp).resolve()
                code = '''
. "$1/tools/diagnostics.sh"
diag_begin intel-course
DRY_RUN=0; learn_status='실패'; path_manual=''; course_python=fake_python
COURSE_BOOTSTRAP=test; COURSE_PAYLOAD=test
command() { if [[ "$*" = '-v ilson' ]]; then return 1; fi; builtin command "$@"; }
fake_python() { cat >/dev/null; if [[ "$*" = *'import base64'* ]]; then return BOOT_RC; else return 37; fi; }
''' .replace('BOOT_RC', '37' if failure == 'bootstrap' else '0')
                result = subprocess.run(['bash', '-c', code + stage + '\ndiag_finish 0', 'test', str(ROOT)],
                                        env=dict(os.environ, HOME=str(home)), capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                folder = next((home / '.ilson-diagnostics/runs').iterdir())
                events, damaged = diag.read_run(folder)
                self.assertFalse(damaged)
                end = next(e for e in events if e['step_id'] == 'helper.install' and e['event'] == 'step-end')
                self.assertEqual((end['result'], end['reason_code'], end['exit_code'], end['exit_source']),
                                 ('failed', 'EXECUTE_FAILED', 37, 'native'))

    def test_full_mac_helper_command_failure_is_execution_failure_and_signal_stays_interrupted(self):
        source = (ROOT / 'install.sh').read_text()
        handler = 'install_interrupted=0\n' + source.split('install_interrupted=0\n', 1)[1]
        # Keep only the actual exit handler/traps, not the installer's main flow.
        handler = handler.split("trap 'install_interrupted=1; exit 3' INT TERM", 1)[0] + "trap 'install_interrupted=1; exit 3' INT TERM\n"
        for code in (3, 37, 'signal'):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temp:
                home = Path(temp).resolve()
                script = '. "$1/tools/diagnostics.sh"\ndiag_begin full-mac\ncleanup() { :; }\ndiag_next() { :; }\n'
                script += handler + '\ndiag_step_start helper.install\n'
                script += 'kill -TERM $$\n' if code == 'signal' else 'exit ' + str(code) + '\n'
                result = subprocess.run(['sh', '-c', script, 'test', str(ROOT)], env=dict(os.environ, HOME=str(home)),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 3 if code == 'signal' else code, result.stderr)
                folder = next((home / '.ilson-diagnostics/runs').iterdir())
                events, damaged = diag.read_run(folder)
                self.assertFalse(damaged)
                end = next(e for e in events if e['step_id'] == 'helper.install' and e['event'] == 'step-end')
                self.assertEqual(end['result'], 'failed')
                self.assertEqual(end['reason_code'], 'INTERRUPTED' if code == 'signal' else 'EXECUTE_FAILED')
                self.assertEqual(end['exit_code'], 3 if code == 'signal' else code)


if __name__ == '__main__':
    unittest.main()
