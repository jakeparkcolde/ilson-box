import importlib.util
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('weekly_summary', ROOT / 'template/lib/weekly_summary.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='일손 테스트 ')
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / 'vault'
        (self.vault / 'reports').mkdir(parents=True)

    def write(self, path, text):
        file = self.vault / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
        return file

    def test_empty_and_private_learning_never_read(self):
        self.write('.ilson-learning/state.json', '비밀 초안')
        result = w.build(self.vault, date(2026, 11, 8))
        self.assertIn('기록 없음', result)
        self.assertIn('승인된 공개 요약 없음', result)
        self.assertNotIn('비밀 초안', result)
        self.assertNotIn('= 0분', result)

    def test_real_files_duplicate_missing_baseline_and_privacy(self):
        self.write('journal/2026-11-02.md', '- [x] [수행:일손] [유형:정리] 고객 원문\n- [x] [수행:일손] [유형:정리] 고객 원문\n- [x] [유형:검토] 미확인\n')
        self.write('journal/2026-11-01.md', '- [x] 이전 주')
        self.write('reports/briefing/2026-11-08.md', '확인 필요: 민감한 내용')
        self.write('reports/pending/초안.md', '고객 원문')
        self.write('reports/weekly-input.json', json.dumps({'baseline_minutes': {'정리': 10}, 'completed': [{'title': '가짜'}]}))
        result = w.build(self.vault, date(2026, 11, 8))
        self.assertEqual(result.count('완료 표시된 업무'), 2)
        self.assertIn('1건 × 사장님 기준 10분 = 10분', result)
        self.assertIn('전체 절약 시간은 확인 필요', result)
        self.assertIn('브리핑 확인 필요 항목', result)
        self.assertIn('승인 대기 문서', result)
        self.assertNotIn('고객 원문', result)
        self.assertNotIn('가짜', result)
        self.assertNotIn('2026-11-01.md', result)

    def test_missing_baseline_never_invents_minutes(self):
        self.write('journal/2026-11-08.md', '- [x] [수행:일손] [유형:정리] 업무\n')
        result = w.build(self.vault, date(2026, 11, 8))
        self.assertIn('완료 근거와 업무 유형별 기준 시간', result)
        self.assertNotIn(' = ', result)

    def test_course_skills_are_read_from_flat_vault(self):
        skill = self.vault / '.claude/skills/demo/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('출처: 스킬 나눔 · 1기 · 나눔-123456789a · 12345678-1234-1234-1234-123456789abc\n', encoding='utf-8')
        stamp = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
        os.utime(skill, (stamp, stamp))
        self.assertIn('출처: 스킬 나눔', w.build(self.vault, date(2026, 11, 8), flat_vault=True))
        self.assertNotIn('출처: 스킬 나눔', w.build(self.vault, date(2026, 11, 8), flat_vault=False))

    def test_approved_public_and_timezone(self):
        self.write('reports/weekly/.learning-summary.json', json.dumps({'version': 1, 'items': [
            {'id': '1', 'type': 'skill', 'status': 'pending', 'title': '초안', 'source': '승인 기록', 'date': '2026-11-05'},
            {'id': '2', 'type': 'skill', 'status': 'approved', 'title': '승인 스킬', 'source': '승인 기록', 'date': '2026-11-01T15:00:00Z'},
            {'id': '3', 'type': 'skill', 'status': 'approved', 'title': '지난주', 'source': '승인 기록', 'date': '2026-11-01T14:59:59Z'}]}))
        result = w.build(self.vault, date(2026, 11, 8))
        self.assertNotIn('초안', result)
        self.assertIn('승인 스킬 · 2026-11-02', result)
        self.assertNotIn('지난주', result)

    def test_share_installed_and_fake_approval_store(self):
        skill = self.vault.parent / '.claude/skills/demo/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('출처: 스킬 나눔 · 1기 · 나눔-123456789a · 12345678-1234-1234-1234-123456789abc\n', encoding='utf-8')
        stamp = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
        os.utime(skill, (stamp, stamp))
        fake = types.SimpleNamespace(weekly_counts=lambda since, until: {'pending': 2},
            list_titles=lambda states, since, until, limit: [{'id': 'a', 'state': 'pending', 'updated_at': '2026-11-07T00:00:00Z', 'title': '비밀'}])
        with patch.dict(sys.modules, {'approval_store': fake}):
            result = w.build(self.vault, date(2026, 11, 8))
        self.assertIn('승인 대기: 2건', result)
        self.assertIn('스킬 나눔으로 설치된 스킬', result)
        self.assertIn('출처: 스킬 나눔', result)
        self.assertNotIn('비밀', result)

    def test_failed_store_and_symlinked_report_folder(self):
        def fail(*args, **kwargs):
            raise OSError('not available')
        fake = types.SimpleNamespace(weekly_counts=fail, list_titles=fail)
        with patch.dict(sys.modules, {'approval_store': fake}):
            self.assertIn('조회 실패', w.build(self.vault, date(2026, 11, 8)))
        external = self.vault.parent / 'outside'
        external.mkdir()
        (self.vault / 'reports' / 'weekly').symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            w.main(['--vault', str(self.vault), '--end', '2026-11-08'])
        self.assertEqual(list(external.iterdir()), [])

    def test_rerun_and_flat_vault(self):
        for script in ('template/lib/weekly_summary.py', 'course/lib/weekly_summary.py'):
            cmd = [sys.executable, str(ROOT / script), '--vault', str(self.vault), '--end', '2026-11-08']
            subprocess.run(cmd, check=True, capture_output=True)
            target = self.vault / 'reports/weekly/2026-11-08-ilson.md'
            before = target.read_bytes()
            subprocess.run(cmd, check=True, capture_output=True)
            self.assertEqual(before, target.read_bytes())
        self.assertFalse((self.vault / 'vault').exists())


if __name__ == '__main__':
    unittest.main()
