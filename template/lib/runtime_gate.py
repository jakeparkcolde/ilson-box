"""관리자 요청·외부 실행과 코드 교체를 같은 파일 잠금으로 분리한다."""
from contextlib import contextmanager
import fcntl
from pathlib import Path

@contextmanager
def running(home):
    store=Path(home)/'.updates'
    store.mkdir(exist_ok=True)
    path=store/'runtime.lock'
    if store.is_symlink() or path.is_symlink():raise ValueError('업데이트 잠금 경로를 확인하세요')
    with path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        yield
