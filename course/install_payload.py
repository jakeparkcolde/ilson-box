"""Install the embedded course helper without replacing existing files."""
import base64
import gzip
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError('helper directory is not a normal directory')
    root.mkdir(parents=True, exist_ok=True)
    files = json.loads(gzip.decompress(base64.b64decode(os.environ['ILSON_COURSE_PAYLOAD'])))
    if set(files) != {'ilson.py', 'license.py', 'selflearn.py'}:
        raise ValueError('invalid helper bundle')
    for name, content in files.items():
        path = root / name
        data = content.encode('utf-8')
        if path.is_symlink():
            raise ValueError('helper path is a link')
        if path.exists():
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError('existing helper differs; ask the instructor')
        else:
            with path.open('xb') as stream:
                stream.write(data)


if __name__ == '__main__':
    main()
