"""검색·모델을 바꾸지 않고 원문 입력 예산만 비교하는 명시적 실험."""
import copy
import math
import re

try:
    from .evidence import excerpt, prepare_sources
    from .run import ResearchError
except ImportError:
    from evidence import excerpt, prepare_sources
    from run import ResearchError


EXPERIMENTS = ('baseline', 'evidence_budget_v1', 'concise_answer_v1', 'evidence_concise_v1')
BUDGETS = {'quick': 9000, 'deep': 14000}


def validate(experiment, model):
    if experiment not in EXPERIMENTS:
        raise ResearchError('지원하지 않는 조사 실험')
    if model is not None and (not isinstance(model, str) or not re.fullmatch(
            r'(?:sonnet|opus|haiku|claude-[A-Za-z0-9._-]{1,100})', model)):
        raise ResearchError('모델 이름을 확인하세요')


def snapshot_sources(snapshot):
    """생성 결과 대신 capture 경로에서 얻은 자료만 실험 입력으로 받는다."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('sources'), list) or not snapshot['sources']:
        raise ResearchError('비교할 원문 자료를 확인하세요')
    rows = snapshot['sources']
    ids = [row.get('id') for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or any(type(item) is not int or item < 1 for item in ids) or len(set(ids)) != len(ids):
        raise ResearchError('원문 출처 번호를 확인하세요')
    if any(not all(isinstance(row.get(key), str) for key in ('title', 'url', 'content')) for row in rows):
        raise ResearchError('비교할 원문 형식을 확인하세요')
    coverage = snapshot.get('coverage')
    if not isinstance(coverage, dict) or any(not isinstance(coverage.get(key), list) or
            any(not isinstance(value, str) for value in coverage[key]) for key in ('attempts', 'failures')):
        raise ResearchError('원문 검색 이력을 확인하세요')
    # 알 수 없는 필드(예: 이전 답변)는 다음 모델의 입력으로 들어갈 수 없다.
    allowed = {'id', 'title', 'url', 'content', 'published_date', 'method', 'read_status',
               'read_note', 'read_error', 'cache_hit', 'content_trimmed'}
    return [{key: copy.deepcopy(value) for key, value in row.items() if key in allowed} for row in rows], copy.deepcopy(coverage)


def _focused_excerpt(text, question, limit):
    result = excerpt(text, question, limit)
    if len(text) <= limit:
        return result
    ignored = {'what', 'how', 'the', 'and', 'vs', 'versus', '차이', '비교', '알려줘', '설명해줘'}
    terms = sorted({term for term in re.findall(r'[\w-]{2,}', question) if term.casefold() not in ignored})
    terms = sorted(set(terms) | {re.sub(r'(?:와|과|의|은|는|이랑|랑)$', '', term) for term in terms
                                if re.search(r'(?:와|과|의|은|는|이랑|랑)$', term) and
                                len(re.sub(r'(?:와|과|의|은|는|이랑|랑)$', '', term)) >= 2})
    matches = [match for term in terms if (match := re.search(re.escape(term), text, re.I))]
    if not matches or all(match.group().casefold() in result.casefold() for match in matches):
        return result
    # 600자 단락 단위의 기존 발췌로 비교 대상 한쪽이 사라지면 원문의 짧은 구간을
    # 고른다. 요약문을 만들지 않고 첫 부분·질의어 주변을 원래 순서로 보존한다.
    marker = '\n[…]\n'
    width = (limit - len(marker) * len(matches)) // (len(matches) + 1)
    if width < max(match.end() - match.start() for match in matches):
        return result
    spans = [(0, min(width, len(text)))]
    for match in matches:
        begin = max(0, match.start() - max(0, width - (match.end() - match.start())) // 2)
        spans.append((begin, min(len(text), begin + width)))
    merged = []
    for begin, end in sorted(spans):
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    return marker.join(text[begin:end] for begin, end in merged)[:limit]


def prepare(question, sources, mode, experiment):
    validate(experiment, None)
    rows = prepare_sources(question, sources, mode)
    budget = BUDGETS[mode] if experiment in ('evidence_budget_v1', 'evidence_concise_v1') else None
    if budget is not None and sum(len(row['content']) for row in rows) > budget:
        # 짧은 검색 발췌문은 그대로 두고 남는 예산을 나눈다. 자료의 순서·번호·방법은
        # 바꾸지 않으므로 검색 정렬 변경과 입력 예산 효과가 섞이지 않는다.
        limits = [0] * len(rows)
        active = list(range(len(rows)))
        remaining = budget
        while active:
            share, extra = divmod(remaining, len(active))
            short = [index for index in active if len(rows[index]['content']) <= share]
            if not short:
                for position, index in enumerate(active):
                    limits[index] = share + (position < extra)
                break
            for index in short:
                limits[index] = len(rows[index]['content'])
                remaining -= limits[index]
            active = [index for index in active if index not in short]
        for row, limit in zip(rows, limits):
            before = row['content']
            row['content'] = _focused_excerpt(before, question, limit)
            row['content_trimmed'] = row.get('content_trimmed', False) or row['content'] != before
    return rows, {'pipeline_id': experiment, 'evidence_budget_characters': budget,
                  'supplied_evidence_characters': sum(len(row['content']) for row in rows)}


def model_metrics(envelope, requested_model):
    """CLI 결과의 허용된 집계값만 보존한다. API 환산액은 구독 청구액이 아니다."""
    usage = envelope.get('usage')
    token_keys = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
    counts = {key: value for key in token_keys if isinstance(usage, dict) and
              type(value := usage.get(key)) is int and value >= 0}
    model_usage = envelope.get('modelUsage')
    models = sorted(key for key in model_usage if isinstance(key, str) and
                    re.fullmatch(r'claude-[A-Za-z0-9._-]{1,100}', key)) if isinstance(model_usage, dict) else []
    cost = envelope.get('total_cost_usd')
    cost = cost if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0 else None
    return {'requested_model': requested_model, 'actual_models': models, 'usage': counts,
            'estimated_api_cost_usd': cost}
