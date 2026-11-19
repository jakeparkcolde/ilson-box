"""Shared setup for tests that run the Windows course installer under pwsh.

The tests run real PowerShell code, so they must never reach the network and must
not depend on host quirks that the product would rightly reject:

* every network primitive in course/install-windows.ps1 is replaced by a test
  client before the script runs, and a dead proxy is set as a second guard;
* temporary homes are realpath'd (macOS TMPDIR lives under the /var symlink,
  which the installer's reparse-point check correctly refuses);
* the diagnostics root is created by Python with 0700 and the child runs with
  umask 077, because on non-Windows hosts New-IlsonDiagDirectory falls back to
  plain CreateDirectory (Windows itself uses an owner-only ACL instead).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'course/install-windows.ps1'
WEBCLIENT = 'New-Object Net.WebClient'
# Anything that could open a connection from the installer source.
NETWORK_PRIMITIVES = ('Net.WebClient', 'Invoke-WebRequest', 'Invoke-RestMethod', 'HttpClient',
                      'Start-BitsTransfer', 'DownloadFile', 'DownloadString', 'WebRequest]::Create')
DEAD_PROXY = 'http://127.0.0.1:9'


# Host gap, not a product bug: course/ilson.py reports its edition from os.name, so
# on a non-Windows test host the real helper answers `ilson intel-course ILSON-DIAG-1`
# and the installer's absolute check (which wants `windows-course`) records
# VERIFY_FAILED with native exit 0. On Windows os.name == 'nt' and the check passes.
# Only this one step is tolerated, and only off Windows; every other required step
# must still succeed or fail exactly as each test expects.
HOST_EDITION_GAP = frozenset() if os.name == 'nt' else frozenset({('verify.absolute', 'VERIFY_FAILED')})
# Mirrors Complete-IlsonDiagnostics: these reasons never make a required step count as failed.
NEUTRAL_REASONS = ('DRY_RUN', 'NOT_APPLICABLE', 'NOT_SELECTED')


def failed_required_steps(home):
    """(step_id, reason_code) of every required step-end that sets INSTALL_RESULT=1."""
    runs = Path(home) / 'diagnostics/runs'
    failed = set()
    for events in runs.glob('*/events.jsonl'):
        for line in events.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if (event.get('event') == 'step-end' and event.get('required') and event.get('result') != 'ok'
                    and event.get('reason_code') not in NEUTRAL_REASONS):
                failed.add((event['step_id'], event['reason_code']))
    return failed


def assert_install_result(test, result, home, expected_failures=frozenset(), helper_verified=True,
                          file_mode=True):
    """Exact required-step failures and the exit code the installer must derive from them.

    helper_verified: the helper installed, so verify.absolute ran and HOST_EDITION_GAP applies.
    file_mode: a file run exits with INSTALL_RESULT; under `irm | iex` the session stays open,
    the process exits 0 and the code is left in $global:IlsonInstallExitCode.
    """
    expected = set(expected_failures) | (set(HOST_EDITION_GAP) if helper_verified else set())
    test.assertEqual(failed_required_steps(home), expected, result.stdout + result.stderr)
    code = 1 if expected else 0
    test.assertEqual(result.returncode, code if file_mode else 0, result.stdout + result.stderr)
    test.assertIn('INSTALL_RESULT=%d' % code, result.stdout)


def find_pwsh():
    return os.environ.get('ILSON_TEST_PWSH') or shutil.which('pwsh')


def offline_installer_source():
    """Installer text with its single download client swapped for New-TestClient.

    Callers must define `function New-TestClient` in their mocks. Raises if the
    installer gains a network path this helper does not neutralize.
    """
    source = INSTALLER.read_text(encoding='ascii')
    if source.count(WEBCLIENT) != 1:
        raise AssertionError('install-windows.ps1 download client changed; update tests/pwsh_support.py')
    source = source.replace(WEBCLIENT, 'New-TestClient')
    code = '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
    leaked = [name for name in NETWORK_PRIMITIVES if name in code]
    if leaked:
        raise AssertionError('unmocked network path in install-windows.ps1: ' + ', '.join(leaked))
    return source.replace('[IO.Path]::GetPathRoot($env:USERPROFILE).Substring(0,1)', "'T'")


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def offline_env(home, **extra):
    """Environment for a pwsh child: sealed proxies and a private diagnostics root."""
    home = Path(home)
    diagnostics = private_dir(home / 'diagnostics')
    private_dir(diagnostics / 'runs')
    env = dict(os.environ, USERPROFILE=str(home), LOCALAPPDATA=str(home), ProgramFiles=str(home),
               ILSON_DIAGNOSTICS_DIR=str(diagnostics))
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env[key] = DEAD_PROXY
    for key in ('NO_PROXY', 'no_proxy'):
        env.pop(key, None)
    env.update({key: str(value) for key, value in extra.items()})
    return env


def run_pwsh(pwsh, script, *args, env, timeout=30):
    posix = {'umask': 0o077} if os.name == 'posix' else {}
    return subprocess.run([pwsh, '-NoProfile', '-File', str(script), *map(str, args)], env=env,
                          text=True, capture_output=True, timeout=timeout, **posix)
