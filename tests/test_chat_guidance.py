"""Model-free verification of installed Claude/Codex chat entry and user-file preservation."""
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_setup

ROOT = Path(__file__).resolve().parents[1]


class Launched(Exception):
    pass


class ChatGuidanceTests(unittest.TestCase):
    def capture(self, script, home, provider, model=''):
        result = {}
        def launch(executable, argv):
            result.update(executable=executable, argv=argv, cwd=Path.cwd(), pwd=os.environ['PWD'])
            raise Launched()
        original = Path.cwd()
        try:
            with patch.dict(os.environ), patch.object(sys, 'argv', [str(script), '--home', str(home), provider, model, '--chat']), patch('os.execvp', side_effect=launch):
                with self.assertRaises(Launched):runpy.run_path(str(script), run_name='__main__')
        finally:
            os.chdir(original)
        return result

    def test_claude_and_codex_argv_preserve_model_and_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)/'한글 Box 공백';home.mkdir()
            for provider in ('claude', 'codex'):
                for model in ('', 'chosen-model'):
                    with self.subTest(provider=provider, model=model):
                        result = self.capture(ROOT/'template/lib/research/settings.py', home, provider, model)
                        self.assertEqual(result['cwd'], home.resolve());self.assertEqual(result['pwd'], str(home))
                        args = result['argv'];self.assertEqual(result['executable'], provider)
                        if model:self.assertEqual(args[args.index('--model')+1], model)
                        if provider == 'claude':
                            self.assertEqual(args, ['claude', '--permission-mode', 'auto'] + (['--model', model] if model else []))
                        else:
                            self.assertEqual(args[:-1], ['codex'] + (['--model', model] if model else []))
                            for instruction in ('CLAUDE.md', '.claude/commands/employee.md', 'ilson people', '이름·역할', '요청 ID', '직원 ID', 'ILSON_HOME'):
                                self.assertIn(instruction, args[-1])
                            self.assertNotIn('--config', args);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)

    def test_install_reinstall_preserves_user_agents_and_installs_both_entry_paths(self):
        fixture = test_setup.SetupTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.box.mkdir();isolated = fixture.base/'isolated-user';isolated.mkdir();fixture.env['HOME'] = str(isolated)
        names = ('AGENTS.md', 'AGENTS.override.md')
        for name in names:(fixture.box/name).write_text('사용자 고유 지침 '+name)
        before = {name: (fixture.box/name).read_bytes() for name in names}
        command = 'TEMPLATE="' + str(ROOT/'template') + '"; SANDBOX=1; init_step_box'
        for _ in range(2):
            result = fixture.shell(command, timeout=30);self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            for name, body in before.items():self.assertEqual((fixture.box/name).read_bytes(), body)
            for provider in ('claude', 'codex'):
                launched = self.capture(fixture.box/'lib/research/settings.py', fixture.box, provider)
                self.assertEqual(launched['executable'], provider)
            self.assertIn('ilson people', (fixture.box/'CLAUDE.md').read_text())
            self.assertIn('ilson people', (fixture.box/'.claude/commands/employee.md').read_text())
        self.assertFalse((isolated/'.codex').exists());self.assertFalse((isolated/'.claude').exists())

    def test_update_and_rollback_preserve_existing_agents(self):
        import test_update
        fixture = test_update.UpdateTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        home = fixture.roots['box']
        before = {}
        for name in ('AGENTS.md', 'AGENTS.override.md'):
            path = home/name;path.write_text('사용자 원본 '+name);before[name] = path.read_bytes()
        body = (ROOT/'template/lib/research/settings.py').read_bytes()
        manifest, archive = fixture.bundle([('box', 'lib/research/settings.py', body, None),
                                            ('cli', 'template/lib/research/settings.py', body, None)])
        test_update.u.apply(fixture.roots, manifest, archive)
        self.assertEqual((home/'lib/research/settings.py').read_bytes(), body)
        for name, value in before.items():self.assertEqual((home/name).read_bytes(), value)
        storage = home/'.updates';test_update.u.rollback(fixture.roots, storage, test_update.u.read(storage/'journal.json'))
        for name, value in before.items():self.assertEqual((home/name).read_bytes(), value)

    def test_update_whitelist_ships_entry_without_owning_agents(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('guidance_update', ROOT/'tools/update.py')
        updater = importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
        for area, path in [('cli','template/lib/research/settings.py'), ('box','lib/research/settings.py'),
                           ('box','CLAUDE.md'), ('box','.claude/commands/employee.md')]:
            self.assertTrue(updater.allowed(area,path))
        for name in ('AGENTS.md', 'AGENTS.override.md'):
            self.assertFalse(updater.allowed('box',name));self.assertFalse(updater.allowed('cli','template/'+name))


if __name__ == '__main__':unittest.main()
