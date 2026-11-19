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
