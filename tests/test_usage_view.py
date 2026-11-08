import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template' / 'lib'))
import usage_observer as u
import usage_dashboard as dashboard


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'box'
        self.settings = Path(self.tmp.name) / 'claude' / 'settings.json'

    def test_course_usage_needs_no_license_or_account(self):
        script = Path(__file__).resolve().parents[1] / 'course' / 'ilson.py'
        result = subprocess.run([sys.executable, str(script), 'usage'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={'HOME': self.tmp.name}, check=True)
        self.assertIn('/usage', result.stdout)
        self.assertIn('자동 경고', result.stdout)

    def test_allowlist_missing_zero_versions_and_private_data(self):
        sample = u.extract({'rate_limits': {'five_hour': {'used_percentage': 0, 'resets_at': 2000}}, 'cost': {'total_cost_usd': 0}, 'cwd': 'SECRET_PATH', 'key':'SECRET_KEY', 'context_window': {'used_percentage': 99}}, 1000)
        self.assertEqual(sample['five_hour']['used_percentage'], 0)
        self.assertIsNone(sample['seven_day']['used_percentage'])
        self.assertEqual(sample['cost_usd'], 0)
        self.assertNotIn('SECRET', json.dumps(sample))
        self.assertIsNone(u.extract({'rate_limits': {'five_hour': {'used_percentage': True}}})['five_hour']['used_percentage'])
        self.assertIsNone(u.extract({'rate_limits': {'five_hour': {'used_percentage': float('nan')}}})['five_hour']['used_percentage'])

    def test_existing_statusline_wrap_and_restore_conflict(self):
        old = {'type':'command', 'command':'printf existing', 'padding':2, 'hideVimModeIndicator':True}
        u.write_json(self.settings, {'statusLine': old, 'other': 1})
        u.enable(self.home, self.settings)
        self.assertTrue(u.preview(self.home, self.settings)['enabled'])
        conf = u.read_json(self.settings, {})
        self.assertEqual(conf['statusLine']['padding'], 2)
        self.assertTrue(conf['statusLine']['hideVimModeIndicator'])
        conf['other'] = 2
        u.write_json(self.settings, conf)
        u.disable(self.home, self.settings)
        self.assertEqual(u.read_json(self.settings, {}), {'statusLine':old, 'other':2})
        u.enable(self.home, self.settings)
        conf = u.read_json(self.settings, {})
        conf['statusLine'] = {'type':'command', 'command':'new command'}
        u.write_json(self.settings, conf)
        with self.assertRaises(ValueError): u.disable(self.home, self.settings)
        self.assertEqual(u.read_json(self.settings, {})['statusLine']['command'], 'new command')

    def test_wrapper_passes_input_and_existing_output_without_recording_secrets(self):
        userhome = Path(self.tmp.name) / 'user'
        settings = userhome / '.claude' / 'settings.json'
        u.write_json(settings, {'statusLine': {'type':'command', 'command':'cat'}})
        with patch.object(u, 'settings_path', return_value=settings):
            u.enable(self.home)
        raw = b'{"cost":{"total_cost_usd":0},"cwd":"PRIVATE_PATH","secret":"PRIVATE_KEY"}'
        env = dict(os.environ, HOME=str(userhome))
        result = subprocess.run([sys.executable, str(Path(u.__file__)), '--observe', str(self.home)], input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=True)
        self.assertEqual(result.stdout, raw)
        saved = (u.state_dir(self.home) / 'latest.json').read_text()
        self.assertNotIn('PRIVATE', saved)

    def test_symlink_settings_are_never_replaced(self):
        target = Path(self.tmp.name) / 'original.json'
        target.write_text('{"other": 1}')
        self.settings.parent.mkdir(parents=True)
        self.settings.symlink_to(target)
        with self.assertRaises(ValueError): u.enable(self.home, self.settings)
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(target.read_text(), '{"other": 1}')

    def test_other_box_observer_is_not_wrapped(self):
        u.write_json(self.settings, {'statusLine': {'type':'command', 'command':'python /another/usage_observer.py --observe /another'}})
        with self.assertRaises(ValueError): u.enable(self.home, self.settings)
        self.assertIn('/another/', u.read_json(self.settings, {})['statusLine']['command'])

    def test_project_override_refused(self):
        u.write_json(self.home / '.claude' / 'settings.local.json', {'statusLine': {'type':'command','command':'true'}})
        with self.assertRaises(ValueError): u.enable(self.home, self.settings)

    def test_alert_off_threshold_dedup_reset_and_missing(self):
        sent=[]
        def sample(p, reset=2000):
            return json.dumps({'rate_limits': {'five_hour': {'used_percentage':p, 'resets_at': reset}}, 'secret':'never save'})
        u.observe(self.home, sample(95), 1000, sent.append, lambda: True)
        self.assertEqual(sent, [])
        u.write_json(u.state_dir(self.home) / 'alerts.json', {'enabled':True, 'threshold':80})
        u.observe(self.home, sample(79), 1000, sent.append, lambda: True)
        u.observe(self.home, sample(80), 1001, sent.append, lambda: False)
        self.assertEqual(sent, [])
        u.observe(self.home, sample(80), 1001, sent.append, lambda: True)
        u.observe(self.home, sample(99, 2000.0), 1002, sent.append, lambda: True)
        self.assertEqual(len(sent),1)
        u.observe(self.home, sample(99, 999), 1003, sent.append, lambda: True)
        u.observe(self.home, sample(81, 3000), 1004, sent.append, lambda: True)
        u.observe(self.home, sample(81, 2000), 1005, sent.append, lambda: True)
        self.assertEqual(len(sent),2)
        u.write_json(u.state_dir(self.home) / 'alerts.json', {'enabled':True, 'threshold':90})
        u.observe(self.home, sample(95, 3000), 1006, sent.append, lambda: True)
        u.observe(self.home, sample(95, 3000), 1007, sent.append, lambda: True)
        self.assertEqual(len(sent),3)
        self.assertIn('받은 시각', sent[-1])
        self.assertIn('/usage', sent[-1])
        self.assertNotIn('never save', (u.state_dir(self.home) / 'latest.json').read_text())

    def test_staleness_and_zero(self):
        u.write_json(u.state_dir(self.home) / 'latest.json', u.extract({'cost': {'total_cost_usd':0}}, 1000))
        with patch.object(dashboard, 'preview', return_value={}):
            self.assertFalse(dashboard.dashboard(self.home, 1900)['stale'])
            result = dashboard.dashboard(self.home, 1901)
            self.assertTrue(result['stale'])
            self.assertEqual(result['sample']['cost_usd'],0)
        u.write_json(u.state_dir(self.home) / 'latest.json', u.extract({'rate_limits': {'five_hour': {'used_percentage': 90, 'resets_at': 1001}}}, 1000))
        with patch.object(dashboard, 'preview', return_value={}):
            self.assertTrue(dashboard.dashboard(self.home, 1001)['sample']['five_hour']['stale'])


if __name__ == '__main__': unittest.main()
