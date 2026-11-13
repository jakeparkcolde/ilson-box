"""Install the embedded course helper without replacing existing files."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


# Only exact published/baseline bytes may be replaced. Unknown user edits stay intact.
KNOWN_HELPER_SHA256 = {'ilson.py': {'70c922f15483534e401dccf7f7fefdea88c4be1102b32196ad00fb60f4fa4bff', '39d10d5e65089bc23e53c09e720e594195891ccb60438253651de6546bb83182', 'b8491dea3dd3f9b9bf82070c0a054d669386f083a68f1380f0a44e6a141cc5e4'}, 'license.py': {'4b6e50b84073c6e8178b3c0c3c8055839a9d7d607be284ce3e0651e929e15ba9'}, 'selflearn.py': {'48b6804a599765af19f6ab35c75409986fb5bd3e52967bdd52d1386119ee528d', 'b1eabe4380dbd53cc3f35d1a0a82f511f96b04320b2bb585925478f7d8e60b68'}, 'skill_share.py': {'b233d29be73af4e7f9c63a3e948b51ee2946607ea61b71c30f9c473e82fa7412'}, 'weekly_summary.py': {'10a7935d68726ef63457014e64a2702ba0a22167a65c8aa002f3e8a994d48bf7'}}
ALLOWED_FILES = set(KNOWN_HELPER_SHA256) | {'install_diagnostics.py'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    for part in [path, *path.parents]:
        if sys.platform == 'darwin' and str(part) in ('/var', '/tmp', '/etc') and os.readlink(part) in ('/private' + str(part), 'private' + str(part)): continue
        if part.is_symlink() or (part.exists() and getattr(part.stat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('helper path is a link')


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.ilson-update-', dir=path.parent)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def install(root, files):
    safe(root)
    if root.exists() and not root.is_dir(): raise ValueError('helper directory is not a normal directory')
    if set(files) != ALLOWED_FILES or any(not isinstance(value, str) for value in files.values()):
        raise ValueError('invalid helper bundle')
    changes = []
    for name, content in files.items():
        data = content.encode('utf-8'); compile(content, name, 'exec')
        path = root / name; safe(path)
        if path.exists() and not path.is_file(): raise ValueError('existing helper differs; ask the instructor')
        old = path.read_bytes() if path.exists() else None
        if old == data: continue
        if old is not None and digest(old) not in KNOWN_HELPER_SHA256.get(name, set()):
            raise ValueError('existing helper differs; ask the instructor: ' + name)
        changes.append((path, old, data))
    root.mkdir(parents=True, exist_ok=True)
    if not changes: return None
    base = root / '.install-backups'; safe(base); base.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='upgrade-', dir=base))
    manifest = {'schema': 1, 'files': []}
    for path, old, data in changes:
        if old is not None: (backup / path.name).write_bytes(old)
        manifest['files'].append({'name': path.name, 'before': digest(old) if old is not None else None, 'after': digest(data)})
    (backup / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
    applied = []
    try:
        # Dependencies first, entry point last. Validate every target again before replacing.
        for path, old, data in sorted(changes, key=lambda item: item[0].name == 'ilson.py'):
            safe(path)
            current = path.read_bytes() if path.exists() else None
            if current != old: raise ValueError('existing helper changed; ask the instructor')
            if old is None:
                with path.open('xb') as stream: stream.write(data)
            else: atomic_write(path, data)
            applied.append((path, old, data))
        for path, _, data in changes:
            if path.read_bytes() != data: raise ValueError('helper verification failed')
    except Exception:
        for path, old, data in reversed(applied):
            safe(path)
            if path.read_bytes() != data: continue
            if old is None: path.unlink()
            else: atomic_write(path, old)
        raise
    print('HELPER_UPGRADE_BACKUP=' + backup.name)
    return backup


def rollback(root, backup):
    safe(root); safe(backup)
    if backup.parent != root / '.install-backups' or not backup.name.startswith('upgrade-'):
        raise ValueError('invalid helper backup')
    manifest_path = backup / 'manifest.json'; safe(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    changes = []
    if manifest.get('schema') != 1: raise ValueError('invalid helper backup')
    seen = set()
    for item in manifest['files']:
        name = item['name']
        if name not in ALLOWED_FILES or name in seen: raise ValueError('invalid helper backup')
        seen.add(name)
        path = root / name; safe(path)
        if not path.is_file() or digest(path.read_bytes()) != item['after']:
            raise ValueError('existing helper changed; rollback preserved user edits')
        data = None
        if item['before'] is not None:
            old = backup / name; safe(old); data = old.read_bytes()
            if digest(data) != item['before']: raise ValueError('invalid helper backup')
        changes.append((path, data))
    for path, data in sorted(changes, key=lambda item: item[0].name == 'ilson.py'):
        if data is None: path.unlink()
        else: atomic_write(path, data)


def main():
    root = Path(sys.argv[1]).absolute()
    if len(sys.argv) == 4 and sys.argv[2] == '--rollback':
        rollback(root, root / '.install-backups' / sys.argv[3]); return
    # The installer streams the bundle after its bootstrap line. Neither environment
    # variables nor command-line arguments can carry arbitrarily large bundles.
    files = json.loads(gzip.decompress(base64.b64decode(sys.stdin.buffer.read())))
    install(root, files)


if __name__ == '__main__':
    main()
