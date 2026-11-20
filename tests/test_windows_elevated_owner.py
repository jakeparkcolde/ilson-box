"""Elevated ("관리자") Windows sessions: owner claim, repair and clear failure messages.

Real-device defect D1/D1-b (2026-11-20): files an elevated token creates are owned by
BUILTIN\\Administrators, so the user-only owner check rejected them and the course admin never
started; mkdir(0o700) folders left by an elevated install excluded the user entirely.

Real NTFS ACLs cannot run on this Mac. These tests check (1) the Python decisions with the
ACL call mocked and (2) the PowerShell decision and tree-walk logic under pwsh with the ACL
cmdlets replaced by an in-memory model. Neither proves the behaviour on Windows itself.
"""
import base64
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/lib'))
import ilson_platform as platform
import course_admin as launch
from course_bundle import sources

PWSH = shutil.which('pwsh')
ME, BA, SY, OTHER = 'S-1-5-21-1-2-3-1001', 'S-1-5-32-544', 'S-1-5-18', 'S-1-5-21-9-9-9-2002'
HINT = 'ELEVATED-HINT-FIXTURE'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


course_license = load('course_license_elevated', ROOT / 'course/lib/license.py')
payload = load('course_payload_elevated', ROOT / 'course/install_payload.py')
server = load('course_server_elevated', ROOT / 'template/lib/web-admin-server.py')
diag = load('course_diag_elevated', ROOT / 'template/lib/install_diagnostics.py')


class ElevatedOwnerError(ValueError):
    def __init__(self): super().__init__('ELEVATED_OWNER')


def fake_license(acl=None, tree=None):
    return SimpleNamespace(windows_acl=acl or Mock(), windows_tree=tree or Mock(), ELEVATED_OWNER_HINT=HINT)


def nt_os():
    proxy = SimpleNamespace(**{key: getattr(os, key) for key in dir(os) if not key.startswith('__')})
    proxy.name = 'nt'
    return proxy


class PlatformClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def windows(self, acl):
        native = SimpleNamespace(LK_NBLCK=9, locking=Mock())
        return [patch.object(platform, 'IS_WINDOWS', True), patch.dict(sys.modules, license=fake_license(acl), msvcrt=native)]

    def run_patched(self, patches, body):
        for item in patches: item.start(); self.addCleanup(item.stop)
        return body()

    def test_atomic_write_claims_the_temporary_file_before_any_byte(self):
        seen = []
        def acl(path, create=False):
            seen.append((Path(path).name.startswith('.admin-'), create, Path(path).stat().st_size))
        self.run_patched(self.windows(Mock(side_effect=acl)), lambda: platform.atomic_write(self.root / 'token', b'secret-value'))
        self.assertEqual(seen, [(True, True, 0)])
        self.assertEqual((self.root / 'token').read_bytes(), b'secret-value')
        self.assertEqual([p.name for p in self.root.iterdir()], ['token'])

    def test_failed_claim_leaves_no_file_and_no_temporary(self):
        acl = Mock(side_effect=ValueError('STORAGE_ERROR'))
        with self.assertRaises(platform.AccessProblem):
            self.run_patched(self.windows(acl), lambda: platform.atomic_write(self.root / 'token', b'x'))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_new_lock_and_log_are_claimed_once_existing_ones_are_not(self):
        acl = Mock()
        def body():
            fd = platform.acquire_lock(self.root / 'server.lock'); os.close(fd)
            fd = platform.acquire_lock(self.root / 'server.lock'); os.close(fd)
            fd = platform.open_private(self.root / 'stderr.log', os.O_WRONLY | os.O_APPEND); os.close(fd)
            fd = platform.open_private(self.root / 'stderr.log', os.O_WRONLY | os.O_APPEND); os.close(fd)
        self.run_patched(self.windows(acl), body)
        self.assertEqual([c.args[0].name for c in acl.call_args_list], ['server.lock', 'stderr.log'])
        self.assertTrue(all(c.kwargs == {'create': True} for c in acl.call_args_list))

    def test_posix_lock_and_atomic_write_never_call_the_windows_helper(self):
        acl = Mock()
        with patch.object(platform, 'IS_WINDOWS', False), patch.dict(sys.modules, license=fake_license(acl)):
            os.close(platform.acquire_lock(self.root / 'server.lock'))
            platform.atomic_write(self.root / 'token', b'x')
        acl.assert_not_called()
        self.assertEqual(os.stat(self.root / 'server.lock').st_mode & 0o777, 0o600)

    def test_private_read_reports_elevated_and_other_acl_failures_distinctly(self):
        (self.root / 'token').write_text('fixture')
        for error, elevated in ((ElevatedOwnerError(), True), (ValueError('STORAGE_ERROR'), False)):
            with self.subTest(elevated=elevated):
                patches = self.windows(Mock(side_effect=error))
                for item in patches: item.start()
                try:
                    with self.assertRaises(platform.AccessProblem) as caught:
                        platform.WindowsFiles(self.root).text('token', 100, private=True)
                finally:
                    for item in reversed(patches): item.stop()
                self.assertIs(caught.exception.elevated, elevated)
                self.assertIsInstance(caught.exception, platform.Unreadable)
                with self.assertRaises(platform.AccessProblem):
                    patches = self.windows(Mock(side_effect=error))
                    for item in patches: item.start()
                    try: platform.private_dir(self.root)
                    finally:
                        for item in reversed(patches): item.stop()

    def test_posix_private_read_is_an_access_problem_not_a_generic_failure(self):
        token = self.root / 'token'; token.write_text('fixture'); token.chmod(0o644)
        with self.assertRaises(platform.AccessProblem) as caught:
            platform.PosixFiles(self.root).text('token', 100, private=True)
        self.assertFalse(caught.exception.elevated)


class CourseAdminRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name).resolve()

    def test_windows_regenerates_unverifiable_values_only_without_a_running_server(self):
        problem = platform.AccessProblem('x', elevated=True)
        with patch.object(platform, 'IS_WINDOWS', True), patch.object(launch, 'read', side_effect=problem), \
                patch.object(launch, 'locked', return_value=False), patch.object(platform, 'atomic_write') as write:
            launch.prepare(self.private)
        self.assertEqual([c.args[0].name for c in write.call_args_list], ['token', 'instance'])
        self.assertTrue(all(launch.SECRET.fullmatch(c.args[1].decode()) for c in write.call_args_list))
        with patch.object(platform, 'IS_WINDOWS', True), patch.object(launch, 'read', side_effect=problem), \
                patch.object(launch, 'locked', return_value=True), patch.object(platform, 'atomic_write') as write:
            with self.assertRaises(platform.AccessProblem): launch.prepare(self.private)
        write.assert_not_called()

    def test_posix_keeps_the_existing_value_and_refuses(self):
        (self.private / 'token').write_text('a' * 43); (self.private / 'token').chmod(0o644)
        with self.assertRaises(platform.AccessProblem): launch.prepare(self.private)
        self.assertEqual((self.private / 'token').read_text(), 'a' * 43)

    def test_main_names_the_permission_cause_and_the_fix_without_paths(self):
        args = SimpleNamespace(command='start', home=self.private / 'home', vault=self.private, port=None, force=False)
        for elevated, expected in ((True, HINT), (False, 'ilson doctor로 확인해주세요.')):
            with self.subTest(elevated=elevated), patch.dict(sys.modules, license=SimpleNamespace(
                    evaluate=lambda home: (True, 'ACTIVE'), ELEVATED_OWNER_HINT=HINT)), \
                    patch.object(launch, 'start', side_effect=platform.AccessProblem('x', elevated=elevated)), \
                    patch('builtins.print') as output:
                self.assertEqual(launch.main(args), 1)
            text = output.call_args.args[0]
            self.assertIn(launch.PERMISSION_MESSAGE, text); self.assertIn(expected, text)
            self.assertNotIn(str(self.private), text)

    def test_license_elevated_owner_error_keeps_the_hint(self):
        args = SimpleNamespace(command='start', home=self.private / 'home', vault=self.private, port=None, force=False)
        def evaluate(home): raise course_license.ElevatedOwnerError()
        with patch.dict(sys.modules, license=SimpleNamespace(evaluate=evaluate, ELEVATED_OWNER_HINT=HINT)), \
                patch('builtins.print') as output:
            self.assertEqual(launch.main(args), 1)
        self.assertIn(launch.PERMISSION_MESSAGE, output.call_args.args[0]); self.assertIn(HINT, output.call_args.args[0])
        with patch.dict(sys.modules, license=SimpleNamespace(evaluate=Mock(side_effect=ValueError('STORAGE_ERROR')), ELEVATED_OWNER_HINT=HINT)), \
                patch('builtins.print') as output:
            self.assertEqual(launch.main(args), 1)
        self.assertNotIn(HINT, output.call_args.args[0])

    def test_child_exit_codes_map_to_one_cause_each(self):
        with patch.dict(sys.modules, license=SimpleNamespace(ELEVATED_OWNER_HINT=HINT)):
            self.assertEqual(launch.child_failure(launch.EXIT_PORT), launch.PORT_MESSAGE)
            self.assertEqual(launch.child_failure(launch.EXIT_SETTINGS), launch.SETTINGS_MESSAGE)
            self.assertIn(HINT, launch.child_failure(launch.EXIT_ELEVATED))
            self.assertNotIn(HINT, launch.child_failure(launch.EXIT_PERMISSION))
            self.assertIn('ilson doctor', launch.child_failure(1))
        self.assertEqual(len({launch.EXIT_PERMISSION, launch.EXIT_PORT, launch.EXIT_SETTINGS, launch.EXIT_ELEVATED, 1}), 5)


class ServerFailureTests(unittest.TestCase):
    def test_course_failures_are_classified_by_cause(self):
        with patch.dict(sys.modules, license=SimpleNamespace(ELEVATED_OWNER_HINT=HINT)):
            cases = [(server.PortProblem('x'), launch.EXIT_PORT), (server.SettingsProblem('x'), launch.EXIT_SETTINGS),
                     (server.PermissionProblem('x', elevated=True), launch.EXIT_ELEVATED),
                     (server.PermissionProblem('x'), launch.EXIT_PERMISSION),
                     (platform.AccessProblem('x', elevated=True), launch.EXIT_ELEVATED),
                     (PermissionError(13, 'denied', '/secret/path'), launch.EXIT_PERMISSION),
                     (launch.CourseAdminError('관리자 상태는 Documents·OneDrive 밖의 개인 폴더에 보관하세요.'), 1),
                     (OSError('/secret/path'), 1)]
            for error, code in cases:
                with self.subTest(error=type(error).__name__):
                    got, message = server.course_failure(error)
                    self.assertEqual(got, code)
                    self.assertNotIn('/secret', message)
                    self.assertNotIn('연결 설정·파일 권한·사용 중인 포트', message)

    def test_windows_socket_codes_count_as_a_busy_port(self):
        self.assertTrue(server.port_busy(OSError(10048, 'in use')))
        self.assertTrue(server.port_busy(SimpleNamespace(errno=None, winerror=10013)))
        self.assertFalse(server.port_busy(OSError(2, 'missing')))

    def test_real_server_process_reports_settings_and_permission_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); library = root / 'code/lib'
            shutil.copytree(ROOT / 'template/lib', library, ignore=shutil.ignore_patterns('__pycache__', '.*'))
            shutil.copy2(ROOT / 'course/lib/license.py', library / 'license.py')
            home, vault = root / 'home', root / 'vault'; vault.mkdir()
            command = [sys.executable, '-X', 'utf8', str(library / 'web-admin-server.py'), '--home', str(home), '--vault', str(vault),
                       '--profile', 'course', '--port', '0', '--idle-seconds', '5']
            env = dict(os.environ, ILSON_HOME=str(home), ILSON_PROFILE='course')
            first = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            self.assertEqual(first.returncode, launch.EXIT_SETTINGS, first.stderr)
            self.assertIn(launch.SETTINGS_MESSAGE, first.stderr)
            private = home / 'state/web-admin'
            for name, size in (('token', 43), ('instance', 32)):
                (private / name).write_text('a' * size); (private / name).chmod(0o600)
            (private / 'token').chmod(0o644)
            second = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
            self.assertEqual(second.returncode, launch.EXIT_PERMISSION, second.stderr)
            self.assertIn(launch.PERMISSION_MESSAGE, second.stderr)
            for output in (first.stderr, second.stderr):
                self.assertNotIn(str(root), output); self.assertNotIn('a' * 32, output)


