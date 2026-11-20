"""Elevated ("관리자") Windows sessions: owner claim, repair and clear failure messages.

Real-device defect D1/D1-b (2026-11-20): files an elevated token creates are owned by
BUILTIN\\Administrators, so the user-only owner check rejected them and the course admin never
started; mkdir(0o700) folders left by an elevated install excluded the user entirely.

Real NTFS ACLs cannot run on this Mac. These tests check (1) the Python decisions with the
ACL call mocked, (2) the PowerShell decision and tree-walk logic under pwsh with the ACL
cmdlets replaced by an in-memory model, (3) the elevated Python handle route against a fake
Win32 layer and (4) the ctypes glue against fake DLL functions that check each argument with
the declared argtypes. None of them proves the behaviour on Windows itself.
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
        self.assertEqual((env['ILSON_ACL_TARGET'], env['ILSON_ACL_CREATE']), (os.path.abspath(str(Path('C:/x/token'))), '1'))
        self.assertNotIn('ILSON_ACL_CS', env)  # F2: no C# travels to PowerShell any more
        self.assertEqual(run.call_args.args[0][:4], ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand'])
        with patch.object(course_license.subprocess, 'run', return_value=self.completed(3)):
            with self.assertRaises(course_license.ElevatedOwnerError) as caught: course_license.windows_acl('t')
        self.assertEqual(str(caught.exception), 'ELEVATED_OWNER')
        # 4: the script found an elevated token although Python's check did not (fail closed).
        for failure in (self.completed(1), self.completed(4), OSError('no powershell'), subprocess.TimeoutExpired('powershell.exe', 120)):
            with self.subTest(failure=type(failure).__name__):
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(course_license.subprocess, 'run', **kwargs):
                    with self.assertRaises(ValueError) as caught: course_license.windows_acl('t')
                self.assertEqual(str(caught.exception), 'STORAGE_ERROR')
                self.assertNotIsInstance(caught.exception, course_license.ElevatedOwnerError)

    def test_tree_result_is_parsed_strictly(self):
        with patch.object(course_license.subprocess, 'run', return_value=self.completed(0, b'noise\r\nILSON_ACL 7 4 0 1 1 2 1\r\n')) as run:
            counts = course_license.windows_tree([Path('C:/a'), Path('C:/b')], repair=True)
        self.assertEqual(counts, {'checked': 7, 'repaired': 4, 'admin_owned': 0, 'no_access': 1, 'foreign': 1, 'error': 2, 'skipped': 1,
                                  'refused': 0, 'unscanned': 0})
        env = run.call_args.kwargs['env']
        self.assertEqual((env['ILSON_ACL_REPAIR'], env['ILSON_ACL_LIMIT']), ('1', '5000'))
        self.assertEqual(env['ILSON_ACL_ROOTS'].split('\n'), [os.path.abspath(str(Path('C:/a'))), os.path.abspath(str(Path('C:/b')))])
        for out, code in ((b'ILSON_ACL 1 2 3', 0), (b'ILSON_ACL 1 2 3 4 5 6', 0), (b'ILSON_ACL 1 2 3 4 5 6 x', 0),
                          (b'ILSON_ACL 1 2 3 4 5 6 7', 1), (b'ILSON_ACL_GUARDED\r\n', 4)):
            with self.subTest(out=out), patch.object(course_license.subprocess, 'run', return_value=self.completed(code, out)):
                with self.assertRaises(ValueError): course_license.windows_tree(['C:/a'])

    def test_scripts_stay_ascii_for_windows_powershell(self):
        for script in (course_license.ACL_PRIVATE_PS, course_license.ACL_TREE_PS):
            script.encode('ascii')
            self.assertIn('SetOwner($Me)', script)
            self.assertIn('SetAccessRuleProtection($true, $false)', script)
            # CreateProcess caps the whole command line at 32,767 characters; keep a margin.
            self.assertLess(len(base64.b64encode(script.encode('utf-16le'))), 28000)

    def test_elevated_route_opens_without_following_links_and_sets_security_on_the_handle(self):
        lic = course_license
        self.assertEqual(lic.OPEN_FLAGS, 0x02200000)    # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT
        self.assertEqual(lic.WRITE_ACCESS, 0xE0080)     # READ_CONTROL | WRITE_DAC | WRITE_OWNER | FILE_READ_ATTRIBUTES
        self.assertEqual(lic.READ_ACCESS, 0x20080)      # READ_CONTROL | FILE_READ_ATTRIBUTES
        self.assertEqual((lic.OWNER_INFO, lic.OWNER_PROTECTED_DACL_INFO), (0x1, 0x80000005))
        source = (ROOT / 'course/lib/license.py').read_text(encoding='utf-8')
        self.assertNotIn('AdjustTokenPrivileges', source)
        # F2: no C# helper and no compile anywhere; both scripts refuse an elevated token up front.
        for script in (lic.ACL_PRIVATE_PS, lic.ACL_TREE_PS):
            self.assertNotIn('Add-Type', script); self.assertNotIn('ILSON_ACL_CS', script)
        self.assertLess(lic.ACL_PRIVATE_PS.index('if (Test-IlsonGuarded) { exit 4 }'), lic.ACL_PRIVATE_PS.index('Get-Item'))
        self.assertLess(lic.ACL_TREE_PS.index("if ($repair -and (Test-IlsonGuarded)) { 'ILSON_ACL_GUARDED'; exit 4 }"),
                        lic.ACL_TREE_PS.index('Get-Item'))


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

    def test_refused_linked_paths_are_reported_without_the_elevated_rerun(self):
        tree = Mock(return_value={'checked': 3, 'repaired': 2, 'admin_owned': 0, 'no_access': 0, 'foreign': 0, 'error': 0, 'skipped': 0,
                                  'refused': 1})
        module = payload.acl_module(sources()); module.windows_tree = tree  # the bundle's own hint text
        with tempfile.TemporaryDirectory() as temp, patch.object(payload, 'IS_WINDOWS', True), \
                patch.object(payload, 'acl_module', return_value=module), patch('builtins.print') as output:
            root = Path(temp).resolve() / 'lib'; root.mkdir()
            payload.install(root, sources())
        lines = [c.args[0] for c in output.call_args_list]
        self.assertIn('HELPER_PERMISSIONS=left', lines)
        self.assertIn(module.REDIRECTED_HINT, lines)
        self.assertNotIn(module.ELEVATED_OWNER_HINT, lines); self.assertNotIn(payload.RERUN_ELEVATED_HINT, lines)
        self.assertNotIn('강사', module.REDIRECTED_HINT)

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
                                  ({'foreign': 1}, 'foreign'), ({'error': 2, 'skipped': 1}, 'incomplete'),
                                  ({'refused': 2, 'admin_owned': 1}, 'redirected')):
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
                    if state == 'redirected':
                        # F1: a guard refusal is not another user's file; no instructor, no admin rerun.
                        self.assertNotIn('강사', lines[0]); self.assertNotIn('다른 사용자', lines[0])
                        self.assertNotIn('--fix-permissions', lines[0]); self.assertIn('2개', lines[0])
                    self.assertEqual(value['refused'], values.get('refused', 0))
                    for line in lines: self.assertNotIn(temp, line)
            self.assertEqual(tree.call_args.args[0], [Path(temp) / 'ilson-course', Path(temp) / 'state'])
            self.assertEqual(tree.call_args.kwargs, {'repair': False})
            # Foreign and refused together: both lines, foreign first.
            tree.return_value = self.counts(foreign=1, refused=3)
            lines = diag.permission_lines(diag.windows_permissions())
            self.assertEqual(len(lines), 2); self.assertIn('강사', lines[0]); self.assertIn('3개', lines[1])
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
            tree.return_value = self.counts(repaired=1, refused=1)
            self.assertEqual(diag.main(['--fix-permissions'], edition='windows-course'), 1)
            self.assertIn('연결(바로가기)', output.call_args.args[0])
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


OI, CI, IO, ID = 0x01, 0x02, 0x08, 0x10  # ACE flags (MS-DTYP 2.4.4.1)
OW = 'S-1-3-4'


def rule(value):
    """(sid, allow[, ace flags[, mask]]) -> model rule; FullControl unless a mask is given."""
    return {'sid': value[0], 'allow': value[1], 'flags': value[2] if len(value) > 2 else 0,
            'mask': value[3] if len(value) > 3 else 0x1F01FF}


def node(path, owner, rules, dir=False, protected=False, children=(), **flags):
    """One object of the in-memory ACL model shared by the pwsh stubs and the fake Win32 layer.
    h* fields describe what a handle sees when it differs from the path: hfinal (the handle's
    final path), hreparse (a reparse point planted after the path check), howner/hrules (the ACL
    as the change handle reads it, i.e. changed in between); links = hard links. ownerdrop: an
    owner change also turns this user's entries inherit-only (to drive the D2 read-back guard)."""
    value = {'path': path, 'owner': owner, 'rules': [rule(r) for r in rules], 'dir': dir,
             'protected': protected, 'children': list(children), 'reparse': False, 'denied': False, 'denyset': False,
             'busy': False, 'links': 1}
    if 'hrules' in flags: flags['hrules'] = [rule(r) for r in flags['hrules']]
    value.update(flags); return value


