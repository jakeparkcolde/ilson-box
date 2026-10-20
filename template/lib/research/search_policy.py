"""질문별 검색 계획과 근거 신호. 어휘 일치는 사실 검증이나 정답 판정이 아니다."""
import re
from urllib.parse import urlsplit


_STOP = {'차이', '비교', '알려줘', '알려주세요', '어떻게', '무엇', '뭐야', '얼마',
         '얼마나', '어떤', '거리', '시간', '소요시간', '코스', '요금', '요금제',
         '가격', '비용', '혜택', '포함', '기능', '추천', '현재', '최신', '오늘',
         '기준', '한국', '국내', '미국', '일본', '유럽', '에서', '까지', '그리고',
         '같은', '되는', '있는', '대한', '하고', '대해', '하나', 'vs', 'versus'}
_OFFICIAL = (
    # 한국어 조사가 붙은 Python에서/Python의도 공식 문서 대상이다.
    (r'(?<![A-Za-z0-9])python(?=$|[^A-Za-z0-9])|파이썬', ('docs.python.org',)),
    (r'구글|google|gemini|제미나이', ('google.com',)),
    (r'애플|apple|아이폰|iphone', ('apple.com',)),
    (r'국립공원|설악산|흔들바위|울산바위', ('knps.or.kr',)),
    (r'openai|chatgpt|챗지피티', ('openai.com',)),
    (r'perplexity|퍼플렉시티', ('perplexity.ai',)),
)
_FACETS = {
    'distance': ('거리', r'\d[\d.,]*\s*(?:km|킬로미터|m\b|미터)'),
    'duration': ('소요 시간', r'\d[\d.,]*\s*(?:시간|분|hours?\b|minutes?\b)'),
    'route_basis': ('출발점·도착점 및 편도/왕복 기준', r'편도|왕복|one[- ]way|round[- ]trip'),
    'price': ('금액·통화·결제 주기', r'(?:[$€₩]\s*\d|\d[\d.,]*\s*(?:원|달러|usd\b|krw\b|eur\b))'),
    'benefits': ('포함되는 혜택과 기능', r'포함|제공|이용\s*가능|혜택|includes?\b|features?\b'),
    'exceptions': ('제외·제한·자격 조건', r'제외|제한|조건|대상|한도|불가|eligible|exclud|limit|restrict'),
    'validity': ('적용 시점과 기간', r'(?:20\d{2}[년./-]|\d{1,2}월\s*\d{1,2}일|유효\s*기간|적용\s*기간|시행일|effective\s+(?:date|from)|valid\s+(?:until|from))'),
}


def _tokens(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9+.-]*|[가-힣]+|\d+', text.lower())
    result = []
    for word in words:
        # 지명·상품명 조사만 제거한다. 짧은 이름 자체를 깎지 않는다.
        for suffix in ('에서는', '에서', '까지', '으로', '이랑', '에는', '에게', '은', '는', '을', '를', '와', '과', '의'):
            if word.endswith(suffix) and len(word) - len(suffix) >= 2:
                word = word[:-len(suffix)]
                break
        if word not in _STOP and len(word) >= 2 and word not in result:
            result.append(word)
    return result[:12]