class LicenseHelperTests(unittest.TestCase):
    def completed(self, code, out=b''):
        return subprocess.CompletedProcess([], code, stdout=out, stderr=b'')

    def test_exit_codes_and_environment_of_the_private_check(self):
        with patch.object(course_license.subprocess, 'run', return_value=self.completed(0)) as run:
            course_license.windows_acl(Path('C:/x/token'), create=True)
        env = run.call_args.kwargs['env']
        # Absolute, so the elevated route can compare it with the handle's final path.
        self.assertEqual((env['ILSON_ACL_TARGET'], env['ILSON_ACL_CREATE']), (os.path.abspath(str(Path('C:/x/token'))), '1'))
        self.assertEqual(env['ILSON_ACL_CS'], course_license.ACL_HANDLE_CS)
        self.assertEqual(run.call_args.args[0][:4], ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand'])
        with patch.object(course_license.subprocess, 'run', return_value=self.completed(3)):
            with self.assertRaises(course_license.ElevatedOwnerError) as caught: course_license.windows_acl('t')
        self.assertEqual(str(caught.exception), 'ELEVATED_OWNER')
        for failure in (self.completed(1), OSError('no powershell'), subprocess.TimeoutExpired('powershell.exe', 120)):
            with self.subTest(failure=type(failure).__name__):
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(course_license.subprocess, 'run', **kwargs):
                    with self.assertRaises(ValueError) as caught: course_license.windows_acl('t')
                self.assertEqual(str(caught.exception), 'STORAGE_ERROR')
                self.assertNotIsInstance(caught.exception, course_license.ElevatedOwnerError)

    def test_tree_result_is_parsed_strictly(self):
        with patch.object(course_license.subprocess, 'run', return_value=self.completed(0, b'noise\r\nILSON_ACL 7 4 0 1 1 2 1\r\n')) as run:
            counts = course_license.windows_tree([Path('C:/a'), Path('C:/b')], repair=True)
        self.assertEqual(counts, {'checked': 7, 'repaired': 4, 'admin_owned': 0, 'no_access': 1, 'foreign': 1, 'error': 2, 'skipped': 1})
        env = run.call_args.kwargs['env']
        self.assertEqual((env['ILSON_ACL_REPAIR'], env['ILSON_ACL_LIMIT']), ('1', '5000'))
        self.assertEqual(env['ILSON_ACL_ROOTS'].split('\n'), [os.path.abspath(str(Path('C:/a'))), os.path.abspath(str(Path('C:/b')))])
        for out, code in ((b'ILSON_ACL 1 2 3', 0), (b'ILSON_ACL 1 2 3 4 5 6', 0), (b'ILSON_ACL 1 2 3 4 5 6 x', 0),
                          (b'ILSON_ACL 1 2 3 4 5 6 7', 1)):
            with self.subTest(out=out), patch.object(course_license.subprocess, 'run', return_value=self.completed(code, out)):
                with self.assertRaises(ValueError): course_license.windows_tree(['C:/a'])

    def test_scripts_stay_ascii_for_windows_powershell(self):
        course_license.ACL_HANDLE_CS.encode('ascii')
        for script in (course_license.ACL_PRIVATE_PS, course_license.ACL_TREE_PS):
            script.encode('ascii')
            self.assertIn('SetOwner($Me)', script)
            self.assertIn('SetAccessRuleProtection($true, $false)', script)
            # CreateProcess caps the whole command line at 32,767 characters; keep a margin.
            self.assertLess(len(base64.b64encode(script.encode('utf-16le'))), 28000)

    def test_elevated_route_opens_without_following_links_and_sets_security_on_the_handle(self):
        cs = course_license.ACL_HANDLE_CS
        self.assertIn('0x02200000', cs)  # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
        self.assertIn('0xE0080', cs)     # READ_CONTROL | WRITE_DAC | WRITE_OWNER | FILE_READ_ATTRIBUTES
        self.assertIn('SetSecurityInfo(h, 1, info', cs)
        self.assertNotIn('AdjustTokenPrivileges', cs)
        guarded = course_license.ACL_VERDICT_PS.split('$handle = Open-IlsonHandle $Path', 1)[1].split('return $true', 1)[0]
        self.assertNotIn('Set-Acl', guarded); self.assertNotIn('SetAccessControl', guarded)


class InstallPayloadOwnerTests(unittest.TestCase):
    def test_windows_install_repairs_the_install_tree_after_success_failure_and_no_change(self):
        tree = Mock(return_value={'checked': 3, 'repaired': 3, 'admin_owned': 0, 'no_access': 0, 'foreign': 0, 'error': 0, 'skipped': 0})
        with tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', True), \
                patch.object(payload, 'acl_module', return_value=fake_license(tree=tree)), patch('builtins.print') as output:
            root = Path(temp).resolve() / 'ilson-course/lib'; root.mkdir(parents=True)
            self.assertIsNotNone(payload.install(root, sources()))
            self.assertIsNone(payload.install(root, sources()))
            fresh = Path(temp).resolve() / 'other/lib'; fresh.mkdir(parents=True)
            with self.assertRaises(RuntimeError): payload.install(fresh, sources(), verify=Mock(side_effect=RuntimeError('verify')))
            self.assertFalse((fresh / 'ilson.py').exists())
        self.assertEqual(tree.call_args_list[0].args, ([root.parent],))
        self.assertEqual(tree.call_count, 3)
        self.assertEqual(tree.call_args.args, ([fresh.parent],))
        self.assertTrue(all(c.kwargs == {'repair': True} for c in tree.call_args_list))
        self.assertIn('HELPER_PERMISSIONS=ok', [c.args[0] for c in output.call_args_list])

    def test_left_or_unverified_permissions_are_reported_but_do_not_fail_the_install(self):
        cases = ((Mock(return_value={'checked': 3, 'repaired': 0, 'admin_owned': 0, 'no_access': 2, 'foreign': 0, 'error': 0, 'skipped': 0}), 'left'),
                 (Mock(side_effect=ValueError('STORAGE_ERROR')), 'unverified'))
        for tree, state in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', True), \
                    patch.object(payload, 'acl_module', return_value=fake_license(tree=tree)), patch('builtins.print') as output:
                root = Path(temp).resolve() / 'lib'; root.mkdir()
                payload.install(root, sources())
                lines = [c.args[0] for c in output.call_args_list]
                self.assertIn('HELPER_PERMISSIONS=' + state, lines)
                self.assertEqual(HINT in lines, state == 'left')
                self.assertEqual(tree.call_args.args, ([root.parent],))

    def test_failed_install_left_permissions_name_the_installer_rerun(self):
        tree = Mock(return_value={'checked': 3, 'repaired': 0, 'admin_owned': 0, 'no_access': 2, 'foreign': 0, 'error': 0, 'skipped': 0})
        with tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', True), \
                patch.object(payload, 'acl_module', return_value=fake_license(tree=tree)), patch('builtins.print') as output:
            root = Path(temp).resolve() / 'lib'; root.mkdir()
            with self.assertRaises(RuntimeError): payload.install(root, sources(), verify=Mock(side_effect=RuntimeError('verify')))
        lines = [c.args[0] for c in output.call_args_list]
        self.assertIn('HELPER_PERMISSIONS=left', lines)
        self.assertIn(payload.RERUN_ELEVATED_HINT, lines)
        self.assertNotIn(HINT, lines)

    def test_posix_install_never_runs_the_windows_repair(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', False), \
                patch.object(payload, 'acl_module') as module:
            root = Path(temp).resolve() / 'lib'; root.mkdir()
            payload.install(root, sources())
        module.assert_not_called()

    def test_bundle_acl_module_is_the_license_being_installed(self):
        module = payload.acl_module(sources())
        self.assertTrue(callable(module.windows_tree))
        self.assertIn('fix-permissions', module.ELEVATED_OWNER_HINT)

    def test_permission_denied_on_windows_prints_the_fix_and_exits_3(self):
        stream = SimpleNamespace(buffer=io.BytesIO(base64.b64encode(gzip.compress(json.dumps(sources()).encode()))))
        with patch.object(payload.sys, 'argv', ['install_payload.py', 'C:/lib']), patch.object(payload.sys, 'stdin', stream), \
                patch.object(payload, 'install', side_effect=PermissionError(13, 'denied')), patch.object(payload, 'IS_WINDOWS', True), \
                patch('builtins.print') as output:
            with self.assertRaises(SystemExit) as caught: payload.main()
        self.assertEqual(caught.exception.code, 3)
        line = output.call_args.args[0]
        self.assertTrue(line.startswith('HELPER_PERMISSION_DENIED: '))
        # The helper left in place may predate --fix-permissions: name the elevated installer rerun.
        self.assertNotIn('fix-permissions', line)
        self.assertIn('「관리자: Windows PowerShell」', line)
        self.assertIn(payload.WINDOWS_INSTALL_COMMAND, line)
        self.assertIn(payload.WINDOWS_INSTALL_COMMAND, (ROOT / 'README.md').read_text(encoding='utf-8'))
        stream.buffer.seek(0)
        with patch.object(payload.sys, 'argv', ['install_payload.py', 'C:/lib']), patch.object(payload.sys, 'stdin', stream), \
                patch.object(payload, 'install', side_effect=PermissionError(13, 'denied')), patch.object(payload, 'IS_WINDOWS', False):
            with self.assertRaises(PermissionError): payload.main()


class PublicBuildUpgradeTests(unittest.TestCase):
    PUBLIC = 'e67f806'  # student public build v2026.11.14.1

    def test_exact_public_windows_bundle_upgrades_and_rolls_back(self):
        try:
            installer = subprocess.check_output(['git', 'show', self.PUBLIC + ':course/install-windows.ps1'], cwd=ROOT, text=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('public build commit not available in this clone')
        encoded = installer.split("$CoursePayload='", 1)[1].split("'", 1)[0]
        public = json.loads(gzip.decompress(base64.b64decode(encoded)))
        with tempfile.TemporaryDirectory() as temp, patch('builtins.print'):
            root = Path(temp).resolve() / 'ilson-course/lib'; root.mkdir(parents=True)
            for name, text in public.items():
                path = root.parent / name if name.startswith('web/') else root / name
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')
            before = {p.relative_to(root.parent): p.read_bytes() for p in root.parent.rglob('*') if p.is_file()}
            backup = payload.install(root, sources())
            self.assertIsNotNone(backup)
            for name, text in sources().items():
                self.assertEqual((root.parent / name if name.startswith('web/') else root / name).read_text(encoding='utf-8'), text)
            payload.rollback(root, backup)
            after = {p.relative_to(root.parent): p.read_bytes() for p in root.parent.rglob('*')
                     if p.is_file() and '.install-backups' not in p.parts and p.name != '.install.lock'}
            self.assertEqual(after, before)


class DoctorPermissionTests(unittest.TestCase):
    def counts(self, **values):
        base = {'checked': 9, 'repaired': 0, 'admin_owned': 0, 'no_access': 0, 'foreign': 0, 'error': 0, 'skipped': 0}
        base.update(values); return base

    def test_states_lines_and_roots(self):
        tree = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'os', nt_os()), \
                patch.dict(os.environ, {'LOCALAPPDATA': temp, 'ILSON_COURSE_STATE': str(Path(temp) / 'state')}), \
                patch.dict(sys.modules, license=fake_license(tree=tree)):
            for values, state in (({}, 'ok'), ({'admin_owned': 4}, 'elevated_owner'), ({'no_access': 2, 'admin_owned': 1}, 'needs_admin'),
                                  ({'foreign': 1}, 'foreign'), ({'error': 2, 'skipped': 1}, 'incomplete')):
                with self.subTest(state=state):
                    tree.return_value = self.counts(**values)
                    value = diag.windows_permissions()
                    self.assertEqual(value['state'], state)
                    lines = diag.permission_lines(value)
                    self.assertEqual(bool(lines), state != 'ok')
                    if state in ('elevated_owner', 'needs_admin'): self.assertIn('ilson doctor --fix-permissions', lines[0])
                    if state == 'needs_admin': self.assertIn('관리자: Windows PowerShell', lines[0])
                    if state == 'incomplete':
                        self.assertNotIn('관리자', lines[0]); self.assertNotIn('강사', lines[0])
                        self.assertEqual((value['error'], value['skipped']), (2, 1))
                    for line in lines: self.assertNotIn(temp, line)
            self.assertEqual(tree.call_args.args[0], [Path(temp) / 'ilson-course', Path(temp) / 'state'])
            self.assertEqual(tree.call_args.kwargs, {'repair': False})
            tree.side_effect = ValueError('STORAGE_ERROR')
            self.assertEqual(diag.windows_permissions(), {'state': 'unknown'})
        self.assertEqual(diag.windows_permissions(), {'state': 'unverified'})

    def test_fix_permissions_repairs_and_reports_exit_codes(self):
        tree = Mock()
        with tempfile.TemporaryDirectory() as temp, patch.object(diag, 'os', nt_os()), patch.dict(os.environ, {'LOCALAPPDATA': temp}), \
                patch.dict(sys.modules, license=fake_license(tree=tree)), patch('builtins.print') as output:
            tree.return_value = self.counts(repaired=5)
            self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 0)
            self.assertEqual(tree.call_args.kwargs, {'repair': True})
            self.assertIn('사용자 소유로 돌린 항목 5개', output.call_args_list[0].args[0])
            tree.return_value = self.counts(repaired=1, no_access=1)
            self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 1)
            tree.side_effect = ValueError('STORAGE_ERROR')
            self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 3)
        with patch('builtins.print'): self.assertEqual(diag.main(['--fix-permissions']), 0)

    def test_course_cli_routes_fix_permissions_without_the_usage_tick(self):
        cli = load('course_cli_elevated', ROOT / 'course/ilson.py')
        with patch.object(cli.subprocess, 'Popen') as popen, patch('builtins.print') as output:
            self.assertEqual(cli.main(['doctor', '--fix-permissions']), 0)
        popen.assert_not_called()
        self.assertIn('Windows', output.call_args.args[0])


