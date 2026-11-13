"""Cross-runtime version contract and recoverable Windows install histories."""
import base64
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from test_install_diagnostics import ROOT, diag, event


VALID = ('5.1.26100.9818', '10.0.26100', '7.4.6', '26.6.2', '3.15.2',
         '123456.123456.123456.123456', 'missing', 'unknown')
INVALID = ('version 5.1.26100.9818 private-note', '7.4.6-preview', '1234567.0',
           '1.2.3.4.5', '1', '1..2', '1.2\n', '1.2\n3.4', '１.２', '', None, 123,
           {'private-note': 'suppressed'})


def windows_events():
    # Faithful Windows run: upgrade succeeded; both shell confirmations await user.
    env = {'os': 'Windows', 'arch': 'AMD64', 'shell': 'powershell',
           'shell_version': '5.1.26100.9818', 'os_version': '10.0.26100'}
    entries = [event(edition='windows-course', environment=env)]
    for step in ('verify.current', 'verify.new-window'):
        entries.append(event(len(entries)+1, edition='windows-course', environment=env,
                             event='step-start', step_id=step, required=False))
        entries.append(event(len(entries)+1, edition='windows-course', environment=env,
                             event='step-end', step_id=step, required=False,
                             result='skipped-with-reason', reason_code='USER_CONFIRMATION_REQUIRED'))
    entries.append(event(len(entries)+1, edition='windows-course', environment=env,
                         event='run-end', step_id='finish', result='ok', reason_code='OK'))
    return entries