def _entities(question):
    # 구분이 명확할 때만 두 독립 질의로 나눈다. 추정한 제품명을 만들지 않는다.
    base = re.split(r'\s*(?:차이|비교|중에|중에서|어느|어떤)', question, maxsplit=1)[0].strip()
    parts = re.split(r'\s+(?:vs\.?|versus|대)\s+|\s*(?:와|과|랑|하고)\s+', base, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        parts = re.split(r'(?<=[가-힣])(?:와|과)(?=[가-힣A-Za-z])', base, maxsplit=1)
    if len(parts) == 2 and all(1 <= len(part.strip()) <= 90 for part in parts):
        return [part.strip() for part in parts]
    return []


def question_plan(question):
    """모델을 부르지 않는 제한된 계획. 불명확한 비교 대상은 분리하지 않는다."""
    text = question.strip()
    comparison = bool(re.search(r'비교|차이|\bvs\.?\b|\bversus\b', text, re.I))
    distance = bool(re.search(r'거리|소요\s*시간|(?:등산|코스|까지).{0,12}시간', text))
    pricing = bool(re.search(r'요금|가격|비용|혜택|구독|보상판매|할인', text))
    kind = 'comparison' if comparison else 'distance_time' if distance else 'pricing' if pricing else 'general'
    entities = _entities(text) if comparison else []
    facets = []
    topic_terms = _tokens(text)
    facets.append(dict(key='topic', label='질문의 대상', terms=topic_terms))
    if comparison:
        for index, entity in enumerate(entities):
            facets.append(dict(key='entity_' + str(index + 1), label=entity, terms=_tokens(entity)))
        if not entities:
            facets.append(dict(key='comparison_entities', label='비교 대상 두 개', terms=[]))
    if distance:
        keys = (['distance'] if '거리' in text else []) + (['duration'] if '시간' in text else []) + ['route_basis']
        for key in keys:
            facets.append(dict(key=key, label=_FACETS[key][0], terms=[]))
    if pricing:
        for key in ('price', 'benefits', 'exceptions', 'validity'):
            facets.append(dict(key=key, label=_FACETS[key][0], terms=[]))
        region = next((s for s in ('한국', '국내', '미국', '일본', '유럽') if s in text), None)
        facets.append(dict(key='region', label='적용 지역', terms=[region] if region else []))
    elif re.search(r'현재|최신|오늘|올해|20\d{2}', text):
        facets.append(dict(key='validity', label=_FACETS['validity'][0], terms=[]))
    # 비교축은 원 질문에 그대로 보존하고, 대상별 독립 검색의 앞부분만 바꾼다.
    queries = [(entity + ' ' + text)[:400] for entity in entities] if len(entities) == 2 else [text[:400]]
    return dict(kind=kind, facets=facets, entities=entities, topic_terms=topic_terms,
                concise=kind in ('distance_time', 'general'), primary_queries=queries,
                heuristic=True)


def official_domains_for(question, configured=()):
    domains = []
    for domain in configured:
        if not isinstance(domain, str):
            continue
        value = domain.lower().strip().strip('.')
        if re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) and '.' in value and value not in domains:
            domains.append(value)
    for pattern, candidates in _OFFICIAL:
        if re.search(pattern, question, re.I):
            domains.extend(domain for domain in candidates if domain not in domains)
    return domains


def official_candidate(url, domains):
    """질문에 연결한 도메인 일치일 뿐, 원문 진위나 주장의 정확성 판정은 아니다."""
    host = (urlsplit(url).hostname or '').lower().removeprefix('www.')
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def evidence_coverage(plan, rows):
    """원문과 제목에서 필요한 신호를 찾는다. 날짜·수치의 실제 정합성은 별도 검토한다."""
    reports = []
    for facet in plan['facets']:
        key, terms = facet['key'], facet['terms']
        source_ids = []
        for row in rows:
            text = (str(row.get('title', '')) + '\n' + str(row.get('content', ''))).lower()
            topic_terms=plan['topic_terms']
            topical=(any(_tokens(entity) and all(term in text for term in _tokens(entity)) for entity in plan['entities'])
                     if plan['kind']=='comparison' and plan['entities'] else
                     bool(topic_terms) and all(term in text for term in topic_terms))
            # 2026-10-06 재현: 다른 노선의 km·편도 표기로 현재 질문의 누락을
            # 메우지 않는다. 조건·수치는 질문 대상에 연결되는 자료에서만 센다.
            if key!='topic' and not topical:
                continue
            if key == 'topic' and plan['kind']=='comparison' and plan['entities']:
                present = any(_tokens(entity) and all(term in text for term in _tokens(entity)) for entity in plan['entities'])
            elif key == 'region':
                patterns = {'한국': r'한국|대한민국|국내|korea', '국내': r'한국|대한민국|국내|korea',
                            '미국': r'미국|united states|\bus\b', '일본': r'일본|japan', '유럽': r'유럽|europe'}
                present = bool(re.search(patterns.get(terms[0], r'(?!)'), text)) if terms else False
            elif key in _FACETS:
                present = bool(re.search(_FACETS[key][1], text, re.I))
            elif key == 'comparison_entities':
                present = False
            else:
                # 일부 어휘만 맞는 별개 상품/노선을 충분하다고 처리하지 않는다.
                present = bool(terms) and all(term in text for term in terms)
            if present:
                source_ids.append(row['id'])
        reports.append(dict(key=key, label=facet['label'],
                            status='signal_present' if source_ids else 'missing', source_ids=source_ids))
    missing = [item['key'] for item in reports if item['status'] == 'missing']
    return dict(status='insufficient' if missing else 'signals_present', missing=missing,
                observed=[item['key'] for item in reports if item['status'] == 'signal_present'],
                facets=reports, heuristic=True)


def supplement_query(question, coverage, domains=()):
    labels = [facet['label'] for facet in coverage['facets'] if facet['status'] == 'missing']
    suffix = ' '.join(labels[:4])
    if domains:
        suffix += ' site:' + domains[0]
    return (question[:240] + ' ' + suffix)[:400]
