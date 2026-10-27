'use strict';
(() => {
  let root = null, active = false, request = null;
  const $ = id => root.querySelector('#db-' + id);
  const states = {ok:'관측됨',empty:'등록 항목 없음',failure:'수집 실패',unavailable:'관측 불가',stale:'지난 관측 · 갱신 실패',running:'프로세스 실행 중',exit_nonzero:'최근 종료값 확인 필요',idle:'등록 · 대기',paused:'멈춤 기록',not_loaded:'등록되지 않음'};
  let data = null, timer = null, failed = false;
  const open = new Set();
  const node = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const time = value => value ? new Date(value).toLocaleString('ko-KR') : '기록 없음';
  const bytes = value => `${(value / 1024 ** 3).toFixed(1)} GiB`;
  const warn = state => ['failure','exit_nonzero'].includes(state)?'db-failure':['stale','unavailable'].includes(state)?'db-warning':'';
  function resources() {
    $('resources').replaceChildren();
    for(const [key,title] of [['cpu','CPU'],['memory','메모리'],['disk','디스크']]) {
      const item=data[key],value=item.value,card=node('article',undefined,'db-card');
      card.append(node('h3',title),node('p',value?`${value.percent}%`:'—','db-value'),node('span',states[failed?'stale':item.state],'db-badge '+warn(failed?'stale':item.state)));
      if(value&&key==='memory')card.append(node('p',`${bytes(value.used_bytes)} / ${bytes(value.total_bytes)} 사용`));
      if(value&&key==='disk')card.append(node('p',`${bytes(value.free_bytes)} / ${bytes(value.total_bytes)} 여유`));
      card.append(node('p','관측 '+time(item.observed_at),'db-time'));$('resources').append(card);
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
      const detail=node('details',undefined,'db-job');detail.open=open.has(row.id);
      detail.addEventListener('toggle',()=>{if(detail.open)open.add(row.id);else open.delete(row.id);});
      const summary=node('summary'),name=node('div');name.append(node('h3',row.name),node('small',row.source==='box'?'일손 업무':'다른 launchd 등록'));
      summary.append(name,node('span',states[failed?'stale':row.state],'db-badge '+warn(failed?'stale':row.state)));
      const facts=node('dl');
      for(const [label,value] of [['식별자',row.id],['일정',row.schedule||'수집하지 않음'],['일손 멈춤',row.registration==='paused'?'멈춤 기록 있음':'해당 기록 없음'],['프로세스 PID',row.process?.pid??'관측된 실행 PID 없음'],['최근 종료값',row.process?`${row.process.exit_code} · 업무 성공 여부와 별개`:'관측 불가'],['마지막 성공',row.last_success_at?time(row.last_success_at):row.last_success_state==='unknown'?'기록을 읽지 못함':'성공 도장 없음']])facts.append(node('dt',label),node('dd',value));
      detail.append(summary,facts);fragment.append(detail);
    }
    if(!items.length)fragment.append(node('p',data.automations.items.length?'검색·필터에 맞는 업무가 없습니다.':data.automations.state==='empty'?'현재 관측 범위에 등록된 업무가 없습니다.':'표시할 업무가 없습니다. 위 관측 상태를 확인하세요.','db-empty'));
    $('jobs').replaceChildren(fragment);
  }
  // A request belongs to one mount. Even a transport ignoring abort cannot update a later mount.
  function schedule() {
    clearTimeout(timer);
    timer = null;
    if (active && !document.hidden) timer = setTimeout(refresh, 30000);
  }
  async function refresh() {
    if (!active || request || document.hidden) return;
    clearTimeout(timer);
    timer = null;
    const run = {abort: new AbortController(), timeout: null};
    request = run;
    $('refresh').disabled = true;
    run.timeout = setTimeout(() => run.abort.abort(), 20000);
    try {
      const response = await fetch('/api/dashboard', {signal: run.abort.signal, cache: 'no-store'});
      if (!active || request !== run) return;
      if (response.status === 401) {
        failed = true;
        $('error').textContent = '인증이 필요합니다. 터미널에서 ilson open으로 다시 연 뒤 현황판으로 이동하세요.';
        $('error').hidden = false;
        return;
      }
      if (!response.ok) throw Error('관측 응답 실패');
      const next = await response.json();
      if (!active || request !== run) return;
      data = next;
      failed = false;
      $('error').hidden = true;
      $('status').textContent = `확인 ${time(data.observed_at)} · ${data.platform} · 30초 캐시`;
    } catch {
      if (!active || request !== run) return;
      failed = true;
      $('error').hidden = false;
      $('error').textContent = data
        ? '새 관측을 가져오지 못했습니다. 표시 중인 값은 지난 관측입니다. 연결을 확인한 뒤 다시 확인하세요.'
        : '관측을 가져오지 못했습니다. 연결을 확인한 뒤 다시 확인하세요.';
    } finally {
      clearTimeout(run.timeout);
      if (active && request === run) {
        request = null;
        $('refresh').disabled = false;
        if (data) { resources(); jobs(); }
        schedule();
      }
    }
  }
  function visibility() {
    clearTimeout(timer);
    timer = null;
    if (!document.hidden) refresh();
  }
  function leave() {
    if (!active) return;
    active = false;
    clearTimeout(timer);
    timer = null;
    document.removeEventListener('visibilitychange', visibility);
    if (request) {
      clearTimeout(request.timeout);
      request.abort.abort();
      request = null;
    }
    $('refresh').disabled = false;
  }
  function mount(host) {
    if (!root) {
      root = node('section', undefined, 'screen ilson-dashboard');
      root.setAttribute('aria-label', '자동화·컴퓨터 현황');
      root.innerHTML = `<div class="db-heading"><div><p class="db-eyebrow">이 컴퓨터 · 읽기 전용</p><h1>자동화와 컴퓨터 현황</h1><p>일손 업무와 이 사용자의 launchd 등록 상태를 한곳에서 확인합니다.</p></div><button id="db-refresh" type="button">새로 확인</button></div>
<p id="db-status" role="status">관측을 준비하고 있습니다.</p><p id="db-error" role="alert" hidden></p>
<section aria-labelledby="db-resources-title"><h2 id="db-resources-title">컴퓨터 사용량</h2><div id="db-resources" class="db-resources"></div><p class="db-hint">CPU는 약 1초 구간의 전체 사용률, 메모리는 앱·유선·압축 메모리 합계입니다. 디스크는 일손이 설치된 볼륨의 사용자 가용 공간 기준입니다.</p></section>
<section aria-labelledby="db-jobs-title"><div class="db-section-heading"><h2 id="db-jobs-title">자동화 관측</h2><span id="db-count"></span></div><p id="db-automation-status" class="db-hint"></p><div class="db-filters"><label>검색<input id="db-search" type="search" placeholder="업무 이름 또는 식별자" maxlength="200"></label><label>범위<select id="db-source"><option value="all">전체</option><option value="box">일손 업무</option><option value="launchd">다른 launchd 등록</option></select></label><label>상태<select id="db-state"><option value="all">전체</option><option value="running">프로세스 실행 중</option><option value="exit_nonzero">최근 종료값 확인 필요</option><option value="idle">등록 · 대기</option><option value="not_loaded">미등록</option><option value="paused">멈춤 기록</option><option value="unknown">관측 불가·오래됨</option></select></label></div><div id="db-jobs"></div></section>
<section class="db-limits" aria-labelledby="db-limits-title"><h2 id="db-limits-title">이 화면이 확인하는 범위</h2><p>launchd의 PID는 프로세스 실행 관측이고 종료값 0은 업무 성공 증거가 아닙니다. 마지막 성공은 일손 실행기가 남긴 도장이 있을 때만 표시합니다. 멈춤 기록과 실제 실행이 다를 수 있습니다.</p><p>다른 launchd 등록은 현재 로그인한 사용자의 등록 목록입니다. Apple 시스템 항목·일반 앱 항목은 제외합니다. 미등록 외부 예약, 시스템 데몬, cron·PM2·앱 내부 예약은 포함하지 않으며 일정과 결과를 추정하지 않습니다.</p><p>LLM 사용량: 공식 사용량 연결이 없어 미표시입니다. 로그인 정보나 쿠키를 읽지 않습니다. 다중기기: 이 설치 기기만 관측하며 다른 컴퓨터에 연결하거나 전송하지 않습니다.</p><p>30초 동안 관측값을 재사용합니다. 숨긴 창에서는 자동 조회를 멈춥니다. 새로 확인도 캐시 기간 안에서는 같은 표본을 표시합니다.</p></section>`;
      for (const id of ['search', 'source', 'state']) $(id).addEventListener(id === 'search' ? 'input' : 'change', jobs);
      $('refresh').addEventListener('click', refresh);
    }
    if (root.parentNode !== host) host.replaceChildren(root);
    // Shell/SNS background renders must not restart polling or reset filter/detail state.
    if (active) return;
    active = true;
    document.addEventListener('visibilitychange', visibility);
    if (data) { resources(); jobs(); }
    refresh();
  }
  window.IlsonDashboard = {mount, leave};
})();
