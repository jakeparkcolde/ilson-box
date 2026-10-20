"""Tavily + 기존 Aside 검색 + 선택적 영상 자막. 실패한 소스는 누락 사유로 남긴다."""
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
try:
    from .answer_profiles import is_flight_question
    from .run import ResearchError, call, safe_url
    from .search_policy import question_plan, evidence_coverage, official_domains_for, official_candidate, supplement_query
except ImportError:
    from answer_profiles import is_flight_question
    from run import ResearchError, call, safe_url
    from search_policy import question_plan, evidence_coverage, official_domains_for, official_candidate, supplement_query


def options_from(value):
    value={} if value is None else value
    if not isinstance(value,dict):raise ResearchError('조사 옵션 형식 오류')
    mode=value.get('mode','quick');video=value.get('videos',False);context=value.get('context',[])
    if mode not in ('quick','deep') or type(video) is not bool or not isinstance(context,list) or len(context)>3 or any(not isinstance(q,str) or not 1<=len(q)<=400 for q in context):
        raise ResearchError('조사 옵션을 확인하세요')
    result = dict(mode=mode,videos=video,context=context)
    if "image" in value:
        try:
            from .image_input import validate_image
        except ImportError:
            from image_input import validate_image
        result["image"] = validate_image(value["image"])
    return result


def parse_rows(data,provider):
    if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise ResearchError('검색 응답 형식 오류')
    sources=[]
    for row in data['results'][:12]:
        if not isinstance(row,dict) or not isinstance(row.get('title'),str) or not isinstance(row.get('content'),str):raise ResearchError('검색 자료 형식 오류')
        raw=row.get('raw_content')
        if not row['content'].strip() and not (isinstance(raw,str) and raw.strip()):continue
        original=isinstance(raw,str) and bool(raw.strip())
        # 긴 공식 문서의 뒤쪽 설명도 발췌 후보에 남긴다. 모델 입력은 별도로 제한한다.
        sources.append(dict(title=row['title'][:500],url=safe_url(row.get('url')),content=(raw[:60000] if original else row['content'][:12000]),
            published_date=row.get('published_date') if isinstance(row.get('published_date'),str) else None,
            method='original-text-partial' if original else provider+'-snippet',read_status='read' if original else 'pending',provider=provider,source_type='web'))
    if not sources:raise ResearchError('검색 자료 없음')
    return sources


def tavily(query,period,cwd,mode='quick'):
    tool=shutil.which('tvly')
    if not tool:raise ResearchError('Tavily CLI 미설치')
    args=[tool,'search',query,'--depth','advanced' if mode=='deep' else 'basic','--max-results','8' if mode=='deep' else '6','--include-raw-content','text','--include-images','--json']
    # 전체 웹은 기간 필터를 걸지 않는다. 기존 Box 기간 요청은 그대로 전달한다.
    if period!='all':args+=['--time-range',period]
    data=json.loads(call(args,cwd=cwd,timeout=60))
    rows=parse_rows(data,'tavily')
    images=[]
    for item in (data.get('images') or [])[:12]:
        url=item if isinstance(item,str) else item.get('url') if isinstance(item,dict) else None
        try:
            url=safe_url(url)
            if urlsplit(url).scheme=='https':images.append(dict(url=url,title='검색 관련 이미지'))
        except ResearchError:continue
    if images:rows[0]['search_images']=images
    return rows


def youtube_sources(query,cwd):
    for args in (['aside','guide'],['aside','guide','repl'],['aside','skills','show','youtube']):call(args,cwd=cwd,timeout=20)
    script=r'''await (async()=>{
const found=await youtube.search(QUERY,{limit:3});const results=[];let failed=0;
for(const video of found){if(results.length>=2)break;try{const meta=await youtube.getMetadata(video.videoId);const content=await youtube.getTranscript(video.videoId,{includeTimestamp:true});if(!content.trim()){failed++;continue;}results.push({title:meta.title,url:meta.url,content:content.slice(0,12000),published_date:meta.publishDate||null});}catch{failed++;}}
console.log('ILSON_VIDEO:'+JSON.stringify({results,failed}));
})()'''.replace('QUERY',json.dumps(query))
    raw=call(['aside','repl',script],cwd=cwd,timeout=100)
    found=re.findall(r'ILSON_VIDEO:(\{[^\n]+\})',raw)
    if not found:raise ResearchError('영상 검색 또는 자막 수집 미완료')
    data=json.loads(found[-1]);rows=parse_rows(data,'youtube')
    for row in rows:row.update(method='youtube-transcript-partial',read_status='read',source_type='video')
    return rows, int(data.get('failed',0))


