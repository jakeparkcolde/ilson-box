# coding: utf-8
"""Synthetic provider shapes; no real prompts, accounts, external requests or installs."""
import contextlib
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/lib'))
import usage_timeline as usage
import usage_sync as sync


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = Path(self.tmp.name).resolve() / 'user'
        self.workspace = self.user / '실습 PRIVATE_PROJECT'
        self.workspace.mkdir(parents=True)
        self.home = self.user / 'box'
        self.home.mkdir()
        self.now = [usage.stamp('2026-11-15T12:00:00Z')]
        self.ledger = usage.Ledger(self.home, user_home=self.user, clock=lambda: self.now[0])

    def on(self, backfill='2026-11-14', zone='Asia/Seoul'):
        self.ledger.on(self.workspace, zone, backfill=backfill)
        source = self.ledger.source(self.ledger.config())
        source.mkdir(parents=True, exist_ok=True)
        return source

    def fixture(self, source, name='claude.jsonl'):
        text = (ROOT / 'tests/fixtures/usage-timeline' / name).read_text().replace('WORKSPACE', str(self.workspace))
        path = source / name
        path.write_text(text)
        return path


class CollectorTests(Fixture):
    def test_default_off_no_state_no_network(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            self.assertEqual(self.ledger.collect()['state'], 'off')
            self.assertIsNone(self.ledger.payload())
            self.assertEqual(sync.Client(self.ledger).sync()['state'], 'off')
        self.assertFalse(self.ledger.root.exists())

    def test_stream_dedupe_midnight_and_idempotent_incremental(self):
        source = self.on(); path = self.fixture(source)
        before = path.read_bytes()
        data = self.ledger.collect()
        self.assertEqual(data['totals']['sessions'], 1)
        self.assertEqual(data['totals']['turns'], 2)
        self.assertEqual(data['totals']['active_days'], 2)
        self.assertEqual(data['totals']['output_tokens'], 30)
        self.assertEqual(data['totals']['cache_read_tokens'], 20)
        self.assertEqual([r['date'] for r in data['daily']], ['2026-11-14', '2026-11-14', '2026-11-15'])
        first = self.ledger.payload()
        self.fixture(source).rename(source / 'rotated-copy.jsonl')
        self.fixture(source)
        self.assertEqual(self.ledger.collect()['totals'], data['totals'])
        self.assertEqual(self.ledger.payload(), first)
        self.assertEqual(path.read_bytes(), before)
        path.unlink(); (source / 'rotated-copy.jsonl').unlink()
        self.assertEqual(self.ledger.collect()['totals']['turns'], 2)
        self.assertGreater(data['totals']['estimated_cost']['usd_max'], data['totals']['estimated_cost']['usd_min'])

    def test_consent_no_implicit_backfill_and_off_gap(self):
        source = self.on(backfill=None); self.fixture(source)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 0)
        self.ledger.off()
        self.now[0] += 86400
        self.on(backfill=None)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 0)
        self.assertFalse(self.ledger.config()['sync_enabled'])

    def test_incremental_scan_does_not_starve_later_files(self):
        source = self.on()
        for i in range(257): (source / ('%03d.jsonl' % i)).write_text('')
        self.fixture(source)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 0)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 2)
        with patch.object(self.ledger, 'parse', side_effect=AssertionError('reparsed unchanged source')):
            self.assertEqual(self.ledger.collect()['totals']['turns'], 2)

    def test_snapshot_excludes_ledger_and_refuses_already_tracked_usage(self):
        source = self.on(); self.fixture(source); self.ledger.collect()
        (self.home/'lib').mkdir(); (self.home/'vault').mkdir()
        for name in ('common.sh','snapshot.sh'):
            shutil.copyfile(ROOT/'template/lib'/name,self.home/'lib'/name)
        env = dict(os.environ, ILSON_HOME=str(self.home))
        cmd = ['bash',str(self.home/'lib/snapshot.sh')]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        tracked = subprocess.check_output(['git','ls-files'],cwd=self.home,text=True)
        self.assertNotIn('usage-timeline',tracked)
        subprocess.run(['git','add','-f','state/usage-timeline/settings.json'],cwd=self.home,check=True,capture_output=True)
        self.assertNotEqual(subprocess.run(cmd,env=env,capture_output=True).returncode,0)

    def test_new_workspace_has_its_own_consent_window(self):
        source = self.on(); self.fixture(source); self.ledger.collect()
        self.ledger.off()
        self.now[0] += 86400
        other = self.user / 'new-practice'; other.mkdir()
        self.ledger.on(other, 'Asia/Seoul')
        new_source = self.ledger.source(self.ledger.config()); new_source.mkdir()
        text = (ROOT / 'tests/fixtures/usage-timeline/claude.jsonl').read_text().replace('WORKSPACE', str(other)).replace('synthetic-session', 'different-session')
        (new_source/'new.jsonl').write_text(text)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 2)
        self.assertEqual(len(self.ledger.config()['windows']), 1)

    def test_unknown_partial_no_guessed_counts(self):
        source = self.on(); self.fixture(source, 'unknown.jsonl')
        result = self.ledger.collect()
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['totals']['turns'], 0)
        self.assertEqual(result['daily'], [])
        self.assertEqual(self.ledger.collect()['state'], 'partial')

    def test_trailing_line_retried_after_append(self):
        source = self.on(); path = self.fixture(source)
        rows = path.read_text().splitlines()
        path.write_text(rows[0][:-2])
        self.assertEqual(self.ledger.collect()['state'], 'partial')
        with path.open('a') as stream: stream.write(rows[0][-2:] + '\n')
        self.assertEqual(self.ledger.collect()['totals']['turns'], 1)
        self.assertEqual(self.ledger.summary()['state'], 'on')

    def test_private_artifacts_strict_payload_properties(self):
        source = self.on(); self.fixture(source); self.fixture(source, 'unknown.jsonl')
        self.ledger.collect()
        payload = self.ledger.payload()
        sync.validate_payload(payload, date(2026, 11, 15), linked=False)
        for p in self.ledger.root.iterdir():
            if os.name != 'nt': self.assertEqual(p.stat().st_mode & 0o077, 0, p.name)
            if p.name != 'settings.json':
                raw = p.read_bytes()
                for secret in (b'PRIVATE_', b'synthetic-session', b'synthetic-answer', str(self.workspace).encode()):
                    self.assertNotIn(secret, raw)
        # Mutation/property checks: no arbitrary field or model string can cross the boundary.
        for field in ('prompt', 'title', 'filename', 'path', 'project', 'hostname', 'username'):
            for value in ('PRIVATE_SENTINEL', '/Users/private/secret.txt', '<script>'):
                mutated = json.loads(json.dumps(payload)); mutated['daily'][0][field] = value
                with self.assertRaises(ValueError): sync.validate_payload(mutated, date(2026,11,15), linked=False)
                mutated = json.loads(json.dumps(payload)); mutated[field] = value
                with self.assertRaises(ValueError): sync.validate_payload(mutated, date(2026,11,15), linked=False)
                mutated = json.loads(json.dumps(payload)); mutated['daily'][0]['model'] = value
                with self.assertRaises(ValueError): sync.validate_payload(mutated, date(2026,11,15), linked=False)

    def test_sources_symlink_hardlink_and_scope_rejected(self):
        source = self.on(); path = self.fixture(source)
        text = path.read_text().replace(str(self.workspace), str(self.user / 'other'))
        path.write_text(text)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 0)
        path.unlink()
        outside = self.user / 'outside.jsonl'; outside.write_text(text)
        path.symlink_to(outside)
        self.assertEqual(self.ledger.collect()['state'], 'partial')
        path.unlink(); os.link(outside, path)
        self.assertEqual(self.ledger.collect()['totals']['turns'], 0)

    def test_timezone_dst_streak_and_recent_window(self):
        source = self.on(zone='America/New_York'); self.fixture(source)
        self.assertEqual(self.ledger.collect()['totals']['active_days'], 1)
        rows = []
        for day in ('2026-10-01','2026-11-01','2026-11-02','2026-11-03','2026-11-14'):
            rows.append(dict(date=day, tool='claude_code', model=None, sessions=1, turns=1, quality='observed', **dict.fromkeys(usage.COUNTERS)))
        data = usage.metrics(rows, date(2026,11,15))
        self.assertEqual(data['longest_streak'], 3)
        self.assertEqual(data['current_streak'], 1)
        self.assertEqual(data['recent_30_days']['active_days'], 4)
        self.assertEqual(data['peak_month'], '2026-11')
        self.assertEqual(usage.stamp('2026-11-01T01:30:00-04:00') + 3600, usage.stamp('2026-11-01T01:30:00-05:00'))

    def test_off_and_delete_remain_offline(self):
        source = self.on(); self.fixture(source); self.ledger.collect()
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            self.ledger.off()
            self.assertEqual(self.ledger.summary()['state'], 'off')
            self.ledger.delete_local()
        self.assertEqual(self.ledger.payload()['daily'], [])
        self.assertTrue(self.ledger.source(dict(workspace=str(self.workspace))).is_dir())

    def test_company_mode_is_excluded(self):
        (self.home/'state').mkdir(); (self.home/'state/company.json').write_text('{}')
        with self.assertRaises(usage.UsageError): self.on()

    def test_cli_and_course_cli_without_license_network(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(usage.main(['status'], home=self.home, user_home=self.user), 0)
        self.assertEqual(json.loads(output.getvalue())['state'], 'off')
        env = dict(os.environ, ILSON_COURSE_STATE=str(self.home))
        result = subprocess.run([sys.executable, str(ROOT/'course/ilson.py'), 'usage', 'status'], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'off')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(usage.main(['on','--codex'],home=self.home,user_home=self.user),1)
        self.assertIn('준비 중', err.getvalue())


class SyncTests(Fixture):
    def setUp(self):
        super().setUp()
        self.received = []; self.status = [200]
        self.enrollment, self.consent = str(uuid.uuid4()), str(uuid.uuid4())
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self): self.handle_request()
            def do_PUT(self): self.handle_request()
            def handle_request(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.received.append((self.path, data, self.headers.get('Authorization')))
                if self.path.endswith('/link'):
                    result = dict(device_token='SYNTHETIC_TOKEN_'+'x'*32, device_id=data['device_id'], enrollment_id=outer.enrollment,
                                  consent_id=outer.consent, expires_at='2027-01-01T00:00:00Z', retention_days=60)
                    status = 201
                elif self.path.endswith('/revoke'):
                    result = dict(revoked=True, deleted=outer.status[0] == 200); status=outer.status[0]
                else:
                    result = dict(accepted_revision=data['revision'], accepted_rows=len(data['daily']), delete_after='2026-12-30T00:00:00Z')
                    status = outer.status[0]
                raw = json.dumps(result).encode(); self.send_response(status); self.send_header('Content-Length',str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port) + '/learn'
        source = self.on(); self.fixture(source); self.ledger.collect()
        self.client = sync.Client(self.ledger)

    def link(self): self.client.link(self.base, 'ABCD1234EFGH')

    def test_link_sync_preview_exact_retry_idempotent_and_revoke(self):
        preview = self.ledger.payload(); self.link()
        payload = self.ledger.payload()
        self.assertEqual(preview['daily'], payload['daily'])
        self.client.sync()
        self.assertEqual(self.received[-1][1], payload)
        sync.validate_payload(payload,date(2026,11,15))
        count = len(self.received); self.client.sync(); self.assertEqual(len(self.received),count)
        self.assertNotIn('SYNTHETIC_TOKEN', json.dumps(self.ledger.summary()))
        self.assertEqual(self.client.unlink()['sync_state'], 'deleted')
        self.assertFalse(self.client.credential.exists())

    def test_backoff_off_no_upload_and_pending_delete(self):
        self.link(); self.status[0] = 503
        self.assertEqual(self.client.sync()['sync_state'], 'retry_pending')
        count=len(self.received); self.client.sync(); self.assertEqual(len(self.received),count)
        self.ledger.off(); self.now[0] += 86400
        self.client.sync(); self.assertEqual(len(self.received),count)
        data = self.client.unlink(); self.assertTrue(data['revoke_pending']); self.assertTrue(self.client.credential.exists())
        self.status[0] = 200; self.now[0] += 86400
        self.assertEqual(self.client.sync()['sync_state'], 'deleted')

    def test_auth_error_disables_upload_but_does_not_claim_deleted(self):
        self.link(); self.status[0] = 401
        data = self.client.sync()
        self.assertFalse(data['sync_enabled']); self.assertEqual(data['sync_state'],'needs_attention')
        self.assertTrue(self.client.unlink()['revoke_pending'])

    def test_bad_urls_no_code_in_query(self):
        for url in ('http://example.com','https://u:p@example.com','https://example.com?code=x','https://example.com/#x'):
            with self.assertRaises(ValueError): sync.base_url(url)
