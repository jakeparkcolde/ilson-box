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


class AccessTests(unittest.TestCase):
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

if __name__ == '__main__':
    unittest.main()
