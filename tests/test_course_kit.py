import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CourseKitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.box = self.home / 'ilson'
        self.env = dict(os.environ, HOME=str(self.home), ILSON_HOME=str(self.box))

    def run_kit(self):
        return subprocess.run(['bash', str(ROOT / 'ilson'), 'course-kit'], env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)

    def test_existing_install_and_repeat_preserve_files(self):
        vault = self.box / 'vault'
        vault.mkdir(parents=True)
        (vault / 'CONTEXT.md').write_text('existing vault')
        kit = self.box / '강의키트-20261109'
        kit.mkdir()
        note = kit / '내 업무 소개.md'
        note.write_text('my own work')
        for _ in range(2):
            result = self.run_kit()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(note.read_text(), 'my own work')
        self.assertEqual((vault / 'CONTEXT.md').read_text(), 'existing vault')
        self.assertTrue((kit / '시작과_막힘_복구.md').is_file())

    def test_symlink_destination_is_refused(self):
        self.box.mkdir()
        other = self.home / 'other'
        other.mkdir()
        (self.box / '강의키트-20261109').symlink_to(other, target_is_directory=True)
        self.assertNotEqual(self.run_kit().returncode, 0)
        self.assertEqual(list(other.iterdir()), [])

    def test_new_install_setup_creates_kit_and_reopens_saved_file(self):
        env = dict(self.env, ILSON_SRC=str(ROOT), ILSON_CLI_DIR=str(self.home / 'cli'),
                   ILSON_BIN_DIR=str(self.home / 'bin'))
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--sandbox'], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        note = self.box / '강의키트-20261109' / '작업_연습.md'
        original = note.read_text()
        note.write_text(original + '\n저장 확인\n')
        self.assertIn('저장 확인', note.read_text())
        installed = subprocess.run(['bash', str(self.home / 'cli/ilson'), 'course-kit'],
                                   env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(note.read_text(), original + '\n저장 확인\n')


if __name__ == '__main__':
    unittest.main()
