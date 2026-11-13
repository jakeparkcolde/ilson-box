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
                transport_code=None, proxy='unknown', clock='unverified') | kw


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
            values = ['-' if e[k] is None else str(e[k]).lower() if isinstance(e[k], bool) else str(e[k]) for k in diag.TSV_FIELDS]
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


if __name__ == '__main__': unittest.main()
