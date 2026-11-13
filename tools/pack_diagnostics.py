"""Generate identical reviewed native recorder bytes; no downloads at installer start."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def pack():
    for suffix, paths in [('sh', ['ilson', 'install.sh', 'course/install-intel-mac.sh', 'tools/doctor.sh', 'tools/bootstrap.sh']),
                          ('ps1', ['course/install-windows.ps1', 'tools/doctor.ps1', 'tools/bootstrap.ps1'])]:
        source = (ROOT / ('tools/diagnostics.' + suffix)).read_text()
        for name in paths:
            path = ROOT / name
            if not path.exists(): continue
            text = path.read_text()
            if '# DIAGNOSTICS_BEGIN\n' not in text: continue
            text, count = re.subn(r'(?ms)^# DIAGNOSTICS_BEGIN\n.*?^# DIAGNOSTICS_END$',
                                 lambda _: '# DIAGNOSTICS_BEGIN\n' + source.rstrip() + '\n# DIAGNOSTICS_END', text)
            if count != 1: raise ValueError(name)
            with path.open('w', encoding='utf-8', newline='\n') as stream: stream.write(text)
    for name in ('diagnostics.sh', 'doctor.sh'):
        (ROOT / 'template/lib' / name).write_bytes((ROOT / 'tools' / name).read_bytes())

if __name__ == '__main__': pack()
