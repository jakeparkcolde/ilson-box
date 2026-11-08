"""Install the embedded course helper without replacing existing files."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

# Only the exact course entry point from 8c67266 is eligible for replacement.
# Unknown or edited files remain protected by the existing no-overwrite rule.
SHARE_SELFLEARN_SHA256 = '48b6804a599765af19f6ab35c75409986fb5bd3e52967bdd52d1386119ee528d'
SHARE_ILSON_SHA256 = '70c922f15483534e401dccf7f7fefdea88c4be1102b32196ad00fb60f4fa4bff'
LEGACY_ILSON_SHA256 = 'b8491dea3dd3f9b9bf82070c0a054d669386f083a68f1380f0a44e6a141cc5e4'


def main():
    root = Path(sys.argv[1])
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError('helper directory is not a normal directory')
    root.mkdir(parents=True, exist_ok=True)
    files = json.loads(gzip.decompress(base64.b64decode(os.environ['ILSON_COURSE_PAYLOAD'])))
    if set(files) != {'ilson.py', 'license.py', 'selflearn.py', 'skill_share.py', 'weekly_summary.py'}:
        raise ValueError('invalid helper bundle')
    replacements = []
    missing = []
    for name, content in files.items():
        path = root / name
        data = content.encode('utf-8')
        if path.is_symlink():
            raise ValueError('helper path is a link')
        if path.exists():
            if not path.is_file():
                raise ValueError('existing helper differs; ask the instructor')
            old = path.read_bytes()
            if old != data:
                if not ((name == 'ilson.py' and hashlib.sha256(old).hexdigest() in (LEGACY_ILSON_SHA256, SHARE_ILSON_SHA256)) or (name == 'selflearn.py' and hashlib.sha256(old).hexdigest() == SHARE_SELFLEARN_SHA256)):
                    raise ValueError('existing helper differs; ask the instructor')
                replacements.append((path, old, data))
        else:
            missing.append((path, data))
    # Install dependencies first so the old entry point remains usable if writing fails.
    for path, data in missing:
        with path.open('xb') as stream:
            stream.write(data)
    for path, old, data in replacements:
        fd, temporary = tempfile.mkstemp(prefix='.ilson-update-', dir=root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if path.is_symlink() or path.read_bytes() != old:
                raise ValueError('existing helper changed; ask the instructor')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


if __name__ == '__main__':
    main()
