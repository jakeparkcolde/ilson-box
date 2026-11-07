"""Refresh embedded, self-contained course files after editing their sources."""
import base64
import gzip
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
files = {
    'ilson.py': (root / 'course/ilson.py').read_text(encoding='utf-8'),
    'license.py': (root / 'course/lib/license.py').read_text(encoding='utf-8'),
    'selflearn.py': (root / 'course/lib/selflearn.py').read_text(encoding='utf-8'),
    'skill_share.py': (root / 'course/lib/skill_share.py').read_text(encoding='utf-8'),
}
payload = base64.b64encode(gzip.compress(json.dumps(files, ensure_ascii=False, sort_keys=True).encode('utf-8'), mtime=0)).decode('ascii')
bootstrap = base64.b64encode((root / 'course/install_payload.py').read_bytes()).decode('ascii')
guide = base64.b64encode((root / 'course/00_강의_시작.md').read_bytes()).decode('ascii')
rules = base64.b64encode((root / 'course/CLAUDE.md').read_bytes()).decode('ascii')

for name in ('install-intel-mac.sh', 'install-windows.ps1'):
    path = root / 'course' / name
    source = path.read_text(encoding='utf-8')
    for key, value in (('PAYLOAD', payload), ('BOOTSTRAP', bootstrap), ('GUIDE', guide), ('RULES', rules)):
        pattern = r'(?m)^(# COURSE_' + key + r'_BEGIN\n).*?(\n# COURSE_' + key + r'_END)$'
        if name.endswith('.ps1'):
            variable = '$Course' + key.title()
        else:
            variable = 'COURSE_' + key
        source, count = re.subn(pattern, lambda m: m.group(1) + variable + "='" + value + "'" + m.group(2), source, flags=re.S)
        if count != 1:
            raise RuntimeError(f'{name}: expected one {key} marker, got {count}')
    path.write_text(source, encoding='utf-8', newline='\n')
