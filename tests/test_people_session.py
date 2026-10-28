"""Separate CLI process → authenticated manager → shared employee record, without model calls."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
import test_mini_workspace as fixtures

ROOT = fixtures.ROOT
spec = importlib.util.spec_from_file_location('people_cli', ROOT/'template/lib/people-cli.py')
cli = importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


class PollingTests(unittest.TestCase):
    def test_jobs_initial_and_visible_loading_recovery(self):
        result = subprocess.run(['node', str(ROOT/'tests/people_jobs_loading_check.js'), str(ROOT/'template/web/people.js')], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_polling_lifecycle(self):
        result = subprocess.run(['node', str(ROOT/'tests/people_poll_check.js'), str(ROOT/'template/web/people.js')], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class SessionPeopleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkspaceHTTPTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home = self.fixture.home
        shutil.copytree(ROOT/'template/lib', self.home/'lib')
        self.config = self.home/'state/web-admin/config.json'
        self.write_private(self.config, json.dumps({'version': 1, 'port': self.fixture.server.server_port}))
        self.request = 'registration-request-0001'

    @staticmethod
    def write_private(path, value, mode=0o600):
        path.unlink(missing_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, mode), 'w') as f:f.write(value)

    def run_cli(self, *args, home=None):
        result = subprocess.run(['bash', str(ROOT/'ilson'), 'people', *args],
                                env={**os.environ, 'ILSON_HOME': str(home or self.home)}, capture_output=True, text=True, timeout=12)
        self.assertNotIn(self.fixture.token, result.stdout + result.stderr)
        return result

    def add(self, request=None, **kwargs):
        return self.run_cli('add', '--name', '회의 담당', '--role', '회의 기록 작성',
                            '--request-id', request or self.request, **kwargs)

    def state(self):
        status, _, data = self.fixture.call('GET', '/api/workspace/people', headers={'Cookie': self.fixture.cookie})
        self.assertEqual(status, 200);return data

    def test_separate_cli_and_authenticated_api_same_id_and_retry(self):
        first = self.add();self.assertEqual(first.returncode, 0, first.stderr)
        employee = json.loads(first.stdout)
        self.assertTrue(employee['ok']);self.assertEqual(self.state()['employees'][0]['id'], employee['id'])
        second = json.loads(self.add().stdout)
        self.assertEqual(second['id'], employee['id']);self.assertTrue(second['replayed'])
        self.assertEqual(len(self.state()['employees']), 1)
        self.assertEqual(json.loads(self.run_cli('get', employee['id']).stdout)['id'], employee['id'])
        self.assertEqual(len(self.fixture.server.box.sessions), 1)  # CLI sessions logged out

    def test_concurrent_retries_and_same_names_separate_intent(self):
        with ThreadPoolExecutor(max_workers=4) as pool:results = list(pool.map(lambda _: self.add(), range(4)))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual(len({json.loads(r.stdout)['id'] for r in results}), 1)
        self.assertEqual(self.add('different-request-0002').returncode, 0)
        self.assertEqual(len(self.state()['employees']), 2)

    def test_retry_after_admin_edit_does_not_overwrite_and_changed_payload_conflicts(self):
        result = json.loads(self.add().stdout);work = self.fixture.server.box.workspace()
        work.people.save('employees', {'id': result['id'], 'name': '수정된 이름', 'role': '수정된 역할'})
        retried = json.loads(self.add().stdout)
        self.assertEqual(retried['employee']['name'], '수정된 이름')
        conflict = self.run_cli('add', '--name', '다른 내용', '--role', '역할', '--request-id', self.request)
        self.assertNotEqual(conflict.returncode, 0)
        work.people.delete('employees', result['id'])
        self.assertNotEqual(self.add().returncode, 0)
        self.assertEqual(self.state()['employees'], [])

    def test_missing_required_fields_invalid_department_and_permissions(self):
        for args in [('add', '--name', '이름'), ('add', '--name', '', '--role', '역할', '--request-id', self.request),
                     ('add', '--name', '이름', '--role', '역할', '--request-id', self.request, '--department-id', 'f'*32)]:
            self.assertNotEqual(self.run_cli(*args).returncode, 0)
        self.write_private(self.home/'state/web-admin/token', self.fixture.token, 0o644)
        result = self.add();self.assertNotEqual(result.returncode, 0);self.assertIn('현재 사용자만', result.stderr)
        self.assertEqual(self.state()['employees'], [])

    def test_server_down_wrong_box_and_expired_session(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0));unused = sock.getsockname()[1]
        self.write_private(self.config, json.dumps({'version': 1, 'port': unused}))
        self.assertNotEqual(self.add().returncode, 0)
        self.write_private(self.config, json.dumps({'version': 1, 'port': self.fixture.server.server_port}))
        self.write_private(self.home/'state/web-admin/instance', 'x'*32)
        self.assertNotEqual(self.add().returncode, 0)
        self.write_private(self.home/'state/web-admin/instance', self.fixture.server.box.instance)
        with patch.object(self.fixture.server.box, 'authenticated', return_value=False):
            result = self.add();self.assertNotEqual(result.returncode, 0);self.assertIn('만료', result.stderr)
        self.assertEqual(self.state()['employees'], [])

    def test_spaces_korean_box_path_and_no_default_box_fallback(self):
        other = self.home/'다른 박스 공백';other.mkdir()
        shutil.copytree(self.home/'lib', other/'lib');shutil.copytree(self.home/'state', other/'state')
        # The instance identifies the server's real box, not a copied path. Bind config to Box path below.
        result = self.add(home=other)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()['employees'], [])
        server = fixtures.admin.Server(fixtures.admin.Box(other), 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True);worker.start()
        self.write_private(other/'state/web-admin/config.json', json.dumps({'version': 1, 'port': server.server_port}))
        try:
            registered = self.add(home=other)
            self.assertEqual(registered.returncode, 0, registered.stderr)
            self.assertEqual(server.box.workspace().people.state()['employees'][0]['id'], json.loads(registered.stdout)['id'])
            self.assertEqual(self.state()['employees'], [])
        finally:
            server.shutdown();server.server_close();worker.join()
            if server.box._workspace:server.box._workspace.close()

    def test_symlink_wrong_owner_and_redirect_rejected(self):
        token = self.home/'state/web-admin/token';saved = token.with_name('saved-token')
        token.rename(saved);token.symlink_to(saved)
        self.assertNotEqual(self.add().returncode, 0)
        token.unlink();saved.rename(token)
        real = os.fstat
        def wrong_owner(fd):
            info = list(real(fd));info[4] = os.getuid() + 1
            return os.stat_result(info)
        with patch.object(cli.os, 'fstat', side_effect=wrong_owner):
            with self.assertRaises(cli.PeopleError):cli.private_text(self.home, 'token')
        from unittest.mock import Mock
        connection = Mock();response = connection.getresponse.return_value
        response.status = 302;response.read.return_value = b'raw secret error'
        client = cli.Client.__new__(cli.Client);client.port = 18700;client.origin = 'http://127.0.0.1:18700';client.cookie = ''
        with patch.object(cli, 'HTTPConnection', return_value=connection):
            with self.assertRaises(cli.PeopleError) as error:client.call('GET', '/api/health')
        self.assertNotIn('secret', str(error.exception));self.assertEqual(connection.request.call_count, 1)

    def test_optimistic_edit_preserves_concurrent_admin_change(self):
        key = json.loads(self.add().stdout)['id'];people = self.fixture.server.box.workspace().people
        original = people.row('employees', key)
        people.save('employees', {'id': key, 'name': '다른 관리자', 'role': '새 역할'})
        with self.assertRaisesRegex(Exception, '다른 곳에서 수정'):
            people.save('employees', {'id': key, 'name': '오래된 폼', 'role': '역할', 'expected': original})
        self.assertEqual(people.row('employees', key)['name'], '다른 관리자')

    def test_failed_transaction_does_not_claim_request_id(self):
        people = self.fixture.server.box.workspace().people
        data = {'name': '담당', 'role': '문서', 'request_id': self.request}
        with patch.object(people.work, 'record', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):people.save('employees', data)
        self.assertEqual(people.state()['employees'], [])
        self.assertEqual(people.db.execute('SELECT count(*) FROM people_requests').fetchone()[0], 0)
        self.assertIn('id', people.save('employees', data))


if __name__ == '__main__':unittest.main()