def ps_literal(value):
    return "'" + value.replace("'", "''") + "'"


@unittest.skipUnless(PWSH, 'pwsh required to run the PowerShell ACL logic')
class PowerShellAclLogicTests(unittest.TestCase):
    """The real script text with the ACL cmdlets replaced by an in-memory model."""
    IDENTITY = '[Security.Principal.WindowsIdentity]::GetCurrent().User'
    STUBS = r'''
$global:M = @{}
foreach ($e in @(ConvertFrom-Json $env:ACL_MODEL)) { $global:M[$e.path] = $e }
$global:StubMe = [pscustomobject]@{ Value = $env:ACL_ME }
function Test-Path { param([string]$LiteralPath) return $global:M.ContainsKey($LiteralPath) }
function Get-Item { param([string]$LiteralPath, [switch]$Force)
    $o = $global:M[$LiteralPath]
    if (-not $o) { throw (New-Object Management.Automation.ItemNotFoundException 'gone') }
    $attributes = [IO.FileAttributes]::Normal
    if ($o.reparse) { $attributes = [IO.FileAttributes]::ReparsePoint }
    $item = [pscustomobject]@{ FullName = $LiteralPath; PSIsContainer = [bool]$o.dir; Attributes = $attributes }
    $item | Add-Member ScriptMethod GetAccessControl { param($sections)
        $x = [pscustomobject]@{ P = $this.FullName; Owner = $null }
        $x | Add-Member ScriptMethod SetOwner { param($sid) $this.Owner = $sid.Value }
        return $x }
    $item | Add-Member ScriptMethod SetAccessControl { param($x)
        if ($global:M[$x.P].denyset) { throw (New-Object UnauthorizedAccessException 'denied') }
        $global:M[$x.P].owner = $x.Owner; [Console]::Out.WriteLine('ACT owner:' + $x.P) }
    return $item
}
function Get-Acl { param([string]$LiteralPath)
    $o = $global:M[$LiteralPath]
    if ($o.denied) { throw (New-Object UnauthorizedAccessException 'denied') }
    if ($o.busy) { throw (New-Object IO.IOException 'sharing violation') }
    $acl = [pscustomobject]@{ O = $o.owner; R = @($o.rules); AreAccessRulesProtected = [bool]$o.protected }
    $acl | Add-Member ScriptMethod GetOwner { param($t) if ($this.O) { return [pscustomobject]@{ Value = $this.O } } return $null }
    $acl | Add-Member ScriptMethod GetAccessRules { param($a, $b, $t)
        foreach ($r in $this.R) {
            $type = 'Deny'; if ($r.allow) { $type = 'Allow' }
            [pscustomobject]@{ IdentityReference = [pscustomobject]@{ Value = $r.sid }; AccessControlType = $type } } }
    return $acl
}
function New-IlsonPrivateAcl($Item, $Me) { return [pscustomobject]@{ Me = $Me.Value } }
function Set-ModelPrivate([string]$Path, [string]$Me) {
    $o = $global:M[$Path]
    if ($o.denyset) { throw (New-Object UnauthorizedAccessException 'denied') }
    $o.owner = $Me; $o.protected = $true; $o.rules = @([pscustomobject]@{ sid = $Me; allow = $true })
    foreach ($c in @($o.children)) { $child = $global:M[$c]; if ($child -and -not $child.protected) { $child.rules = @([pscustomobject]@{ sid = $Me; allow = $true }) } }
}
function Set-Acl { param([string]$LiteralPath, $AclObject)
    Set-ModelPrivate $LiteralPath $AclObject.Me
    [Console]::Out.WriteLine('ACT private:' + $LiteralPath)
}
function Get-ChildItem { param([string]$LiteralPath, [switch]$Force)
    foreach ($c in @($global:M[$LiteralPath].children)) { [pscustomobject]@{ FullName = $c } } }
# Elevated (guarded) route: the handle layer is modelled per node. h* fields describe what the
# handle sees when it differs from the path read: a swapped path (hfinal), a reparse point
# planted after Get-Item (hreparse), ACL changed in between (howner/hrules); links = hard links.
function Test-IlsonGuarded { return $env:ACL_GUARDED -eq '1' }
function Open-IlsonHandle([string]$Path) {
    if (-not $global:M.ContainsKey($Path)) { throw (New-Object IO.IOException 'gone') }
    if ($global:M[$Path].denied) { throw (New-Object UnauthorizedAccessException 'denied') }
    if ($Path -eq $env:ACL_VANISH) { throw (New-Object IO.FileNotFoundException 'gone') }
    [Console]::Out.WriteLine('OPEN ' + $Path)
    return [pscustomobject]@{ P = $Path }
}
function Close-IlsonHandle($Handle) { [Console]::Out.WriteLine('CLOSE ' + $Handle.P) }
function Get-IlsonHandleState($Handle, [bool]$Container) {
    $o = $global:M[$Handle.P]
    $final = $Handle.P; if ($o.hfinal) { $final = $o.hfinal }
    $owner = $o.owner; if ($o.howner) { $owner = $o.howner }
    $rules = @($o.rules); if ($o.hrules) { $rules = @($o.hrules) }
    return @{ Reparse = [bool]($o.reparse -or $o.hreparse); Links = [int]$o.links; Final = '\\?\' + $final
              Facts = @{ Owner = $owner; Rules = $rules; Protected = [bool]$o.protected } }
}
function Set-IlsonHandleSecurity($Handle, $Me, $Acl) {
    if ($Acl) { Set-ModelPrivate $Handle.P $Acl.Me; [Console]::Out.WriteLine('ACT hprivate:' + $Handle.P); return }
    $global:M[$Handle.P].owner = $Me.Value; [Console]::Out.WriteLine('ACT howner:' + $Handle.P)
}
'''

    def node(self, path, owner, rules, dir=False, protected=False, children=(), **flags):
        value = {'path': path, 'owner': owner, 'rules': [{'sid': s, 'allow': a} for s, a in rules], 'dir': dir,
                 'protected': protected, 'children': list(children), 'reparse': False, 'denied': False, 'denyset': False,
                 'busy': False, 'links': 1}
        if 'hrules' in flags: flags['hrules'] = [{'sid': s, 'allow': a} for s, a in flags['hrules']]
        value.update(flags); return value

    def run_script(self, script, model, **env):
        logic = script.split(course_license.ACL_VERDICT_PS, 1)[1]
        self.assertIn(self.IDENTITY, logic)
        body = course_license.ACL_VERDICT_PS + self.STUBS + logic.replace(self.IDENTITY, '$global:StubMe')
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True,
                                timeout=60, stdin=subprocess.DEVNULL,
                                env=dict(os.environ, ACL_MODEL=json.dumps(model), ACL_ME=ME, **env))
        lines = result.stdout.splitlines()
        result.actions = [line[4:] for line in lines if line.startswith('ACT ')]
        # Every handle the guarded route opens is closed again, whatever it decided.
        self.assertEqual(sorted(l[5:] for l in lines if l.startswith('OPEN ')), sorted(l[6:] for l in lines if l.startswith('CLOSE ')))
        result.opened = [l[5:] for l in lines if l.startswith('OPEN ')]
        return result

    def test_scripts_parse_without_errors(self):
        for script in (course_license.ACL_PRIVATE_PS, course_license.ACL_TREE_PS):
            check = '$e=$null; [void][Management.Automation.Language.Parser]::ParseInput($env:S,[ref]$null,[ref]$e); $e.Count'
            result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', check], capture_output=True, text=True,
                                    timeout=60, stdin=subprocess.DEVNULL, env=dict(os.environ, S=script))
            self.assertEqual(result.stdout.strip(), '0', result.stderr)

    def test_verdict_table(self):
        cases = [
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true}) '%s'" % (ME, ME, ME), 'ok'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true}) '%s'" % (BA, ME, ME), 'repair'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true},@{Sid='S-1-3-4';Allow=$true}) '%s'" % (BA, SY, BA, ME), 'repair'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true}) '%s'" % (OTHER, ME, ME), 'foreign'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='S-1-1-0';Allow=$true}) '%s'" % (BA, ME, ME), 'foreign'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$false}) '%s'" % (BA, SY, ME), 'foreign'),
            ("Get-IlsonPrivateVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true}) '%s'" % (ME, ME, SY, ME), 'repair'),
            ("Get-IlsonPrivateVerdict '' @() '%s'" % ME, 'denied'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='S-1-1-0';Allow=$true}) '%s' $false" % (ME, ME, ME), 'ok'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true}) '%s' $false" % (BA, ME, SY, BA, ME), 'fix-owner'),
            # S1: an Administrators-owned object with a foreign grant or any Deny entry is left alone.
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='S-1-5-32-545';Allow=$true}) '%s' $false" % (BA, ME, ME), 'foreign'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$false},@{Sid='S-1-1-0';Allow=$true}) '%s' $false" % (BA, ME, ME), 'foreign'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$false}) '%s' $false" % (BA, ME, SY, ME), 'foreign'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true}) '%s' $false" % (BA, ME, OTHER, ME), 'foreign'),
            # S2: Python 3.13+ mkdir(0o700) in a normal window (CPython SDDL D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)).
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true},@{Sid='S-1-3-4';Allow=$true}) '%s' $true" % (ME, SY, BA, ME), 'ok'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true},@{Sid='S-1-3-4';Allow=$true}) '%s' $false" % (ME, SY, BA, ME), 'ok'),
            # OWNER RIGHTS grants the owner, so under an Administrators owner the user still has no entry.
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true},@{Sid='S-1-3-4';Allow=$true}) '%s' $true" % (BA, SY, BA, ME), 'fix-private'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true},@{Sid='%s';Allow=$true}) '%s' $true" % (BA, SY, BA, ME), 'fix-private'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='S-1-5-32-545';Allow=$true}) '%s' $true" % (BA, ME), 'foreign'),
            ("Get-IlsonTreeVerdict '%s' @(@{Sid='%s';Allow=$true}) '%s' $false" % (OTHER, ME, ME), 'foreign'),
        ]
        body = course_license.ACL_VERDICT_PS + '\n' + '\n'.join(case for case, _ in cases)
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True,
                                timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(result.stdout.split(), [expected for _, expected in cases], result.stderr)

    def test_private_check_repairs_elevated_files_and_refuses_the_rest(self):
        target = 'C:\\state\\web-admin\\token'
        cases = [
            (dict(owner=BA, rules=[(ME, True)]), '0', ['private:' + target]),
            (dict(owner=ME, rules=[(ME, True)]), '0', []),
            (dict(owner=OTHER, rules=[(ME, True)]), '1', []),
            (dict(owner=BA, rules=[(ME, True), ('S-1-1-0', True)]), '1', []),
            (dict(owner=BA, rules=[(ME, True)], denied=True), '3', []),
            (dict(owner=BA, rules=[(ME, True)], denyset=True), '3', []),
            (dict(owner=ME, rules=[(ME, True)], reparse=True), '1', []),
        ]
        for values, code, log in cases:
            with self.subTest(values=values):
                values = dict(values); owner, rules = values.pop('owner'), values.pop('rules')
                result = self.run_script(course_license.ACL_PRIVATE_PS, [self.node(target, owner, rules, **values)],
                                         ILSON_ACL_TARGET=target, ILSON_ACL_CREATE='0')
                self.assertEqual(str(result.returncode), code, result.stderr)
                self.assertEqual(result.actions, log)
        result = self.run_script(course_license.ACL_PRIVATE_PS, [self.node(target, OTHER, [(OTHER, True)])],
                                 ILSON_ACL_TARGET=target, ILSON_ACL_CREATE='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.actions, ['private:' + target])

    def model(self):
        r, inherit = 'C:\\ilson-course', [(ME, True), (SY, True), (BA, True)]
        return r, [
            self.node(r, BA, inherit, dir=True, children=[r + '\\lib', r + '\\web', r + '\\link', r + '\\other', r + '\\denied', r + '\\gone']),
            self.node(r + '\\lib', ME, inherit, dir=True, children=[r + '\\lib\\a.py']),
            self.node(r + '\\lib\\a.py', BA, inherit),
            # Python 3.13+ mkdir(0o700) in an elevated window: protected, no user entry.
            self.node(r + '\\web', BA, [(SY, True), (BA, True), ('S-1-3-4', True)], dir=True, protected=True, children=[r + '\\web\\course.html']),
            self.node(r + '\\web\\course.html', BA, [(SY, True), (BA, True)]),
            self.node(r + '\\link', ME, inherit, dir=True, reparse=True, children=[r + '\\lib']),
            self.node(r + '\\other', OTHER, [(OTHER, True)], dir=True, children=[r + '\\other\\x']),
            self.node(r + '\\other\\x', BA, inherit),
            self.node(r + '\\denied', BA, inherit, denied=True),
        ]

    def test_tree_repair_fixes_parents_before_children_and_never_touches_foreign_or_links(self):
        root, model = self.model()
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        # checked repaired admin no_access foreign skipped
        self.assertIn('ILSON_ACL 7 4 0 1 1 0 2', lines)
        self.assertEqual(result.opened, [])  # a normal window never takes the handle route
        log = result.actions
        self.assertEqual(sorted(log), sorted(['owner:' + root, 'owner:' + root + '\\lib\\a.py', 'private:' + root + '\\web',
                                              'owner:' + root + '\\web\\course.html']))
        self.assertLess(log.index('private:' + root + '\\web'), log.index('owner:' + root + '\\web\\course.html'))
        self.assertFalse(any('other' in entry or 'link' in entry for entry in log))

    def test_tree_scan_changes_nothing_and_respects_the_limit(self):
        root, model = self.model()
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000')
        self.assertIn('ILSON_ACL 7 0 4 1 1 0 2', result.stdout.splitlines(), result.stderr)
        self.assertEqual(result.actions, [])
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='2')
        counts = next(line for line in result.stdout.splitlines() if line.startswith('ILSON_ACL ')).split()[1:]
        self.assertEqual(counts[0], '2')
        self.assertGreater(int(counts[6]), 0)
        root, model = self.model(); model[1]['busy'] = True  # lib: sharing violation, not a permission verdict
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000')
        self.assertIn('ILSON_ACL 6 0 3 1 1 1 2', result.stdout.splitlines(), result.stderr)

    def tree(self, model, root, guarded):
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='1',
                                 ILSON_ACL_LIMIT='5000', ACL_GUARDED='1' if guarded else '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        result.counts = next(line for line in result.stdout.splitlines() if line.startswith('ILSON_ACL ')).split()[1:]
        return result

    def test_normal_window_python_private_folders_count_as_the_users_own(self):
        r = 'C:\\state'
        model = [self.node(r, ME, [(ME, True), (SY, True), (BA, True)], dir=True, children=[r + '\\usage-timeline']),
                 self.node(r + '\\usage-timeline', ME, [(SY, True), (BA, True), ('S-1-3-4', True)], dir=True, protected=True,
                           children=[r + '\\usage-timeline\\2026-11.json']),
                 self.node(r + '\\usage-timeline\\2026-11.json', ME, [(SY, True), (BA, True), ('S-1-3-4', True)])]
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=r, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000')
        self.assertIn('ILSON_ACL 3 0 0 0 0 0 0', result.stdout.splitlines(), result.stderr)
        for guarded in (False, True):
            self.assertEqual((self.tree(model, r, guarded).actions), [])

    def test_foreign_grant_or_deny_on_an_administrators_object_is_left_alone(self):
        r = 'C:\\ilson-course'
        for rules in ([(ME, True), ('S-1-5-32-545', True)], [(ME, True), ('S-1-1-0', False)], [(ME, False), (SY, True)]):
            model = [self.node(r, ME, [(ME, True)], dir=True, children=[r + '\\x']), self.node(r + '\\x', BA, rules)]
            for guarded in (False, True):
                with self.subTest(rules=rules, guarded=guarded):
                    result = self.tree(model, r, guarded)
                    self.assertEqual(result.actions, [])
                    self.assertEqual(result.counts, ['2', '0', '0', '0', '1', '0', '0'])

    def test_elevated_repair_acts_on_the_handle_and_matches_the_normal_route(self):
        root, model = self.model()
        result = self.tree(model, root, True)
        self.assertEqual(result.counts, ['7', '4', '0', '1', '1', '0', '2'])
        self.assertEqual(sorted(result.actions), sorted(['howner:' + root, 'howner:' + root + '\\lib\\a.py', 'hprivate:' + root + '\\web',
                                                         'howner:' + root + '\\web\\course.html']))
        self.assertLess(result.actions.index('hprivate:' + root + '\\web'), result.actions.index('howner:' + root + '\\web\\course.html'))
        self.assertFalse(any('other' in entry or 'link' in entry for entry in result.opened))

    def test_elevated_repair_refuses_hard_links_swapped_paths_and_changed_acls(self):
        root = 'C:\\ilson-course'
        inherit = [(ME, True), (SY, True), (BA, True)]
        cases = {
            # Second name for a file outside the tree (hard link): skipped, counted as left alone.
            'hard link': (dict(links=2), ['2', '0', '0', '0', '1', '0', '0']),
            # lib was swapped for a junction after it was listed: the handle resolves elsewhere.
            'junction swap': (dict(hfinal='C:\\Program Files\\Vendor\\a.py'), ['2', '0', '0', '0', '1', '0', '0']),
            # Same name, but the handle shows a reparse point planted after Get-Item.
            'reparse after check': (dict(hreparse=True), ['2', '0', '0', '0', '1', '0', '0']),
            # ACL changed between the path read and the handle (foreign grant appeared).
            'acl changed': (dict(hrules=[(ME, True), ('S-1-1-0', True)]), ['2', '0', '0', '0', '1', '0', '0']),
            # Object vanished before the handle opened.
            'gone at open': (dict(vanish=True), ['2', '0', '0', '0', '0', '1', '0']),
        }
        for name, (flags, counts) in cases.items():
            with self.subTest(case=name):
                flags = dict(flags); vanish = flags.pop('vanish', False)
                model = [self.node(root, ME, [(ME, True)], dir=True, children=[root + '\\a.py']),
                         self.node(root + '\\a.py', BA, inherit, **flags)]
                result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='1',
                                         ILSON_ACL_LIMIT='5000', ACL_GUARDED='1', ACL_VANISH=root + '\\a.py' if vanish else '')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.actions, [])
                self.assertEqual(next(l for l in result.stdout.splitlines() if l.startswith('ILSON_ACL ')).split()[1:], counts)
        # A swapped directory is not descended into either.
        model = [self.node(root, ME, [(ME, True)], dir=True, children=[root + '\\lib']),
                 self.node(root + '\\lib', BA, inherit, dir=True, children=[root + '\\lib\\a.py'], hfinal='C:\\Windows\\System32'),
                 self.node(root + '\\lib\\a.py', BA, inherit)]
        result = self.tree(model, root, True)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.counts, ['2', '0', '0', '0', '1', '0', '0'])
        self.assertNotIn(root + '\\lib\\a.py', result.opened)

    def test_elevated_private_check_uses_the_handle_and_refuses_redirects(self):
        target = 'C:\\state\\web-admin\\token'
        cases = [
            (dict(owner=BA, rules=[(ME, True)]), '0', '0', ['hprivate:' + target]),
            (dict(owner=OTHER, rules=[(OTHER, True)]), '1', '0', ['hprivate:' + target]),  # create: new mkstemp file
            (dict(owner=BA, rules=[(ME, True)], links=2), '0', '1', []),
            (dict(owner=BA, rules=[(ME, True)], links=2), '1', '1', []),
            (dict(owner=BA, rules=[(ME, True)], hfinal='C:\\ProgramData\\Vendor\\cfg'), '1', '1', []),
            (dict(owner=BA, rules=[(ME, True)], hreparse=True), '0', '1', []),
            (dict(owner=BA, rules=[(ME, True)], hrules=[(ME, True), ('S-1-1-0', True)]), '0', '1', []),
            (dict(owner=BA, rules=[(ME, True)], howner=OTHER), '0', '1', []),
            (dict(owner=ME, rules=[(ME, True)]), '0', '0', []),  # already private: no handle at all
        ]
        for values, create, code, log in cases:
            with self.subTest(values=values, create=create):
                values = dict(values); owner, rules = values.pop('owner'), values.pop('rules')
                result = self.run_script(course_license.ACL_PRIVATE_PS, [self.node(target, owner, rules, **values)],
                                         ILSON_ACL_TARGET=target, ILSON_ACL_CREATE=create, ACL_GUARDED='1')
                self.assertEqual(str(result.returncode), code, result.stderr)
                self.assertEqual(result.actions, log)
                self.assertFalse(any(a.startswith('private:') for a in result.actions))  # never Set-Acl by path

    def test_handle_helper_compiles_and_paths_compare_without_following_names(self):
        body = course_license.ACL_VERDICT_PS + r'''
Add-Type -TypeDefinition $env:ILSON_ACL_CS
[IlsonAclHandle].FullName
ConvertTo-IlsonLongPath 'C:\a\b'
ConvertTo-IlsonLongPath '\\srv\s\x'
Test-IlsonSamePath '\\?\C:\Users\Me\AppData\Local\ilson-course\WEB' 'c:\users\me\appdata\local\ilson-course\web'
Test-IlsonSamePath '\\?\C:\Program Files\Vendor' 'C:\Users\Me\AppData\Local\ilson-course\web'
Test-IlsonSamePath '\\?\UNC\srv\s\x' '\\srv\s\x'
Test-IlsonSamePath '\\?\C:\a\bc' 'C:\a\b'
'''
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True,
                                timeout=120, stdin=subprocess.DEVNULL, env=dict(os.environ, ILSON_ACL_CS=course_license.ACL_HANDLE_CS))
        self.assertEqual(result.stdout.split(), ['IlsonAclHandle', '\\\\?\\C:\\a\\b', '\\\\?\\UNC\\srv\\s\\x',
                                                 'True', 'False', 'True', 'False'], result.stderr)


if __name__ == '__main__':
    unittest.main()
