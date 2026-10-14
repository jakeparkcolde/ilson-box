# coding: utf-8
"""사용자 기기의 Aside에서 지정 링크의 자료를 제한 수집한다."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


class CollectionError(ValueError):
    pass


def source_target(url):
    if not isinstance(url, str) or len(url) > 2000:
        raise CollectionError('링크 형식 오류')
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise CollectionError('인증 정보 없는 HTTPS 링크를 입력하세요')
    host = p.hostname.lower()
    if host in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be'):
        if host == 'youtu.be' or p.path in ('/watch',) or p.path.startswith(('/shorts/','/live/','/embed/')):
            return 'video', url
        if re.fullmatch(r'/@[A-Za-z0-9_.-]+(?:/videos)?/?',p.path):
            return 'channel', 'https://www.youtube.com'+p.path.rstrip('/').removesuffix('/videos')+'/videos'
        raise CollectionError('유튜브 영상 또는 @채널 링크를 입력하세요')
    if host in ('threads.com','www.threads.com','threads.net','www.threads.net'):
        if not re.fullmatch(r'/@[A-Za-z0-9_.]+(?:/post/[A-Za-z0-9_-]+)?/?',p.path):
            raise CollectionError('쓰레드 계정 또는 게시물 링크를 입력하세요')
        return 'threads', 'https://www.threads.com'+p.path.rstrip('/')
    raise CollectionError('첫 버전은 유튜브 영상·채널과 쓰레드 계정·게시물 링크를 지원합니다')


def script_for(url, limit):
    kind, target = source_target(url)
    if type(limit) is not int or not 1 <= limit <= 10:
        raise CollectionError('수집 범위는 1~10건입니다')
    # URL은 JS 문자열 리터럴로 인코딩한다. 페이지 본문은 실행 코드로 사용하지 않는다.
    return '''await (async()=>{
const target=TARGET, kind=KIND, limit=LIMIT;
const rows=[], failures=[];
if(kind==='video'||kind==='channel'){
  let urls=[target];
  if(kind==='channel'){
    const open=(await listBrowserTabs()).find(t=>t.url.split('?')[0]===target);
    const tab=open?await attachBrowserTab(open.targetId):await openTab(target);
    await snapshot(tab,{interactive:true});
    const found=new Map();
    for(let pass=0;pass<4&&found.size<limit;pass++){
      const links=await tab.evaluate(()=>Array.from(document.querySelectorAll('a[href*="/watch?v="]')).map(a=>a.href));
      for(const link of links){const parsed=new URL(link);const id=parsed.searchParams.get('v');if(parsed.hostname==='www.youtube.com'&&/^[A-Za-z0-9_-]{11}$/.test(id))found.set(id,'https://www.youtube.com/watch?v='+id);}
      if(found.size>=limit)break;
      await tab.evaluate(()=>window.scrollBy(0,1600));await sleep(1000);
    }
    urls=Array.from(found.values()).slice(0,limit);
  }
  for(const url of urls){
    try{
      const m=await youtube.getMetadata(url);
      let content='';
      try{content=await youtube.getTranscript(url,{includeTimestamp:true});}catch{failures.push({url,reason:'자막 수집 실패 또는 자막 없음'});continue;}
      if(!content.trim()){failures.push({url,reason:'자막 내용 없음'});continue;}
      rows.push({title:m.title,url:m.url,author:m.channelName||'',published_at:m.publishDate||null,content:content.slice(0,24000),method:'aside-youtube-transcript',truncated:content.length>24000});
    }catch{failures.push({url,reason:'영상 정보 수집 실패'});}
  }
}else{
  const open=(await listBrowserTabs()).find(t=>t.url.split('?')[0]===target);
  const tab=open?await attachBrowserTab(open.targetId):await openTab(target);
  const first=await snapshot(tab,{interactive:true});
  // 실제 열람한 사이트의 게시물 링크·컨테이너만 읽는다. 클릭·게시 동작은 없다.
  const found=new Map();
  for(let pass=0;pass<8&&found.size<limit;pass++){
    const items=await tab.evaluate(()=>{
      const out=[];
      for(const a of document.querySelectorAll('a[href*="/post/"]')){
        let box=a.closest('div[data-pressable-container],article');if(!box)continue;
        const time=box.querySelector('time[datetime]');
        out.push({url:a.href.split('?')[0],title:'쓰레드 게시물',published_at:time?.getAttribute('datetime')||null,content:box.innerText.slice(0,8000)});
      }return out;
    });
    const owner=new URL(target).pathname.split('/')[1];
    for(const row of items){const p=new URL(row.url);if(p.hostname!=='www.threads.com'||p.pathname.split('/')[1]!==owner)continue;if(target.includes('/post/')&&row.url!==target)continue;found.set(row.url,{...row,author:owner,method:'aside-browser-visible-text',truncated:false});}
    if(found.size>=limit||target.includes('/post/'))break;
    await tab.evaluate(()=>window.scrollBy(0,1400));await sleep(1000);
  }
  rows.push(...Array.from(found.values()).slice(0,limit));
  if(!rows.length)failures.push({url:target,reason:'게시물 본문을 확인하지 못함. 로그인·접근 제한·페이지 구조를 확인하세요'});
}
console.log('ILSON_COLLECTION:'+JSON.stringify({rows,failures}));
})()
'''.replace('TARGET',json.dumps(target)).replace('KIND',json.dumps(kind)).replace('LIMIT',str(limit))


def invoke(args, timeout=150):
    try:
        result=subprocess.run(args,text=True,capture_output=True,timeout=timeout,stdin=subprocess.DEVNULL)
    except (OSError,subprocess.TimeoutExpired):
        raise CollectionError('Aside 실행 실패 또는 시간 초과. 기기의 설치·로그인 상태를 확인하세요') from None
    if result.returncode:
        raise CollectionError('Aside 수집 미완료. 기기의 브라우저 연결을 확인하세요')
    return result.stdout


def collect(url, limit=5, run=invoke):
    _,target=source_target(url)
    code=script_for(target,limit)
    # 실제 설치 버전의 사용법부터 확인한다. exec 에이전트/LLM 없이 직접 읽는다.
    for args in (['aside','guide'],['aside','guide','repl'],['aside','skills','show','youtube']):
        run(args)
    raw=run(['aside','repl',code])
    matches=re.findall(r'ILSON_COLLECTION:(\{[^\n]+\})',raw)
    if not matches:
        raise CollectionError('Aside 결과를 확인하지 못했습니다. 빈 결과를 성공으로 처리하지 않습니다')
    try: data=json.loads(matches[-1])
    except ValueError: raise CollectionError('수집 결과 형식 오류') from None
    rows=data.get('rows')
    if not isinstance(rows,list) or not rows or len(rows)>limit:
        raise CollectionError('수집된 자료가 없습니다. 자막·로그인·접근 범위를 확인하세요')
    seen=set();sources=[]
    for row in rows:
        if not isinstance(row,dict): raise CollectionError('자료 형식 오류')
        _,item=source_target(row.get('url'))
        if item in seen:continue
        seen.add(item)
        content=row.get('content');title=row.get('title')
        if not isinstance(content,str) or not content.strip() or not isinstance(title,str):
            raise CollectionError('본문 없는 자료는 능력 생성에 사용하지 않습니다')
        sources.append(dict(id=len(sources)+1,title=title[:500],url=item,
            author=str(row.get('author',''))[:120],published_at=row.get('published_at'),
            content=content[:24000],method=row.get('method'),truncated=bool(row.get('truncated'))))
    return dict(version=1,type='ilson-source-bundle',target=target,checked_at=datetime.now(timezone.utc).isoformat(),
        requested=limit,collected=len(sources),coverage='partial',sources=sources,
        failures=[{'url':r.get('url'),'reason':r.get('reason')} for r in data.get('failures',[]) if isinstance(r,dict)],
        limitations='지정 범위의 표본입니다. 계정 전체 수집·긴 본문 펼치기·영상 시각 정보는 검증하지 않았습니다. 자동 자막과 UI 문자열에 오류가 있을 수 있습니다.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url');parser.add_argument('--limit',type=int,default=5);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.output.exists():raise CollectionError('기존 파일을 덮어쓰지 않습니다')
        data=collect(args.url,args.limit)
        import os
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2)
        print('자료 수집 완료. 지식 훔치기 화면에서 결과를 여세요.')
    except (CollectionError,ValueError,OSError) as exc:
        parser.exit(1,'수집 미완료: '+(str(exc) if isinstance(exc,CollectionError) else '입력·파일을 확인하세요')+'\n')