def canonical(url):
    p=urlsplit(url)
    query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('gclid','fbclid')]
    return urlunsplit((p.scheme,p.netloc,p.path.rstrip('/') or '/',urlencode(sorted(query)),''))


def merge(rows,limit=12):
    seen=set();counts={};result=[]
    for row in rows:
        key=canonical(row['url']);host=urlsplit(row['url']).hostname.lower().removeprefix('www.')
        if key in seen or counts.get(host,0)>=2:continue
        seen.add(key);counts[host]=counts.get(host,0)+1
        result.append(dict(row,id=len(result)+1))
        if len(result)>=limit:break
    return result


def ranked_merge(rankings,limit=12,official_domains=()):
    """독립 검색 순위를 RRF로 합친다. 같은 검색 안의 중복은 한 번만 센다."""
    records={};scores={};first={}
    for ranking in rankings:
        seen=set()
        for rank,row in enumerate(ranking,1):
            parts=urlsplit(canonical(safe_url(row['url'])))
            key=urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path,parts.query,''))
            if key in seen:continue
            seen.add(key)
            scores[key]=scores.get(key,0)+1/(60+rank)
            if key not in records:
                records[key]=dict(row);first[key]=len(first)
            elif len(row.get('content',''))>len(records[key].get('content','')):
                images=records[key].get('search_images')
                records[key]=dict(row)
                if images and not records[key].get('search_images'):records[key]['search_images']=images
    # 공식 도메인은 동점 때 우선하는 후보다. 도메인만으로 사실 여부를 판정하지 않는다.
    ordered=sorted(records,key=lambda key:(-scores[key],-int(official_candidate(records[key]['url'],official_domains)),first[key]))
    result=[];counts={}
    for key in ordered:
        row=records[key];host=(urlsplit(row['url']).hostname or '').lower().removeprefix('www.')
        if counts.get(host,0)>=2:continue
        counts[host]=counts.get(host,0)+1
        result.append(dict(row,id=len(result)+1,ranking_score=round(scores[key],8),
                           official_candidate=official_candidate(row['url'],official_domains)))
        if len(result)>=limit:break
    return result