def owner_change(n, new_owner):
    """What Windows did on the laptop (2026-11-20, D2) when only the owner changed: every OWNER
    RIGHTS entry became inherit-only; if one was inherited, the DACL became protected with the
    inherited entries copied as explicit ones."""
    if n['owner'] == new_owner: return
    inherited = any(r['sid'] == OW and not r['flags'] & IO and r['flags'] & ID for r in n['rules'])
    for r in n['rules']:
        if r['sid'] == OW or (n.get('ownerdrop') and r['sid'] == ME): r['flags'] |= IO
        if inherited: r['flags'] &= ~ID
    if inherited: n['protected'] = True


def tree_model(r='C:\\ilson-course'):
    inherit = [(ME, True), (SY, True), (BA, True)]
    return r, [
        node(r, BA, inherit, dir=True, children=[r + '\\lib', r + '\\web', r + '\\link', r + '\\other', r + '\\denied', r + '\\gone']),
        node(r + '\\lib', ME, inherit, dir=True, children=[r + '\\lib\\a.py']),
        node(r + '\\lib\\a.py', BA, inherit),
        # Python 3.13+ mkdir(0o700) in an elevated window: protected, no user entry.
        node(r + '\\web', BA, [(SY, True), (BA, True), ('S-1-3-4', True)], dir=True, protected=True, children=[r + '\\web\\course.html']),
        node(r + '\\web\\course.html', BA, [(SY, True), (BA, True)]),
        node(r + '\\link', ME, inherit, dir=True, reparse=True, children=[r + '\\lib']),
        node(r + '\\other', OTHER, [(OTHER, True)], dir=True, children=[r + '\\other\\x']),
        node(r + '\\other\\x', BA, inherit),
        node(r + '\\denied', BA, inherit, denied=True),
    ]


# Binary security descriptors, written here independently of license.py. Documented well-known
# SIDs (MS-DTYP 2.4.2.4) anchor the encoding.
KNOWN_SID_HEX = {'S-1-5-18': '010100000000000512000000', 'S-1-5-32-544': '01020000000000052000000020020000',
                 'S-1-3-4': '010100000000000304000000', 'S-1-1-0': '010100000000000100000000'}


def enc_sid(text):
    parts = [int(x) for x in text.split('-')[2:]]
    return bytes([1, len(parts) - 1]) + parts[0].to_bytes(6, 'big') + b''.join(x.to_bytes(4, 'little') for x in parts[1:])


def enc_acl(rules, flags=0, extra=b''):
    """rules: (sid, allow[, ace flags[, mask]]); flags is the default ACE flag byte."""
    aces = b''.join(bytes([0 if r[1] else 1, r[2] if len(r) > 2 else flags]) + (8 + len(enc_sid(r[0]))).to_bytes(2, 'little')
                    + (r[3] if len(r) > 3 else 0x1F01FF).to_bytes(4, 'little') + enc_sid(r[0]) for r in rules) + extra
    return bytes([2, 0]) + (8 + len(aces)).to_bytes(2, 'little') + (len(rules) + (1 if extra else 0)).to_bytes(2, 'little') + b'\0\0' + aces


def enc_sd(owner, rules, protected=False, dacl=True, extra=b''):
    body = b''
    owner_at = dacl_at = 0
    if owner:
        owner_at = 20; body += enc_sid(owner)
    if dacl:
        dacl_at = 20 + len(body); body += enc_acl(rules, extra=extra)
    control = 0x8000 | (0x4 if dacl else 0) | (0x1000 if protected else 0)
    return bytes([1, 0]) + control.to_bytes(2, 'little') + owner_at.to_bytes(4, 'little') + b'\0' * 8 + dacl_at.to_bytes(4, 'little') + body


def dec_acl(data):
    count, at, rules = int.from_bytes(data[4:6], 'little'), 8, []
    for _ in range(count):
        size = int.from_bytes(data[at + 2:at + 4], 'little')
        rules.append({'sid': course_license.sid_text(data[at + 8:at + size])[0], 'allow': data[at] == 0, 'flags': data[at + 1],
                      'mask': int.from_bytes(data[at + 4:at + 8], 'little')})
        at += size
    return rules


