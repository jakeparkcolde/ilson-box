"""Offline diagnostics: isolated homes and synthetic secrets only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_diagnostics', ROOT / 'template/lib/install_diagnostics.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def event(seq=1, **kw):
    return dict(schema=1, run_id='a' * 32, parent_run_id=None, seq=seq,
                installer_version=diag.VERSION, source_ref='49f683a', edition='intel-course',
                event='run-start', step_id='bootstrap.start', attempt=1, started_at='2026-11-13T00:00:00Z',
                ended_at=None, elapsed_ms=None, result='running', reason_code='STARTED',
                required=True, exit_code=None, exit_source='none', host='none', http_code=None,
                transport_code=None, proxy='unknown', clock='unverified', environment={'os': 'Darwin'}, path_facts={}, cwd_kind='unknown') | kw


class ContractTests(unittest.TestCase):
    def test_redaction_builds_only_safe_values_before_persistence(self):
        raw = event() | {'token': 'TOKEN-secret', 'error_tail': ['serial ILSON-SECRET email@host username private note'],
                         'cwd_display': '/Users/username/note', 'environment': {'os': 'Darwin', 'python': '3.9.1 secret'},
                         'path_facts': {'bin_in_path': True, 'PATH': 'username'}, 'host': 'https://user:token@evil/?q=note'}
        clean = diag.redact_event(raw)
        data = json.dumps(clean)
        for secret in ('TOKEN-secret', 'ILSON-SECRET', 'email@host', 'username', 'private note', 'evil'):
            self.assertNotIn(secret, data)
        with self.assertRaises(ValueError): diag.validate_event(raw)
        self.assertEqual(diag.validate_event(clean)['error_tail'], ['DETAIL_SUPPRESSED'])

    def test_required_skip_and_interruption_never_look_successful(self):
        events = [event(), event(2, event='step-start', step_id='helper.install'),
                  event(3, event='step-end', step_id='helper.install', result='skipped-with-reason', reason_code='DEPENDENCY_FAILED'),
                  event(4, event='run-end', step_id='finish', result='ok', reason_code='OK')]
        self.assertEqual(diag.summarize_run(events)['exit_code'], 1)
        self.assertEqual(diag.summarize_run(events[:-1])['status'], 'interrupted')

    def test_tsv_without_python_and_share_revalidation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = root / ('a' * 32); run.mkdir(mode=0o700)
            e = event()
            values = ['-' if e[k] is None else str(e[k]).lower() if isinstance(e[k], bool) else json.dumps(e[k]) if isinstance(e[k], dict) else str(e[k]) for k in diag.TSV_FIELDS]
            fd = os.open(run / 'events.tsv', os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'w') as stream: stream.write('\t'.join(values) + '\ntruncated')
            events, damaged = diag.read_run(run)
            self.assertTrue(damaged); self.assertEqual(len(events), 1)
            reference = diag.export_share(events, root, damaged)
            self.assertEqual(json.loads((root / 'share' / (reference + '.json')).read_text())['summary']['status'], 'interrupted')

    def test_retention_preserves_unknown_files_and_limits_completed_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); runs = root / 'runs'; runs.mkdir(mode=0o700)
            for i in range(23):
                name = '%032x' % i; folder = runs / name; folder.mkdir(mode=0o700)
                fd = os.open(folder / 'events.jsonl', os.O_WRONLY | os.O_CREAT, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(json.dumps(event(run_id=name)) + '\n')
                    stream.write(json.dumps(event(2, run_id=name, event='run-end', step_id='finish', result='ok', reason_code='OK')) + '\n')
            other = runs / ('f' * 32); other.mkdir(mode=0o700); (other / 'student-note').write_text('keep')
            diag.retain(root)
            self.assertEqual(len(list(runs.glob('*/events.jsonl'))), 20)
            self.assertEqual((other / 'student-note').read_text(), 'keep')

    def test_symlink_storage_rejected_and_cli_does_not_need_license_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp); (home / 'real').mkdir(); (home / '.ilson-diagnostics').symlink_to(home / 'real')
            with self.assertRaises(ValueError): diag.safe_path(home / '.ilson-diagnostics/runs', private=True)
            result = subprocess.run([sys.executable, str(ROOT / 'template/lib/install_diagnostics.py'), '--install', '--json'],
                                    env=dict(os.environ, HOME=temp, ILSON_DIAGNOSTICS_DIR=str(home / 'missing')),
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads(result.stdout)['status'], 'interrupted')
            self.assertFalse((home / 'missing').exists())


class NativeTests(unittest.TestCase):
    def run_native(self, code, home):
        return subprocess.run(['bash', '-c', '. "$1"; ' + code, 'test', str(ROOT / 'tools/diagnostics.sh')],
                              env=dict(os.environ, HOME=str(home)), capture_output=True, text=True, timeout=10)

    def test_first_download_failure_and_sanitized_dns_http_timeout(self):
        for curl_code, http, reason in [(6,'000','DNS_FAILED'),(22,'503','HTTP_FAILED'),(28,'000','TIMEOUT')]:
            with self.subTest(curl_code=curl_code), tempfile.TemporaryDirectory() as temp:
                home=Path(temp).resolve()
                code=('curl() { printf "' + http + '"; printf "email@secret token serial note username" >&2; return ' + str(curl_code) + '; }; '
                      'diag_begin intel-course; diag_download "https://claude.ai/install.sh?token=secret" "$HOME/download" tools.claude.download || :; '
                      'diag_skip tools.claude.execute DEPENDENCY_FAILED; diag_finish 0')
                result=self.run_native(code,home)
                self.assertEqual(result.returncode,1,result.stderr)
                folder=next((home/'.ilson-diagnostics/runs').iterdir())
                events, damaged=diag.read_run(folder)
                self.assertFalse(damaged)
                self.assertIn(reason,[e['reason_code'] for e in events])
                for secret in ('email@secret','token','serial','note','username'):
                    self.assertNotIn(secret,(folder/'events.tsv').read_text())
                doctor=subprocess.run(['sh',str(ROOT/'tools/doctor.sh'),'--share'],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=10)
                self.assertEqual(doctor.returncode,1,doctor.stderr)
                self.assertIn('공유 참조:',doctor.stdout)

    def test_dry_run_zero_writes_and_interrupt_remains_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            result=self.run_native('diag_begin intel-course --dry-run; diag_step_start runtime.python; diag_finish 0',home)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((home/'.ilson-diagnostics').exists())
            self.run_native('diag_begin intel-course; diag_step_start runtime.python',home)
            folder=next((home/'.ilson-diagnostics/runs').iterdir())
            events,damaged=diag.read_run(folder)
            self.assertEqual(diag.summarize_run(events,damaged)['status'],'interrupted')

    def test_native_recorder_is_identically_embedded_in_standalone_doctor(self):
        source=(ROOT/'tools/doctor.sh').read_text().split('# DIAGNOSTICS_BEGIN\n')[1].split('# DIAGNOSTICS_END')[0]
        self.assertEqual(source,(ROOT/'tools/diagnostics.sh').read_text())


class InstallerIntegrationTests(unittest.TestCase):
    def test_python39_intel_records_required_failure_and_doctor_without_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            for app in ('Orca','Obsidian'): (home/'Applications'/(app+'.app')).mkdir(parents=True)
            hook=home/'hook'
            hook.write_text(r'''
uname() { case "$1" in -s) echo Darwin ;; -m) echo x86_64 ;; esac; }
sysctl() { return 1; }
sw_vers() { echo 13.6; }
claude() { echo '1.2.3'; }
python3() { return 1; }
command() {
 case "$*" in '-v claude'|'-v python3') return 0 ;; '-v python3.'*) return 1 ;; esac
 builtin command "$@"
}
curl() { dest=; while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then dest=$2; shift; fi; shift; done; printf fixture > "$dest"; printf 200; }
''')
            result=subprocess.run(['bash',str(ROOT/'course/install-intel-mac.sh')],env=dict(os.environ,HOME=str(home),BASH_ENV=str(hook)),capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertFalse((home/'.local/bin/ilson').exists())
            folder=next((home/'.ilson-diagnostics/runs').iterdir())
            events,damaged=diag.read_run(folder)
            summary=diag.summarize_run(events,damaged)
            self.assertEqual(summary['first_failure'],'PYTHON_TOO_OLD')
            self.assertEqual(summary['steps']['helper.install'],{'result':'skipped-with-reason','reason_code':'DEPENDENCY_FAILED'})
            doctor=subprocess.run(['sh',str(ROOT/'tools/doctor.sh'),'--share'],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=10)
            self.assertEqual(doctor.returncode,1,doctor.stderr)
            self.assertIn('PYTHON_TOO_OLD',doctor.stdout)

    def test_cli_doctor_before_license_smart_dash_wrong_edition_and_wrong_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve();vault=home/'한글 볼트';vault.mkdir()
            env=dict(os.environ,HOME=str(home),ILSON_COURSE_VAULT=str(vault))
            for args in (['--version'],['--help']):
                r=subprocess.run([sys.executable,str(ROOT/'course/ilson.py')]+args,env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([sys.executable,str(ROOT/'course/ilson.py'),'—version'],env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,2);self.assertIn('SMART_DASH',r.stdout)
            native=subprocess.run(['bash','-c','. "$1"; diag_begin full-mac; diag_finish 0','test',str(ROOT/'tools/diagnostics.sh')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(native.returncode,0,native.stderr)
            r=subprocess.run([sys.executable,str(ROOT/'course/ilson.py'),'doctor','--install','--json'],env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,2,r.stderr)
            data=json.loads(r.stdout);self.assertEqual(data['first_failure'],'WRONG_INSTALLER');self.assertEqual(data['cwd_kind'],'outside_vault')
            self.assertTrue(data['vault_exists']);self.assertFalse((home/'.ilson-course/state/license').exists())

    def test_generated_inline_bootstrap_records_first_fetch_and_never_executes_partial_code(self):
        spec=importlib.util.spec_from_file_location('build_commands',ROOT/'tools/build_install_commands.py')
        commands=importlib.util.module_from_spec(spec);spec.loader.exec_module(commands)
        for failure in (6,22,28,0):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temp:
                home=Path(temp).resolve();hook=home/'hook'
                hook.write_text('curl() { dest=; while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then dest=$2; shift; fi; shift; done; printf \'touch "$HOME/partial-executed"\\n\' > "$dest"; printf 503; return '+str(failure)+'; }; export -f curl\n')
                command=commands.build('a'*40,'intel-course')
                self.assertNotIn('\n',command)
                # bash is used for the outer harness so exported fake curl reaches macOS /bin/sh.
                r=subprocess.run(['bash','-c',command],env=dict(os.environ,HOME=str(home),BASH_ENV=str(hook),TMPDIR=str(home)),capture_output=True,text=True,timeout=15)
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                self.assertFalse((home/'partial-executed').exists())
                folder=next((home/'.ilson-diagnostics/runs').iterdir())
                events,damaged=diag.read_run(folder)
                self.assertFalse(damaged)
                self.assertIn('HASH_MISMATCH' if failure==0 else {6:'DNS_FAILED',22:'HTTP_FAILED',28:'TIMEOUT'}[failure],[e['reason_code'] for e in events])

    def test_native_log_retention_does_not_touch_student_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            run=subprocess.run(['bash','-c','. "$1"; for n in $(seq 1 23); do unset ILSON_DIAG_RUN_ID; diag_begin intel-course; diag_finish 0; done','test',str(ROOT/'tools/diagnostics.sh')],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(len(list((home/'.ilson-diagnostics/runs').iterdir())),20)

    def test_windows_51_static_contract_and_payload_parity(self):
        import base64,gzip,re
        ps=(ROOT/'course/install-windows.ps1').read_bytes()
        ps.decode('ascii');self.assertNotIn(b'\x00',ps)
        self.assertIn(b'New-Object System.Text.UTF8Encoding($false)',ps)
        self.assertNotIn(b'Out-File -Encoding utf8',ps)
        self.assertIn(b'[Net.WebException]',ps)
        self.assertIn(b'NameResolutionFailure',ps)
        self.assertLess(ps.index(b'Start-IlsonDiagnostics \'windows-course\''),ps.index(b'$CoursePayload='))
        for file,prefix in [('course/install-intel-mac.sh','COURSE_PAYLOAD'),('course/install-windows.ps1',r'\$CoursePayload')]:
            value=re.search(prefix+r"='([^']+)'",(ROOT/file).read_text()).group(1)
            files=json.loads(gzip.decompress(base64.b64decode(value)))
            for name,content in files.items():
                source=ROOT/'course'/('' if name=='ilson.py' else 'lib')/name
                self.assertEqual(content,source.read_text())
        self.assertEqual((ROOT/'course/lib/install_diagnostics.py').read_bytes(),(ROOT/'template/lib/install_diagnostics.py').read_bytes())


class ShellConfirmationTests(unittest.TestCase):
    def test_current_new_and_simulated_checks_are_distinct_and_wrong_name_is_not_confirmed(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve();bin_dir=home/'.local/bin';bin_dir.mkdir(parents=True)
            wrapper=bin_dir/'ilson'
            fd=os.open(wrapper,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o755)
            import shlex
            with os.fdopen(fd,'w') as stream:
                stream.write('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(ROOT/'course/ilson.py'))+' "$@"\n')
            env=dict(os.environ,HOME=str(home),PATH='/usr/bin:/bin')
            setup=subprocess.run(['bash','-c','. "$1"; diag_begin intel-course; diag_skip verify.current USER_CONFIRMATION_REQUIRED false; diag_skip verify.new-window USER_CONFIRMATION_REQUIRED false; diag_finish 0','test',str(ROOT/'tools/diagnostics.sh')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(setup.returncode,0,setup.stderr)
            run=next((home/'.ilson-diagnostics/runs').iterdir()).name
            def doctor(*args, changed_env=None):
                r=subprocess.run([sys.executable,str(ROOT/'course/ilson.py'),'doctor','--install','--run',run,'--json']+list(args),env=changed_env or env,capture_output=True,text=True,timeout=10)
                self.assertFalse(r.stderr,r.stderr)
                return r,json.loads(r.stdout)
            r,data=doctor('--confirm-shell','current')
            self.assertEqual(data['current'],'failed');self.assertEqual(data['new_window'],'skipped-with-reason')
            current_env=dict(env,PATH=str(bin_dir)+':'+env['PATH'])
            r,data=doctor('--confirm-shell','current',changed_env=current_env)
            self.assertEqual(data['current'],'ok');self.assertEqual(r.returncode,4)
            r,data=doctor('--confirm-shell','new',changed_env=current_env)
            self.assertEqual(r.returncode,0);self.assertEqual(data['new_window'],'ok')
            native=subprocess.run(['sh',str(ROOT/'tools/doctor.sh'),'--run',run,'--share'],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(native.returncode,0,native.stdout+native.stderr)
            # A different command with the same name must not be accepted even if it prints our version.
            other=home/'other';other.mkdir();fake=other/'ilson'
            fd=os.open(fake,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o755)
            with os.fdopen(fd,'w') as stream: stream.write('#!/bin/sh\necho "ilson intel-course ILSON-DIAG-1"\n')
            r,data=doctor('--confirm-shell','current',changed_env=dict(env,PATH=str(other)+':'+env['PATH']))
            self.assertEqual(data['current'],'failed')
            r,data=doctor('--simulate-shell','bash',changed_env=current_env)
            self.assertIn('verify.simulated',data['steps'])
            self.assertEqual(data['current'],'failed')

    def test_probe_output_is_bounded_and_custom_paths_are_shell_quoted(self):
        code,output=diag.probe_command([sys.executable,'-c',"print('private note'*100000)"])
        self.assertNotEqual(code,0);self.assertEqual(output,b'')
        from unittest import mock
        with mock.patch.object(diag.os, 'killpg', side_effect=PermissionError('synthetic signal restriction')):
            code,output=diag.probe_command([sys.executable,'-c',"print('synthetic'*100000)"])
        self.assertNotEqual(code,0);self.assertEqual(output,b'')
        lines=diag.next_lines('intel-course','a'*32,cli="/a path/with'quote/ilson")
        import shlex
        self.assertEqual(shlex.split(lines[-1])[0],"/a path/with'quote/ilson")
        self.assertEqual(diag.next_lines('intel-course','a'*32,cli='/bad\npath'),['강사와 경로 확인'])

    def test_log_link_rejection_and_wrong_installer_are_recorded_without_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve();(home/'real').mkdir();(home/'.ilson-diagnostics').symlink_to(home/'real')
            r=subprocess.run(['bash','-c','. "$1"; diag_begin intel-course; diag_finish 0','test',str(ROOT/'tools/diagnostics.sh')],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,3);self.assertIn('LOG_UNAVAILABLE',r.stderr)
            self.assertEqual(list((home/'real').iterdir()),[])
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve();hook=home/'hook'
            hook.write_text('uname() { case "$1" in -s) echo Darwin;; -m) echo arm64;; esac; }; sysctl() { return 1; }\n')
            r=subprocess.run(['bash',str(ROOT/'course/install-intel-mac.sh')],env=dict(os.environ,HOME=str(home),BASH_ENV=str(hook)),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,2)
            folder=next((home/'.ilson-diagnostics/runs').iterdir());events,damaged=diag.read_run(folder)
            self.assertFalse(damaged);self.assertIn('WRONG_INSTALLER',[e['reason_code'] for e in events])
            self.assertFalse((home/'.ilson-course').exists())


class SetupDownloadTests(unittest.TestCase):
    def test_actual_setup_tool_path_keeps_claude_dns_codex_503_and_path_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp).resolve()
            functions=(ROOT/'ilson').read_text().split('cmd="${1:-}"')[0]
            harness=home/'setup.sh'
            harness.write_text(functions+r'''
diag_begin full-mac
has() { case "$1" in brew|git|jq|gh|gtimeout|python3|node|aside|hc|tvly) return 0;; *) return 1;; esac; }
diag_verify() { return 0; }
app_present() { return 0; }
curl() {
 case "$*" in *claude.ai*) printf 000; printf 'SERIAL-TOKEN email@example private-note username' >&2; return 6;; *) printf 503; return 22;; esac
}
setup_rc=0; setup_tools || setup_rc=$?
diag_skip verify.current USER_CONFIRMATION_REQUIRED false
diag_skip verify.new-window USER_CONFIRMATION_REQUIRED false
diag_finish "$setup_rc"
''')
            r=subprocess.run(['bash',str(harness)],env=dict(os.environ,HOME=str(home)),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,1,r.stdout+r.stderr)
            folder=next((home/'.ilson-diagnostics/runs').iterdir());events,damaged=diag.read_run(folder)
            self.assertFalse(damaged)
            data=diag.summarize_run(events)
            self.assertEqual(data['steps']['tools.claude.download']['reason_code'],'DNS_FAILED')
            self.assertEqual(data['steps']['tools.codex.download']['reason_code'],'HTTP_FAILED')
            self.assertEqual(data['steps']['tools.claude.execute']['reason_code'],'DEPENDENCY_FAILED')
            self.assertEqual(data['steps']['tools.codex.execute']['reason_code'],'DEPENDENCY_FAILED')
            self.assertEqual(data['current'],'skipped-with-reason')
            self.assertEqual(data['new_window'],'skipped-with-reason')
            for secret in ('SERIAL-TOKEN','email@example','private-note','username'):
                self.assertNotIn(secret,(folder/'events.tsv').read_text())
            reference=diag.export_share(events,folder.parent.parent)
            for suffix in ('txt','json'):
                share=(folder.parent.parent/'share'/(reference+'.'+suffix)).read_text()
                for secret in ('SERIAL-TOKEN','email@example','private-note','username'): self.assertNotIn(secret,share)


if __name__ == '__main__': unittest.main()