def write_run(home, entries, suffix='jsonl', extra=b''):
    root = home / 'diagnostics'
    root.mkdir(mode=0o700)
    (root / 'runs').mkdir(mode=0o700)
    folder = root / 'runs' / ('a'*32)
    folder.mkdir(mode=0o700)
    def encode(e):
        if suffix == 'jsonl': return json.dumps(e)
        return '\t'.join('-' if e.get(k) is None else json.dumps(e[k]) if isinstance(e[k], (bool, dict)) else str(e[k]) for k in diag.TSV_FIELDS)
    fd = os.open(folder / ('events.'+suffix), os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(''.join(encode(e)+'\n' for e in entries).encode()+extra)
    return root, folder


class VersionTests(unittest.TestCase):
    def test_shared_version_rule_and_field_redaction(self):
        schema = json.loads((ROOT / 'tools/diagnostic-schema.json').read_text())
        for key in diag.VERSION_FIELDS:
            pattern = schema['properties']['environment']['properties'][key]['pattern']
            self.assertEqual(pattern, diag.VERSION_PATTERN)
            self.assertEqual(schema['properties']['environment']['properties'][key]['not'], {'pattern': r'[\r\n]'})
            for value in VALID + INVALID:
                with self.subTest(key=key, value=value):
                    expected = value if value in VALID else 'unknown'
                    clean = diag.validate_event(event(environment={key: value}))
                    self.assertEqual(clean['environment'][key], expected)
                    if isinstance(value, str):
                        self.assertEqual(bool(re.fullmatch(pattern, value)), value in VALID)
        for filename, declaration in [('tools/diagnostics.sh', "DIAG_VERSION_PATTERN='"),
                                      ('tools/diagnostics.ps1', "$script:DiagVersionPattern = '")]:
            self.assertIn(declaration+diag.VERSION_PATTERN+"'", (ROOT / filename).read_text())

    def test_shell_rule_executes_same_version_matrix(self):
        for value in VALID + tuple(v for v in INVALID if isinstance(v, str)):
            result = subprocess.run(['sh', '-c', '. "$1"; diag_version "$2"', 'test',
                                     str(ROOT / 'tools/diagnostics.sh'), value],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, value if value in VALID else 'unknown')

    def test_windows_jsonl_and_native_tsv_retain_events_and_pending_status(self):
        for suffix in ('jsonl', 'tsv'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp:
                root, folder = write_run(Path(temp).resolve(), windows_events(), suffix)
                entries, damaged = diag.read_run(folder)
                self.assertFalse(damaged)
                self.assertEqual(len(entries), 6)
                self.assertEqual(diag.summarize_run(entries)['exit_code'], 4)
                reference = diag.export_share(entries, root)
                share = json.loads((root / 'share' / (reference+'.json')).read_text())
                self.assertEqual(share['summary']['status'], 'pending')
                self.assertEqual(share['events'][0]['environment']['shell_version'], '5.1.26100.9818')
                with mock.patch.dict(os.environ, ILSON_DIAGNOSTICS_DIR=str(root)), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = diag.main(['--install', '--json'], edition='windows-course')
                self.assertEqual(code, 4)
                self.assertEqual(json.loads(output.getvalue())['run_id'], 'a'*32)

    def test_bad_metadata_field_keeps_event_and_share_has_no_raw_value(self):
        entries = windows_events()
        entries[0] = entries[0] | {'environment': entries[0]['environment'] | {'shell_version': 'private-note', 'python': 123},
                                    'exception_class': 'private-note'}
        with tempfile.TemporaryDirectory() as temp:
            root, folder = write_run(Path(temp).resolve(), entries)
            cleaned, damaged = diag.read_run(folder)
            self.assertFalse(damaged)
            self.assertEqual(len(cleaned), len(entries))
            self.assertEqual(cleaned[0]['environment']['shell_version'], 'unknown')
            self.assertEqual(cleaned[0]['environment']['python'], 'unknown')
            reference = diag.export_share(cleaned, root)
            data = (root / 'share' / (reference+'.json')).read_text()
            self.assertNotIn('private-note', data)
            self.assertEqual(json.loads(data)['summary']['exit_code'], 4)

    def test_malformed_lines_report_damage_and_keep_run_identity_even_without_events(self):
        for entries in (windows_events(), []):
            for extra in (b'{private-note}\n', b'{truncated', b'[]\n', b'null\n', b'{"schema":1}\n'):
                with self.subTest(events=len(entries), extra=extra), tempfile.TemporaryDirectory() as temp:
                    root, folder = write_run(Path(temp).resolve(), entries, extra=extra)
                    with mock.patch.dict(os.environ, ILSON_DIAGNOSTICS_DIR=str(root)), contextlib.redirect_stdout(io.StringIO()) as output:
                        code = diag.main(['--install', '--json', '--share'], edition='windows-course')
                    self.assertEqual(code, 3)
                    summary = json.loads(output.getvalue())
                    self.assertEqual(summary['status'], 'damaged')
                    self.assertEqual(summary['log_status'], 'malformed')
                    self.assertEqual(summary['run_id'], folder.name)
                    shared = json.loads((root / 'share' / (summary['reference']+'.json')).read_text())
                    self.assertEqual(len(shared['events']), len(entries))
                    self.assertEqual(shared['summary']['run_id'], folder.name)
                    self.assertNotIn('private-note', json.dumps(shared))

    def test_standalone_shell_distinguishes_damage_from_unfinished_install(self):
        for malformed in (False, True, 'truncated'):
            with tempfile.TemporaryDirectory() as temp:
                root, folder = write_run(Path(temp).resolve(), windows_events() if malformed else windows_events()[:-1],
                                         suffix='tsv', extra=b'broken' if malformed == 'truncated' else b'broken\n' if malformed else b'')
                result = subprocess.run(['sh', str(ROOT / 'tools/doctor.sh'), '--run', folder.name],
                                        env=dict(os.environ, ILSON_DIAGNOSTICS_DIR=str(root)),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 3, result.stdout+result.stderr)
                self.assertIn('status='+('damaged' if malformed else 'interrupted'), result.stdout)
                self.assertIn('log_status='+('malformed' if malformed else 'ok'), result.stdout)
                self.assertIn('run_id='+folder.name, result.stdout)
                self.assertEqual(result.stdout.count('status=damaged'), 1 if malformed else 0)

    def test_generated_recorders_and_course_payload_match_sources(self):
        for suffix, names in [('sh', ['ilson', 'install.sh', 'course/install-intel-mac.sh', 'tools/doctor.sh', 'tools/bootstrap.sh']),
                              ('ps1', ['course/install-windows.ps1', 'tools/doctor.ps1', 'tools/bootstrap.ps1'])]:
            for name in names:
                embedded = (ROOT / name).read_text().split('# DIAGNOSTICS_BEGIN\n')[1].split('# DIAGNOSTICS_END')[0]
                self.assertEqual(embedded, (ROOT / ('tools/diagnostics.'+suffix)).read_text())
        for name, key in [('course/install-intel-mac.sh', 'COURSE_PAYLOAD'), ('course/install-windows.ps1', r'\$CoursePayload')]:
            payload = re.search(key+r"='([^']+)'", (ROOT / name).read_text()).group(1)
            files = json.loads(gzip.decompress(base64.b64decode(payload)))
            self.assertEqual(files['install_diagnostics.py'], (ROOT / 'template/lib/install_diagnostics.py').read_text())
            self.assertEqual(files['install_payload.py'], (ROOT / 'course/install_payload.py').read_text())

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell unavailable; Windows 5.1 remains a device check')
    def test_powershell_rule_executes_same_version_matrix_and_doctor_reads_history(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            values = home / 'versions.json'
            values.write_text(json.dumps(VALID+INVALID))
            script = home / 'check.ps1'
            script.write_text('param($Source,$Values)\n. $Source\n@(Get-Content -Raw -LiteralPath $Values | ConvertFrom-Json) | ForEach-Object {Get-IlsonDiagVersion $_}\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(ROOT / 'tools/diagnostics.ps1'), str(values)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [v if v in VALID else 'unknown' for v in VALID+INVALID])
            root, folder = write_run(home, windows_events())
            for extra, code, status in [(b'', 4, 'pending'), (b'broken\n', 3, 'damaged')]:
                if extra:
                    with (folder / 'events.jsonl').open('ab') as stream: stream.write(extra)
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'tools/doctor.ps1'), '-Run', folder.name],
                                        env=dict(os.environ, ILSON_DIAGNOSTICS_DIR=str(root)), capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, code, result.stdout+result.stderr)
                self.assertIn('status='+status, result.stdout)
                self.assertIn('run_id='+folder.name, result.stdout)


if __name__ == '__main__': unittest.main()