class FakeWin32:
    """In-memory Win32 layer for guarded_private / guarded_tree. finals maps literal path prefixes
    to the final path the system reports (junction, subst, mapped drive, 8.3 name)."""
    def __init__(self, nodes, finals=(), vanish=(), nofinal=()):
        self.m = {n['path']: n for n in nodes}
        self.finals, self.vanish, self.nofinal = list(finals), set(vanish), set(nofinal)
        self.handles, self.opened, self.actions, self.dacls, self.calls, self.next = {}, [], [], {}, 0, 1
        self.propagated = []

    def user_sid(self): return ME
    def exists(self, path): return path in self.m

    def _node(self, path):
        if path not in self.m: raise FileNotFoundError(2, 'gone')
        return self.m[path]

    def is_reparse(self, path): return bool(self._node(path)['reparse'])

    def children(self, path):
        return [child.rsplit('\\', 1)[1] for child in self._node(path)['children']]

    def open(self, path, write):
        self.calls += 1
        if path not in self.m or (write and path in self.vanish): raise course_license.Win32Error(2)
        n = self.m[path]
        if n['denied']: raise course_license.Win32Error(5)
        if n['busy']: raise course_license.Win32Error(32)
        handle, self.next = self.next, self.next + 1
        self.handles[handle] = (path, write); self.opened.append((path, write))
        return handle

    def close(self, handle): del self.handles[handle]

    def info(self, handle):
        n = self.m[self.handles[handle][0]]
        return (0x10 if n['dir'] else 0) | (0x400 if n['reparse'] or n.get('hreparse') else 0) | 0x20, n['links']

    def final_path(self, handle):
        path = self.handles[handle][0]
        if path in self.nofinal: raise course_license.Win32Error(1)
        final = self.m[path].get('hfinal') or path
        for literal, real in self.finals:
            if final.upper().startswith(literal.upper()): final = real + final[len(literal):]; break
        return '\\\\?\\UNC\\' + final[2:] if final.startswith('\\\\') else '\\\\?\\' + final

    def security(self, handle):
        path, write = self.handles[handle]
        n = self.m[path]
        owner = n.get('howner') if write and n.get('howner') else n['owner']
        rules = n['hrules'] if write and 'hrules' in n else n['rules']
        return enc_sd(owner, [(r['sid'], r['allow'], r.get('flags', 0), r.get('mask', 0x1F01FF)) for r in rules], n['protected'])

    def set_security(self, handle, owner, dacl):
        path, write = self.handles[handle]
        assert write, 'security set through a read handle'
        n = self.m[path]
        if n['denyset']: raise course_license.Win32Error(5)
        if n.get('ignoreset'): self.actions.append('ignored:' + path); return  # call "succeeds", nothing changes
        n.pop('howner', None); n.pop('hrules', None)
        new_owner = course_license.sid_text(owner)[0]
        if dacl is None:
            owner_change(n, new_owner); n['owner'] = new_owner
            self.actions.append('howner:' + path); return
        n['owner'] = new_owner
        self.dacls[path] = dacl
        n['rules'] = [{'sid': r['sid'], 'allow': r['allow'], 'flags': r['flags'], 'mask': r['mask']} for r in dec_acl(dacl)]
        n['protected'] = True
        self.propagate(n)
        self.actions.append('hprivate:' + path)

    def propagate(self, n):
        """The system's walk after a DACL set: by name, into every non-protected child, never
        through a reparse point (laptop N1); a hard-linked file's other name changes with it."""
        for c in n['children']:
            child = self.m.get(c)
            if not child or child['protected'] or child['reparse']: continue
            child['rules'] = [rule((ME, True, ID | (OI | CI if child['dir'] else 0)))]
            self.propagated.append(c)
            if child['dir']: self.propagate(child)


COUNT_KEYS = ('checked', 'repaired', 'admin_owned', 'no_access', 'foreign', 'error', 'skipped', 'refused')


def guarded_tree(model, root, **fake):
    w32 = FakeWin32(model, **fake)
    counts = course_license.guarded_tree([root], 5000, w32)
    w32.counts = [counts[k] for k in COUNT_KEYS]
    w32.unscanned = counts['unscanned']
    assert not w32.handles, 'every handle is closed again: %r' % w32.handles
    return w32


IDENTITY = '[Security.Principal.WindowsIdentity]::GetCurrent().User'
# The ACL cmdlets replaced by the in-memory model. GetAccessRules reports every entry with the
# .NET properties (InheritanceFlags, PropagationFlags, FileSystemRights), unfiltered, so the
# script's own normalisation is what the tests see. Owner changes and DACL propagation follow the
# same rules as FakeWin32 (owner_change, propagate).
PS_STUBS = r'''
$global:M = @{}
foreach ($e in @(ConvertFrom-Json $env:ACL_MODEL)) { $global:M[$e.path] = $e }
$global:StubMe = [pscustomobject]@{ Value = $env:ACL_ME }
function Test-Path { param([string]$LiteralPath) return $global:M.ContainsKey($LiteralPath) }
function Set-ModelOwner($o, [string]$Owner) {
    if ($o.owner -ne $Owner) {
        $inherited = @($o.rules | Where-Object { $_.sid -eq 'S-1-3-4' -and -not ([int]$_.flags -band 8) -and ([int]$_.flags -band 16) }).Count -gt 0
        foreach ($r in @($o.rules)) {
            if ($r.sid -eq 'S-1-3-4' -or ($o.ownerdrop -and $r.sid -eq $env:ACL_ME)) { $r.flags = [int]$r.flags -bor 8 }
            if ($inherited) { $r.flags = [int]$r.flags -band (-bnot 16) }
        }
        if ($inherited) { $o.protected = $true }
    }
    $o.owner = $Owner
}
function Get-Item { param([string]$LiteralPath, [switch]$Force)
    [Console]::Out.WriteLine('READ ' + $LiteralPath)
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
        Set-ModelOwner $global:M[$x.P] $x.Owner; [Console]::Out.WriteLine('ACT owner:' + $x.P) }
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
            $f = [int]$r.flags; $mask = $r.mask; if ($null -eq $mask) { $mask = 2032127 }
            $inheritance = 0; if ($f -band 1) { $inheritance = $inheritance -bor 2 }; if ($f -band 2) { $inheritance = $inheritance -bor 1 }
            $propagation = 0; if ($f -band 4) { $propagation = $propagation -bor 1 }; if ($f -band 8) { $propagation = $propagation -bor 2 }
            [pscustomobject]@{ IdentityReference = [pscustomobject]@{ Value = $r.sid }; AccessControlType = $type;
                               InheritanceFlags = $inheritance; PropagationFlags = $propagation; FileSystemRights = [int64]$mask;
                               IsInherited = (($f -band 16) -ne 0) } } }
    return $acl
}
function New-IlsonPrivateAcl($Item, $Me) { return [pscustomobject]@{ Me = $Me.Value } }
function Push-ModelInherit($o, [string]$Me) {
    foreach ($c in @($o.children)) {
        $child = $global:M[$c]
        if ($child -and -not $child.protected -and -not $child.reparse) {
            $f = 16; if ($child.dir) { $f = 19 }
            $child.rules = @([pscustomobject]@{ sid = $Me; allow = $true; flags = $f; mask = 2032127 })
            [Console]::Out.WriteLine('PROPAGATED ' + $c)
            if ($child.dir) { Push-ModelInherit $child $Me }
        }
    }
}
function Set-ModelPrivate([string]$Path, [string]$Me) {
    $o = $global:M[$Path]
    if ($o.denyset) { throw (New-Object UnauthorizedAccessException 'denied') }
    $f = 0; if ($o.dir) { $f = 3 }
    $o.owner = $Me; $o.protected = $true; $o.rules = @([pscustomobject]@{ sid = $Me; allow = $true; flags = $f; mask = 2032127 })
    Push-ModelInherit $o $Me
}
function Set-Acl { param([string]$LiteralPath, $AclObject)
    Set-ModelPrivate $LiteralPath $AclObject.Me
    [Console]::Out.WriteLine('ACT private:' + $LiteralPath)
}
function Get-ChildItem { param([string]$LiteralPath, [switch]$Force)
    foreach ($c in @($global:M[$LiteralPath].children)) { [pscustomobject]@{ FullName = $c } } }
function Test-IlsonGuarded { return $env:ACL_GUARDED -eq '1' }
'''


