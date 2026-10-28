"""공통 대화/리서치 LLM 설정. 예약 업무의 실행기는 변경하지 않는다."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

# Codex does not discover CLAUDE.md as its default project instructions. Supply an
# initial user prompt, leaving the user's AGENTS files and Codex config intact.
CODEX_CHAT_PROMPT = (
    '현재 작업 폴더는 사용자가 선택한 일손 Box입니다. 먼저 이 폴더의 CLAUDE.md를 읽고 '
    'Box 업무 규칙을 확인한 뒤 사용자의 요청을 기다리세요. 기존 AGENTS.md와 사용자 지침도 존중하세요. '
    '직원 등록 요청에는 .claude/commands/employee.md를 일반 지침 문서로 읽고 공식 ilson people을 사용하세요. '
    '이름·역할이 없으면 먼저 질문하고, ILSON_HOME을 현재 Box로 명시하며, 같은 등록 재시도에는 '
    '같은 요청 ID와 입력을 사용하세요. JSON ok와 실제 직원 ID 확인 전에는 성공을 말하지 마세요. '
    '별도 Markdown 직원 명단이나 직접 SQLite 편집으로 대체하지 마세요. '
    '아직 요청하지 않은 직원 등록이나 설정 변경은 실행하지 마세요.'
)


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
        if data['provider'] == 'codex': args += [CODEX_CHAT_PROMPT]
        os.chdir(a.home); os.environ['PWD'] = str(a.home); os.execvp(args[0], args)
    print(json.dumps({**data, 'research': 'native', 'scheduled_jobs': 'claude'}, ensure_ascii=False))