def _gather_adaptive(question,period,home,options,bing,progress,official_domains):
    plan=question_plan(question)
    domains=official_domains_for(question,official_domains)
    queries=plan['primary_queries']
    # context는 options_from으로 검사한 과거 사용자 질문만 받는다. 생성된 답변은 받지 않는다.
    if options['context']:
        context=' '.join(options['context'])[:160]
        queries=[(q[:235]+' '+context)[:400] for q in queries]
    attempts=[];failures=[];rankings=[];outcomes=[]
    def search(label,query):
        try:
            rows=tavily(query,period,home,options['mode'])
            if not rows:return [],dict(provider=label,status='empty')
            return rows,dict(provider=label,status='ok',count=len(rows))
        except Exception:
            return [],dict(provider=label,status='failed')
    def collect(result):
        rows,outcome=result;rankings.append(rows);outcomes.append(outcome)
        if outcome['status']!='ok':
            reason='자료 없음' if outcome['status']=='empty' else '미완료'
            failures.append(outcome['provider']+' 검색 '+reason+' — 설치·인증·한도·응답 형식을 확인하세요')
    labels=['tavily' if i==0 else 'tavily-comparison' for i in range(len(queries))]
    for label in labels:
        attempts.append(label);progress(stage='searching',search_provider=label)
    if len(queries)==2:
        # CLI 검색만 병렬화한다. Aside/Bing은 브라우저 상태를 공유하므로 이 풀에 넣지 않는다.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(search,label,query) for label,query in zip(labels,queries)]
            for future in futures:collect(future.result())
    else:
        collect(search(labels[0],queries[0]))
    limit=10 if options['videos'] else 12 if options['mode']=='deep' else 6
    rows=ranked_merge(rankings,limit,domains)
    coverage=evidence_coverage(plan,rows)
    # 어휘가 일치해도 비공식 설명만 있는 경우에는 알려진 공식 문서를 한 번 찾는다.
    if coverage['missing'] or (domains and not any(row.get('official_candidate') for row in rows)):
        label='tavily-supplement';attempts.append(label)
        progress(stage='searching',search_provider=label)
        # 긴 후속 질문도 마지막의 누락 조건·site: 조건을 잘라 동일 질의를 반복하지 않는다.
        supplement_base=(question[:160]+' '+' '.join(options['context'])[:80]) if options['context'] else question
        query=supplement_query(supplement_base,coverage,domains)
        collect(search(label,query))
        rows=ranked_merge(rankings,limit,domains)
    # 자료가 있을 때는 개수만을 채우려 느린 브라우저를 추가하지 않는다.
    # 모든 CLI 검색이 실패한 경우의 마지막 폴백만 기존 Aside 경로를 직렬 실행한다.
    if not rows:
        attempts.append('bing');progress(stage='searching',search_provider='bing')
        try:
            fallback=[dict(row,provider='bing',source_type='web') for row in bing(queries[0],'year' if period=='all' else period,home)]
            outcomes.append(dict(provider='bing',status='ok' if fallback else 'empty',count=len(fallback)))
            rankings.append(fallback)
            if not fallback:failures.append('Bing 검색 자료 없음')
        except Exception:
            outcomes.append(dict(provider='bing',status='failed'))
            failures.append('Bing 검색 미완료 — 브라우저 연결·접근 제한을 확인하세요')
        rows=ranked_merge(rankings,limit,domains)
    if options['videos']:
        attempts.append('youtube');progress(stage='searching',search_provider='youtube')
        try:
            videos,failed=youtube_sources(question,home);rankings.append(videos)
            outcomes.append(dict(provider='youtube',status='partial' if failed else 'ok',count=len(videos)))
            rows=ranked_merge(rankings,12,domains)
            if failed:failures.append(str(failed)+'개 영상의 자막을 읽지 못했습니다')
        except Exception:
            outcomes.append(dict(provider='youtube',status='failed'))
            failures.append('영상 자막 수집 미완료 — 검색·자막·브라우저 연결을 확인하세요')
    if not rows:raise ResearchError('사용 가능한 검색 자료가 없습니다. '+' / '.join(failures))
    coverage=evidence_coverage(plan,rows)
    return rows,dict(attempts=attempts,failures=failures,mode=options['mode'],policy='adaptive_v1',
                     question_plan=plan,evidence_coverage=coverage,search_outcomes=outcomes,
                     official_source_status=('candidate_present' if any(row.get('official_candidate') for row in rows)
                                             else 'not_found' if domains else 'not_configured'),
                     official_candidate_domains=domains)


