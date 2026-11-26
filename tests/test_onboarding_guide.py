"""Onboarding 2-step compression, live `ilson guide`/`quickstart`, and canonical GitHub Releases feed tests."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FEED = 'https://github.com/jakeparkcolde/ilson-box/releases/latest/download/latest-v2.json'


class OnboardingGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ilson-guide-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.box = self.home / 'ilson'
        self.fakebin = self.base / 'fakebin'
        self.fakebin.mkdir()
        self.env = {
            k: v for k, v in os.environ.items()
            if not k.startswith('ILSON_')
        }
        self.env.update(
            HOME=str(self.home),
            ILSON_HOME=str(self.box),
            ILSON_CHECK_TIMEOUT='1',
            PATH=f'{self.fakebin}:/usr/bin:/bin:/usr/sbin:/sbin',
        )

    def make_fake(self, name, body):
        path = self.fakebin / name
        path.write_text('#!/bin/bash\n' + body + '\n', encoding='utf-8')
        path.chmod(0o700)
        return path

    def run_cli(self, *args, extra_env=None, timeout=10):
        env = dict(self.env, **(extra_env or {}))
        return subprocess.run(
            ['bash', str(ROOT / 'ilson'), *args],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def run_shell_fn(self, script, timeout=8):
        functions = (ROOT / 'ilson').read_text(encoding='utf-8').split('cmd="${1:-}"')[0]
        harness = self.base / 'harness.sh'
        harness.write_text(functions + '\ndiag_verify() { return 0; };\n' + script, encoding='utf-8')
        proc = subprocess.Popen(
            ['bash', str(harness)],
            cwd=ROOT,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            self.fail('shell harness timed out')
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def stage_box(self, *, company_name='(인터뷰에서 채움)', complete=False, trusted=False):
        (self.box / 'vault').mkdir(parents=True, exist_ok=True)
        (self.box / 'state').mkdir(parents=True, exist_ok=True)
        (self.box / 'CLAUDE.md').write_text('# rules\n', encoding='utf-8')
        (self.box / 'vault/CONTEXT.md').write_text(f'- 회사명: {company_name}\n', encoding='utf-8')
        if complete:
            (self.box / 'state/setup-pending').unlink(missing_ok=True)
            (self.box / 'state/setup-complete').write_text('1\n', encoding='utf-8')
        else:
            (self.box / 'state/setup-complete').unlink(missing_ok=True)
            (self.box / 'state/setup-pending').write_text('1\n', encoding='utf-8')
        if trusted:
            (self.home / '.claude.json').write_text(
                json.dumps({'projects': {str(self.box): {'hasTrustDialogAccepted': True}}}),
                encoding='utf-8',
            )

    def test_guide_and_quickstart_work_without_license_and_are_read_only(self):
        # Even without any license file or staged box, guide and quickstart exit 0 and write nothing.
        for cmd in ('guide', 'quickstart'):
            with self.subTest(cmd=cmd):
                r = self.run_cli(cmd)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn('[필수 2단계]', r.stdout)
                self.assertIn('[선택 항목', r.stdout)
                self.assertIn('다음 실행할 명령:\n  ilson setup', r.stdout)
                self.assertFalse(self.box.exists())
                self.assertFalse((self.home / '.claude.json').exists())

    def test_guide_progression_from_login_to_onboard_to_start_to_complete(self):
        self.make_fake('jq', 'exec /usr/bin/env python3 -c \'import json,sys\n'
                       'args=sys.argv[1:]\n'
                       'data=json.load(sys.stdin if args[-1] not in ("-e",) and not args[-1].startswith("/") else (open(args[-1]) if args[-1].startswith("/") else sys.stdin))\n'
                       '\' "$@"')
        # Use system jq via PATH if available, otherwise skip only if jq missing.
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if real_jq:
            (self.fakebin / 'jq').unlink()
            self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        else:
            self.skipTest('jq required')

        # Step 1a: box staged, claude installed but not logged in -> next command is `claude`
        self.stage_box()
        self.make_fake('claude', 'echo \'{"loggedIn": false}\'')
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('⏳ Claude 로그인 필요', r.stdout)
        self.assertIn('다음 실행할 명령:\n  claude\n', r.stdout)

        # Step 1b: claude logged in, box untrusted & empty CONTEXT.md -> next command is `cd "..." && claude /onboard`
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('✅ Claude 로그인 완료', r.stdout)
        self.assertIn('⏳ 박스 폴더 신뢰 필요', r.stdout)
        self.assertIn('⏳ 회사 정보(CONTEXT.md) 미입력', r.stdout)
        self.assertIn(f'다음 실행할 명령:\n  cd "{self.box}" && claude /onboard\n', r.stdout)

        # Step 2: trusted + company filled, still setup-pending -> next command is `ilson start`
        self.stage_box(company_name='테스트 주식회사', complete=False, trusted=True)
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('✅ 박스 폴더 신뢰 완료', r.stdout)
        self.assertIn('✅ 회사 정보(CONTEXT.md) 준비 완료', r.stdout)
        self.assertIn('⏳ 예약 업무 대기 중 (state/setup-pending)', r.stdout)
        self.assertIn('다음 실행할 명령:\n  ilson start\n', r.stdout)

        # Step 3: setup-complete -> next command is `ilson open` + ilson.work pointer
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('✅ 예약 업무 가동 중 (state/setup-complete)', r.stdout)
        self.assertIn('다음 실행할 명령:\n  ilson open\n', r.stdout)
        self.assertIn('https://ilson.work', r.stdout)

    def test_guide_optional_statuses_codex_telegram_cloud(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        self.make_fake('codex', 'if [ "$1" = login ] && [ "$2" = status ]; then exit 0; fi; exit 1')
        # Telegram-only pairing.json must show telegram connected, cloud NOT connected.
        (self.box / 'state/pairing.json').write_text(
            json.dumps({'telegram_bot_token': '123:TEST', 'telegram_chat_id': 99}),
            encoding='utf-8',
        )
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('✅ Codex 자동 폴백 (선택): 준비됨', r.stdout)
        self.assertIn('✅ 텔레그램 알림 (선택): 연결됨', r.stdout)
        self.assertIn('⚪ 클라우드 ilson.work 연결 (선택): 미연결', r.stdout)

        # Adding state/cloud-pairing.json switches cloud to connected.
        (self.box / 'state/cloud-pairing.json').write_text('{"office_id":"test"}\n', encoding='utf-8')
        r = self.run_cli('guide')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('✅ 클라우드 ilson.work 연결 (선택): 연결됨', r.stdout)

    def test_legacy_ilson_work_feed_warns_in_doctor_and_guide_without_echoing_url(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        legacy = 'https://ilson.work/downloads/box/latest-v2.json'
        (self.box / '.updates').mkdir(parents=True, exist_ok=True)
        (self.box / '.updates/feed').write_text(legacy + '\n', encoding='utf-8')

        # 1. check_update_feed (used by ilson doctor)
        r = self.run_shell_fn(f'SELF_DIR="{ROOT}"; check_update_feed; echo "W=$WARN F=$FAIL P=$PASS"')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('W=1 F=0 P=0', r.stdout)
        self.assertIn('구버전 업데이트 주소 사용 중', r.stdout)
        self.assertIn(f'ilson update --feed {CANONICAL_FEED}', r.stdout)
        self.assertNotIn(legacy, r.stdout)

        # 2. ilson guide recommends migration command when Step 1 & 2 are done
        g = self.run_cli('guide')
        self.assertEqual(g.returncode, 0, g.stdout + g.stderr)
        self.assertIn('구버전 업데이트 주소 사용 중', g.stdout)
        self.assertIn(f'ilson update --feed {CANONICAL_FEED}', g.stdout)
        self.assertIn(f'다음 실행할 명령:\n  ilson update --feed {CANONICAL_FEED}\n', g.stdout)
        self.assertNotIn(legacy, g.stdout)

        # 3. Switching to canonical GitHub Releases feed clears the warning
        (self.box / '.updates/feed').write_text(CANONICAL_FEED + '\n', encoding='utf-8')
        r2 = self.run_shell_fn(f'SELF_DIR="{ROOT}"; check_update_feed; echo "W=$WARN F=$FAIL P=$PASS"')
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn('W=0 F=0 P=1', r2.stdout)
        self.assertNotIn('구버전 업데이트 주소 사용 중', r2.stdout)

    def test_setup_post_install_guide_is_compressed_to_two_required_steps_plus_optional(self):
        tool = self.make_fake('tailscale', 'echo \'{"BackendState":"NeedsLogin"}\'')
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        r = self.run_shell_fn(
            f'TEMPLATE="{ROOT}/template"; TS_BIN="{tool}"; '
            'setup_tools() { return 0; }; setup_web_admin() { return 0; }; '
            'claude_logged_in() { return 1; }; setup'
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('필수 2단계 (지금 바로 시작):', r.stdout)
        self.assertIn('1. Claude 로그인 + 회사 소개:', r.stdout)
        self.assertIn('2. 예약 업무 시작: ilson start', r.stdout)
        self.assertIn('https://ilson.work', r.stdout)
        self.assertIn('ilson open', r.stdout)
        self.assertIn('ilson guide', r.stdout)
        self.assertIn('선택 확장 (나중에 필요할 때 — 지금 안 해도 사용 가능):', r.stdout)
        self.assertIn('ilson telegram connect', r.stdout)
        # Old 11-bullet wall header is gone
        self.assertNotIn('사람이 마칠 단계:', r.stdout)

    def test_canonical_github_releases_feed_is_consistent_across_updater_and_cli(self):
        spec = importlib.util.spec_from_file_location('updater_canon', ROOT / 'tools/update.py')
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        self.assertEqual(updater.FEED, '')
        self.assertEqual(updater.DEFAULT_FEED, CANONICAL_FEED)
        self.assertIn(f"CANONICAL_FEED='{CANONICAL_FEED}'", (ROOT / 'ilson').read_text(encoding='utf-8'))
        self.assertIn(CANONICAL_FEED, (ROOT / 'install.sh').read_text(encoding='utf-8'))
        self.assertIn(CANONICAL_FEED, (ROOT / 'README.md').read_text(encoding='utf-8'))
        # No stale ilson.work/downloads/box feed in active installers or tools
        for rel in (
            'install.sh',
            'tools/update.py',
            'tools/build_release.py',
            'tools/bootstrap.sh',
            'tools/bootstrap.ps1',
            'tools/doctor.sh',
            'tools/doctor.ps1',
            'course/install-intel-mac.sh',
            'course/install-windows.ps1',
            'course/install_payload.py',
        ):
            self.assertNotIn('ilson.work/downloads/box', (ROOT / rel).read_text(encoding='utf-8'), rel)

    def test_usage_documents_guide_and_quickstart(self):
        r = self.run_cli('--help')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('guide | quickstart', r.stdout)

    def test_doctor_sh_and_template_doctor_sh_stay_in_sync_and_print_network_hint(self):
        self.assertEqual(
            (ROOT / 'tools/doctor.sh').read_bytes(),
            (ROOT / 'template/lib/doctor.sh').read_bytes(),
        )
        # Verify tools/bootstrap.ps1 remains pure ASCII for Windows PowerShell 5.1
        (ROOT / 'tools/bootstrap.ps1').read_bytes().decode('ascii')
        (ROOT / 'tools/doctor.ps1').read_bytes().decode('ascii')

    def _make_company_cli(self, *, role, active=True, vault_company_name='주식회사 테스트'):
        """Build an isolated CLI dir whose access_policy.py runs real logic against a temp company."""
        cli = self.base / f'cli-{role}-{active}'
        (cli / 'template/lib').mkdir(parents=True, exist_ok=True)
        (cli / 'tools').mkdir(parents=True, exist_ok=True)
        (cli / 'ilson').write_bytes((ROOT / 'ilson').read_bytes())
        (cli / 'tools/update.py').write_bytes((ROOT / 'tools/update.py').read_bytes())
        shared = self.base / f'shared-{role}-{active}'
        vault = shared / 'acme/vault'
        (vault / 'company').mkdir(parents=True, exist_ok=True)
        (vault / 'company/CONTEXT.md').write_text(f'- 회사명: {vault_company_name}\n', encoding='utf-8')
        uid = os.geteuid()
        owner_uid = uid if role == 'owner' else uid + 100
        staff_uid = uid + 100 if role == 'owner' else uid
        cfg = {
            'schema': 1,
            'id': 'acme',
            'owner_uid': owner_uid,
            'runtime': str(self.box),
            'vault': str(vault),
            'defaults': {
                'company_staff_write': True,
                'personal_private': True,
                'licence': 'one-company-device',
                'employee_web': False,
            },
            'people': [
                {'id': 'boss', 'account': 'boss', 'uid': owner_uid, 'role': 'owner', 'active': True},
                {'id': 'alice', 'account': 'alice', 'uid': staff_uid, 'role': 'staff', 'active': active},
            ],
        }
        wrapper = (
            'import sys\n'
            'from pathlib import Path\n'
            f'sys.path.insert(0, {str(ROOT / "template/lib")!r})\n'
            'import access_policy as ap\n'
            f'ap.SHARED = Path({str(shared)!r})\n'
            f'ap._trusted_config = lambda _path: {cfg!r}\n'
            'raise SystemExit(ap.main())\n'
        )
        (cli / 'template/lib/access_policy.py').write_text(wrapper, encoding='utf-8')
        return cli, vault

    def test_company_malformed_symlink_and_offboarded_fail_closed_on_guide(self):
        self.stage_box(company_name='단독 폴백 금지 회사', complete=True, trusted=True)

        # 1. Malformed company.json must fail closed, never falling back to solo vault/CONTEXT.md
        (self.box / 'state/company.json').write_text('{broken json\n', encoding='utf-8')
        r = self.run_cli('guide')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('[필수 2단계]', r.stdout)

        # company_context_path must also fail non-zero rather than falling back to solo vault
        r_ctx = self.run_shell_fn(f'TEMPLATE="{ROOT}/template"; company_context_path')
        self.assertNotEqual(r_ctx.returncode, 0, r_ctx.stdout + r_ctx.stderr)
        self.assertEqual(r_ctx.stdout, '')

        # 2. Symlinked company.json (both dangling and target-existing) must fail closed
        (self.box / 'state/company.json').unlink()
        (self.box / 'state/company.json').symlink_to(self.base / 'missing-company.json')
        r_dang = self.run_cli('guide')
        self.assertNotEqual(r_dang.returncode, 0, r_dang.stdout + r_dang.stderr)
        self.assertNotIn('[필수 2단계]', r_dang.stdout)

        target = self.base / 'elsewhere-company.json'
        target.write_text('{"company":"acme"}\n', encoding='utf-8')
        (self.box / 'state/company.json').unlink()
        (self.box / 'state/company.json').symlink_to(target)
        r_link = self.run_cli('guide')
        self.assertNotEqual(r_link.returncode, 0, r_link.stdout + r_link.stderr)
        self.assertNotIn('[필수 2단계]', r_link.stdout)

        # 3. Offboarded (active=False) employee must fail closed
        (self.box / 'state/company.json').unlink()
        (self.box / 'state/company.json').write_text('{"company":"acme"}\n', encoding='utf-8')
        cli_off, _ = self._make_company_cli(role='staff', active=False)
        r_off = subprocess.run(
            ['bash', str(cli_off / 'ilson'), 'guide'],
            cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(r_off.returncode, 0, r_off.stdout + r_off.stderr)
        self.assertNotIn('[필수 2단계]', r_off.stdout)
        self.assertNotIn('[직원 사용 안내]', r_off.stdout)

    def test_company_staff_gets_employee_guidance_without_owner_commands(self):
        self.stage_box(company_name='단독 폴백 회사', complete=False, trusted=False)
        (self.box / 'state/company.json').write_text('{"company":"acme"}\n', encoding='utf-8')
        cli_staff, _ = self._make_company_cli(role='staff', active=True)
        r = subprocess.run(
            ['bash', str(cli_staff / 'ilson'), 'guide'],
            cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('회사 모드: 직원', r.stdout)
        self.assertIn('https://ilson.work', r.stdout)
        self.assertIn('대표', r.stdout)
        for forbidden in ('ilson setup', 'claude /onboard', 'ilson start', 'ilson open'):
            self.assertNotIn(forbidden, r.stdout, forbidden)

    def test_company_owner_proceeds_to_guide_using_shared_company_context(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        # Solo CONTEXT.md is empty placeholder, while shared company vault CONTEXT.md is populated.
        self.stage_box(company_name='(인터뷰에서 채움)', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        (self.box / 'state/company.json').write_text('{"company":"acme"}\n', encoding='utf-8')
        cli_owner, _ = self._make_company_cli(role='owner', active=True, vault_company_name='대표 법인')
        r = subprocess.run(
            ['bash', str(cli_owner / 'ilson'), 'guide'],
            cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('[필수 2단계]', r.stdout)
        self.assertIn('✅ 회사 정보(CONTEXT.md) 준비 완료', r.stdout)
        self.assertIn('다음 실행할 명령:\n  ilson open\n', r.stdout)

    def test_cloud_paired_and_telegram_reject_symlinks_and_invalid_json(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        state = self.box / 'state'

        # 1. Symlinked cloud-runner.json & cloud-pairing.json must NOT count as connected
        valid_target = self.base / 'real-cloud.json'
        valid_target.write_text('{"runner_id":"abc"}\n', encoding='utf-8')
        for fname in ('cloud-runner.json', 'cloud-pairing.json'):
            f = state / fname
            f.symlink_to(valid_target)
            r = self.run_shell_fn('cloud_paired')
            self.assertNotEqual(r.returncode, 0, f'symlink {fname} should not pass')
            f.unlink()

        # 2. Malformed, empty object, array, scalar JSON must NOT count as connected (jq AND python3 fallback)
        for bad in ('{broken json', '{}', '[]', '"string"', '123', 'null', ''):
            with self.subTest(bad=bad):
                (state / 'cloud-runner.json').write_text(bad, encoding='utf-8')
                r_jq = self.run_shell_fn('cloud_paired')
                self.assertNotEqual(r_jq.returncode, 0, f'jq accepted {bad!r}')
                r_py = self.run_shell_fn('has() { [ "$1" != jq ] && command -v "$1" >/dev/null 2>&1; }; cloud_paired')
                self.assertNotEqual(r_py.returncode, 0, f'python3 accepted {bad!r}')
        (state / 'cloud-runner.json').unlink()

        # 3. Valid non-empty JSON object passes under both jq and python3 fallback
        (state / 'cloud-runner.json').write_text('{"runner_id":"r1"}\n', encoding='utf-8')
        self.assertEqual(self.run_shell_fn('cloud_paired').returncode, 0)
        self.assertEqual(
            self.run_shell_fn('has() { [ "$1" != jq ] && command -v "$1" >/dev/null 2>&1; }; cloud_paired').returncode,
            0,
        )
        (state / 'cloud-runner.json').unlink()

        # 4. Symlinked pairing.json rejected by both cloud_paired and telegram_configured
        pair_target = self.base / 'real-pairing.json'
        pair_target.write_text(
            json.dumps({'telegram_bot_token': '123:TEST', 'telegram_chat_id': 99, 'cloud_office': 'x'}),
            encoding='utf-8',
        )
        (state / 'pairing.json').symlink_to(pair_target)
        self.assertNotEqual(self.run_shell_fn('cloud_paired').returncode, 0)
        self.assertNotEqual(self.run_shell_fn('telegram_configured').returncode, 0)
        (state / 'pairing.json').unlink()

        # 5. Symlinked $ILSON_HOME/state dir rejected by both cloud_paired and telegram_configured
        real_state = self.base / 'elsewhere-state'
        real_state.mkdir()
        (real_state / 'cloud-runner.json').write_text('{"runner_id":"r1"}\n', encoding='utf-8')
        (real_state / 'pairing.json').write_text(
            json.dumps({'telegram_bot_token': '123:TEST', 'telegram_chat_id': 99}),
            encoding='utf-8',
        )
        for child in list(state.iterdir()):
            child.unlink()
        state.rmdir()
        state.symlink_to(real_state)
        self.assertNotEqual(self.run_shell_fn('cloud_paired').returncode, 0)
        self.assertNotEqual(self.run_shell_fn('telegram_configured').returncode, 0)

    def test_is_deprecated_feed_url_anchored_and_case_insensitive(self):
        cases = [
            ('https://ilson.work/downloads/box/latest-v2.json', True),
            ('https://ILSON.WORK/downloads/box/latest-v2.json', True),
            ('https://ilson.work:443/downloads/box/latest-v2.json', True),
            ('https://www.ilson.work/downloads/box/latest-v2.json', True),
            ('http://WWW.ILSON.WORK:80/downloads/box?v=2', True),
            ('https://ilson.work/downloads/box', True),
            ('https://mirror.example.com/proxy?u=https://ilson.work/downloads/box/latest-v2.json', False),
            ('https://ilson.work/other/downloads/box/foo', False),
            ('https://ilson.work/downloads/box2/latest-v2.json', False),
            ('https://evil-ilson.work/downloads/box/latest-v2.json', False),
            (CANONICAL_FEED, False),
        ]
        script = '\n'.join(
            f'if is_deprecated_feed_url {json.dumps(url)}; then echo 1; else echo 0; fi'
            for url, _ in cases
        )
        r = self.run_shell_fn(script)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        results = [line == '1' for line in r.stdout.strip().splitlines()]
        self.assertEqual(len(results), len(cases))
        for (url, expected), actual in zip(cases, results):
            with self.subTest(url=url):
                self.assertEqual(actual, expected)

    def test_feed_precedence_and_env_override_guidance_in_guide_and_doctor(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        (self.box / '.updates').mkdir(parents=True, exist_ok=True)
        (self.box / '.updates/feed').write_text('not-a-valid-url\n', encoding='utf-8')

        # 1. Valid ILSON_UPDATE_FEED overrides broken .updates/feed in guide
        g_valid = self.run_cli('guide', extra_env={'ILSON_UPDATE_FEED': CANONICAL_FEED})
        self.assertEqual(g_valid.returncode, 0, g_valid.stdout + g_valid.stderr)
        self.assertIn('✅ 업데이트 주소 (선택): GitHub Releases 기본 배포 사용 가능', g_valid.stdout)
        self.assertNotIn('주소 파일 확인 필요', g_valid.stdout)
        self.assertIn('다음 실행할 명령:\n  ilson open\n', g_valid.stdout)

        # 2. Deprecated ILSON_UPDATE_FEED suggests `unset ILSON_UPDATE_FEED && ilson update --feed ...`
        dep_env = 'https://ILSON.WORK/downloads/box/latest-v2.json'
        expected_fix = f'unset ILSON_UPDATE_FEED && ilson update --feed {CANONICAL_FEED}'
        g_dep = self.run_cli('guide', extra_env={'ILSON_UPDATE_FEED': dep_env})
        self.assertEqual(g_dep.returncode, 0, g_dep.stdout + g_dep.stderr)
        self.assertIn('ILSON_UPDATE_FEED', g_dep.stdout)
        self.assertIn(expected_fix, g_dep.stdout)
        self.assertIn(f'다음 실행할 명령:\n  {expected_fix}\n', g_dep.stdout)
        self.assertNotIn(dep_env, g_dep.stdout)

        # Same for check_update_feed (ilson doctor)
        d_dep = self.run_shell_fn(
            f'SELF_DIR="{ROOT}"; ILSON_UPDATE_FEED="{dep_env}"; check_update_feed; echo "W=$WARN F=$FAIL P=$PASS"'
        )
        self.assertEqual(d_dep.returncode, 0, d_dep.stdout + d_dep.stderr)
        self.assertIn('W=1 F=0 P=0', d_dep.stdout)
        self.assertIn(expected_fix, d_dep.stdout)
        self.assertNotIn(dep_env, d_dep.stdout)

        # 3. Stamped FEED in tools/update.py overrides broken .updates/feed in guide
        fake_cli = self.base / 'stamped-cli'
        (fake_cli / 'tools').mkdir(parents=True)
        (fake_cli / 'tools/update.py').write_text(f"FEED='{CANONICAL_FEED}'\n", encoding='utf-8')
        r_stamped = self.run_shell_fn(f'SELF_DIR="{fake_cli}"; guide')
        self.assertEqual(r_stamped.returncode, 0, r_stamped.stdout + r_stamped.stderr)
        self.assertIn('✅ 업데이트 주소 (선택): GitHub Releases 기본 배포 사용 가능', r_stamped.stdout)
        self.assertNotIn('주소 파일 확인 필요', r_stamped.stdout)

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root can read mode 000 files')
    def test_unreadable_feed_file_handled_without_stderr_noise(self):
        real_jq = subprocess.run(['which', 'jq'], capture_output=True, text=True).stdout.strip()
        if not real_jq:
            self.skipTest('jq required')
        self.env['PATH'] = f'{self.fakebin}:{Path(real_jq).parent}:/usr/bin:/bin:/usr/sbin:/sbin'
        self.stage_box(company_name='테스트 주식회사', complete=True, trusted=True)
        self.make_fake('claude', 'echo \'{"loggedIn": true}\'')
        feed = self.box / '.updates/feed'
        feed.parent.mkdir(parents=True, exist_ok=True)
        feed.write_text(CANONICAL_FEED + '\n', encoding='utf-8')
        feed.chmod(0o000)
        self.addCleanup(lambda: feed.exists() and feed.chmod(0o600))

        r_doc = self.run_shell_fn(f'SELF_DIR="{ROOT}"; check_update_feed; echo "W=$WARN F=$FAIL P=$PASS"')
        self.assertEqual(r_doc.returncode, 0, r_doc.stdout + r_doc.stderr)
        self.assertIn('W=1 F=0 P=0', r_doc.stdout)
        self.assertEqual(r_doc.stderr, '')

        r_dep = self.run_shell_fn('saved_feed_deprecated')
        self.assertNotEqual(r_dep.returncode, 0)
        self.assertEqual(r_dep.stderr, '')

        r_guide = self.run_cli('guide')
        self.assertEqual(r_guide.returncode, 0, r_guide.stdout + r_guide.stderr)
        self.assertIn('주소 파일 확인 필요', r_guide.stdout)
        self.assertEqual(r_guide.stderr, '')


if __name__ == '__main__':
    unittest.main()
