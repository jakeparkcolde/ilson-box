"""Copy the course starter files once, leaving all existing user files untouched."""
import os
from pathlib import Path
import sys


def install(source, home):
    source = Path(source)
    home = Path(home)
    if not source.is_dir():
        raise ValueError('강의 키트 원본이 없습니다. 일손 CLI를 다시 설치하세요.')
    if home.is_symlink():
        raise ValueError('Box 폴더가 연결 경로입니다. 위치를 확인하세요.')
    home.mkdir(parents=True, exist_ok=True)
    dest = home / '강의키트-20261109'
    if dest.is_symlink():
        raise ValueError('강의 키트 폴더가 연결 경로입니다. 위치를 확인하세요.')
    dest.mkdir(exist_ok=True)
    for src in sorted(source.glob('*.md')):
        target = dest / src.name
        try:
            with target.open('xb') as output:
                output.write(src.read_bytes())
        except FileExistsError:
            continue
    print('강의 키트:', dest)
    print('기존 파일은 그대로 두었습니다. 시작과_막힘_복구.md를 여세요.')


if __name__ == '__main__':
    try:
        install(sys.argv[1], sys.argv[2])
    except (OSError, ValueError) as error:
        print('강의 키트를 만들지 못했습니다:', error, file=sys.stderr)
        sys.exit(1)
