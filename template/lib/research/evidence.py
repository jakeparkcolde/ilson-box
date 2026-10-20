"""검색 순위와 출처 번호를 보존하면서 질문에 관련된 원문 일부만 전달한다."""
import re
from urllib.parse import urlsplit


def excerpt(text, question, limit):
    # 원문을 요약·재작성하지 않는다. 앞부분과 질의어 주변을 원래 순서대로 발췌한다.
    if len(text) <= limit:
        return text
    terms={t.casefold() for t in re.findall(r'[\w-]{2,}',question) if t.casefold() not in {'what','how','the','차이','알려줘','설명해줘'}}
    segments=[(offset,text[offset:offset+600],{term for term in terms if term in text[offset:offset+600].casefold()}) for offset in range(0,len(text),600)]
    chosen=[];used=0;covered=set()
    token_counts=[max(1,len(re.findall(r'[\w-]{2,}',item[1]))) for item in segments]
    words=[set(re.findall(r'[\w-]{2,}',item[1].casefold())) for item in segments]
    frequencies={term:max(1,text.casefold().count(term)) for term in terms}
    # 첫 부분은 자료의 정의·단위·전제를 보존하고 이후 질의어가 있는 단락을 우선한다.
    for index,item in enumerate(segments):
        if used>=min(600,limit):break
        chosen.append(index);used+=len(item[1]);covered.update(item[2])
    while True:
        available=[i for i in range(len(segments)) if i not in chosen and used+len(segments[i][1])+5<=limit]
        if not available:break
        # 비교 대상 한쪽에만 예산을 쓰지 않고 아직 포함하지 않은 질의어도 발췌한다.
        seen_words=set().union(*(words[i] for i in chosen))
        index=max(available,key=lambda i:(len(segments[i][2]-covered),sum(min(5,segments[i][1].casefold().count(term))/frequencies[term] for term in terms)*len(words[i]-seen_words)/token_counts[i],len(segments[i][2]),-segments[i][0]))
        chosen.append(index);used+=len(segments[index][1])+5;covered.update(segments[index][2])
    result=[];previous=None
    for index in sorted(chosen):
        if previous is not None and index!=previous+1:result.append('\n[…]\n')
        result.append(segments[index][1]);previous=index
    return ''.join(result)[:limit]


def prepare_sources(question, sources, mode):
    limit=2500 if mode=='quick' else 4000
    result=[]
    for source in sources:
        row=dict(source)
        host=(urlsplit(source.get('url','')).hostname or '').lower()
        specification=(host=='support.apple.com' and re.search(r'tech\s*specs|기술\s*사양',source.get('title',''),re.I) and re.search(r'차이|비교|\bvs\b',question,re.I))
        row['content']=excerpt(source['content'],question,8000 if specification else limit)
        row['content_trimmed']=len(row['content'])<len(source['content'])
        result.append(row)
    return result


def cache_ttl(question, period):
    # 가격·일정·최신 정보는 오래된 본문을 반복 제시하지 않는다.
    if period=='day' or re.search(r'가격|요금|할인|시세|환율|주가|일정|오늘|현재|최신|price|latest|today',question,re.I):
        return 0
    return 600
