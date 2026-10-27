'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const states = {ok:'관측됨',empty:'등록 항목 없음',failure:'수집 실패',unavailable:'관측 불가',stale:'지난 관측 · 갱신 실패',running:'프로세스 실행 중',exit_nonzero:'최근 종료값 확인 필요',idle:'등록 · 대기',paused:'멈춤 기록',not_loaded:'등록되지 않음'};
  let data = null, busy = false, timer = null, failed = false;
  const open = new Set();
  const node = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const time = value => value ? new Date(value).toLocaleString('ko-KR') : '기록 없음';
  const bytes = value => `${(value / 1024 ** 3).toFixed(1)} GiB`;
  const warn = state => ['failure','exit_nonzero'].includes(state)?'failure':['stale','unavailable'].includes(state)?'warning':'';
  function resources() {
    $('resources').replaceChildren();
    for(const [key,title] of [['cpu','CPU'],['memory','메모리'],['disk','디스크']]) {
      const item=data[key],value=item.value,card=node('article',undefined,'card');
      card.append(node('h3',title),node('p',value?`${value.percent}%`:'—','value'),node('span',states[failed?'stale':item.state],'badge '+warn(failed?'stale':item.state)));
      if(value&&key==='memory')card.append(node('p',`${bytes(value.used_bytes)} / ${bytes(value.total_bytes)} 사용`));
      if(value&&key==='disk')card.append(node('p',`${bytes(value.free_bytes)} / ${bytes(value.total_bytes)} 여유`));
      card.append(node('p','관측 '+time(item.observed_at),'time'));$('resources').append(card);
    }
  }
  function jobs() {
    if(!data)return;
    const filter=$('search').value.trim().toLowerCase(),source=$('source').value,state=$('state').value;
    const items=data.automations.items.filter(r=>(source==='all'||r.source===source)&&(state==='all'||(state==='unknown'?['failure','stale','unavailable'].includes(r.state):r.state===state))&&`${r.name} ${r.id}`.toLowerCase().includes(filter));
    $('count').textContent=`${items.length} / ${data.automations.items.length}개`;
    $('automation-status').textContent=`${states[failed?'stale':data.automations.state]} · 관측 ${time(data.automations.observed_at)}${data.sandbox?' · 샌드박스: 사용자 예약 조회 안 함':''}${data.automations.notices.length?' · '+data.automations.notices.join(' '):''}`;
    const fragment=document.createDocumentFragment();
    for(const row of items){
      const detail=node('details',undefined,'job');detail.open=open.has(row.id);
      detail.addEventListener('toggle',()=>{if(detail.open)open.add(row.id);else open.delete(row.id);});
      const summary=node('summary'),name=node('div');name.append(node('h3',row.name),node('small',row.source==='box'?'일손 업무':'다른 launchd 등록'));
      summary.append(name,node('span',states[failed?'stale':row.state],'badge '+warn(failed?'stale':row.state)));
      const facts=node('dl');
      for(const [label,value] of [['식별자',row.id],['일정',row.schedule||'수집하지 않음'],['일손 멈춤',row.registration==='paused'?'멈춤 기록 있음':'해당 기록 없음'],['프로세스 PID',row.process?.pid??'관측된 실행 PID 없음'],['최근 종료값',row.process?`${row.process.exit_code} · 업무 성공 여부와 별개`:'관측 불가'],['마지막 성공',row.last_success_at?time(row.last_success_at):row.last_success_state==='unknown'?'기록을 읽지 못함':'성공 도장 없음']])facts.append(node('dt',label),node('dd',value));
      detail.append(summary,facts);fragment.append(detail);
    }
    if(!items.length)fragment.append(node('p',data.automations.items.length?'검색·필터에 맞는 업무가 없습니다.':data.automations.state==='empty'?'현재 관측 범위에 등록된 업무가 없습니다.':'표시할 업무가 없습니다. 위 관측 상태를 확인하세요.','empty'));
    $('jobs').replaceChildren(fragment);
  }
  function schedule(){clearTimeout(timer);if(!document.hidden)timer=setTimeout(refresh,30000);}
  async function refresh(){
    if(busy||document.hidden)return;
    busy=true;$('refresh').disabled=true;
    const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),20000);
    try{
      const response=await fetch('/api/dashboard',{signal:abort.signal,cache:'no-store'});
      if(response.status===401){$('error').textContent='인증이 필요합니다. 터미널에서 ilson open으로 다시 연 뒤 현황판으로 이동하세요.';$('error').hidden=false;failed=true;return;}
      if(!response.ok)throw Error('관측 응답 실패');
      data=await response.json();failed=false;$('error').hidden=true;
      $('status').textContent=`확인 ${time(data.observed_at)} · ${data.platform} · 30초 캐시`;
    }catch{failed=true;$('error').hidden=false;$('error').textContent='새 관측을 가져오지 못했습니다. 표시 중인 값은 지난 관측입니다. 연결을 확인한 뒤 다시 확인하세요.';}
    finally{clearTimeout(timeout);busy=false;$('refresh').disabled=false;if(data){resources();jobs();}schedule();}
  }
  for(const id of ['search','source','state'])$(id).addEventListener(id==='search'?'input':'change',jobs);
  $('refresh').addEventListener('click',refresh);
  try{document.body.dataset.theme=localStorage.getItem('ilson-theme')||'dark';}catch{}
  $('theme').addEventListener('click',()=>{document.body.dataset.theme=document.body.dataset.theme==='light'?'dark':'light';try{localStorage.setItem('ilson-theme',document.body.dataset.theme);}catch{}});
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh();});
  refresh();
})();
