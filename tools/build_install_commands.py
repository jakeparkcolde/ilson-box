"""Build reviewable immutable installer/standalone-doctor one-liners. Never publish or fetch."""
import argparse
import base64
import hashlib
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'full-mac': 'install.sh', 'intel-course': 'course/install-intel-mac.sh',
           'windows-course': 'course/install-windows.ps1', 'doctor-mac': 'tools/doctor.sh',
           'doctor-windows': 'tools/doctor.ps1'}


def build(source_ref, target, sha256=None):
    if not re.fullmatch('[a-f0-9]{40}', source_ref): raise ValueError('immutable 40-character source revision required')
    name = TARGETS[target]
    digest = sha256 or hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    if not re.fullmatch('[a-f0-9]{64}', digest): raise ValueError('invalid SHA-256')
    url = 'https://raw.githubusercontent.com/jakeparkcolde/ilson-box/' + source_ref + '/' + name
    windows = target.endswith('windows') or target == 'windows-course'
    edition = target if target in ('full-mac', 'intel-course', 'windows-course') else 'unknown'
    if windows:
        source = (ROOT / 'tools/bootstrap.ps1').read_text(encoding='ascii')
        encoded = base64.b64encode(source.encode('ascii')).decode('ascii')
        return "& ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')))) -Url '" + url + "' -Sha256 '" + digest + "' -Edition '" + edition + "'" + (' -Doctor' if target == 'doctor-windows' else '')
    source = (ROOT / 'tools/bootstrap.sh').read_bytes()
    encoded = base64.b64encode(source).decode('ascii')
    return 'sh -c "$(printf %s ' + shlex.quote(encoded) + ' | base64 -D)" sh ' + ' '.join(shlex.quote(v) for v in [url, digest, edition, 'doctor' if target == 'doctor-mac' else 'installer'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-ref', required=True)
    parser.add_argument('--target', choices=TARGETS, required=True)
    args = parser.parse_args()
    print(build(args.source_ref, args.target))


if __name__ == '__main__': main()
