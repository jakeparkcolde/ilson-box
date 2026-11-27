"""Unit and contract tests for Full Install Tracking across server, installers, client, and CLI."""
import base64
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pwsh_support import offline_installer_source

ROOT = Path(__file__).resolve().parents[1]
SEED = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
PUBLIC = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')


def load_module(name, rel_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_v1_serial(lic_mod, now=None):
    now = int(time.time() if now is None else now)
    payload = struct.pack('>BB16sHBII', 1, 1, b'k' * 16, 1, 1, now - 60, 0xffffffff)
    return lic_mod.encode_serial(payload, SEED)


class NodeApiContractTests(unittest.TestCase):
    """Exercise server/license/api/v1/[action].js directly via mocked fetch in Node."""

    def call_action(self, action, body, admin=False, rpc_response=None, rate_ok=True):
        js = r'''
const handler = require(process.argv[1]);
const payload = JSON.parse(process.argv[2]);
process.env.ILSON_PUBLIC_KEY_1 = payload.pub;
process.env.ILSON_ADMIN_SECRET = 'test-admin-secret';
process.env.SUPABASE_URL = 'https://example.invalid';
process.env.SUPABASE_SECRET_KEY = 'test-sb-key';
const captured = [];
global.fetch = async (url, opts) => {
  const fn = url.pathname.split('/').pop();
  const parsed = JSON.parse(opts.body);
  captured.push({ fn, body: parsed });
  if (fn === 'ilson_rate_limit') return { ok: true, json: async () => payload.rate_ok };
  return { ok: true, json: async () => payload.rpc_response };
};
const res = {
  setHeader() {},
  status(code) { this.code = code; return this; },
  json(value) {
    process.stdout.write(JSON.stringify({ code: this.code, value, captured }));
    return this;
  },
};
handler({
  method: 'POST',
  query: { action: payload.action },
  body: { nonce: 'a'.repeat(32), ...payload.body },
  headers: {
    'x-forwarded-for': '192.0.2.10',
    ...(payload.admin ? { 'x-ilson-admin': 'test-admin-secret' } : {}),
  },
}, res).catch((err) => { console.error(err); process.exit(2); });
'''
        arg = {
            'pub': PUBLIC.hex(),
            'action': action,
            'body': body,
            'admin': admin,
            'rate_ok': rate_ok,
            'rpc_response': rpc_response if rpc_response is not None else {'status': 'ok'},
        }
        proc = subprocess.run(
            ['node', '-e', js, str(ROOT / 'server/license/api/v1/[action].js'), json.dumps(arg)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_install_telemetry_validation_and_forwarding(self):
        valid = {
            'run_id': 'a' * 32,
            'edition': 'windows-course',
            'os': 'Windows',
            'arch': 'AMD64',
            'os_version': '10.0.26100',
            'shell': 'powershell',
            'shell_version': '5.1.26100.1',
            'installer_version': 'ILSON-DIAG-1',
            'result': 'failed',
            'exit_code': 1,
            'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'HTTP_FAILED', 'http_code': 503}],
            'helper_status': 'INSTALLED',
        }
        res = self.call_action('install-telemetry', valid)
        self.assertEqual(res['code'], 200)
        self.assertEqual(res['value']['status'], 'ok')
        rpc_call = next(c for c in res['captured'] if c['fn'] == 'ilson_install_telemetry')
        self.assertEqual(rpc_call['body']['p']['run_id'], 'a' * 32)
        self.assertRegex(rpc_call['body']['p']['ip_hash'], r'^[a-f0-9]{64}$')

        # Rate limit response
        rl = self.call_action('install-telemetry', valid, rpc_response={'status': 'rate_limited'})
        self.assertEqual(rl['code'], 429)
        self.assertEqual(rl['value']['status'], 'rate_limited')

        # Invalid enums, PII, unknown keys, oversized failed_steps rejected with 400
        bad_cases = [
            {**valid, 'run_id': 'not-hex'},
            {**valid, 'edition': 'unknown'},
            {**valid, 'os': 'Solaris'},
            {**valid, 'arch': 'mips'},
            {**valid, 'os_version': '10.0 /Users/jake'},
            {**valid, 'shell': 'fish'},
            {**valid, 'installer_version': 'has space'},
            {**valid, 'result': 'pending'},
            {**valid, 'helper_status': 'BROKEN'},
            {**valid, 'username': 'jake'},
            {**valid, 'failed_steps': [{'step_id': 'bogus.step', 'reason_code': 'TIMEOUT'}]},
            {**valid, 'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'BOGUS_REASON'}]},
            {**valid, 'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'HTTP_FAILED', 'http_code': 999}]},
            {**valid, 'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'TIMEOUT', 'pii': 'x'}]},
            {**valid, 'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'TIMEOUT'}] * 21},
        ]
        for idx, bad in enumerate(bad_cases):
            with self.subTest(idx=idx):
                r = self.call_action('install-telemetry', bad)
                self.assertEqual(r['code'], 400)
                self.assertEqual(r['value']['status'], 'invalid_request')
                self.assertFalse(any(c['fn'] == 'ilson_install_telemetry' for c in r['captured']))

    def test_admin_overview_auth_and_cohort_filter(self):
        unauth = self.call_action('admin-overview', {}, admin=False)
        self.assertEqual(unauth['code'], 403)
        self.assertEqual(unauth['value']['error'], 'UNAUTHORIZED')

        for bad_cohort in (0, -1, 65536, '1', 1.5):
            r = self.call_action('admin-overview', {'cohort': bad_cohort}, admin=True)
            self.assertEqual(r['code'], 400)
            self.assertEqual(r['value']['status'], 'invalid_request')

        sample_rpc = {
            'status': 'ok',
            'summary': {'total_licenses': 1},
            'cohorts': [],
            'licenses': [],
            'install_runs': [],
            'failure_breakdown': [],
        }
        ok = self.call_action('admin-overview', {'cohort': 2}, admin=True, rpc_response=sample_rpc)
        self.assertEqual(ok['code'], 200)
        self.assertEqual(ok['value']['status'], 'ok')
        rpc_call = next(c for c in ok['captured'] if c['fn'] == 'ilson_admin_overview')
        self.assertEqual(rpc_call['body']['p'], {'cohort': 2})

    def test_activate_and_check_sanitize_client_meta_without_breaking(self):
        lic = load_module('ilson_lic_contract', 'template/lib/license.py')
        serial = make_v1_serial(lic)
        dev = '1' * 64
        # Valid client_meta on V1 activate
        res = self.call_action(
            'activate',
            {
                'serial': serial,
                'device_id': dev,
                'client_meta': {
                    'os': 'macOS', 'arch': 'arm64', 'edition': 'mac-box',
                    'client_version': 'ILSON-DIAG-1', 'run_id': 'b' * 32, 'extra_pii': 'drop-me',
                },
            },
            rpc_response={'status': 'active', 'expires_at': None, 'paid_until': None},
        )
        self.assertEqual(res['code'], 200)
        rpc_p = next(c for c in res['captured'] if c['fn'] == 'ilson_license_request')['body']['p']
        self.assertEqual(rpc_p['client_meta'], {
            'os': 'macOS', 'arch': 'arm64', 'edition': 'mac-box',
            'client_version': 'ILSON-DIAG-1', 'run_id': 'b' * 32,
        })

        # Malformed client_meta on V2 short serial activate still succeeds, invalid fields stripped
        res_v2 = self.call_action(
            'activate',
            {
                'serial': 'IL2-ABCD-EFGH-JKLM',
                'device_id': dev,
                'client_meta': {'os': 'PII', 'arch': 'AMD64', 'run_id': 'bad'},
            },
            rpc_response={'status': 'active', 'expires_at': None, 'paid_until': None, 'sealed_serial': 'A' * 188},
        )
        self.assertEqual(res_v2['code'], 200)
        rpc_v2 = next(c for c in res_v2['captured'] if c['fn'] == 'ilson_license_request')['body']['p']
        self.assertEqual(rpc_v2['client_meta'], {'arch': 'AMD64'})

        # Non-object client_meta on check ignored completely
        res_chk = self.call_action(
            'check',
            {'serial': serial, 'device_id': dev, 'client_meta': 'not-an-object'},
            rpc_response={'status': 'active', 'expires_at': None, 'paid_until': None},
        )
        self.assertEqual(res_chk['code'], 200)
        rpc_chk = next(c for c in res_chk['captured'] if c['fn'] == 'ilson_license_request')['body']['p']
        self.assertNotIn('client_meta', rpc_chk)


class SqlMigrationContractTests(unittest.TestCase):
    def test_004_migration_is_additive_idempotent_rls_protected_and_secret_safe(self):
        sql = (ROOT / 'server/license/migrations/004_install_tracking.sql').read_text(encoding='utf-8')
        self.assertIn('begin;', sql)
        self.assertIn('commit;', sql)
        self.assertIn('add column if not exists os text', sql)
        self.assertIn('create table if not exists license_private.install_runs', sql)
        self.assertIn('alter table license_private.install_runs enable row level security;', sql)
        self.assertIn('revoke all on license_private.install_runs from public, anon, authenticated;', sql)
        for fn in ('ilson_license_request', 'ilson_install_telemetry', 'ilson_admin_overview'):
            self.assertIn(f'create or replace function public.{fn}(p jsonb)', sql)
            self.assertIn(f'revoke all on function public.{fn}(jsonb) from public, anon, authenticated;', sql)
            self.assertIn(f'grant execute on function public.{fn}(jsonb) to service_role;', sql)
        # Admin overview must never expose raw secrets or full device_hash
        overview_sql = sql.split('create or replace function public.ilson_admin_overview', 1)[1]
        self.assertNotIn('sealed_serial', overview_sql)
        self.assertNotIn('payload_hash', overview_sql)
        self.assertIn('left(d.device_hash, 12)', overview_sql)
        self.assertIn('(l.short_code_hash is not null) as has_short_serial', overview_sql)
        self.assertNotIn("'short_code_hash'", overview_sql)


class ClientMetaTests(unittest.TestCase):
    def test_client_meta_picks_newest_hex_run_and_ignores_invalid_entries(self):
        for label, rel in (('course', 'course/lib/license.py'), ('template', 'template/lib/license.py')):
            mod = load_module(f'lic_meta_{label}', rel)
            with self.subTest(module=label), tempfile.TemporaryDirectory() as tmp:
                diag_dir = Path(tmp) / 'diag'
                # Missing dir -> safe, no run_id
                with patch.dict(os.environ, {'ILSON_DIAGNOSTICS_DIR': str(diag_dir)}):
                    meta = mod._client_meta()
                self.assertIn(meta['os'], ('Windows', 'macOS', 'Linux', 'unknown'))
                self.assertIn(meta['arch'], ('AMD64', 'arm64', 'x86_64', 'unknown'))
                self.assertEqual(meta['client_version'], 'ILSON-DIAG-1')
                self.assertNotIn('run_id', meta)

                # Populate valid & invalid entries in runs/
                runs = diag_dir / 'runs'
                runs.mkdir(parents=True)
                old_id = '1' * 32
                new_id = '2' * 32
                (runs / old_id).mkdir()
                (runs / new_id).mkdir()
                (runs / 'not-a-hex-dir').mkdir()
                (runs / ('3' * 32)).write_text('file-not-dir', encoding='utf-8')
                target = Path(tmp) / 'sym-target'
                target.mkdir()
                (runs / ('4' * 32)).symlink_to(target)
                now = time.time()
                os.utime(runs / old_id, (now - 100, now - 100))
                os.utime(runs / new_id, (now, now))
                os.utime(target, (now + 100, now + 100))

                with patch.dict(os.environ, {'ILSON_DIAGNOSTICS_DIR': str(diag_dir)}):
                    meta2 = mod._client_meta()
                self.assertEqual(meta2.get('run_id'), new_id)

                # P1 regression: Path.home() RuntimeError must never break _client_meta()
                with patch.dict(os.environ, {'ILSON_DIAGNOSTICS_DIR': ''}), \
                     patch.object(Path, 'home', side_effect=RuntimeError('no home')):
                    meta3 = mod._client_meta()
                self.assertIn(meta3['os'], ('Windows', 'macOS', 'Linux', 'unknown'))
                self.assertNotIn('run_id', meta3)

    def test_request_attaches_client_meta_for_activate_and_check_only(self):
        mod = load_module('lic_req_meta', 'course/lib/license.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / 'cert.pem'
            key = root / 'key.pem'
            subprocess.run(
                ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                 '-keyout', str(key), '-out', str(cert), '-days', '1',
                 '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            received = {}
            now = int(time.time())

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    act = self.path.rsplit('/', 1)[-1]
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    received[act] = body
                    resp = json.dumps({'nonce': body['nonce'], 'status': 'active', 'server_time': now}).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)

            server = HTTPServer(('127.0.0.1', 0), Handler)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(lambda: (server.shutdown(), thread.join(), server.server_close()))

            endpoint = f'https://localhost:{server.server_port}'
            trusted = lambda: ssl.create_default_context(cafile=str(cert))
            with patch('ssl._create_default_https_context', side_effect=trusted):
                for act in ('activate', 'check', 'deactivate'):
                    mod.request(act, 'ILSON-TEST', 'a' * 64, url=endpoint)
            self.assertIn('client_meta', received['activate'])
            self.assertIn('client_meta', received['check'])
            self.assertNotIn('client_meta', received['deactivate'])


class IssuerOverviewTests(unittest.TestCase):
    def sample_overview(self):
        return {
            'status': 'ok',
            'summary': {
                'total_licenses': 2, 'active_licenses': 1, 'inactive_licenses': 1,
                'revoked_licenses': 0, 'total_active_devices': 1,
                'recent_runs_7d': 2, 'ok_runs_7d': 1, 'failed_runs_7d': 1,
            },
            'cohorts': [{'cohort': 1, 'total': 2, 'activated': 1, 'inactive': 1, 'active_devices': 1}],
            'licenses': [
                {
                    'id': 'a' * 32, 'display_name': '김수강', 'cohort': 1, 'plan': 1,
                    'status': 'active', 'issued': 1700000000, 'expires': None, 'paid_until': None,
                    'has_short_serial': True, 'device_limit': 2, 'active_devices': 1, 'total_devices': 1,
                    'first_activated_at': 1700000100, 'last_seen_at': 1700000200,
                    'devices': [{'device_hash_prefix': '1234567890ab', 'activated_at': 1700000100,
                                 'last_seen_at': 1700000200, 'released_at': None,
                                 'os': 'Windows', 'arch': 'AMD64', 'edition': 'windows-course',
                                 'client_version': 'ILSON-DIAG-1'}],
                },
                {
                    'id': 'b' * 32, 'display_name': '박미활', 'cohort': 1, 'plan': 1,
                    'status': 'active', 'issued': 1700000000, 'expires': None, 'paid_until': None,
                    'has_short_serial': False, 'device_limit': 2, 'active_devices': 0, 'total_devices': 0,
                    'first_activated_at': None, 'last_seen_at': None, 'devices': [],
                },
            ],
            'install_runs': [
                {
                    'run_id': 'c' * 32, 'edition': 'windows-course', 'os': 'Windows', 'arch': 'AMD64',
                    'os_version': '10.0.26100', 'shell': 'powershell', 'shell_version': '5.1.26100',
                    'installer_version': 'ILSON-DIAG-1', 'result': 'ok', 'exit_code': 0,
                    'failed_steps': [], 'helper_status': 'INSTALLED', 'license_id': 'a' * 32,
                    'display_name': '김수강', 'cohort': 1, 'created_at': 1700000050,
                },
                {
                    'run_id': 'd' * 32, 'edition': 'windows-course', 'os': 'Windows', 'arch': 'AMD64',
                    'os_version': '10.0.22631', 'shell': 'powershell', 'shell_version': '5.1.22621',
                    'installer_version': 'ILSON-DIAG-1', 'result': 'failed', 'exit_code': 1,
                    'failed_steps': [{'step_id': 'apps.herdr', 'reason_code': 'HTTP_FAILED', 'http_code': 503}],
                    'helper_status': None, 'license_id': None, 'display_name': None, 'cohort': None,
                    'created_at': 1700000060,
                },
            ],
            'failure_breakdown': [{'step_id': 'apps.herdr', 'reason_code': 'HTTP_FAILED', 'count': 1}],
        }

    def test_format_overview_contains_all_sections(self):
        issuer = load_module('issuer_fmt_test', 'server/license/issuer.py')
        out = issuer.format_overview(self.sample_overview())
        for needle in ('기수별 요약', '수강생별 상태', '김수강', 'V2', 'Windows/AMD64', '박미활', 'V1', '미활성', '(미활성화)', 'apps.herdr', 'HTTP_FAILED'):
            self.assertIn(needle, out)

    def test_cli_overview_env_secret_file_secret_and_json_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / 'cert.pem'
            key = root / 'key.pem'
            subprocess.run(
                ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                 '-keyout', str(key), '-out', str(cert), '-days', '1',
                 '-subj', '/CN=127.0.0.1',
                 '-addext', 'basicConstraints=critical,CA:TRUE',
                 '-addext', 'subjectAltName=IP:127.0.0.1'],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            sample = self.sample_overview()
            seen = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    seen.append((self.path, self.headers.get('X-Ilson-Admin'), body))
                    if self.headers.get('X-Ilson-Admin') != 'top-secret-val':
                        resp = json.dumps({'error': 'UNAUTHORIZED'}).encode()
                        self.send_response(403)
                    else:
                        resp = json.dumps({**sample, 'nonce': body['nonce']}).encode()
                        self.send_response(200)
                    self.send_header('Content-Length', str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)

            server = HTTPServer(('127.0.0.1', 0), Handler)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(lambda: (server.shutdown(), thread.join(), server.server_close()))

            url = f'https://127.0.0.1:{server.server_port}'
            issuer = load_module('issuer_cli_test', 'server/license/issuer.py')
            trusted = lambda: ssl.create_default_context(cafile=str(cert))
            old_config = issuer.CONFIG
            issuer.CONFIG = root / '.config/ilson-license'
            self.addCleanup(lambda: setattr(issuer, 'CONFIG', old_config))

            def run_cli(argv, extra_env=None):
                env = {k: v for k, v in os.environ.items() if k != 'ILSON_LICENSE_ADMIN_SECRET'}
                env['HOME'] = str(root)
                if extra_env:
                    env.update(extra_env)
                out, err = io.StringIO(), io.StringIO()
                with patch.dict(os.environ, env, clear=True), \
                        patch('ssl._create_default_https_context', side_effect=trusted), \
                        patch.object(sys, 'argv', ['issuer.py', *argv]), \
                        contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(err):
                    rc = issuer.main()
                return rc, out.getvalue(), err.getvalue()

            # 0. Missing secret -> fails cleanly with rc=1
            rc0, _, err0 = run_cli(['overview', '--server', url])
            self.assertEqual(rc0, 1)
            self.assertIn('실패', err0)

            # 1. Via ILSON_LICENSE_ADMIN_SECRET env var + --json + --cohort
            rc1, out1, err1 = run_cli(
                ['overview', '--server', url, '--cohort', '1', '--json'],
                {'ILSON_LICENSE_ADMIN_SECRET': 'top-secret-val'},
            )
            self.assertEqual(rc1, 0, err1)
            parsed = json.loads(out1)
            self.assertEqual(parsed['status'], 'ok')
            self.assertEqual(seen[-1][0], '/api/v1/admin-overview')
            self.assertEqual(seen[-1][2]['cohort'], 1)

            # 2. Via ~/.config/ilson-license/admin-secret (0600 file) + formatted report
            cfg = root / '.config/ilson-license'
            cfg.mkdir(mode=0o700, parents=True)
            fd = os.open(str(cfg / 'admin-secret'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write('top-secret-val\n')
            rc2, out2, err2 = run_cli(['overview', '--server', url])
            self.assertEqual(rc2, 0, err2)
            self.assertIn('김수강', out2)
            self.assertIn('(미활성화)', out2)


class InstallerStaticAndTelemetryTests(unittest.TestCase):
    def test_windows_installer_ascii_single_webclient_and_base64_table(self):
        source = (ROOT / 'course/install-windows.ps1').read_text(encoding='ascii')
        self.assertEqual(source.count('New-Object Net.WebClient'), 1)
        self.assertIn('function New-IlsonWebClient', source)
        self.assertIn('function Send-IlsonInstallTelemetry', source)
        # Must pass pwsh_support.offline_installer_source() without leaking any network primitive
        offline = offline_installer_source()
        self.assertIn('function New-IlsonWebClient { New-TestClient }', offline)
        # Base64 text table must still match 100%
        win_b64 = re.compile(
            r"(?<=K ')[A-Za-z0-9+/=]+(?=')|"
            r"(?<=FromBase64String\(')[A-Za-z0-9+/=]+(?=')|"
            r"(?<=        ')[A-Za-z0-9+/=]+(?='$)", re.M)
        expected = json.loads((ROOT / 'tests/course_windows_base64_text.json').read_text(encoding='utf-8'))
        expected = [(ROOT / item['file']).read_text(encoding='utf-8') if isinstance(item, dict) else item
                    for item in expected]
        encoded = win_b64.findall(source)
        self.assertEqual(len(encoded), len(expected))
        for val, orig in zip(encoded, expected):
            self.assertEqual(base64.b64decode(val, validate=True).decode('utf-8'), orig)

    def test_intel_mac_installer_telemetry_payload_and_opt_out(self):
        script = ROOT / 'course/install-intel-mac.sh'
        syn = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(syn.returncode, 0, syn.stderr)

        # Run mocked intel-mac install (failing on python 3.9) and capture telemetry JSON sent to curl
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            for app in ('Orca', 'Obsidian'):
                (home / 'Applications' / (app + '.app')).mkdir(parents=True)
            tel_log = home / 'telemetry.json'
            hook = home / 'hook'
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
curl() {
  local dest='' data='' url=''
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -o) dest=$2; shift ;;
      -d) data=$2; shift ;;
      https://*) url=$1 ;;
    esac
    shift
  done
  case "$url" in
    */api/v1/install-telemetry) printf '%s' "$data" > "$ILSON_TEL_LOG"; return 0 ;;
  esac
  [ -n "$dest" ] && printf fixture > "$dest"
  printf 200
}
''')
            # 1. With telemetry enabled -> valid JSON captured and accepted by [action].js validator!
            env = {**os.environ, 'HOME': str(home), 'BASH_ENV': str(hook), 'ILSON_TEL_LOG': str(tel_log)}
            env.pop('ILSON_NO_TELEMETRY', None)
            r = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertTrue(tel_log.is_file(), 'expected telemetry POST')
            sent = json.loads(tel_log.read_text(encoding='utf-8'))
            self.assertEqual(sent['edition'], 'intel-course')
            self.assertEqual(sent['os'], 'macOS')
            self.assertEqual(sent['arch'], 'x86_64')
            self.assertEqual(sent['os_version'], '13.6')
            self.assertEqual(sent['result'], 'failed')
            self.assertTrue(any(s['step_id'] == 'runtime.python' and s['reason_code'] == 'PYTHON_TOO_OLD' for s in sent['failed_steps']))
            # Verify server [action].js accepts this exact payload!
            check = NodeApiContractTests().call_action('install-telemetry', sent)
            self.assertEqual(check['code'], 200, sent)

            # 2. With ILSON_NO_TELEMETRY=1 -> no telemetry POST
            tel_log.unlink()
            r2 = subprocess.run(
                ['bash', str(script)],
                env={**env, 'ILSON_NO_TELEMETRY': '1'},
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(r2.returncode, 1)
            self.assertFalse(tel_log.exists(), 'telemetry must be skipped when ILSON_NO_TELEMETRY=1')


if __name__ == '__main__':
    unittest.main()