def run_acl_script(script, model, **env):
    """Run one of license.py's ACL scripts under pwsh against the model. Needs PWSH."""
    logic = script.split(course_license.ACL_VERDICT_PS, 1)[1]
    assert IDENTITY in logic
    body = course_license.ACL_VERDICT_PS + PS_STUBS + logic.replace(IDENTITY, '$global:StubMe')
    result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True,
                            timeout=60, stdin=subprocess.DEVNULL,
                            env=dict(os.environ, ACL_MODEL=json.dumps(model), ACL_ME=ME, **env))
    lines = result.stdout.splitlines()
    result.actions = [line[4:] for line in lines if line.startswith('ACT ')]
    result.reads = [line[5:] for line in lines if line.startswith('READ ')]
    result.opened = [line[5:] for line in lines if line.startswith('OPEN ')]
    result.propagated = [line[11:] for line in lines if line.startswith('PROPAGATED ')]
    counts = [line.split()[1:] for line in lines if line.startswith('ILSON_ACL ')]
    result.counts = [int(v) for v in counts[-1]] if counts else None
    return result


@unittest.skipUnless(PWSH, 'pwsh required to run the PowerShell ACL logic')
class PowerShellAclLogicTests(unittest.TestCase):
    """The real script text with the ACL cmdlets replaced by an in-memory model."""
    IDENTITY = IDENTITY
    STUBS = PS_STUBS

    def node(self, *args, **kwargs): return node(*args, **kwargs)
    def model(self): return tree_model()

    def run_script(self, script, model, **env):
        return run_acl_script(script, model, **env)

    def test_scripts_parse_without_errors(self):
        for script in (course_license.ACL_PRIVATE_PS, course_license.ACL_TREE_PS):
            check = '$e=$null; [void][Management.Automation.Language.Parser]::ParseInput($env:S,[ref]$null,[ref]$e); $e.Count'
            result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', check], capture_output=True, text=True,
                                    timeout=60, stdin=subprocess.DEVNULL, env=dict(os.environ, S=script))
            self.assertEqual(result.stdout.strip(), '0', result.stderr)

    def test_verdict_table(self):
        # One table for both routes: the pwsh functions and the Python handle-route mirrors.
        body = course_license.ACL_VERDICT_PS + '\n' + '\n'.join(
            ("Get-IlsonPrivateVerdict %s %s %s" % (ps_literal(owner or ''), ps_rules(rules), ps_literal(ME)) if kind == 'private' else
             "Get-IlsonTreeVerdict %s %s %s $%s" % (ps_literal(owner or ''), ps_rules(rules), ps_literal(ME), 'true' if protected else 'false'))
            for kind, owner, rules, protected, _ in VERDICT_CASES)
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True,
                                timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(result.stdout.split(), [expected for *_, expected in VERDICT_CASES], result.stderr)


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


    def tree(self, model, root):
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000')
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
        self.assertEqual(self.tree(model, r).actions, [])
        # Elevated: the Python handle route (design change F2), same verdicts.
        fake = guarded_tree(model, r)
        self.assertEqual((fake.actions, fake.counts), ([], [3, 0, 0, 0, 0, 0, 0, 0]))

    def test_foreign_grant_or_deny_on_an_administrators_object_is_left_alone(self):
        r = 'C:\\ilson-course'
        for rules in ([(ME, True), ('S-1-5-32-545', True)], [(ME, True), ('S-1-1-0', False)], [(ME, False), (SY, True)]):
            model = [self.node(r, ME, [(ME, True)], dir=True, children=[r + '\\x']), self.node(r + '\\x', BA, rules)]
            with self.subTest(rules=rules, route='normal'):
                result = self.tree(model, r)
                self.assertEqual(result.actions, [])
                self.assertEqual(result.counts, ['2', '0', '0', '0', '1', '0', '0'])
            with self.subTest(rules=rules, route='elevated'):
                fake = guarded_tree(model, r)
                self.assertEqual((fake.actions, fake.counts), ([], [2, 0, 0, 0, 1, 0, 0, 0]))

    def test_elevated_token_scripts_refuse_before_reading_anything(self):
        # F2: nothing compiles and nothing changes by path in an elevated token; Python handles it.
        target = 'C:\\state\\web-admin\\token'
        for create in ('0', '1'):
            result = self.run_script(course_license.ACL_PRIVATE_PS, [self.node(target, BA, [(ME, True)])],
                                     ILSON_ACL_TARGET=target, ILSON_ACL_CREATE=create, ACL_GUARDED='1')
            self.assertEqual((result.returncode, result.actions, result.reads), (4, [], []), result.stderr)
        root, model = self.model()
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='1', ILSON_ACL_LIMIT='5000',
                                 ACL_GUARDED='1')
        self.assertEqual((result.returncode, result.actions, result.reads), (4, [], []), result.stderr)
        self.assertEqual(result.stdout.split(), ['ILSON_ACL_GUARDED'])
        # A scan changes nothing, so it still runs in PowerShell in an elevated token.
        result = self.run_script(course_license.ACL_TREE_PS, model, ILSON_ACL_ROOTS=root, ILSON_ACL_REPAIR='0', ILSON_ACL_LIMIT='5000',
                                 ACL_GUARDED='1')
        self.assertIn('ILSON_ACL 7 0 4 1 1 0 2', result.stdout.splitlines(), result.stderr)


def ps_rules(rules):
    """(sid, allow[, effective]) -> PowerShell rule list as Get-IlsonAclFacts returns it."""
    return '@(' + ','.join("@{Sid='%s';Allow=$%s;Effective=$%s}" % (r[0], 'true' if r[1] else 'false',
                                                                    'true' if len(r) < 3 or r[2] else 'false') for r in rules) + ')'