def _gather_purchase(query, question, period, home, options, bing, progress):
    """이미지 식별어와 사용자 구매 조건으로 판매 페이지를 찾는다. 답변 산문은 입력하지 않는다."""
    if not isinstance(question, str) or not 1 <= len(question) <= 400:
        raise ResearchError('구매 질문을 확인하세요')
    options = options_from(options)
    # 현재 사진이 대상을 정한다. 과거 다른 상품 질문을 붙이면 새 사진의 식별어가 희석된다.
    base = query[:230]
    constraint = question[:100]
    queries = [(base + ' ' + constraint)[:400], (base + ' ' + constraint + ' 쇼핑몰 가격 판매')[:400]]
    if options['mode'] == 'deep':
        queries.append((base + ' ' + constraint + ' 재고 예약판매 배송')[:400])
    rankings, failures, attempts = [], [], []
    def search(index, text):
        label = 'tavily-purchase-' + str(index + 1)
        try:
            return label, tavily(text, period, home, options['mode']), None
        except Exception:
            return label, [], label + ' 검색 미완료 — 연결·잔여 한도를 확인하세요'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for index, text in enumerate(queries):
            progress(stage='searching', search_provider='tavily-purchase-' + str(index + 1))
            futures.append(pool.submit(search, index, text))
        for future in futures:
            label, rows, error = future.result()
            attempts.append(label); rankings.append(rows)
            if error: failures.append(error)
            elif not rows: failures.append(label + ' 검색 자료 없음')
    limit = 12 if options['mode'] == 'deep' else 8
    rows = ranked_merge(rankings, limit)
    if not rows:
        attempts.append('bing')
        try:
            rows = merge(bing(queries[0], 'year' if period == 'all' else period, home), limit)
        except Exception:
            failures.append('Bing 구매처 검색 미완료')
    if not rows:
        raise ResearchError('구매처 검색 자료를 확보하지 못했습니다. ' + ' / '.join(failures))
    if options['videos']:
        attempts.append('youtube')
        try:
            videos, failed = youtube_sources(base, home)
            rows = merge(rows + videos, 12)
            if failed: failures.append(str(failed) + '개 영상의 자막을 읽지 못했습니다')
        except Exception:
            failures.append('영상 자막 수집 미완료')
    return rows, dict(attempts=attempts, failures=failures, mode=options['mode'],
                      policy='image-purchase-v1', query_count=len(queries))


def gather(question,period,home,options,bing,progress,*,policy='baseline',official_domains=(),purchase_question=None):
    if purchase_question is not None:
        return _gather_purchase(question,purchase_question,period,home,options,bing,progress)
    if is_flight_question(question):
        return gather_travel(question,period,home,options,bing,progress)
    models=mac_comparison_models(question)
    if models:
        return gather_mac_comparison(question,models,period,home,options,progress)
    if policy not in ('baseline','adaptive_v1'):raise ResearchError('검색 정책을 확인하세요')
    if policy=='adaptive_v1':return _gather_adaptive(question,period,home,options_from(options),bing,progress,official_domains)
    options=options_from(options);context=options['context']
    query=(question[:260]+' '+context[-1][:130]) if context else question
    rows=[];failures=[];attempts=[]
    plan=[('tavily',query)]
    if options['mode']=='deep':plan.append(('tavily-primary',(query[:330]+(' 실사용 후기 장단점 long term review' if re.search(r'실사용|후기|리뷰|\breview',question,re.I) else ' official documentation research report'))[:400]))
    for label,q in plan:
        progress(stage='searching',search_provider=label)
        attempts.append(label)
        try:rows.extend(tavily(q,period,home,options['mode']))
        except Exception:failures.append(label+' 검색 미완료 — 설치·인증·한도·응답 형식을 확인하세요')
    # 2026-10-02 실측: 빠른 조사에서 매번 브라우저를 기다리면 검색 지연이 늘었다.
    # 자료가 3개 미만/서로 다른 호스트가 2개 미만이면 보강한다. 심층은 계속 대조한다.
    selected=merge(rows)
    enough=len(selected)>=3 and len({urlsplit(s['url']).hostname for s in selected})>=2
    if options['mode']=='deep' or not enough:
        progress(stage='searching',search_provider='bing');attempts.append('bing')
        try:
            for s in bing(query,'year' if period=='all' else period,home):rows.append(dict(s,provider='bing',source_type='web'))
        except Exception:failures.append('Bing 검색 미완료 — 브라우저 연결·접근 제한을 확인하세요')
    rows=merge(rows,10 if options['videos'] else 12 if options['mode']=='deep' else 6)
    if options['videos']:
        progress(stage='searching',search_provider='youtube');attempts.append('youtube')
        try:
            videos,failed=youtube_sources(query,home);rows=merge(rows+videos)
            if failed:failures.append(str(failed)+'개 영상의 자막을 읽지 못했습니다')
        except Exception:failures.append('영상 자막 수집 미완료 — 검색·자막·브라우저 연결을 확인하세요')
    if not rows:raise ResearchError('사용 가능한 검색 자료가 없습니다. '+ ' / '.join(failures))
    return rows,dict(attempts=attempts,failures=failures,mode=options['mode'],
                     policy='multi-source' if options['mode']=='deep' else 'primary-with-fallback')


