"""Course-only command: license protects learning, not the student's documents."""
import os
from pathlib import Path
import subprocess
import sys


def main(argv):
    if not argv or argv[0] not in ('learn', 'license', 'skill'):
        print('사용법: ilson learn ... | ilson skill share|list|get|withdraw | ilson license activate|status')
        return 0 if not argv or argv[0] in ('-h', '--help') else 2
    lib = Path(__file__).resolve().parent
    home = Path(os.environ.get('ILSON_COURSE_STATE', Path.home() / '.ilson-course'))
    vault = Path(os.environ.get('ILSON_COURSE_VAULT', Path.home() / 'Documents' / '일손강의-1기'))
    license_cmd = [sys.executable, '-X', 'utf8', str(lib / 'license.py'), '--home', str(home)]
    if argv[0] == 'license':
        return subprocess.call(license_cmd + (argv[1:] or ['status']))
    if subprocess.call(license_cmd + ['check']):
        return 1
    if argv[0] == 'skill':
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'skill_share.py'),
                                '--home', str(vault), '--license-home', str(home), '--flat-vault'] + argv[1:])
    return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'selflearn.py'),
                            '--home', str(vault), '--flat-vault'] + argv[1:])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