VERDICT_CASES = [
    ('private', ME, [(ME, True)], False, 'ok'),
    ('private', BA, [(ME, True)], False, 'repair'),
    ('private', BA, [(SY, True), (BA, True), ('S-1-3-4', True)], False, 'repair'),
    ('private', OTHER, [(ME, True)], False, 'foreign'),
    ('private', BA, [(ME, True), ('S-1-1-0', True)], False, 'foreign'),
    ('private', BA, [(SY, False)], False, 'foreign'),
    ('private', ME, [(ME, True), (SY, True)], False, 'repair'),
    ('private', '', [], False, 'denied'),
    ('tree', ME, [(ME, True), ('S-1-1-0', True)], False, 'ok'),
    ('tree', BA, [(ME, True), (SY, True), (BA, True)], False, 'fix-owner'),
    # S1: an Administrators-owned object with a foreign grant or any Deny entry is left alone.
    ('tree', BA, [(ME, True), ('S-1-5-32-545', True)], False, 'foreign'),
    ('tree', BA, [(ME, False), ('S-1-1-0', True)], False, 'foreign'),
    ('tree', BA, [(ME, True), (SY, False)], False, 'foreign'),
    ('tree', BA, [(ME, True), (OTHER, True)], False, 'foreign'),
    # S2: Python 3.13+ mkdir(0o700) in a normal window (CPython SDDL D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)).
    ('tree', ME, [(SY, True), (BA, True), ('S-1-3-4', True)], True, 'ok'),
    ('tree', ME, [(SY, True), (BA, True), ('S-1-3-4', True)], False, 'ok'),
    # OWNER RIGHTS grants the owner, so under an Administrators owner the user still has no entry.
    ('tree', BA, [(SY, True), (BA, True), ('S-1-3-4', True)], True, 'fix-private'),
    ('tree', BA, [(SY, True), (BA, True)], True, 'fix-private'),
    ('tree', BA, [('S-1-5-32-545', True)], True, 'foreign'),
    ('tree', OTHER, [(ME, True)], False, 'foreign'),
    # D2 (laptop run 2): access counts from effective entries only; a third value False marks an
    # inherit-only entry. An owner-only fix needs an entry naming the user, since an owner change
    # turns OWNER RIGHTS inherit-only.
    ('tree', BA, [(SY, True), (BA, True), ('S-1-3-4', True)], False, 'fix-private'),   # elevated.txt before
    ('tree', ME, [(SY, True), (BA, True), ('S-1-3-4', True, False)], True, 'fix-private'),  # elevated.txt after
    ('tree', ME, [('S-1-3-4', True, False), (SY, True), (BA, True)], False, 'fix-private'),  # note.txt
    ('tree', BA, [(SY, True), (BA, True)], False, 'fix-private'),
    ('tree', BA, [(ME, True, False), (SY, True)], False, 'fix-private'),
    ('tree', BA, [(ME, True), ('S-1-3-4', True)], False, 'fix-owner'),
    ('tree', ME, [(ME, True, False), (SY, True)], False, 'fix-private'),
    ('tree', BA, [(ME, True), ('S-1-1-0', True, False)], False, 'foreign'),  # an inherit-only foreign grant still blocks
    ('private', ME, [(ME, True, False)], False, 'repair'),
    ('private', ME, [(ME, True), (ME, True, False)], False, 'ok'),
    ('private', ME, [(SY, True), (BA, True), ('S-1-3-4', True, False)], False, 'repair'),
]