def youtube_id(url):
    """영상 상세주소만 허용한다. 채널·검색·위장 도메인은 미리보기로 만들지 않는다."""
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password: return None
        host=(p.hostname or '').lower()
        if host=='youtu.be': value=p.path.strip('/')
        elif host in ('youtube.com','www.youtube.com','m.youtube.com'):
            if p.path=='/watch': value=dict(parse_qsl(p.query)).get('v','')
            elif p.path.startswith(('/shorts/','/embed/')): value=p.path.split('/')[2]
            else: return None
        else: return None
        return value if re.fullmatch(r'[A-Za-z0-9_-]{11}',value) else None
    except (ValueError,TypeError): return None


def supplement_review_videos(question, period, home, options, sources, coverage, progress):
    # 기본은 링크·썸네일 검색이다. 자막 수집은 기존 '영상 포함' 선택에서만 실행한다.
    if not re.search(r'후기|실사용|리뷰|비교|추천|\breviews?\b|\bvs\b',question,re.I): return sources,coverage
    if len({youtube_id(s['url']) for s in sources if youtube_id(s['url'])})>=2: return sources,coverage
    coverage=dict(coverage,attempts=list(coverage.get('attempts',[])),failures=list(coverage.get('failures',[])))
    coverage['attempts'].append('youtube-links');progress(stage='searching',search_provider='youtube-links')
    query=(question[:240]+' '+' '.join(options.get('context',[])[-1:])[:100]+' site:youtube.com/watch 리뷰')
    try:
        found=tavily(query,period,home,'quick')
        videos=[row for row in found if youtube_id(row['url'])][:3]
        if not videos: coverage['failures'].append('관련 유튜브 영상 링크를 찾지 못했습니다')
        # 웹 자료 순서 유지. 영상은 최대3개, 전체12개. 자막을 읽은 것으로 표시하지 않는다.
        seen={canonical(row['url']) for row in sources};rows=list(sources)
        for row in videos:
            if canonical(row['url']) not in seen and len(rows)<12:
                rows.append(dict(row,id=len(rows)+1));seen.add(canonical(row['url']))
        return rows,coverage
    except Exception:
        coverage['failures'].append('유튜브 링크 검색 미완료 — 검색 연결·잔여 한도를 확인하세요')
        return sources,coverage


def mac_comparison_models(question):
    if not re.search(r'맥북|macbook',question,re.I) or not re.search(r'차이|비교|\bvs\b',question,re.I): return []
    matches=re.findall(r'(?<![a-z0-9])m(\d+)(?:\s*(pro|max|ultra|프로|맥스|울트라))?(?![a-z0-9])',question,re.I)
    tiers={'pro':'Pro','프로':'Pro','max':'Max','맥스':'Max','ultra':'Ultra','울트라':'Ultra'}
    models=list(dict.fromkeys('M'+n+(' '+tiers[t.lower()] if t else '') for n,t in matches))
    return models if len(models)==2 else []


