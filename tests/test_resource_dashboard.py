"""Isolated observations, HTTP privacy and shipped installation/update coverage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/lib'))
import resource_dashboard as rd
import test_web_admin as wa

TOP = 'CPU usage: 10.0% user, 10.0% sys, 80.0% idle\nCPU usage: 20.0% user, 10.0% sys, 70.0% idle\n'
VM = 'Mach Virtual Memory Statistics: (page size of 4096 bytes)\nAnonymous pages: 100.\nPages purgeable: 10.\nPages wired down: 20.\nPages occupied by compressor: 5.\n'
LAUNCH = 'PID\tStatus\tLabel\n42\t0\torg.example.worker\n-\t7\torg.example.failed\n-\t0\tcom.ilson.briefing\n-\t0\tcom.apple.system\n'


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000000.0]
        self.calls = []
        self.broken = False
        def run(args):
            self.calls.append(args)
            if self.broken:
                raise OSError('private exception must never leave collector')
            return {'/usr/bin/top': TOP, '/usr/bin/vm_stat': VM,
                    '/usr/sbin/sysctl': '1000000', '/bin/launchctl': LAUNCH}[args[0]]
        disk = Mock(return_value=Mock(f_blocks=100, f_frsize=100, f_bavail=30))
        self.collector = rd.Collector('/synthetic', run=run, system=lambda: 'Darwin',
                                      clock=lambda:self.now[0], monotonic=lambda:self.now[0], disk=disk)

    def test_real_formulas_and_cached_concurrent_observation(self):
        values = []
        threads = [threading.Thread(target=lambda:values.append(self.collector.snapshot())) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(values[0]['cpu']['value']['percent'], 30)
        self.assertEqual(values[0]['memory']['value']['used_bytes'], 115 * 4096)
        self.assertEqual(values[0]['disk']['value']['free_bytes'], 3000)
        self.assertEqual(len(values[0]['launchd']['value']), 3)
        values[0]['cpu']['value']['percent'] = -1
        self.assertEqual(self.collector.snapshot()['cpu']['value']['percent'], 30)

    def test_failure_retains_timestamp_and_recovers(self):
        old = self.collector.snapshot()
        self.now[0] += 31; self.broken = True
        stale = self.collector.snapshot()
        self.assertEqual(stale['cpu']['state'], 'stale')
        self.assertEqual(stale['cpu']['observed_at'], old['cpu']['observed_at'])
        self.assertEqual(stale['disk']['state'], 'ok')
        self.assertNotIn('private exception', json.dumps(stale))
        self.now[0] += 31; self.broken = False
        self.assertEqual(self.collector.snapshot()['cpu']['state'], 'ok')

    def test_no_previous_value_is_failure_not_zero(self):
        self.broken = True
        result = self.collector.snapshot()
        self.assertEqual(result['cpu']['state'], 'failure')
        self.assertIsNone(result['cpu']['value'])

    def test_sandbox_never_observes_user_jobs_and_unsupported_is_explicit(self):
        self.assertEqual(self.collector.snapshot(True)['launchd']['state'], 'unavailable')
        self.assertFalse(any(c[0] == '/bin/launchctl' for c in self.calls))
        self.collector.system = lambda:'Unsupported'
        self.now[0] += 31
        self.assertEqual(self.collector.snapshot()['cpu']['state'], 'unavailable')

    def test_empty_is_distinct_from_bad_data(self):
        self.assertEqual(rd.launchd('PID Status Label\n'), [])
        for raw in ['garbage', 'PID Status Label\n- x org.example.bad']:
            with self.assertRaises(ValueError):rd.launchd(raw)
        with self.assertRaises(ValueError):rd.cpu('CPU usage: 100% idle')
        with self.assertRaises(ValueError):rd.memory('missing', '1000')

    def test_launchd_labels_preserve_text_and_exclude_system_apps(self):
        labels = ['org.example.worker:daily', 'org.example.백업',
                  'org.example.daily backup', 'org.example.$(never-execute); worker',
                  'x' * 200, ' ' * 199 + 'x', ' com.ilson.briefing']
        raw = 'PID\tStatus\tLabel\n42\t0\tcom.ilson.briefing\n'
        raw += ''.join('99\t7\t' + label + '\n' for label in labels)
        raw += '-\t0\tcom.apple.백업:daily task\n-\t0\tapplication.Example App:daily\n'
        observed = self.collector.observe('launchd', lambda: rd.launchd(raw))
        self.assertEqual(observed['state'], 'ok')
        rows = {row['id']: row for row in observed['value']}
        self.assertEqual(set(rows), set(labels) | {'com.ilson.briefing'})
        self.assertEqual(rows['com.ilson.briefing']['pid'], 42)
        box = Mock()
        box.files.marker.return_value = False
        box.jobs.return_value = ([{'id': 'briefing', 'label': 'Briefing',
            'schedule': 'daily', 'registration': 'loaded',
            'last_success_at': None, 'last_success_state': 'unavailable'}], [])
        collector = Mock()
        collector.snapshot.return_value = {'launchd': observed, 'sandbox': False}
        result = rd.dashboard(box, collector)['automations']
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(result['items'][0]['source'], 'box')
        self.assertEqual(result['items'][0]['state'], 'running')
        self.assertEqual(result['items'][0]['process']['pid'], 42)
        self.assertEqual(result['items'][0]['process']['exit_code'], 0)
        other = next(row for row in result['items'] if row['id'] == ' com.ilson.briefing')
        self.assertEqual(other['source'], 'launchd')
        self.assertEqual(other['process']['pid'], 99)
        self.assertEqual(other['process']['exit_code'], 7)
        self.assertEqual(len(result['items']), len(labels) + 1)

    def test_launchd_rejects_malformed_controls_and_oversized_labels(self):
        bad_labels = ['', ' ', 'x' * 201, ' ' * 201 + 'org.example.job',
                      ' ' * 200 + 'x', '\torg.example.job']
        bad_labels += ['org.example.bad' + chr(code) + 'suffix'
                       for code in [0, 9, 10, 11, 12, 13, 27, 31, 127, 128, 133, 159]]
        for label in bad_labels:
            for prefix in ['', 'com.apple.', 'application.']:
                # Empty labels cease to be empty when prefixed.
                if not label.strip() and prefix:
                    continue
                with self.subTest(label=repr(label), prefix=prefix):
                    raw = 'PID\tStatus\tLabel\n42\t0\tcom.ilson.briefing\n-\t0\t' + prefix + label
                    collector = rd.Collector('/synthetic')
                    self.assertEqual(collector.observe('launchd', lambda: rd.launchd(raw))['state'], 'failure')
                    collector.observe('launchd', lambda: rd.launchd(LAUNCH))
                    stale = collector.observe('launchd', lambda: rd.launchd(raw))
                    self.assertEqual(stale['state'], 'stale')
                    self.assertEqual(stale['value'], rd.launchd(LAUNCH))
        for row in ['x\t0\torg.example.job', '-\tx\torg.example.job', '-\t0', '- 0 org.example.job',
                    '- 0\torg.example.job']:
            with self.subTest(row=row), self.assertRaises(ValueError):
                rd.launchd('PID\tStatus\tLabel\n' + row)
        with self.assertRaises(ValueError):
            rd.launchd('PID\tStatus\tLabel\n' + '-\t0\torg.example.job\n' * 2001)


class DashboardHTTPTests(wa.BoxFixture):
    def setUp(self):
        super().setUp()
        self.server = wa.admin.Server(self.box, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    stop = wa.HTTP시험.stop
    request = wa.HTTP시험.request
    login = wa.HTTP시험.login

    def test_auth_read_only_and_private_fields(self):
        self.box.resource_collector = Mock()
        result = self.request('GET', '/api/dashboard')
        self.assertEqual(result[0], 401)
        self.box.resource_collector.snapshot.assert_not_called()
        cookie, _ = self.login()
        headers = {'Cookie':cookie}
        self.box.resource_collector.snapshot.return_value = {
            'launchd':{'state':'ok','observed_at':'2026-01-01T00:00:00+00:00','value':rd.launchd(LAUNCH)},
            'sandbox':False}
        status, _, body = self.request('GET', '/api/dashboard', headers=headers)
        self.assertEqual(status, 200)
        rows = {r['id']:r for r in body['automations']['items']}
        self.assertEqual(rows['org.example.worker']['state'], 'running')
        self.assertEqual(rows['org.example.failed']['state'], 'exit_nonzero')
        self.assertEqual(rows['com.ilson.briefing']['state'], 'idle')
        self.assertIsNotNone(rows['com.ilson.briefing']['last_success_at'])
        self.assertEqual(rows['com.ilson.weekly']['state'], 'not_loaded')
        raw = json.dumps(body)
        for secret in [self.token, str(self.home), 'run-job.sh', 'NEVER_RETURN_RAW_AUTH']:
            self.assertNotIn(secret, raw)
        self.assertEqual(self.request('POST','/api/dashboard',{},headers)[0],404)
        self.assertEqual(self.request('GET','/api/dashboard',headers={**headers,'Origin':'https://example.org'})[0],403)

    def test_empty_failure_and_stale_jobs_remain_distinct(self):
        self.write('launchd/jobs.conf', '# empty\n')
        self.box.resource_collector = Mock()
        for state in ['empty','failure','stale','unavailable']:
            self.box.resource_collector.snapshot.return_value = {'launchd':{
                'state':state,'value':[] if state=='empty' else None,'observed_at':None},'sandbox':False}
            result = rd.dashboard(self.box,self.box.resource_collector)
            self.assertEqual(result['automations']['state'],state)
            self.assertEqual(result['automations']['items'],[])
        self.write('launchd/jobs.conf','invalid line')
        self.assertEqual(rd.dashboard(self.box,self.box.resource_collector)['automations']['state'],'failure')


class DashboardInstallTests(unittest.TestCase):
    def test_clean_sandbox_setup_reinstall_preserves_user_data(self):
        with tempfile.TemporaryDirectory(prefix='dashboard-install-') as folder:
            home = Path(folder); box = home/'box'
            env = dict(os.environ,HOME=str(home),ILSON_HOME=str(box),ILSON_SRC=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
            # Existing installer code is exercised only inside disposable HOME, no services/tool install.
            for cycle in range(2):
                result = subprocess.run(['sh',str(ROOT/'install.sh'),'--sandbox'],cwd=ROOT,
                                        env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                for name in ['lib/resource_dashboard.py','web/dashboard.html','web/dashboard.js','web/dashboard.css']:
                    self.assertEqual((box/name).read_bytes(),(ROOT/'template'/name).read_bytes())
                    self.assertEqual((home/'.ilson-cli/template'/name).read_bytes(),(ROOT/'template'/name).read_bytes())
                if cycle == 0:
                    (box/'launchd/jobs.conf').write_text('# custom schedule\n')
                    (box/'vault/CONTEXT.md').write_text('custom context')
                    (box/'state/pairing.json').write_text('{"secret":"synthetic-private"}')
            self.assertEqual((box/'launchd/jobs.conf').read_text(),'# custom schedule\n')
            self.assertEqual((box/'vault/CONTEXT.md').read_text(),'custom context')
            self.assertEqual((box/'state/pairing.json').read_text(),'{"secret":"synthetic-private"}')
            self.assertFalse((home/'Library/LaunchAgents').exists())

    def test_real_release_contains_dashboard_and_update_rollback_preserve_config(self):
        from test_integrated_release import load, research_pack, FEED, u
        builder = load('dashboard_builder',ROOT/'tools/build_release.py')
        with tempfile.TemporaryDirectory(prefix='dashboard-release-') as folder:
            base=Path(folder); release=builder.build(base/'out','9999.20',research_pack(base),FEED)
            archive=(base/'out'/release['archive']).read_bytes()
            roots={area:base/area for area in ['box','cli']}
            for root in roots.values():root.mkdir()
            config=roots['box']/'launchd/jobs.conf';config.parent.mkdir();config.write_text('# private schedule')
            token=roots['box']/'state/web-admin/token';token.parent.mkdir(parents=True);token.write_text('synthetic-secret')
            previous = {}
            for area, name, source in [('box','lib/web-admin-server.py','template/lib/web-admin-server.py'),
                                       ('box','web/current/shell.js','template/web/current/shell.js'),
                                       ('cli','ilson','ilson')]:
                content = subprocess.check_output(['git','show','26bf963:'+source],cwd=ROOT)
                target = roots[area]/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
                previous[target] = content
            u.apply(roots,release,archive)
            for name in ['lib/resource_dashboard.py','web/dashboard.html','web/dashboard.js','web/dashboard.css']:
                self.assertEqual((roots['box']/name).read_bytes(),(ROOT/'template'/name).read_bytes())
                self.assertEqual((roots['cli']/'template'/name).read_bytes(),(ROOT/'template'/name).read_bytes())
            self.assertEqual(config.read_text(),'# private schedule');self.assertEqual(token.read_text(),'synthetic-secret')
            u.rollback(roots,roots['box']/'.updates',u.read(roots['box']/'.updates/journal.json'))
            self.assertFalse((roots['box']/'web/dashboard.html').exists())
            for target, content in previous.items():self.assertEqual(target.read_bytes(),content)
            self.assertEqual(config.read_text(),'# private schedule');self.assertEqual(token.read_text(),'synthetic-secret')


if __name__ == '__main__':unittest.main()
