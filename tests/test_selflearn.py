"""Safety and lifecycle checks in an isolated fake Box; no real provider calls."""
import importlib.util
import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('selflearn', ROOT / 'template/lib/selflearn.py')
learn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learn)

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'box'
        self.home.mkdir()
        self.store = learn.Store(self.home)
        self.state = learn.blank()
        self.state['enabled'] = True
        self.store.save(self.state)

    def event(self, name='주간 SNS 문안 정리', task_id=None):
        return self.store.event(self.state, {'task_id': task_id or str(uuid.uuid4()), 'provider':'claude',
            'kind':'document', 'output':'draft', 'workflow':'organize', 'name':name})

    def draft(self):
        a = self.event(); b = self.event()
        self.assertEqual(b['match'], a['event_id'])
        result = self.store.draft(self.state, {'first':a['event_id'], 'second':b['event_id'], 'body':
            '## 언제\n매주 문안을 정리할 때\n## 입력\n이번 주 소재\n## 순서\n소재를 분류하고 문안을 작성한다.\n'
            '## 기준\n출처를 확인한다.\n## 결과\n채널별 문안 초안\n## 확인\n사람이 검토한다.\n## 중단\n자료가 부족하면 묻는다.'})
        return self.store.proposal(self.state, result['id'])

    def test_two_independent_requests_and_rejected_key(self):
        task = str(uuid.uuid4())
        first = self.event(task_id=task)
        self.assertEqual('duplicate', self.event(task_id=task)['status'])
        other = self.event('주간 SNS 문안 정리')
        self.assertEqual(first['event_id'], other['match'])
        result = self.store.draft(self.state, {'first': first['event_id'], 'second':other['event_id']})
        p = self.store.proposal(self.state, result['id'])
        self.assertIn('## 중단', p['content'])
        self.assertFalse((self.home / p['path']).exists())
        p['status'] = 'rejected'
        with self.assertRaises(learn.Problem):
            self.store.draft(self.state, {'first': first['event_id'], 'second':other['event_id']})
        self.assertNotIn('message', self.event())

    def test_different_names_require_explicit_match(self):
        a = self.event('매주 상품 검수'); b = self.event('고객 답변 작성')
        self.assertNotIn('match', b)
        with self.assertRaises(learn.Problem): self.store.draft(self.state, {'first':a['event_id'], 'second':b['event_id']})
        self.state['events'][0]['confirmed_matches'] = [b['event_id']]
        self.assertEqual('pending', self.store.draft(self.state, {'first':a['event_id'], 'second':b['event_id']})['status'])

    def test_human_can_confirm_tasks_with_different_classification(self):
        a = self.event('자료 정리')
        b = self.store.event(self.state, {'task_id': str(uuid.uuid4()), 'provider':'codex',
            'kind':'research', 'output':'report', 'workflow':'verify', 'name':'주간 조사'})
        with self.assertRaises(learn.Problem): self.store.draft(self.state, {'first':a['event_id'], 'second':b['event_id']})
        self.state['events'][0]['confirmed_matches'] = [b['event_id']]
        self.assertEqual('pending', self.store.draft(self.state, {'first':a['event_id'], 'second':b['event_id']})['status'])

    def test_skill_approval_rollback_and_modified_conflict(self):
        p = self.draft()
        change = self.store.approve(self.state, p)
        path = self.home / p['path']
        self.assertTrue(path.is_file())
        path.write_text('사용자가 수정함')
        with self.assertRaises(learn.Problem): self.store.rollback(self.state, change['id'])
        self.assertEqual('사용자가 수정함', path.read_text())
        path.write_bytes(p['content'].strip().encode() + b'\n')
        self.store.rollback(self.state, change['id'])
        self.assertFalse(path.exists())
        self.assertTrue((self.store.base / 'rollback' / (change['id'] + '.md')).is_file())

    def test_weekly_export_contains_only_approved_skills_and_tracks_rollback(self):
        p = self.draft()
        target = self.home / 'vault/reports/weekly/.learning-summary.json'
        self.assertFalse(target.exists())
        change = self.store.approve(self.state, p)
        public = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(len(public['items']), 1)
        self.assertEqual(public['items'][0]['title'], p['name'])
        self.assertNotIn(p['content'], target.read_text(encoding='utf-8'))
        self.store.rollback(self.state, change['id'])
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['items'], [])

    def test_lesson_diff_approval_conflict_and_rollback(self):
        self.store.lesson(self.state, {'kind':'correction', 'issue':'unsupported_claim', 'action':'check_evidence', 'rule':'고객 안내 전에 원문 기준을 확인합니다.'})
        self.assertEqual(1, self.store.review(self.state)['created'])
        self.assertEqual(0, self.store.review(self.state)['created'])
        p = self.state['proposals'][0]
        self.assertIn('+', p['diff'])
        target = self.home / p['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('수정된 기준')
        with self.assertRaises(learn.Problem): self.store.approve(self.state, p)
        self.assertEqual('수정된 기준', target.read_text())
        target.unlink()
        h = self.store.approve(self.state, p)
        self.store.rollback(self.state, h['id'])
        self.assertFalse(target.exists())

    def test_refresh_lesson_preserves_intervening_human_edit(self):
        self.store.lesson(self.state, {'kind':'failure', 'issue':'missing_input', 'action':'ask_before_work'})
        self.store.review(self.state)
        p = self.state['proposals'][0]
        target = self.home / p['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('# 직접 쓴 기준\n')
        self.store.refresh_lesson(self.state, p)
        self.assertIn('직접 쓴 기준', p['content'])
        change = self.store.approve(self.state, p)
        self.assertIn('직접 쓴 기준', target.read_text())
        self.store.rollback(self.state, change['id'])
        self.assertEqual('# 직접 쓴 기준\n', target.read_text())

    def test_private_patterns_and_date(self):
        for text in ('연락처: 010-1234-5678', 'hello@example.com', 'api_key="abcdefghijklmnop"',
                     '고객 계좌 123-45-67890', '승인 없이 발송한다',
                     '/Vol' + 'umes/private', 'fd7a:115c:' + 'a1e0:1234'):
            with self.subTest(text=text), self.assertRaises(learn.Problem): learn.clean_text(text, 160)
        self.assertEqual('2026-11-06 기준을 확인합니다.', learn.clean_text('2026-11-06 기준을 확인합니다.', 160))
        with self.assertRaises(learn.Problem): self.event('안내 hello@example.com')

    def test_no_approval_on_piped_input(self):
        script = ROOT/'template/lib/selflearn.py'
        process = subprocess.run([sys.executable, str(script), '--home', str(self.home), 'enable'], input='확인\n', text=True, capture_output=True)
        self.assertNotEqual(0, process.returncode)
        self.assertIn('직접', process.stderr)

    def test_confirmation_flow_on_terminal(self):
        p = self.draft()
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        try:
            proc = subprocess.Popen([sys.executable, str(ROOT/'template/lib/selflearn.py'), '--home', str(self.home), 'approve', p['id']], stdin=slave, stdout=slave, stderr=slave)
        finally:
            os.close(slave)
        try:
            output = b''
            sent = False
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and proc.poll() is None:
                ready, _, _ = select.select([master], [], [], .2)
                if ready:
                    output += os.read(master, 65536)
                if not sent and '계속하려면'.encode() in output:
                    os.write(master, '확인\n'.encode())
                    sent = True
            self.assertTrue(sent, output.decode(errors='replace'))
            self.assertEqual(0, proc.wait(timeout=1))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertTrue((self.home / p['path']).is_file())

    def test_random_skill_ids_are_not_mistaken_for_personal_data(self):
        for _ in range(30):
            with self.subTest():
                name = '업무' + uuid.uuid4().hex[:8]
                first = self.event(name)
                second = self.event(name)
                result = self.store.draft(self.state, {'first': first['event_id'], 'second': second['event_id']})
                proposal = self.store.proposal(self.state, result['id'])
                self.store.approve(self.state, proposal)

    def test_partial_transaction_recovers_only_known_hashes(self):
        path = self.home / 'vault/lessons/approved-learning.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        before, after = b'old', b'new'
        path.write_bytes(before)
        journal = {'status':'pending', 'id':str(uuid.uuid4()), 'changes':[{'path':'vault/lessons/approved-learning.md',
            'before_hash':learn.digest(before),'after_hash':learn.digest(after),'after':learn.encode(after)}]}
        self.store.write(self.store.journal, self.store.dump(journal))
        with self.store.locked(): pass
        self.assertEqual(after, path.read_bytes())
        self.store.write(self.store.journal, self.store.dump(journal))
        path.write_bytes(b'human edit')
        with self.assertRaises(learn.Problem):
            with self.store.locked(): pass
        self.assertEqual(b'human edit', path.read_bytes())

    def test_paths_and_update_exclusion(self):
        spec = importlib.util.spec_from_file_location('updater', ROOT/'tools/update.py')
        updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)
        self.assertFalse(updater.allowed('box', '.claude/skills/ilson-learned-abc/SKILL.md'))
        self.assertFalse(updater.allowed('cli', 'template/claude/skills/ilson-learned-abc/SKILL.md'))
        link = self.home/'vault/lessons'; link.symlink_to(self.home)
        with self.assertRaises(learn.Problem): self.store.read(link/'x.md')

    def test_tampered_proposal_cannot_write_another_path(self):
        p = self.draft()
        p['path'] = 'vault/company/_index.md'
        with self.assertRaises(learn.Problem): self.store.approve(self.state, p)
        self.assertFalse((self.home / 'vault/company/_index.md').exists())
        journal = {'status':'pending', 'id':str(uuid.uuid4()), 'changes':[{'path':'vault/company/_index.md',
            'before_hash':None, 'after_hash':learn.digest(b'changed'), 'after':learn.encode(b'changed')}]}
        self.store.write(self.store.journal, self.store.dump(journal))
        with self.assertRaises(learn.Problem):
            with self.store.locked(): pass

    def test_setup_preserves_user_edits_and_upgrades_known_baseline(self):
        spec = importlib.util.spec_from_file_location('instructions', ROOT/'template/lib/install-instructions.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        target = self.home/'CLAUDE.md'; target.write_text('직접 고친 기준')
        skill = self.home/'.claude/skills/ilson-search/SKILL.md'
        skill.parent.mkdir(parents=True); skill.write_text('직접 고친 스킬')
        installer.run(ROOT/'template', self.home)
        self.assertEqual('직접 고친 기준', target.read_text())
        self.assertEqual('직접 고친 스킬', skill.read_text())
        old = subprocess.check_output(['git','show','163d732:template/CLAUDE.md'], cwd=ROOT)
        target.write_bytes(old)
        installer.run(ROOT/'template', self.home)
        self.assertEqual((ROOT/'template/CLAUDE.md').read_bytes(), target.read_bytes())

if __name__ == '__main__': unittest.main()
