"""Generate identical reviewed native recorder bytes; no downloads at installer start."""
from pathlib import Path
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[1]

def pack():
    spec = importlib.util.spec_from_file_location('install_diagnostics', ROOT / 'template/lib/install_diagnostics.py')
    diagnostics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostics)
    pattern = diagnostics.VERSION_PATTERN
    # These are generated values, including the native recorders embedded below.
    for suffix, declaration in [('sh', "DIAG_VERSION_PATTERN='"), ('ps1', "$script:DiagVersionPattern = '")]:
        path = ROOT / ('tools/diagnostics.' + suffix)
        source = path.read_text()
        source, count = re.subn(r'(?m)^' + re.escape(declaration) + r"[^']*'$",
                                lambda _: declaration + pattern + "'", source)
        if count != 1: raise ValueError(str(path.relative_to(ROOT)))
        path.write_text(source)
    schema_path = ROOT / 'tools/diagnostic-schema.json'
    schema = json.loads(schema_path.read_text())
    for key in diagnostics.VERSION_FIELDS:
        field = schema['properties']['environment']['properties'][key]
        field['pattern'] = pattern
        # JSON Schema regex search permits a final newline at $. Native callers
        # reject line breaks separately; express the same guard in the schema.
        field['not'] = {'pattern': r'[\r\n]'}
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'course/lib/install_diagnostics.py').write_bytes((ROOT / 'template/lib/install_diagnostics.py').read_bytes())
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
