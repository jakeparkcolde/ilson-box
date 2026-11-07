import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'course/lib'))
spec = importlib.util.spec_from_file_location('skill_share_test', ROOT / 'course/lib/skill_share.py')
share = importlib.util.module_from_spec(spec)
spec.loader.exec_module(share)

class ShareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / '.claude/skills/sample').mkdir(parents=True)
        (self.home / 'company').mkdir()
        (self.home / '.claude/skills/sample/SKILL.md').write_text('# 정리\n결과를 검토합니다.\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_sensitive_and_safe(self):
        examples = ['010-1234-5678', 'person@example.com', '900101-1234567',
                    '123-456-789012', '4111 1111 1111 1111', '서울특별시 강남구 테헤란로 123',
                    'api_key = abcdefghijklmnopqrstuv', '고유회사']
        for example in examples:
            with self.subTest(example=example):
                self.assertTrue(share.inspect_files({'SKILL.md':example}, {'고유회사'}))
        self.assertEqual(share.inspect_files({'SKILL.md':'# 일반 업무\n2026-11-07 기준으로 확인합니다.'}), [])
        self.assertTrue(share.inspect_files({'SKILL.md':'https://example.org'}))

    def test_company_and_bundle(self):
        (self.home / 'company/고유회사.md').write_text('일반 정보', encoding='utf-8')
        (self.home / 'company/팀.md').write_text('- **이름**: 박가명\n', encoding='utf-8')
        self.assertEqual(len(share.bundle(self.home, 'sample', True)), 1)
        (self.home / '.claude/skills/sample/SKILL.md').write_text('고유회사 정리', encoding='utf-8')
        with self.assertRaisesRegex(share.Problem, '회사 고유 이름'):
            share.bundle(self.home, 'sample', True)
        (self.home / '.claude/skills/sample/SKILL.md').write_text('박가명 확인', encoding='utf-8')
        with self.assertRaisesRegex(share.Problem, '회사 고유 이름'):
            share.bundle(self.home, 'sample', True)

    def test_paths_files_and_links(self):
        for name in ('../sample','/tmp/sample','sample/../../evil'):
            with self.subTest(name=name), self.assertRaises(share.Problem):
                share.bundle(self.home, name, True)
        for name in ('../evil.md','/evil.md','sub/evil.md','run.sh'):
            with self.subTest(name=name), self.assertRaises(share.Problem):
                share.inspect_files({'SKILL.md':'정리',name:'정리'})
        (self.home / '.claude/skills/sample/link.md').symlink_to(self.home / 'company', target_is_directory=True)
        with self.assertRaisesRegex(share.Problem, '링크'):
            share.bundle(self.home, 'sample', True)

    def test_executable_limits_and_collision(self):
        path = self.home / '.claude/skills/sample/SKILL.md'
        original_fstat = os.fstat
        def executable(fd):
            values = list(original_fstat(fd))
            values[0] |= stat.S_IXUSR
            return os.stat_result(values)
        with mock.patch.object(share.os, 'fstat', side_effect=executable):
            with self.assertRaises(share.Problem): share.bundle(self.home, 'sample', True)
        with self.assertRaises(share.Problem): share.inspect_files({'SKILL.md':'가' * 17000})
        with self.assertRaises(share.Problem): share.inspect_files({'SKILL.md':'정리',**{str(n)+'.md':'정리' for n in range(10)}})
        item = {'name':'sample','id':'12345678-1234-1234-1234-123456789abc','cohort':1,'alias':'나눔-0123456789','files':{'SKILL.md':'# 검토'}}
        with self.assertRaisesRegex(share.Problem, '덮어쓰지'):
            share.install(self.home, item)
        item['name'] = 'new-skill'
        target = share.install(self.home, item)
        self.assertIn('출처: 스킬 나눔 · 1기 · 나눔-0123456789', (target/'SKILL.md').read_text(encoding='utf-8'))

    def test_non_tty_confirmation_fails(self):
        with mock.patch.object(sys, 'stdin', io.StringIO('yes\n')):
            with self.assertRaisesRegex(share.Problem, '터미널'):
                share.confirm('확인')

    def test_untrusted_metadata_and_download(self):
        item = {'name':'sample\x1b','id':'12345678-1234-1234-1234-123456789abc','cohort':1,'alias':'나눔-0123456789','files':{'SKILL.md':'# 검토'}}
        with self.assertRaises(share.Problem): share.validate_item(item)
        item['name']='sample'
        item['files']={'SKILL.md':'\x1b[2J'}
        with self.assertRaises(share.Problem): share.validate_item(item)

    def test_online_failure_does_not_use_offline_grace(self):
        with mock.patch.object(share.licensing, 'private_dir', return_value=self.home), \
             mock.patch.object(share.licensing, 'safe_read', side_effect=['serial','a'*64]), \
             mock.patch.object(share.licensing, 'parse_serial'), \
             mock.patch.object(share.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect=OSError('offline')
            with self.assertRaisesRegex(share.Problem, '오프라인 유예'):
                share.request(self.home, 'list')

    def test_upload_and_download_use_reviewed_snapshot(self):
        item={'name':'received','id':'12345678-1234-1234-1234-123456789abc','cohort':1,
              'alias':'나눔-0123456789','files':{'SKILL.md':'# 검토\n일반 내용을 확인합니다.'}}
        with mock.patch.object(share, 'request', side_effect=[{'item':item},{'item':item}]) as request, \
             mock.patch.object(share, 'confirm', return_value=True), mock.patch.object(sys, 'stdout', io.StringIO()):
            result=share.main(['--home',str(self.home),'--license-home',str(self.home),'get',item['id']])
        self.assertEqual(result,0)
        self.assertEqual(request.call_count,2)
        self.assertTrue((self.home/'.claude/skills/received/SKILL.md').is_file())
        changed=dict(item,files={'SKILL.md':'# 내용이 바뀜'})
        with mock.patch.object(share,'request',side_effect=[{'item':item},{'item':changed}]), \
             mock.patch.object(share,'confirm',return_value=True), mock.patch.object(sys,'stdout',io.StringIO()), \
             mock.patch.object(sys,'stderr',io.StringIO()):
            self.assertEqual(share.main(['--home',str(self.home),'--license-home',str(self.home),'get',item['id']]),1)

    def test_same_sources_are_packaged_and_unlicensed_cannot_reach_network(self):
        self.assertEqual((ROOT/'course/lib/skill_share.py').read_bytes(),(ROOT/'template/lib/skill_share.py').read_bytes())
        with mock.patch.object(share.urllib.request,'build_opener') as opener:
            with self.assertRaises((OSError, ValueError)):
                share.request(self.home,'list')
            opener.assert_not_called()

if __name__ == '__main__':
    unittest.main()
