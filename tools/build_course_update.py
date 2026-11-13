"""Print an immutable course update pin from committed installer bytes; never publish/fetch."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(source_ref, edition):
    if not re.fullmatch('[a-f0-9]{40}', source_ref) or edition not in ('intel-course', 'windows-course'):
        raise ValueError('immutable source revision and course edition required')
    filename = 'install-windows.ps1' if edition == 'windows-course' else 'install-intel-mac.sh'
    data = subprocess.check_output(['git', 'show', source_ref + ':course/' + filename], cwd=ROOT)
    return {'schema': 1, 'edition': edition, 'source_ref': source_ref, 'sha256': hashlib.sha256(data).hexdigest()}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-ref', required=True)
    p.add_argument('--edition', required=True, choices=('intel-course', 'windows-course'))
    args = p.parse_args()
    print(json.dumps(build(args.source_ref, args.edition), sort_keys=True, indent=2))
