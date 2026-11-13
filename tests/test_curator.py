"""Offline curator acceptance tests: synthetic vaults and no external requests."""
import importlib.util
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('curator_test', ROOT / 'template/lib/curator.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
SCRATCH = ROOT / '.scratch'
SCRATCH.mkdir(exist_ok=True)


class CuratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='큐레이터 ', dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = c.Store(self.home)
        self.store.vault.mkdir()
        self.now = datetime.now().replace(hour=23, minute=5, second=0, microsecond=0).timestamp()
        c.set_enabled(self.store, True)

    def note(self, relative, text, at=None):
        path = self.store.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        at = self.now - 30 if at is None else at
        os.utime(path, (at, at))
        return path

    def run_digest(self, **kwargs):
        return c.run_once(self.store, now=self.now, license_check=lambda *_: True, **kwargs)

    def output(self):
        return next((self.store.vault / 'journal/curator').glob('*.md')).read_text()

    def test_new_note_only_original_bytes_and_mtimes_preserved_and_local_semantics(self):
        a = self.note('company/한글 업무.md', '#매출\n[[company/참고]]\n- [x] 송장 확인\n- [ ] 입금 확인\n확인 필요: 수량')
        b = self.note('company/참고.md', '#매출\n참고 내용', at=self.now - 7*86400)
        original = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (a, b)}
        with mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            self.assertEqual(self.run_digest(), 'OK')
        self.assertEqual(original, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in original})
        text = self.output()
        for expected in ('로컬 규칙으로 정리 · AI 요약 없음', '완료를 뜻하지 않음', '명시적 완료 표시', '기존 내부 링크', '같은 태그', '입금 확인', '수량'):
            self.assertIn(expected, text)
        state = (self.store.state / 'result.json').read_text()
        for private in ('한글 업무', '참고.md', '송장', str(self.home)):
            self.assertNotIn(private, state)

    def test_default_off_no_vault_enumeration_or_reads(self):
        for enabled in (None, False):
            store = c.Store(self.home / str(enabled))
            if enabled is False:
                c.set_enabled(store, False)
            with mock.patch.object(c, 'collect_notes', side_effect=AssertionError('read')), mock.patch.object(c, 'candidates', side_effect=AssertionError('enumerate')):
                self.assertEqual(c.run_once(store), 'OFF')
            self.assertFalse(store.vault.exists())

    def test_exclusions_and_unresolved_links_never_read_or_leak(self):
        self.note('company/허용.md', '[[management/기밀]]\n[[people/other/비밀]]\n[[../management/기밀]]\n#일반')
        for name in ('management/기밀.md', 'people/other/비밀.md', '.hidden/비밀.md', 'company/.hidden/비밀.md', 'reports/pending/비밀.md', 'lessons/미승인.md', 'company/people/other/비밀.md', 'company/management/기밀.md'):
            self.note(name, 'PRIVATE_SENTENCE')
        self.assertEqual(self.run_digest(), 'OK')
        self.assertNotIn('PRIVATE_SENTENCE', self.output())
        self.assertNotIn('기밀', self.output())
        self.assertNotIn('people/other', self.output())
        self.assertIn('읽음 1', self.output())

    def test_symlink_hardlink_and_root_link_boundaries(self):
        private = self.home / 'private.md'
        private.write_text('PRIVATE_SENTENCE')
        company = self.store.vault / 'company'
        company.mkdir()
        (company / 'link.md').symlink_to(private)
        os.link(private, company / 'hard.md')
        (company / 'linked-dir').symlink_to(self.home, target_is_directory=True)
        self.assertEqual(self.run_digest(), 'OK')
        self.assertNotIn('PRIVATE_SENTENCE', self.output())
        other = c.Store(self.home / 'other')
        other.home.mkdir()
        other.vault.symlink_to(self.store.vault, target_is_directory=True)
        c.set_enabled(other, True)
        with self.assertRaises((OSError, c.CuratorError)):
            c.run_once(other, now=self.now, license_check=lambda *_: True)

    def test_ancestor_link_output_link_and_reparse_rejected(self):
        with mock.patch.object(Path, 'lstat') as ls:
            info = mock.Mock(st_mode=0o40700, st_file_attributes=0x400)
            ls.return_value = info
            with self.assertRaises(c.CuratorError):
                c.check_path(self.store.vault)
        (self.store.vault / 'journal').mkdir()
        (self.store.vault / 'journal/curator').symlink_to(self.home)
        with self.assertRaises((OSError, c.CuratorError)):
            self.run_digest()
        self.assertFalse(list(self.home.glob('20*.md')))

    def test_once_per_day_and_addendum_do_not_overwrite_user_edits(self):
        self.note('company/a.md', '- [ ] first')
        self.assertEqual(self.run_digest(), 'OK')
        output = next((self.store.vault / 'journal/curator').glob('*.md'))
        output.write_text('USER EDIT')
        before = (output.read_bytes(), output.stat().st_mtime_ns)
        with mock.patch.object(c, 'collect_notes', side_effect=AssertionError('duplicate read')):
            self.assertEqual(self.run_digest(), 'already_exists')
        self.assertEqual(self.run_digest(addendum=True), 'OK')
        self.assertEqual((output.read_bytes(), output.stat().st_mtime_ns), before)
        self.assertEqual(len(list(output.parent.glob('*.md'))), 2)

    def test_lock_excludes_second_process_and_released_on_exit(self):
        with c.vault_lock(self.store):
            with self.assertRaisesRegex(c.CuratorError, 'LOCKED'):
                self.run_digest()
        self.assertEqual(self.run_digest(), 'OK')

    def test_partial_failure_and_limits_do_not_invent_work(self):
        self.note('company/large.md', 'x' * (c.MAX_FILE + 1))
        bad = self.note('company/bad.md', '')
        bad.write_bytes(b'\xff')
        self.assertEqual(self.run_digest(), 'PARTIAL')
        self.assertIn('한도 초과 1', self.output())
        self.assertIn('읽기 실패 1', self.output())
        self.assertIn('변경된 노트가 없습니다', self.output())

    def test_file_and_total_limits_enforced(self):
        for n in range(5):
            self.note(f'company/{n}.md', '#태그\n' + 'a'*100)
        with mock.patch.object(c, 'MAX_FILES', 2):
            self.assertEqual(self.run_digest(), 'PARTIAL')
        self.assertIn('읽음 2', self.output())
        with mock.patch.object(c, 'MAX_TOTAL', 115):
            self.assertEqual(self.run_digest(addendum=True), 'PARTIAL')

    def test_publish_failure_leaves_no_final_and_retry_works(self):
        self.note('company/a.md', '- [x] done')
        with mock.patch.object(c.os, 'link', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_digest()
        self.assertFalse(list((self.store.vault / 'journal/curator').glob('*.md')))
        self.assertNotIn('last_date', self.store.result())
        self.assertEqual(self.run_digest(), 'OK')

    def test_state_failure_after_publication_does_not_duplicate_or_overwrite(self):
        with mock.patch.object(self.store, 'record', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.run_digest()
        with mock.patch.object(c, 'collect_notes', side_effect=AssertionError('read')):
            self.assertEqual(self.run_digest(), 'already_exists')
        self.assertEqual(len(list((self.store.vault / 'journal/curator').glob('*.md'))), 1)

    def test_revoke_during_collection_does_not_publish(self):
        original = c.collect_notes
        def revoke(*args):
            notes, counts = original(*args)
            cfg = self.store.config()
            cfg['enabled'] = False
            c.save_json(self.store.state / 'config.json', cfg)
            return notes, counts
        with mock.patch.object(c, 'collect_notes', side_effect=revoke):
            self.assertEqual(self.run_digest(), 'OFF')
        self.assertFalse((self.store.vault / 'journal/curator').exists())

    def test_due_run_sleep_manual_completion_clock_and_timezone(self):
        cfg = self.store.config()
        cfg.update(auto=True, changed_at=self.now - 3*86400)
        c.save_json(self.store.state / 'config.json', cfg)
        self.assertEqual(c.due_run(self.store, self.now), str(datetime.fromtimestamp(self.now).date()))
        self.assertEqual(c.due_run(self.store, self.now - 3600), str((datetime.fromtimestamp(self.now) - timedelta(days=1)).date()))
        with mock.patch.object(c, 'watchdog_active', return_value=True):
            self.assertEqual(self.run_digest(automatic=True), 'OK')
            self.assertEqual(self.run_digest(automatic=True), 'NOT_DUE')
        with self.assertRaisesRegex(c.CuratorError, 'CLOCK_REVIEW'):
            c.due_run(self.store, self.now - 600)
        with mock.patch.object(c, 'timezone_id', return_value='changed'):
            with self.assertRaisesRegex(c.CuratorError, 'CLOCK_REVIEW'):
                c.due_run(self.store, self.now + 600)

    def test_interval_continues_from_previous_completion(self):
        self.note('company/a.md', 'first')
        self.assertEqual(self.run_digest(), 'OK')
        next_time = self.now + 86400
        self.note('company/b.md', 'second', at=self.now + 600)
        self.assertEqual(c.run_once(self.store, now=next_time, license_check=lambda *_: True), 'OK')
        text = (self.store.vault / 'journal/curator' / (str(datetime.fromtimestamp(next_time).date()) + '.md')).read_text()
        day_record = text.split('## 하루 기록')[1].split('## 관련 노트')[0]
        self.assertNotIn('a.md', day_record)
        self.assertIn('b.md', day_record)

    def test_unconsented_cli_and_course_auto_never_touch_notes_or_network(self):
        env = dict(os.environ, ILSON_HOME=str(self.home / 'fresh'))
        for args, expected in (([], 'CONSENT_REQUIRED'), (['--on'], 'CONSENT_REQUIRED'), (['--edition', 'intel-course', '--auto-on'], 'AUTO_UNSUPPORTED'), (['--ai-on'], 'AI_DISABLED')):
            p = subprocess.run([sys.executable, str(ROOT / 'template/lib/curator.py'), *args], env=env, input='', capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn(expected, p.stdout)
        self.assertFalse((self.home / 'fresh').exists())

    def test_local_license_missing_no_content_reads_and_no_requests(self):
        with mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network')), mock.patch.object(c, 'collect_notes', side_effect=AssertionError('read')):
            self.assertEqual(c.run_once(self.store, now=self.now), 'LICENSE_LOCAL_REQUIRED')
        self.assertFalse((self.store.vault / 'journal/curator').exists())

    def test_local_license_accepts_only_fresh_verified_cache_without_mutation(self):
        import struct
        module = c.license_module()
        module.PUBLIC_KEYS = {1: bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')}
        seed = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        serial = module.encode_serial(struct.pack('>BB16sHBII', 1, 1, b't'*16, 1, 1, int(self.now)-100, 0xffffffff), seed)
        state_dir = self.home / 'state/license'
        state_dir.mkdir(mode=0o700)
        info = module.parse_serial(serial, self.now)
        for age, expected in ((10, True), (module.CHECK_INTERVAL, False)):
            for name, text in (('serial', serial), ('state.json', json.dumps({'id': info['id'], 'registered': True, 'last_success': self.now-age, 'last_observed': self.now}))):
                target = state_dir / name
                if target.exists():
                    target.write_text(text)
                else:
                    with os.fdopen(os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as f:
                        f.write(text)
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in state_dir.iterdir()}
            with mock.patch.object(c, 'license_module', return_value=module), mock.patch.object(module, 'request', side_effect=AssertionError('network')):
                self.assertEqual(c.local_license(self.home, self.now), expected)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_course_resolver_uses_selected_vault_and_hash_is_per_vault(self):
        for edition in ('intel-course', 'windows-course'):
            vault = self.home / edition / '한글 강의 볼트'
            vault.mkdir(parents=True)
            store = c.Store(self.home, edition, vault)
            c.set_enabled(store, True)
            self.assertEqual(c.run_once(store, now=self.now, license_check=lambda *_: True), 'OK')
            self.assertTrue(list((vault / 'journal/curator').glob('*.md')))
            self.assertNotEqual(store.state, self.store.state)
            self.assertFalse((vault / 'vault').exists())

    def test_markdown_payload_is_literal_and_cannot_embed_remote_media(self):
        self.note('company/a.md', '- [ ] ![secret](https://example.invalid/collect) <img src="https://example.invalid/collect">')
        self.assertEqual(self.run_digest(), 'OK')
        self.assertNotIn('![secret](', self.output())
        self.assertNotIn('<img', self.output())

    def test_watchdog_returns_without_waiting_for_curator_child(self):
        import shutil
        box = self.home / 'watchdog-box'
        (box / 'lib').mkdir(parents=True)
        for name in ('watchdog.sh', 'common.sh'):
            shutil.copyfile(ROOT / 'template/lib' / name, box / 'lib' / name)
        (box / 'lib/license.py').write_text('import sys; sys.exit(0)')
        marker = box / 'state/child-finished'
        (box / 'lib/curator.py').write_text('import time; from pathlib import Path; time.sleep(1); Path(' + repr(str(marker)) + ').touch()')
        env = dict(os.environ, ILSON_HOME=str(box))
        start = time.monotonic()
        result = subprocess.run(['bash', str(box / 'lib/watchdog.sh')], env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic()-start, 0.9)
        self.assertTrue((box / 'state/last-run.watchdog').is_file())
        for _ in range(30):
            if marker.exists():
                break
            time.sleep(0.1)
        self.assertTrue(marker.is_file())

    def test_ai_hook_cannot_send(self):
        with self.assertRaisesRegex(c.CuratorError, 'AI_DISABLED'):
            c.run_ai_summary('do anything')
        self.assertEqual((ROOT / 'template/lib/curator.py').read_bytes(), (ROOT / 'course/lib/curator.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
