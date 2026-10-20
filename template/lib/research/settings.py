"""공통 대화/리서치 LLM 설정. 예약 업무의 실행기는 변경하지 않는다."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile


def load(home):
    path = Path(home) / 'state' / 'ai-settings.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    provider, model = data.get('provider', 'claude'), data.get('model', '')
    if provider not in ('claude', 'codex') or not isinstance(model, str) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', model)):
        raise ValueError('기본 LLM 설정을 확인하세요: ilson llm claude 또는 ilson llm codex')
    return {'provider': provider, 'model': model}


def save(home, provider, model=''):
    data = {'provider': provider, 'model': model}
    if provider not in ('claude', 'codex') or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', model)):
        raise ValueError('LLM 설정 형식 오류')
    path = Path(home) / 'state' / 'ai-settings.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)
    return data


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--home', type=Path, required=True)
    p.add_argument('provider', nargs='?', choices=['claude', 'codex']); p.add_argument('model', nargs='?', default='')
    p.add_argument('--chat', action='store_true'); a = p.parse_args()
    data = save(a.home, a.provider, a.model) if a.provider else load(a.home)
    if a.chat:
        args = [data['provider']]
        if data['provider'] == 'claude': args += ['--permission-mode', 'auto']
        if data['model']: args += ['--model', data['model']]
        os.chdir(a.home); os.environ['PWD'] = str(a.home); os.execvp(args[0], args)
    print(json.dumps({**data, 'research': 'native', 'scheduled_jobs': 'claude'}, ensure_ascii=False))