class GuardedRouteTests(unittest.TestCase):
    """The elevated route in Python (F1 anchors, F2 no process) against FakeWin32."""

    def test_python_verdicts_match_the_powershell_table(self):
        for kind, owner, rules, protected, expected in VERDICT_CASES:
            with self.subTest(kind=kind, owner=owner, rules=rules):
                got = (course_license.private_verdict(owner or None, rules, ME) if kind == 'private'
                       else course_license.tree_verdict(owner or None, rules, ME, protected))
                self.assertEqual(got, expected)

    def test_security_descriptor_parse_and_private_dacl_bytes(self):
        lic = course_license
        for sid, hexed in KNOWN_SID_HEX.items():
            self.assertEqual(enc_sid(sid).hex(), hexed)
            self.assertEqual((lic.sid_bytes(sid).hex(), lic.sid_text(bytes.fromhex(hexed))), (hexed, (sid, len(hexed) // 2)))
        self.assertEqual(lic.sid_text(lic.sid_bytes(ME))[0], ME)
        rules = [(SY, True), (OTHER, False), ('S-1-3-4', True)]
        self.assertEqual(lic.parse_security_descriptor(enc_sd(BA, rules, protected=True)), (BA, [r + (True,) for r in rules], True))
        self.assertEqual(lic.parse_security_descriptor(enc_sd(ME, [(ME, True)])), (ME, [(ME, True, True)], False))
        # No DACL: everybody has access, as .NET reports it.
        self.assertEqual(lic.parse_security_descriptor(enc_sd(BA, [], dacl=False)), (BA, [('S-1-1-0', True, True)], False))
        self.assertIsNone(lic.parse_security_descriptor(enc_sd(None, [(ME, True)]))[0])
        # A callback ACE (type 9) is never a trusted grant.
        callback = bytes([9, 0, 24, 0]) + (0x1F01FF).to_bytes(4, 'little') + enc_sid(ME)[:16]
        owner, parsed, _ = lic.parse_security_descriptor(enc_sd(BA, [(ME, True)], extra=callback))
        self.assertEqual(lic.private_verdict(owner, parsed, ME), 'foreign')
        good = enc_sd(BA, [(ME, True)])
        for bad in (good[:19], bytes([2]) + good[1:], good[:2] + b'\0\0' + good[4:], good[:-3],
                    good[:good.index(enc_acl([(ME, True)])) + 10] + b'\xff\xff' + good[good.index(enc_acl([(ME, True)])) + 12:]):
            with self.subTest(bad=bad.hex()):
                with self.assertRaises(ValueError): lic.parse_security_descriptor(bad)
        # The exact entry New-IlsonPrivateAcl adds: Allow FullControl, OI|CI on a folder, none on a file.
        for container, flags in ((True, 3), (False, 0)):
            acl = lic.private_dacl(ME, container)
            self.assertEqual(acl, enc_acl([(ME, True)], flags=flags))
            self.assertEqual(dec_acl(acl), [{'sid': ME, 'allow': True, 'flags': flags, 'mask': 0x1F01FF}])

    def test_paths_compare_by_final_component_without_following_names(self):
        lic = course_license
        self.assertEqual((lic.long_path('C:\\a\\b'), lic.long_path('\\\\srv\\s\\x'), lic.long_path('\\\\?\\C:\\a')),
                         ('\\\\?\\C:\\a\\b', '\\\\?\\UNC\\srv\\s\\x', '\\\\?\\C:\\a'))
        u = lic.under
        self.assertTrue(u('\\\\?\\C:\\Users\\Me\\AppData\\Local\\ilson-course\\WEB', '\\\\?\\c:\\users\\me\\appdata\\local\\ilson-course'))
        self.assertTrue(u('\\\\?\\C:\\a\\b', '\\\\?\\C:\\a\\b\\'))
        self.assertTrue(u('\\\\?\\UNC\\srv\\s\\x\\y', '\\\\?\\UNC\\SRV\\s\\x'))
        self.assertFalse(u('\\\\?\\C:\\a\\bc', '\\\\?\\C:\\a\\b'))            # component-wise, not a string prefix
        self.assertFalse(u('\\\\?\\C:\\a', '\\\\?\\C:\\a\\b'))
        self.assertFalse(u('\\\\?\\C:\\Program Files\\Vendor', '\\\\?\\C:\\Users\\Me\\AppData\\Local\\ilson-course'))
        self.assertFalse(u('\\\\?\\UNC\\C:\\x', '\\\\?\\C:\\x'))               # UNC never equals a drive path
        self.assertFalse(u('\\\\?\\C:\\x', '\\\\?\\'))                         # an empty anchor never matches
        self.assertFalse(u('\\\\?\\C:\\STRASSE', '\\\\?\\C:\\straße'))        # one character never becomes two

    def test_elevated_repair_acts_on_the_handle_and_matches_the_normal_route(self):
        root, model = tree_model()
        fake = guarded_tree(model, root)
        self.assertEqual(fake.counts, [7, 4, 0, 1, 1, 0, 2, 0])  # same as the pwsh normal route, refused 0
        self.assertEqual(sorted(fake.actions), sorted(['howner:' + root, 'howner:' + root + '\\lib\\a.py', 'hprivate:' + root + '\\web',
                                                       'howner:' + root + '\\web\\course.html']))
        self.assertLess(fake.actions.index('hprivate:' + root + '\\web'), fake.actions.index('howner:' + root + '\\web\\course.html'))
        self.assertFalse(any('other\\' in path or 'link' in path for path, _ in fake.opened))
        self.assertEqual(fake.dacls[root + '\\web'], course_license.private_dacl(ME, True))
        # Changes only ever go through a write handle that was checked first; reads use read handles.
        self.assertEqual(sorted(p for p, w in fake.opened if w), sorted(a.split(':', 1)[1] for a in fake.actions))

    def test_elevated_repair_refuses_hard_links_swapped_paths_and_changed_acls(self):
        root = 'C:\\ilson-course'
        inherit = [(ME, True), (SY, True), (BA, True)]
        cases = {
            # Second name for a file outside the tree (hard link).
            'hard link': (dict(links=2), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            # The path now resolves outside the root (a folder on the way swapped for a junction).
            'junction swap': (dict(hfinal='C:\\Program Files\\Vendor\\a.py'), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            # A sibling folder whose name only starts like the root's is still outside it.
            'prefix lookalike': (dict(hfinal='C:\\ilson-course-old\\a.py'), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            # Same name, but the handle shows a reparse point planted after the path check.
            'reparse after check': (dict(hreparse=True), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            # ACL changed between the read handle and the change handle (foreign grant appeared).
            'acl changed': (dict(hrules=[(ME, True), ('S-1-1-0', True)]), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            'owner changed': (dict(howner=OTHER), {}, [2, 0, 0, 0, 0, 0, 0, 1]),
            # The final path cannot be read (e.g. SMB): not verifiable, so not changed. One call, no retry.
            'no final path': ({}, dict(nofinal={root + '\\a.py'}), [2, 0, 0, 0, 0, 1, 0, 0]),
            # Object vanished before the change handle opened. Design change: skipped (was error in pwsh).
            'gone at open': ({}, dict(vanish={root + '\\a.py'}), [2, 0, 0, 0, 0, 0, 1, 0]),
        }
        for name, (flags, fake_args, counts) in cases.items():
            with self.subTest(case=name):
                model = [node(root, ME, [(ME, True)], dir=True, children=[root + '\\a.py']), node(root + '\\a.py', BA, inherit, **flags)]
                fake = guarded_tree(model, root, **fake_args)
                self.assertEqual((fake.actions, fake.counts), ([], counts))
        # A swapped directory is not descended into either.
        model = [node(root, ME, [(ME, True)], dir=True, children=[root + '\\lib']),
                 node(root + '\\lib', BA, inherit, dir=True, children=[root + '\\lib\\a.py'], hfinal='C:\\Windows\\System32'),
                 node(root + '\\lib\\a.py', BA, inherit)]
        fake = guarded_tree(model, root)
        self.assertEqual((fake.actions, fake.counts), ([], [2, 0, 0, 0, 0, 0, 0, 1]))
        self.assertNotIn(root + '\\lib\\a.py', [p for p, _ in fake.opened])
        # Also when the swapped folder itself needs no change: its outside children are never walked.
        model[1].update(owner=ME, rules=[{'sid': ME, 'allow': True}])
        fake = guarded_tree(model, root)
        self.assertEqual((fake.actions, fake.counts), ([], [2, 0, 0, 0, 0, 0, 0, 1]))
        self.assertNotIn(root + '\\lib\\a.py', [p for p, _ in fake.opened])

    def test_indirect_roots_are_accepted_when_objects_lie_under_the_roots_final_path(self):
        # F1: profile behind a junction, subst drive, mapped drive (UNC), 8.3 short name, other case.
        cases = {
            'junction profile': ('C:\\Users\\Me\\AppData\\Local\\ilson-course', [('C:\\Users\\Me', 'D:\\Users\\Me')]),
            'subst drive': ('X:\\ilson-course', [('X:\\', 'C:\\work\\')]),
            'mapped drive': ('Z:\\ilson-course', [('Z:\\', '\\\\srv\\share\\')]),
            'short name': ('C:\\Users\\MEKIM~1\\AppData\\Local\\ilson-course', [('C:\\Users\\MEKIM~1', 'C:\\Users\\Me Kim')]),
            'case': ('c:\\users\\me\\appdata\\local\\ilson-course', [('c:\\users\\me', 'C:\\Users\\Me')]),
        }
        for name, (root, finals) in cases.items():
            with self.subTest(case=name):
                _, model = tree_model(root)
                fake = guarded_tree(model, root, finals=finals)
                self.assertEqual(fake.counts, [7, 4, 0, 1, 1, 0, 2, 0])
                self.assertEqual(len(fake.actions), 4)
                # An object that leaves the root's final path is still refused under the same mapping.
                _, model = tree_model(root)
                model[2]['hfinal'] = 'D:\\Users\\Other\\a.py'
                fake = guarded_tree(model, root, finals=finals)
                self.assertEqual(fake.counts, [7, 3, 0, 1, 1, 0, 2, 1])
                self.assertNotIn('howner:' + root + '\\lib\\a.py', fake.actions)
                # The private route through the same indirection.
                folder = root + '\\state'
                for create in (True, False):
                    fake = FakeWin32([node(folder, ME, [(ME, True)], dir=True), node(folder + '\\token', BA, [(ME, True)])], finals=finals)
                    course_license.guarded_private(folder + '\\token', create, fake)
                    self.assertEqual(fake.actions, ['hprivate:' + folder + '\\token'])
                    self.assertFalse(fake.handles)

    def private(self, values, create, parent=None):
        target = 'C:\\state\\web-admin\\token'
        values = dict(values); owner, rules = values.pop('owner'), values.pop('rules')
        fake_args = {k: values.pop(k) for k in ('vanish',) if k in values}
        model = [node('C:\\state\\web-admin', ME, [(ME, True)], dir=True, **(parent or {})), node(target, owner, rules, **values)]
        fake = FakeWin32(model, **fake_args)
        try:
            course_license.guarded_private(target, create, fake)
            outcome = 'ok'
        except course_license.GuardRefusedError as error:
            outcome = 'refused'; self.assertEqual(str(error), 'PATH_REDIRECTED')
        except course_license.ElevatedOwnerError:
            outcome = 'elevated'
        except ValueError as error:
            outcome = str(error)
        self.assertFalse(fake.handles, 'every handle is closed again')
        return outcome, fake

    def test_elevated_private_check_uses_the_handle_and_refuses_redirects(self):
        target = 'C:\\state\\web-admin\\token'
        cases = [
            (dict(owner=BA, rules=[(ME, True)]), False, 'ok', ['hprivate:' + target]),
            (dict(owner=OTHER, rules=[(OTHER, True)]), True, 'ok', ['hprivate:' + target]),  # create: new mkstemp file
            (dict(owner=BA, rules=[(ME, True)], links=2), False, 'refused', []),
            (dict(owner=BA, rules=[(ME, True)], links=2), True, 'refused', []),
            (dict(owner=BA, rules=[(ME, True)], hfinal='C:\\ProgramData\\Vendor\\cfg'), True, 'refused', []),
            (dict(owner=BA, rules=[(ME, True)], hreparse=True), False, 'refused', []),
            (dict(owner=BA, rules=[(ME, True)], hrules=[(ME, True), ('S-1-1-0', True)]), False, 'refused', []),
            (dict(owner=BA, rules=[(ME, True)], howner=OTHER), False, 'refused', []),
            (dict(owner=ME, rules=[(ME, True)]), False, 'ok', []),  # already private: read handle only
            (dict(owner=OTHER, rules=[(ME, True)]), False, 'STORAGE_ERROR', []),
            (dict(owner=BA, rules=[(ME, True)], reparse=True), False, 'STORAGE_ERROR', []),
            (dict(owner=BA, rules=[(ME, True)], denied=True), False, 'elevated', []),
            (dict(owner=BA, rules=[(ME, True)], denyset=True), False, 'elevated', []),
            (dict(owner=BA, rules=[(ME, True)], busy=True), False, 'STORAGE_ERROR', []),
            (dict(owner=BA, rules=[(ME, True)], vanish={target}), True, 'STORAGE_ERROR', []),
            # The change did not take: the read-back on the same handle fails closed.
            (dict(owner=BA, rules=[(ME, True)], ignoreset=True), False, 'STORAGE_ERROR', ['ignored:' + target]),
        ]
        for values, create, expected, log in cases:
            with self.subTest(values=values, create=create):
                outcome, fake = self.private(values, create)
                self.assertEqual((outcome, fake.actions), (expected, log))
                if (values['owner'], values['rules']) == (ME, [(ME, True)]):
                    self.assertEqual(fake.opened, [(target, False)])
        # The parent folder itself swapped for a link: the anchor is refused before any change.
        outcome, fake = self.private(dict(owner=BA, rules=[(ME, True)]), True, parent=dict(reparse=True))
        self.assertEqual((outcome, fake.actions), ('refused', []))
        # The parent's final path elsewhere and the object's with it is fine; the object alone elsewhere is not.
        outcome, fake = self.private(dict(owner=BA, rules=[(ME, True)], hfinal='D:\\moved\\token'), True, parent=dict(hfinal='D:\\moved'))
        self.assertEqual((outcome, fake.actions), ('ok', ['hprivate:' + target]))
        self.assertEqual(fake.dacls[target], course_license.private_dacl(ME, False))

    def test_elevated_calls_take_no_process_and_fail_closed_fast(self):
        # F2: an elevated windows_acl / windows_tree repair runs no PowerShell (so no compile).
        lic = course_license
        target = os.path.abspath('C:\\state\\token')
        import ntpath  # the route splits Windows paths, whatever the test host
        fake = FakeWin32([node(ntpath.dirname(target), ME, [(ME, True)], dir=True), node(target, BA, [(ME, True)])])
        root = os.path.abspath('C:\\ilson-course')
        _, model = tree_model(root)
        tree = FakeWin32(model)
        with patch.object(lic.subprocess, 'run') as run:
            with patch.object(lic, 'elevated_win32', return_value=fake):
                lic.windows_acl(target, create=True)
            with patch.object(lic, 'elevated_win32', return_value=tree):
                self.assertEqual(lic.windows_tree([root], repair=True)['repaired'], 4)
            run.assert_not_called()
        self.assertEqual(fake.actions, ['hprivate:' + target])
        # A scan in an elevated window takes the same handle checks as its repair (run 3, N2), on
        # read handles only, changing nothing and running no PowerShell.
        scan = FakeWin32(tree_model(root)[1])
        with patch.object(lic, 'elevated_win32', return_value=scan), patch.object(lic.subprocess, 'run') as run:
            counts = lic.windows_tree([root])
        run.assert_not_called()
        self.assertEqual((counts['repaired'], counts['admin_owned'], scan.actions), (0, 4, []))
        self.assertFalse([path for path, write in scan.opened if write])
        # A normal window reads through PowerShell, as before.
        with patch.object(lic, 'elevated_win32', return_value=None), \
                patch.object(lic.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'ILSON_ACL 1 0 0 0 0 0 0', b'')) as run:
            lic.windows_tree([root])
        run.assert_called_once()
        # Layer failures cost one call per object and end in a clear, closed result.
        broken = FakeWin32(tree_model(root)[1], nofinal={p['path'] for p in tree_model(root)[1]})
        self.assertEqual(lic.guarded_tree([root], 5000, broken), dict(zip(COUNT_KEYS, (1, 0, 0, 0, 0, 1, 0, 0)), unscanned=0))
        self.assertEqual(broken.calls, 1)
        failing = Mock(user_sid=Mock(side_effect=lic.Win32Error(1)))
        with patch.object(lic, 'elevated_win32', return_value=failing):
            with self.assertRaises(ValueError) as caught: lic.windows_tree([root], repair=True)
        self.assertEqual(str(caught.exception), 'STORAGE_ERROR')
        # Unknown elevation (ctypes or the check failing) falls back to PowerShell, which refuses an
        # elevated token itself (exit 4) and reports STORAGE_ERROR; nothing is retried.
        with patch.object(lic, 'os', nt_os()), patch.object(lic, '_WIN32', []), patch.object(lic, 'Win32', side_effect=OSError('no ctypes')):
            self.assertIsNone(lic.elevated_win32())
        with patch.object(lic, 'os', nt_os()), patch.object(lic, '_WIN32', [Mock(guarded=Mock(side_effect=lic.Win32Error(5)))]):
            self.assertIsNone(lic.elevated_win32())
        with patch.object(lic, 'os', nt_os()), patch.object(lic, '_WIN32', [Mock(guarded=Mock(return_value=True))]) as cached:
            self.assertIs(lic.elevated_win32(), cached[0])
        self.assertIsNone(lic.elevated_win32())  # POSIX
        with patch.object(lic, 'elevated_win32', return_value=None), \
                patch.object(lic.subprocess, 'run', return_value=subprocess.CompletedProcess([], 4, b'', b'')) as run:
            with self.assertRaises(ValueError) as caught: lic.windows_acl(target)
            self.assertEqual(str(caught.exception), 'STORAGE_ERROR')
            run.return_value = subprocess.CompletedProcess([], 4, b'ILSON_ACL_GUARDED\r\n', b'')
            with self.assertRaises(ValueError): lic.windows_tree([root], repair=True)
        self.assertEqual(run.call_count, 2)

    def test_guard_refusal_reaches_the_student_without_the_instructor(self):
        lic = course_license
        with patch.object(lic, 'evaluate', side_effect=lic.GuardRefusedError()), patch.object(sys, 'argv', ['license.py', 'check']), \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(lic.main(), 1)
        self.assertIn('PATH_REDIRECTED', err.getvalue()); self.assertIn(lic.REDIRECTED_HINT, err.getvalue())
        self.assertNotIn('강사', lic.REDIRECTED_HINT)
        # ilson_platform keeps it a non-elevated access problem (no admin-window advice).
        acl = Mock(side_effect=lic.GuardRefusedError())
        with patch.object(platform, 'IS_WINDOWS', True), patch.dict(sys.modules, license=fake_license(acl)), \
                tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(platform.AccessProblem) as caught: platform.claim(Path(temp).resolve() / 'x')
        self.assertFalse(caught.exception.elevated)


class FakeFunction:
    """A DLL function stand-in: every argument must pass its declared argtype's from_param."""
    def __init__(self, name, handler, log):
        self.name, self.handler, self.log, self.argtypes, self.restype = name, handler, log, None, None

    def __call__(self, *args):
        assert self.argtypes is not None and len(args) == len(self.argtypes), self.name
        for kind, value in zip(self.argtypes, args): kind.from_param(value)
        self.log.append(self.name)
        return self.handler(*args)


class Win32GlueTests(unittest.TestCase):
    """The ctypes layer against fake kernel32/advapi32 functions. It checks the Python glue and
    the argument types only; real Win32 behaviour is a laptop item."""

    def test_ctypes_layer_calls_and_buffers(self):
        import ctypes
        sd = enc_sd(BA, [(ME, True), (SY, True)])
        keep, log, applied = {}, [], {}

        def out(ref, value): ref._obj.value = value
        def security_info(h, kind, info, o, g, d, s, descriptor):
            keep['sd'] = ctypes.create_string_buffer(sd, len(sd)); out(descriptor, ctypes.addressof(keep['sd'])); return 0
        def token_info(token, kind, buffer, size, needed):
            if buffer is None: out(needed, 64); return 0
            keep['sid'] = ctypes.create_string_buffer(enc_sid(ME))
            ctypes.memmove(buffer, ctypes.byref(ctypes.c_void_p(ctypes.addressof(keep['sid']))), ctypes.sizeof(ctypes.c_void_p))
            return 1
        def file_info(h, info):
            info = ctypes.cast(info, ctypes.POINTER(ctypes.c_ulong * 13)).contents if not isinstance(info, ctypes.Array) else info
            info[0], info[10] = 0x10, 1; return 1
        def final(h, buffer, size, flags): buffer.value = '\\\\?\\C:\\ilson-course'; return len(buffer.value)
        def membership(token, sid, member): out(member, int(bytes(sid.raw[:len(enc_sid(BA))]) == enc_sid(BA))); return 1
        def apply(h, kind, info, owner, group, dacl, sacl):
            applied.update(info=info, owner=bytes(owner.raw), dacl=None if dacl is None else bytes(dacl.raw)); return 0
        handlers = {
            'CreateFileW': lambda *a: 100, 'CloseHandle': lambda h: 1, 'GetFileInformationByHandle': file_info,
            'GetFinalPathNameByHandleW': final, 'GetCurrentProcess': lambda: 2**64 - 1, 'LocalFree': lambda p: None,
            'GetSecurityInfo': security_info, 'SetSecurityInfo': apply, 'GetSecurityDescriptorLength': lambda p: len(sd),
            'OpenProcessToken': lambda p, access, token: (out(token, 7), 1)[1], 'GetTokenInformation': token_info,
            'GetLengthSid': lambda p: len(enc_sid(ME)), 'CheckTokenMembership': membership,
        }
        dll = SimpleNamespace(**{name: FakeFunction(name, handler, log) for name, handler in handlers.items()})
        with patch.object(ctypes, 'WinDLL', return_value=dll, create=True), patch.object(ctypes, 'get_last_error', return_value=5, create=True):
            w32 = course_license.Win32()
            self.assertTrue(w32.guarded())
            self.assertEqual(w32.user_sid(), ME)
            handle = w32.open('C:\\ilson-course', True)
            self.assertEqual(w32.info(handle), (0x10, 1))
            self.assertEqual(w32.final_path(handle), '\\\\?\\C:\\ilson-course')
            self.assertEqual(course_license.parse_security_descriptor(w32.security(handle)), (BA, [(ME, True, True), (SY, True, True)], False))
            dacl = course_license.private_dacl(ME, True)
            w32.set_security(handle, course_license.sid_bytes(ME), dacl)
            self.assertEqual(applied, {'info': 0x80000005, 'owner': enc_sid(ME), 'dacl': dacl})
            w32.set_security(handle, course_license.sid_bytes(ME), None)
            self.assertEqual((applied['info'], applied['dacl']), (1, None))
            w32.close(handle)
            self.assertIn('LocalFree', log)
            dll.CreateFileW.handler = lambda *a: 2**64 - 1  # INVALID_HANDLE_VALUE
            with self.assertRaises(course_license.Win32Error) as caught: w32.open('C:\\x', False)
            self.assertEqual((caught.exception.code, course_license._failure(caught.exception)), (5, 'denied'))
            dll.GetSecurityInfo.handler = lambda *a: 32
            with self.assertRaises(course_license.Win32Error) as caught: w32.security(100)
            self.assertEqual(course_license._failure(caught.exception), 'error')


if __name__ == '__main__':
    unittest.main()
