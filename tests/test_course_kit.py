import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


class CourseKitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.box = self.home / 'ilson'
        # Course-file preservation tests exercise a licensed CLI copy. The real
        # signed and unlicensed flows are tested in test_license_integration.
        self.repo = self.home / 'repo'
        self.repo.mkdir()
        shutil.copy2(ROOT / 'ilson', self.repo / 'ilson')
        shutil.copytree(ROOT / 'template', self.repo / 'template', ignore=shutil.ignore_patterns('__pycache__'))
        (self.repo / 'template/lib/license.py').write_text('import sys\nsys.exit(0)\n')
        self.env = dict(os.environ, HOME=str(self.home), ILSON_HOME=str(self.box))

    def run_kit(self):
        return subprocess.run(['bash', str(self.repo / 'ilson'), 'course-kit'], env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True)

    def test_kit_filenames_and_text_are_nfc(self):
        files = list((ROOT / 'template/claude/skills/course-kit-20261109').glob('*.md'))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path.name):
                self.assertTrue(unicodedata.is_normalized('NFC', path.name))
                self.assertTrue(unicodedata.is_normalized('NFC', path.read_text(encoding='utf-8')))

    def test_symlink_file_is_refused(self):
        kit = self.box / '강의키트-20261109-v2'
        kit.mkdir(parents=True)
        outside = self.home / 'outside.md'
        outside.write_text('기존 파일')
        (kit / '내 업무 소개.md').symlink_to(outside)
        result = self.run_kit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('강의 키트 파일이 연결 경로입니다', result.stderr)
        self.assertEqual(outside.read_text(), '기존 파일')

    def test_existing_install_and_repeat_preserve_files(self):
        vault = self.box / 'vault'
        vault.mkdir(parents=True)
        (vault / 'CONTEXT.md').write_text('existing vault')
        kit = self.box / '강의키트-20261109-v2'
        kit.mkdir()
        note = kit / '내 업무 소개.md'
        note.write_text('my own work')
        for _ in range(2):
            result = self.run_kit()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(note.read_text(), 'my own work')
        self.assertEqual((vault / 'CONTEXT.md').read_text(), 'existing vault')
        self.assertTrue((kit / '시작과_막힘_복구.md').is_file())

    def test_upgrade_creates_separate_kit_and_preserves_both_versions(self):
        old = self.box / '강의키트-20261109'
        old.mkdir(parents=True)
        (old / '작업_연습.md').write_text('사용자 수정')
        result = self.run_kit()
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self.box / '강의키트-20261109-v2' / '작업_연습.md'
        self.assertIn('STANDARD.md', new.read_text())
        new.write_text('새 폴더에서도 수정')
        result = self.run_kit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((old / '작업_연습.md').read_text(), '사용자 수정')
        self.assertEqual(new.read_text(), '새 폴더에서도 수정')

    def test_symlink_destination_is_refused(self):
        self.box.mkdir()
        other = self.home / 'other'
        other.mkdir()
        (self.box / '강의키트-20261109-v2').symlink_to(other, target_is_directory=True)
        self.assertNotEqual(self.run_kit().returncode, 0)
        self.assertEqual(list(other.iterdir()), [])

    def test_new_install_setup_creates_kit_and_reopens_saved_file(self):
        env = dict(self.env, ILSON_SRC=str(self.repo), ILSON_CLI_DIR=str(self.home / 'cli'),
                   ILSON_BIN_DIR=str(self.home / 'bin'))
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--sandbox'], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('설치 요약', result.stdout)
        self.assertIn('설치됨:', result.stdout)
        self.assertIn('실패: 없음', result.stdout)
        self.assertIn('다음 할 일:', result.stdout)
        self.assertIn('강의 키트', result.stdout)
        note = self.box / '강의키트-20261109-v2' / '작업_연습.md'
        original = note.read_text()
        note.write_text(original + '\n저장 확인\n')
        self.assertIn('저장 확인', note.read_text())
        installed = subprocess.run(['bash', str(self.home / 'cli/ilson'), 'course-kit'],
                                   env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(note.read_text(), original + '\n저장 확인\n')


if __name__ == '__main__':
    unittest.main()