def gather_mac_comparison(question,models,period,home,options,progress):
    options=options_from(options)
    family='MacBook Air' if re.search(r'에어|\bair\b',question,re.I) and not re.search(r'맥북\s*프로|macbook\s*pro',question,re.I) else 'MacBook Pro'
    queries=[]
    for model in models:
        size='16' if re.search(r'16\s*(?:인치|형|inch)',question,re.I) else '14'
        queries.append(f'{family} ({size}-inch, {model}) tech specs site:support.apple.com')
    queries.append(question+' 사양 비교')
    failures=[];rankings=[]
    def search(query):
        try:return tavily(query,'all',home,options['mode'])
        except Exception:return []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[]
        for query in queries:
            progress(stage='searching',search_provider='model-specifications')
            futures.append(pool.submit(search,query))
        for index,future in enumerate(futures):
            rows=future.result()
            if index<2:rows=[r for r in rows if official_candidate(r['url'],('apple.com',)) and matches_mac_model(r['title'],models[index],family)]
            if not rows:failures.append((models[index]+' 공식 사양' if index<2 else '비교 자료')+' 검색 미완료')
            rankings.append(rows)
    # 각각의 모델 원문을 먼저 확보한다. 전역 도메인 제한으로 두 모델 중 하나를 버리지 않는다.
    selected=[];seen=set()
    for ranking in rankings:
        for row in ranking[:3]:
            parts=urlsplit(row['url']);article=re.fullmatch(r'/[a-z]{2}-[a-z]{2}/(\d+)/?',parts.path)
            key='apple-support:'+article[1] if parts.hostname=='support.apple.com' and article else canonical(row['url'])
            if key not in seen:selected.append(dict(row,id=len(selected)+1));seen.add(key)
    if not selected:raise ResearchError('비교할 공식 사양·자료를 확보하지 못했습니다')
    if options['videos']:
        try:
            videos,failed=youtube_sources(question,home)
            for row in videos:
                if canonical(row['url']) not in seen:selected.append(dict(row,id=len(selected)+1));seen.add(canonical(row['url']))
            if failed:failures.append('일부 영상 자막 수집 미완료')
        except Exception:failures.append('영상 자막 수집 미완료')
    return selected,dict(attempts=['model-specifications']*2+['comparison'],failures=failures,mode=options['mode'],policy='model-specifications-v1',comparison_models=models)


def matches_mac_model(title, model, family):
    if family=='MacBook Pro' and re.search(r'MacBook\s+Air|맥북\s*에어',title,re.I):return False
    tokens=re.findall(r'(?<![a-z0-9])m(\d+)(?:\s*(pro|max|ultra|프로|맥스|울트라))?(?![a-z0-9])',title,re.I)
    tiers={'pro':'Pro','프로':'Pro','max':'Max','맥스':'Max','ultra':'Ultra','울트라':'Ultra'}
    return model in ['M'+n+(' '+tiers[t.lower()] if t else '') for n,t in tokens]


# 목적지 이름을 검색용 공항 동의어로 확장한다. 운항 여부나 항공편은 이 표로 판단하지 않는다.
_TRAVEL_PLACES = (
    (r'보라카이|boracay|caticlan|칼리보|카티클란', '보라카이 Boracay 칼리보 KLO 카티클란 MPH'),
    (r'보홀|bohol|panglao|팡라오|판글라오', '보홀 Bohol Panglao TAG'),
    (r'다낭|da nang', '다낭 Da Nang DAD'),
    (r'푸꾸옥|phu quoc', '푸꾸옥 Phu Quoc PQC'),
    (r'코타키나발루|kota kinabalu', '코타키나발루 Kota Kinabalu BKI'),
    (r'푸켓|phuket', '푸켓 Phuket HKT'),
)


def travel_queries(question, context=()):
    # 사용자 질문만 재사용한다. 과거 답변이나 외부 서비스 답변은 검색 입력으로 쓰지 않는다.
    text = question + (' ' + context[-1] if context else '')
    destinations = [name for pattern,name in _TRAVEL_PLACES if re.search(pattern,question,re.I)][:2]
    origins = re.findall(r'(?:인천|김포|김해|부산|서울|대구|청주|제주|무안|광주|ICN|PUS|GMP|[가-힣A-Za-z]+)(?:공항)?\s*(?:에서\s*)?출발', text, re.I)
    dates = re.findall(r'20\d{2}년?|\d{1,2}월\s*\d{1,2}일|\d{4}-\d{2}-\d{2}|[~～]\s*\d{1,2}일',text)
    constraints = ' '.join(origins + dates)
    airline = '필리핀항공 Philippine Airlines' if re.search(r'필리핀에어|필리핀항공|philippine|\bPAL\b',text,re.I) else ''
    # 모르는 목적지는 원문의 지명을 보존하고 검색 관점을 분리한다. 한국어만으로 인천을 가정하지 않는다.
    targets = destinations or [question[:240]]
    plan=[]
    for target in targets:
        direct_target = '보라카이 칼리보 Kalibo KLO' if target.startswith('보라카이') else target
        connect_target = '보라카이 Manila to Caticlan MPH' if target.startswith('보라카이') else '보홀 Manila to Tagbilaran Bohol TAG' if target.startswith('보홀') else target
        plan.append((target, f'{constraints} {direct_target} 직항 항공사'))
        official = 'site:philippineairlines.com' if airline else '공식 항공사'
        plan.append((target, f'{constraints} {connect_target} {airline} flights 환승 {official}'))
    if airline:
        plan.append(('필리핀항공 환승 조건', f'{constraints} Philippine Airlines Manila international domestic connecting flights terminal baggage site:philippineairlines.com'))
    return [(label,query.strip()[:400]) for label,query in plan]



