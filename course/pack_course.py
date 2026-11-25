"""Refresh embedded, self-contained course files after editing their sources."""
import base64
import gzip
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
def build_files():
    files = {}
    files['usage_timeline.py'] = (root / 'course/lib/usage_timeline.py').read_text(encoding='utf-8')
    files['usage_sync.py'] = (root / 'course/lib/usage_sync.py').read_text(encoding='utf-8')
    files['ilson.py'] = (root / 'course/ilson.py').read_text(encoding='utf-8')
    files['license.py'] = (root / 'course/lib/license.py').read_text(encoding='utf-8')
    files['selflearn.py'] = (root / 'course/lib/selflearn.py').read_text(encoding='utf-8')
    files['weekly_summary.py'] = (root / 'course/lib/weekly_summary.py').read_text(encoding='utf-8')
    files['install_diagnostics.py'] = (root / 'course/lib/install_diagnostics.py').read_text(encoding='utf-8')
    files['curator.py'] = (root / 'course/lib/curator.py').read_text(encoding='utf-8')
    files['course_update.py'] = (root / 'course/lib/course_update.py').read_text(encoding='utf-8')
    files['install_payload.py'] = (root / 'course/install_payload.py').read_text(encoding='utf-8')
    files['skill_share.py'] = (root / 'course/lib/skill_share.py').read_text(encoding='utf-8')
    for name in (
        'web-admin-server.py', 'web-admin.py', 'course_admin.py', 'ilson_platform.py',
        'access_policy.py', 'approval_store.py', 'approval_dispatch.py', 'approval_actions.py',
        'runtime_gate.py', 'replies_draft.py', 'cloud_bridge.py',
        'social/__init__.py', 'social/http.py', 'social/meta_publish.py',
    ):
        files[name] = (root / 'template/lib' / name).read_text(encoding='utf-8')
    for name in ('web/course.html', 'web/course.js', 'web/course.css', 'web/current/base.css', 'web/current/shell.css', 'web/usage-history.js', 'web/usage-history.css'):
        files[name] = (root / 'template' / name).read_text(encoding='utf-8')
    return files


def refresh():
    files = build_files()
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
        with path.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(source)

if __name__ == "__main__":
    refresh()
