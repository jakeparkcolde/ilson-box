"""이전에 검증한 리서치 팩의 팩 전용 파일에 현재 template 코드를 얹어 새 팩 ZIP을 만든다.

The repository template is the source of truth for the pack's code: template/lib/research/*.py ships as the
top-level modules and template/web/current/pack-library/* as web/*. Only the pack's own files (serve.py,
start.sh, README.txt, ...) come from the previous pack. build_release refuses any pack that differs.
"""
import argparse
import ast
import importlib.util
import io
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('refresh_builder', ROOT / 'tools/build_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

# The research pack manifest as of 0.16.1. It holds no file hashes; an unknown key means an unknown format.
MANIFEST_KEYS = {'id', 'version', 'requires', 'llm_one_of', 'optional'}
REQUIRED = ('manifest.json', 'serve.py')
DATE = (2026, 1, 1, 0, 0, 0)


def version_tuple(value):
    # Pack versions have always been three numbers (0.14.0, 0.15.3, 0.16.1).
    parts = value.split('.') if isinstance(value, str) else []
    if len(parts) != 3 or any(not p.isdecimal() for p in parts):
        raise ValueError('팩 버전 형식 오류: ' + repr(value))
    return tuple(map(int, parts))


def pack_name(rel):
    if rel.startswith('template/lib/research/'):
        return rel[len('template/lib/research/'):]
    return 'web/' + rel[len('template/web/current/pack-library/'):]


def allowed_web_files(serve):
    # serve.py only serves the web files named in its top-level ALLOWED_FILES literal. None when it cannot be read.
    try:
        tree = ast.parse(serve)
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ALLOWED_FILES' for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            if isinstance(value, (set, frozenset, list, tuple)) and all(isinstance(v, str) for v in value):
                return set(value)
            return None
    return None


def read_previous(pack):
    # Returns {name: (data, unix mode)} for the previous pack, refusing anything outside the known layout.
    files = {}
    with zipfile.ZipFile(pack) as z:
        for info in z.infolist():
            name = info.filename
            parts = name.rstrip('/').split('/')
            if name.startswith('/') or '\\' in name or any(p in ('', '.', '..') for p in parts):
                raise ValueError('알 수 없는 팩 경로: ' + name)
            if info.is_dir():
                if name == 'web/':
                    continue
                raise ValueError('알 수 없는 팩 폴더: ' + name)
            mode = info.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise ValueError('팩의 링크는 허용하지 않습니다: ' + name)
            if len(parts) > 1 and parts[0] != 'web':
                raise ValueError('알 수 없는 팩 구성(web/ 밖의 하위 폴더): ' + name)
            if name in files:
                raise ValueError('팩에 같은 파일이 두 번 있습니다: ' + name)
            files[name] = (z.read(info), mode & 0o777 or 0o644)
    missing = [name for name in REQUIRED if name not in files]
    if missing:
        raise ValueError('팩 필수 파일이 없습니다: ' + ', '.join(missing))
    return files


def refresh(previous, version, output):
    files = read_previous(previous)
    manifest = json.loads(files['manifest.json'][0])
    if not isinstance(manifest, dict) or set(manifest) - MANIFEST_KEYS or manifest.get('id') != 'research':
        raise ValueError('알 수 없는 팩 manifest 형식입니다')
    if version_tuple(version) <= version_tuple(manifest.get('version')):
        raise ValueError('새 팩 버전은 이전 버전보다 커야 합니다: ' + manifest['version'] + ' → ' + version)
    # Pack-only files: everything top level that the template does not own, plus serve.py.
    own = {name: body for name, body in files.items()
           if name != 'manifest.json' and '/' not in name and (not name.endswith('.py') or name == 'serve.py')}
    code = {pack_name(rel): ((ROOT / rel).read_bytes(), 0o644) for rel in builder.pack_sources()}
    clash = sorted(set(own) & set(code))
    if clash:
        raise ValueError('template 파일이 팩 전용 파일과 겹칩니다: ' + ', '.join(clash))
    rows = dict(own, **code)
    web = sorted(name[len('web/'):] for name in rows if name.startswith('web/'))
    allowed = allowed_web_files(rows['serve.py'][0])
    if allowed is None:
        print('경고: serve.py의 ALLOWED_FILES 목록을 읽지 못해 웹 파일 허용 목록을 확인하지 않았습니다.')
    elif set(web) - allowed:
        raise ValueError('serve.py ALLOWED_FILES에 없는 웹 파일이 있습니다: ' + ', '.join(sorted(set(web) - allowed)))
    readme = rows.get('README.txt', (b'', 0))[0].decode('utf-8', 'replace')
    others = sorted(set(re.findall(r'(?<![0-9.])[0-9]+\.[0-9]+\.[0-9]+(?![0-9.])', readme)) - {version})
    if others:
        print('참고: README.txt는 그대로 두었습니다. 다른 버전 표기가 있습니다:', ', '.join(others))
    rows['manifest.json'] = ((json.dumps(dict(manifest, version=version), ensure_ascii=False, indent=2) + '\n').encode(), 0o644)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(rows):
            data, mode = rows[name]
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, data)
    with Path(output).open('xb') as stream:
        stream.write(buf.getvalue())
    print('리서치 팩:', output, '· 버전', version, '· 팩 전용', len(own), '· template', len(code))
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description='Refresh a research pack from the current template sources.')
    p.add_argument('--from', dest='previous', type=Path, required=True, help='previous verified pack ZIP')
    p.add_argument('--version', required=True, help='new pack version, greater than the previous one')
    p.add_argument('--output', type=Path, required=True, help='new pack ZIP (must not exist)')
    a = p.parse_args(argv)
    refresh(a.previous, a.version, a.output)


if __name__ == '__main__':
    main()