def travel_source_matches(query,row):
    # 검색 결과 개수는 목적지 근거가 아니다. 제목·주소에 해당 목적지가 없는 일반 운임 페이지는 제외한다.
    from urllib.parse import unquote
    text=unquote(row.get('title','')+' '+row['url'])
    if 'Manila to' in query and not re.search(r'마닐라|manila|\bMNL\b',text,re.I):return False
    if 'KLO' in query and 'MPH' not in query:
        if re.search(r'\bMPH\b',text,re.I) and not re.search(r'\bKLO\b',text,re.I):return False
        return bool(re.search(r'칼리보|kalibo|\bKLO\b',text,re.I))
    if 'MPH' in query:
        return bool(re.search(r'보라카이|카티클란|caticlan|boracay|\bMPH\b',text,re.I))
    if 'TAG' in query:
        return bool(re.search(r'보홀|팡라오|판글라오|탁빌라란|bohol|panglao|tagbilaran|\bTAG\b',text,re.I))
    return True


def gather_travel(question,period,home,options,bing,progress):
    options=options_from(options)
    plan=travel_queries(question,options['context'])
    failures=[];attempts=[];rankings=[];outcomes=[]
    def search(label,query):
        try:
            rows=tavily(query,period,home,options['mode'])
            rows=[row for row in rows if travel_source_matches(query,row)]
            return rows,dict(topic=label,query=query,status='ok' if rows else 'empty',count=len(rows))
        except Exception:
            return [],dict(topic=label,query=query,status='failed',count=0)
    # 빠른 조사도 복수 목적지를 각각 찾는다. 개수만 충분하다고 한 목적지 누락을 성공으로 취급하지 않는다.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[]
        for label,query in plan:
            attempts.append('tavily-travel');progress(stage='searching',search_provider='tavily-travel')
            futures.append(pool.submit(search,label,query))
        for future in futures:
            rows,outcome=future.result();rankings.append(rows);outcomes.append(outcome)
            if outcome['status']!='ok':failures.append(outcome['topic']+' 검색 '+('자료 없음' if outcome['status']=='empty' else '미완료'))
    # 검색별 상위 결과를 번갈아 보존한다. 같은 항공사 도메인에 두 목적지 자료가 있어도 버리지 않는다.
    selected=[];seen=set();limit=12 if options['mode']=='deep' else 10
    for rank in range(6):
        for rows in rankings:
            if rank>=len(rows):continue
            row=rows[rank];key=canonical(row['url'])
            if key in seen:continue
            seen.add(key);selected.append(dict(row,id=len(selected)+1))
            if len(selected)>=limit:break
        if len(selected)>=limit:break
    if not selected:
        attempts.append('bing')
        try:selected=merge(bing(question,'year' if period=='all' else period,home),limit)
        except Exception:failures.append('Bing 항공 검색 미완료')
    if not selected:raise ResearchError('항공 노선 자료를 확보하지 못했습니다. '+' / '.join(failures))
    if options['videos']:
        attempts.append('youtube')
        try:
            videos,failed=youtube_sources(question,home)
            for row in videos:
                if canonical(row['url']) not in seen and len(selected)<12:
                    selected.append(dict(row,id=len(selected)+1));seen.add(canonical(row['url']))
            if failed:failures.append('일부 영상 자막 수집 미완료')
        except Exception:failures.append('영상 자막 수집 미완료')
    return selected,dict(attempts=attempts,failures=failures,mode=options['mode'],policy='travel-routes-v1',
                         search_outcomes=outcomes,date_availability='not_verified')
