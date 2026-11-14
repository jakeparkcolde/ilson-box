import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'template/lib'
sys.path.insert(0, str(LIB))
import access_policy as a
import company


def config(root):
    return dict(schema=1, id='acme', owner_uid=501, runtime=str(root / 'runtime'), vault=str(root / 'vault'),
        defaults=a.DEFAULTS.copy(), people=[
            dict(id='boss', account='boss', uid=501, role='owner', active=True),
            dict(id='alice', account='alice', uid=502, role='staff', active=True),
            dict(id='bob', account='bob', uid=503, role='staff', active=True)])


class CompanyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.config = config(self.root)
        self.actor = a.resolve_actor(self.config, uid=502)
        self.policy = a.Policy(self.config, self.actor)
        for rel in ('company', 'people/alice', 'people/bob', 'management'):
            (self.root / 'vault' / rel).mkdir(parents=True)
        (self.root / 'vault/people/bob/secret.md').write_text('BOB_SECRET')
        (self.root / 'vault/management/secret.md').write_text('MANAGEMENT_SECRET')


class AccessTests(CompanyFixture):
    def test_actor_deny_by_default_and_no_name_impersonation(self):
        with patch.dict(os.environ, USER='boss', ILSON_PERSON='boss'), patch.object(os, 'geteuid', return_value=502):
            self.assertEqual(a.resolve_actor(self.config), self.actor)
        for uid in (0, 504, '502'):
            with self.assertRaises(a.AccessDenied):
                a.resolve_actor(self.config, uid=uid)
        removed = copy.deepcopy(self.config)
        removed['people'][1]['active'] = False
        self.assertFalse(a.can_access(removed, self.actor, 'company/x'))

    def test_contract(self):
        for rel in ('company/x.md', 'people/alice/x.md'):
            self.assertTrue(a.can_access(self.config, self.actor, rel, 'write'))
        for rel in ('people/bob/x', 'people/502/x', 'people', 'management/x', '../company/x', 'company/../management/x', '/company/x', 'COMPANY/x', 'company//x', 'state/license', 'lib/x', 'company\\x'):
            self.assertFalse(a.can_access(self.config, self.actor, rel), rel)
        owner = a.resolve_actor(self.config, uid=501)
        self.assertFalse(a.can_access(self.config, owner, 'people/alice/x'))
        self.assertTrue(a.can_access(self.config, owner, 'management/x'))
        self.assertFalse(a.can_access(self.config, owner, 'management/x', company_only=True))

    def test_unknown_duplicate_uid_role_and_policy(self):
        for mutate in (lambda c: c['people'][1].update(uid=501), lambda c: c['people'][1].update(role='admin'),
                       lambda c: c['people'][1].update(id='../boss'), lambda c: c['defaults'].update(employee_web=True)):
            c = copy.deepcopy(self.config)
            mutate(c)
            with self.assertRaises(a.AccessDenied):
                a.validate(c)

    def test_symlink_hardlink_and_parent_swap(self):
        vault = self.root / 'vault'
        (vault / 'company/link.md').symlink_to(vault / 'people/bob/secret.md')
        os.link(vault / 'people/bob/secret.md', vault / 'company/hard.md')
        (vault / 'company/linked').symlink_to(vault / 'management', target_is_directory=True)
        for rel in ('company/link.md', 'company/hard.md', 'company/linked/secret.md'):
            with self.assertRaises((a.AccessDenied, OSError)):
                self.policy.read(rel)
        self.assertEqual(self.policy.files('company'), [])
        (vault / 'company/sub').mkdir()
        with self.policy.folder('company/sub') as fd:
            (vault / 'company/sub').rename(vault / 'company/old')
            (vault / 'company/sub').symlink_to(vault / 'management', target_is_directory=True)
            with self.assertRaises(FileNotFoundError):
                a.read_regular(fd, 'secret.md')
        with self.assertRaises(OSError):
            self.policy.create('company/sub/injected.md', b'no')
        self.assertFalse((vault / 'management/injected.md').exists())

    def test_atomic_saves_rename_and_no_overwrite(self):
        self.policy.create('people/alice/journal/a.md', b'one')
        self.assertEqual(self.policy.read('people/alice/journal/a.md')[0], b'one')
        with self.assertRaises(FileExistsError):
            self.policy.create('people/alice/journal/a.md', b'two')
        path = self.root / 'vault/company'
        (path / 'temp').write_text('atomic')
        os.replace(path / 'temp', path / 'saved.md')
        self.assertEqual(self.policy.read('company/saved.md')[0], b'atomic')
        (path / 'saved.md').rename(path / 'renamed.md')
        self.assertEqual(self.policy.files('company'), ['company/renamed.md'])
        for rel in ('people/bob/new.md', 'management/new.md'):
            with self.assertRaises(a.AccessDenied):
                self.policy.create(rel, b'no')

    def test_acl_plan_exact_commands_and_no_mutation(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        commands = company.init_plan(self.config, LIB)
        vault = Path(self.config['vault'])  # production plan uses fixed shared anchor
        shared = a.SHARED / 'acme/vault'
        self.assertIn(['/usr/sbin/dseditgroup', '-o', 'create', 'ilson_acme'], commands)
        self.assertIn(['/usr/bin/chgrp', 'ilson_acme', str(shared / 'company')], commands)
        self.assertIn(['/bin/chmod', '+a', 'group:ilson_acme allow ' + company.RIGHTS, str(shared / 'company')], commands)
        self.assertIn(['/bin/chmod', '+a', 'user:alice allow ' + company.RIGHTS, str(shared / 'people/alice')], commands)
        self.assertFalse(any('staff allow' in ' '.join(c) or 'everyone allow' in ' '.join(c) for c in commands))
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_offboarding_is_explicit_plan(self):
        plan = company.offboard_plan(self.config, 'alice')
        self.assertIn(['/usr/sbin/dseditgroup', '-o', 'edit', '-d', 'alice', '-t', 'user', 'ilson_acme'], plan)
        self.assertIn(['/bin/mv', str(self.root / 'vault/people/alice'), str(self.root / 'vault/management/offboarding/alice')], plan)
        self.assertTrue((self.root / 'vault/people/alice').exists())
        with self.assertRaises(ValueError):
            company.offboard_plan(self.config, 'boss')

    def test_no_config_unchanged_invalid_config_denied(self):
        self.assertIsNone(a.load(self.root))
        self.assertEqual(a.vault_path(self.root), self.root / 'vault')
        (self.root / 'state').mkdir()
        (self.root / 'state/company.json').write_text('{')
        with self.assertRaises(a.AccessDenied):
            a.load(self.root)

    def test_employee_runtime_guard(self):
        with patch.object(a, 'load', return_value=self.policy):
            with self.assertRaises(a.AccessDenied):
                a.require_owner(self.root)
            for command in ('start', 'pause', 'update', 'admin', 'setup', 'license'):
                with self.assertRaises(ValueError):
                    company.client(self.root, [command])


class ConsumerTests(CompanyFixture):
    def setUp(self):
        super().setUp()
        self.runtime = self.root / 'runtime'
        (self.runtime / 'state').mkdir(parents=True)
        (self.runtime / 'state/company.json').write_text('{"company":"acme"}')
        self.config['owner_uid'] = os.geteuid()
        self.config['people'][0]['uid'] = os.geteuid()
        self.config['people'][1]['uid'] = os.geteuid() + 10
        self.config['people'][2]['uid'] = os.geteuid() + 11
        self.owner = a.Policy(self.config, a.resolve_actor(self.config, uid=os.geteuid()))
        self.staff = a.Policy(self.config, a.resolve_actor(self.config, uid=os.geteuid() + 10))
        self.load = patch.object(a, 'load', return_value=self.owner)
        self.load.start()
        self.addCleanup(self.load.stop)

    # AccessTests run separately; only consumer methods belong in this class.
    def test_company_curator_and_staff_output_never_mix(self):
        import curator as c
        import time
        shared = self.root / 'vault/company/work.md'
        shared.write_text('- [x] SHARED_DONE\n')
        (self.root / 'vault/people/alice/own.md').write_text('- [x] ALICE_PRIVATE\n')
        (self.root / 'vault/people/bob/secret.md').write_text('- [x] BOB_PRIVATE\n')
        (self.root / 'vault/management/secret.md').write_text('- [x] MANAGEMENT_PRIVATE\n')
        store = c.Store(self.runtime)
        c.set_enabled(store, True)
        self.assertEqual(c.run_once(store, license_check=lambda *_: True), 'OK')
        output = next((self.root / 'vault/company/journal/curator').glob('*.md')).read_text()
        self.assertIn('SHARED_DONE', output.replace('\\', ''))
        self.assertNotIn('PRIVATE', output)
        with patch.object(a, 'load', return_value=self.staff):
            local = self.root / 'employee'
            (local / 'state').mkdir(parents=True)
            (local / 'state/company.json').write_text('{"company":"acme"}')
            store = c.Store(local)
            c.set_enabled(store, True)
            self.assertFalse(store.auto_supported)
            self.assertEqual(c.run_once(store, license_check=lambda *_: False), 'OK')
        output = next((self.root / 'vault/people/alice/journal/curator').glob('*.md')).read_text()
        self.assertIn('ALICE_PRIVATE', output.replace('\\', ''))
        self.assertNotIn('BOB_PRIVATE', output)
        self.assertNotIn('MANAGEMENT_PRIVATE', output)

    def test_company_git_objects_and_weekly_do_not_contain_private_data(self):
        import company_runtime as r
        from datetime import date
        import subprocess
        journal = self.root / 'vault/company/journal'
        journal.mkdir()
        (journal / (date.today().isoformat() + '.md')).write_text('- [x] SHARED_DONE\n')
        (self.root / 'vault/company/linked.md').symlink_to(self.root / 'vault/management/secret.md')
        history = r.snapshot(self.runtime, self.owner)
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=history).decode()
        self.assertIn('company/journal/', tracked)
        self.assertNotIn('management', tracked)
        self.assertNotIn('people', tracked)
        objects = subprocess.check_output(['git', 'log', '-p', '--all'], cwd=history).decode()
        self.assertNotIn('SECRET', objects)
        result = r.weekly(self.owner, date.today())
        self.assertIn('완료 표시: 1건', result)
        self.assertNotIn('SECRET', result)

    def test_restricted_ai_projection_and_private_output(self):
        import company_runtime as r
        from types import SimpleNamespace
        commands = self.runtime / '.claude/commands'
        commands.mkdir(parents=True)
        (commands / 'briefing.md').write_text('업무를 보고하세요')
        (self.root / 'vault/company/work.md').write_text('PUBLIC')
        (self.root / 'vault/people/alice/own.md').write_text('PERSONAL_SENTINEL')
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv == ['claude', '--help']:
                return SimpleNamespace(stdout='--restricted --safe-mode --tools --no-session-persistence --strict-mcp-config')
            if argv[0] == 'claude':
                stage = Path(kwargs['cwd'])
                files = [p for p in stage.rglob('*') if p.is_file()]
                all_text = '\n'.join(p.read_text() for p in files)
                self.assertIn('MANAGEMENT_SECRET', all_text)
                self.assertIn('PUBLIC', all_text)
                self.assertNotIn('BOB_SECRET', all_text)
                self.assertNotIn('PERSONAL_SENTINEL', all_text)
                self.assertFalse((stage / 'vault/people').exists())
                self.assertIn('--restricted', argv)
                self.assertIn('--safe-mode', argv)
                self.assertEqual(argv[argv.index('--tools') + 1], 'Read,Glob,Grep')
                self.assertNotIn('--add-dir', argv)
                return SimpleNamespace(stdout=json.dumps(dict(is_error=False, result='MANAGEMENT_SECRET processed')))
            self.assertNotIn('SECRET', kwargs.get('input', ''))
            return SimpleNamespace(returncode=0)
        with patch.object(r.subprocess, 'run', side_effect=run), patch.object(r, 'model_run', side_effect=run):
            self.assertTrue(r.run_job(self.runtime, self.owner, 'briefing'))
        self.assertFalse((self.root / 'vault/company/reports').exists())
        self.assertIn('MANAGEMENT_SECRET', next((self.root / 'vault/management/reports/briefing').glob('*.md')).read_text())
        stage = Path(next(k['cwd'] for av, k in calls if '--restricted' in av))
        self.assertFalse(stage.exists())

    def test_old_cli_fails_before_note_collection_or_model_call(self):
        import company_runtime as r
        from types import SimpleNamespace
        with patch.object(r.subprocess, 'run', return_value=SimpleNamespace(stdout='old help')) as run, patch.object(self.owner, 'files') as files:
            with self.assertRaises(ValueError):
                r.ai_report(self.runtime, self.owner, 'briefing')
            self.assertEqual(run.call_count, 1)
            files.assert_not_called()

    def test_private_approval_cannot_go_to_telegram(self):
        import approval_telegram as t
        with patch.object(t, 'api') as api:
            with self.assertRaises(t.TelegramError):
                t.send_card(self.runtime, 'a' * 32, consent=True)
            api.assert_not_called()

    def test_learning_storage_is_private_and_legacy_notes_preserved(self):
        import selflearn
        legacy = self.runtime / 'vault/lessons'
        legacy.mkdir(parents=True)
        (legacy / 'approved-learning.md').write_text('LEGACY_PRIVATE')
        store = selflearn.Store(self.runtime)
        self.assertEqual(store.home, self.runtime / 'state/company-learning')
        self.assertEqual((legacy / 'approved-learning.md').read_text(), 'LEGACY_PRIVATE')
        self.assertFalse((self.root / 'vault/company/lessons').exists())


    def test_representative_report_list_has_no_personal_paths_or_aliases(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('company_web_test', LIB / 'web-admin-server.py')
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        for relative, body in (('company/reports/briefing/public.md', '# PUBLIC'),
                               ('management/reports/briefing/owner.md', '# OWNER_ONLY'),
                               ('people/alice/reports/hidden.md', '# PRIVATE_TITLE')):
            file = self.root / 'vault' / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(body)
        (self.root / 'vault/company/reports/alias').symlink_to(self.root / 'vault/people/alice/reports', target_is_directory=True)
        box = web.Box.__new__(web.Box)
        box.company_policy = self.owner
        box.token = 'fake-token'
        box.telegram = lambda: None
        rows, limited = box.report_index()
        serialized = json.dumps(rows)
        self.assertIn('PUBLIC', serialized)
        self.assertIn('OWNER_ONLY', serialized)  # representative-only HTTP session
        self.assertNotIn('PRIVATE_TITLE', serialized)
        self.assertNotIn('people', serialized)

    def test_inbox_reads_management_only_and_rejects_hardlinks(self):
        import inbox_files as inbox
        self.owner.create('management/inbox/photo.jpg', b'private-original')
        self.assertEqual(inbox.read_file(self.runtime, 'photo.jpg'), b'private-original')
        source = self.root / 'vault/management/inbox/photo.jpg'
        os.link(source, source.parent / 'copy.jpg')
        with self.assertRaises(inbox.InboxError):
            inbox.read_file(self.runtime, 'photo.jpg')
        with patch.object(a, 'load', return_value=self.staff):
            with self.assertRaises(a.AccessDenied):
                inbox.list_files(self.runtime)

    def test_employee_join_has_no_installer_or_service_calls_and_preserves_wrapper(self):
        c = copy.deepcopy(self.config)
        c['owner_uid'] = os.geteuid() + 20
        c['people'][0]['uid'] = os.geteuid() + 20
        c['people'][1]['uid'] = os.geteuid()
        employee = self.root / 'employee-home'
        employee.mkdir()
        with patch.object(a, '_trusted_config', return_value=c), patch.object(company.subprocess, 'run') as external:
            company.join('acme', employee)
            binary = employee / '.local/bin/ilson'
            before = binary.read_bytes()
            company.join('acme', employee)
            self.assertEqual(binary.read_bytes(), before)
            self.assertEqual(json.loads((employee / '.ilson-company/acme/state/company.json').read_text()), {'company': 'acme'})
            external.assert_not_called()
            self.assertFalse((employee / 'Library/LaunchAgents').exists())
            self.assertFalse((employee / '.ilson-company/acme/state/license').exists())
            binary.write_text('existing CLI')
            with self.assertRaises(ValueError):
                company.join('acme', employee)
            self.assertEqual(binary.read_text(), 'existing CLI')

    def test_open_policy_refresh_denies_removed_actor_before_read(self):
        policy = self.staff
        policy.config_path = self.root / 'company.json'
        removed = copy.deepcopy(self.config)
        removed['people'][1]['active'] = False
        with patch.object(a, '_trusted_config', return_value=removed), patch.object(os, 'geteuid', return_value=self.staff.actor.uid):
            with self.assertRaises(a.AccessDenied):
                policy.read('company/work.md')

    def test_diagnostic_other_uid_run_denied(self):
        import install_diagnostics as diagnostics
        private = self.root / 'diagnostics'
        private.mkdir(mode=0o700)
        company.private_write(private / 'events.jsonl', b'{"note":"PRIVATE_SENTINEL"}\n')
        with patch.object(diagnostics.os, 'getuid', return_value=os.geteuid() + 10):
            with self.assertRaises(ValueError):
                diagnostics.read_run(private)
        events, damaged = diagnostics.read_run(private)
        self.assertTrue(damaged)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(events))

    def test_model_timeout_stops_process_group(self):
        import company_runtime as r
        import subprocess
        import time
        pidfile = self.root / 'child.pid'
        script = ('import os,time; from pathlib import Path; '
                  + 'Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid())); time.sleep(30)')
        with self.assertRaises(subprocess.TimeoutExpired):
            r.model_run([sys.executable, '-c', script], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, input='', text=True, timeout=0.1)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


if __name__ == '__main__':
    unittest.main()
