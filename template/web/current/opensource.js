/* L0 reads only the authenticated local API. All source prose stays plain text. */
(() => {
  'use strict';
  const categories = [['automation','업무 자동화'],['documents','문서·발표자료'],['data','데이터 정리·분석'],['design','디자인·이미지'],['sites','사이트·상점 만들기']];
  const burdens = {browse:'살펴보기', guided:'안내와 함께', expert:'전문가 도움', unknown:'확인 중'};
  const messages = {
    loading:'자료를 불러오고 있어요', empty:'소개할 도구를 검토하고 있어요',
    under_review:'공개 검토 중입니다. 소개할 도구를 검토하고 있어요',
    expired:'자료가 만료되었습니다. 검토된 새 자료가 필요해요',
    load_failed:'자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요',
    verification_failed:'자료 검증에 실패했습니다. 검토된 새 자료가 필요해요',
    session_expired:'접속이 만료되었습니다. 다시 연결해 주세요',
    forbidden:'이 메뉴의 이용 권한을 확인해 주세요',
    unavailable:'공개 가능한 자료가 없습니다. 검토·만료·철회 상태를 확인해 주세요'
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const para = value => `<p class="os-prose">${escape(value)}</p>`;
  const bullets = (values, fallback='확인 중') => values?.length ? `<ul>${values.map(v=>`<li>${escape(v)}</li>`).join('')}</ul>` : para(fallback);
  const link = (url,label) => `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label)} ↗</a>`;
  const date = value => value ? `${escape(value.slice(0,10))} (UTC)` : '확인 중';
  const state = {search:'',category:'all',filter:'all',id:null,scroll:0,windowScroll:0,focus:null};
  let host=null, root=null, data=null, detail=null, status='loading', sequence=0, controller=null, refreshTimer=null, expiryTimer=null, requestTimer=null;
  const clearTimers = () => {clearTimeout(refreshTimer);clearTimeout(expiryTimer);};
  function cancel() {sequence++;controller?.abort();controller=null;clearTimeout(requestTimer);requestTimer=null;clearTimers();}
  function active() {return host && root && host.contains(root);}
  function chrome() {
    root.innerHTML = `<header><h1 tabindex="-1" id="os-title">오픈소스</h1><p>내 일에 맞는 도구를 찾아보세요</p><p class="os-muted">결과 미리보기 · 설치 없이 설명과 검토된 예시를 살펴봅니다</p></header><div id="os-body"></div>`;
  }
  function notice(kind) {
    return `<div class="os-notice" role="status" aria-live="polite"><p>${escape(messages[kind] || messages.load_failed)}</p>${kind==='session_expired'?'<a href="/">다시 연결하기</a>':'<button type="button" data-action="retry">다시 확인</button>'}</div>`;
  }
  function common() {
    return data?.generated_at ? `<p class="os-muted">자료 기준 ${date(data.generated_at)} · 유효 기한 ${escape(data.valid_until)}${data.warning?' · 갱신하지 못해 유효기간 안의 마지막 검토 자료를 보여 드립니다':''}</p>` : '';
  }
  function render() {
    if(!active())return;
    const body=root.querySelector('#os-body');
    if(status!=='ready' && !['empty','under_review'].includes(status)) {
      body.innerHTML=(state.id?'<button type="button" data-action="back">← 목록으로</button>':'')+notice(status)+common();return;
    }
    if(state.id && detail){renderDetail(body);return;}
    body.innerHTML=`<div class="os-tabs" role="tablist" aria-label="업무 분야">${[['all','전체'],...categories].map(([id,label])=>`<button type="button" role="tab" id="os-tab-${id}" data-category="${id}" aria-selected="${state.category===id}" aria-controls="os-results" tabindex="${state.category===id?0:-1}">${label}</button>`).join('')}</div><div class="os-tools"><label>이름·업무 키워드 검색<input id="os-search" type="search" maxlength="200" value="${escape(state.search)}" autocomplete="off"></label><label>준비 정도<select id="os-filter"><option value="all">모든 도구</option><option value="browse" ${state.filter==='browse'?'selected':''}>설치 없이 살펴보기</option><option value="preparation" ${state.filter==='preparation'?'selected':''}>준비가 필요한 도구</option></select></label></div><p class="os-muted">입문 추천 순서 · 난이도는 원본 1~5, 적용 부담은 Box에서 살펴보는 기준입니다. 설치·운영 난이도와 다를 수 있어요.</p><div id="os-results" role="tabpanel" aria-labelledby="os-tab-${state.category}" tabindex="0"></div>${common()}`;
    results();
  }
  function results(){
    if(!active())return;
    const target=root.querySelector('#os-results');if(!target)return;
    const q=state.search.trim().toLocaleLowerCase();
    const rows=(data?.repos||[]).filter(r=>(state.category==='all'||r.category===state.category)&&(!q||[r.full_name,r.one_liner,...r.use_cases].join(' ').toLocaleLowerCase().includes(q))&&(state.filter==='all'||(state.filter==='browse'?r.box_burden==='browse':r.box_burden!=='browse')));
    target.innerHTML=`<p role="status">${rows.length}개 도구</p>`+(rows.length?`<div class="os-grid">${rows.map(r=>`<article class="os-card"><h2><button type="button" data-repo="${r.id}">${escape(r.full_name)}</button></h2>${para(r.one_liner)}<dl><dt>누구에게 맞나</dt><dd>${escape(r.use_cases.join(' · ')||'대상 확인 중')}</dd><dt>난이도 / 적용 부담</dt><dd>${r.difficulty??'확인 중'} / ${burdens[r.box_burden]}</dd><dt>준비물</dt><dd>${escape(r.preparation)}</dd><dt>비용</dt><dd>${escape(r.cost)}</dd><dt>라이선스</dt><dd>${escape(r.license.spdx)} · ${link(r.license.url,'조건 원문')}</dd><dt>가능한 체험</dt><dd>결과 미리보기</dd><dt>Box 공개 검토일</dt><dd>${date(r.reviewed_at)}</dd></dl>${link(r.gitbap_url,'깃밥 설명')}<button type="button" data-repo="${r.id}">결과 미리보기</button><p class="os-muted">설명용 예시이며 이 Box에서 실행한 결과가 아닙니다</p></article>`).join('')}</div>`:notice(status==='under_review'?'under_review':'empty'));
  }
  function renderDetail(body){
    const r=detail,s=r.source,review=r.review;
    body.innerHTML=`<button type="button" data-action="back">← 목록으로</button><h2 tabindex="-1" id="os-detail-title">${escape(r.full_name)}</h2><section><h3>1. 해결하려는 일</h3>${para(r.one_liner)}${bullets(r.use_cases,'대상 확인 중')}</section><section><h3>2. 깃밥 순한맛 설명</h3>${para(r.mild_md)}${link(r.gitbap_url,'깃밥 원문 설명')}<p class="os-muted">소개 작성일 ${date(s.summary_created_at)} · 원본 확인일 ${date(s.synced_at)}</p></section><section><h3>3. 맞는 상황·준비물·한계</h3>${bullets(r.use_cases,'대상 확인 중')}${para(r.preparation)}${bullets(r.prerequisites,'별도 준비물 없음')}<p>원본 난이도 ${r.difficulty??'확인 중'} / 5 · Box 적용 부담: ${burdens[r.box_burden]}</p><p class="os-muted">조회·설치·운영 난이도는 서로 다릅니다.</p>${bullets(r.limitations)}</section><section><h3>4. 기존 영상·샘플 결과</h3>${r.video?`${link(r.video.gitbap_url,'깃밥 설명 페이지에서 한국어 영상 보기')}<p>영상 제작일 ${date(r.video.made_at)} · ${r.video.duration_s}초</p>`:para('공개 승인된 한국어 영상이 확인되지 않았습니다.')}<div class="os-preview"><h4>결과 미리보기</h4><p><strong>설명용 예시이며 이 Box에서 실행한 결과가 아닙니다</strong></p>${r.preview?`<h4>가상 입력 예</h4>${para(r.preview.input)}<h4>검토된 결과 예</h4>${para(r.preview.result)}<h4>내 업무에서 쓸 자리</h4>${para(r.preview.placement)}<p class="os-muted">샘플 출처: ${escape(r.preview.source)}</p>`:para('승인된 샘플 결과가 없어 설명만 제공합니다.')}</div></section><section><h3>5. 라이선스·비용·데이터 처리</h3><p>${escape(r.license.spdx)} · ${link(r.license.url,'고정 버전 조건 원문')}</p>${para(r.license.conditions)}${para(r.cost)}${para(r.data_processing)}<p>Box 공개 검토일 ${date(review.reviewed_at)} · 검토 유효 기한 ${escape(review.valid_until)}</p><p>현재 메타데이터 판정: 확인됨 (${date(review.metadata_checked_at)})</p><p class="os-muted">과거 수집 관문: 안전 ${review.past_safety_pass===null?'확인 중':review.past_safety_pass?'통과 기록':'미통과 기록'} / 유지 ${review.past_alive_pass===null?'확인 중':review.past_alive_pass?'통과 기록':'미통과 기록'} · ${date(review.past_evaluated_at)}. 과거 관문과 현재 공개 검토는 실행 승인을 뜻하지 않습니다.</p></section><section><h3>6. 가능한 다음 단계</h3><p>설명과 결과 예를 살펴본 뒤 내 업무에 맞는지 판단해 보세요.</p>${link(r.gitbap_url,'깃밥 설명 페이지에서 더 보기')} · ${link(r.official_url,'공식 저장소')}<p class="os-muted">이 화면은 설명용 결과 미리보기를 제공합니다.</p></section>${common()}`;
  }
  function armExpiry(){
    if(!active())return;
    clearTimeout(expiryTimer);
    const dates=[data?.valid_until,data?.visible_until,detail?.review?.valid_until];
    if(detail?.source?.status_checked_at)dates.push(new Date(Date.parse(detail.source.status_checked_at)+72*3600000).toISOString());
    if(detail?.review?.metadata_checked_at)dates.push(new Date(Date.parse(detail.review.metadata_checked_at)+72*3600000).toISOString());
    if(detail?.video)dates.push(detail.video.valid_until);
    const ends=dates.filter(Boolean).map(Date.parse).filter(Number.isFinite);
    if(ends.length)expiryTimer=setTimeout(()=>{cancel();data=null;detail=null;status='expired';render();},Math.max(0,Math.min(...ends)-Date.now()));
  }
  function schedule(){
    if(!active())return;
    clearTimers();armExpiry();
    if(['ready','empty','under_review'].includes(status))refreshTimer=setTimeout(()=>load(false),30000);
  }
  async function load(showLoading=true,restore=false){
    cancel();const request=sequence;
    controller=new AbortController();const signal=controller.signal;
    if(showLoading){status='loading';detail=null;render();}else armExpiry();
    const requestController=controller;
    const timeout=requestTimer=setTimeout(()=>requestController.abort(),15000);
    try{
      const path=state.id?'/api/opensource/repos/'+encodeURIComponent(state.id):'/api/opensource/catalog';
      const response=await fetch(path,{signal,credentials:'same-origin',cache:'no-store'});
      const next=await response.json();
      if(request!==sequence||!active())return;
      if(response.status===401)status='session_expired';
      else if(response.status===403)status='forbidden';
      else if(response.status===404)status='unavailable';
      else if(!response.ok)status='load_failed';
      else status=next.state;
      if(!['ready','empty','under_review','expired'].includes(status)){data=null;detail=null;}
      else {data=next;detail=next.repo||null;}
      render();schedule();
      if(restore){host.scrollTop=state.scroll;window.scrollTo(0,state.windowScroll);root.querySelector(`[data-repo="${state.focus}"]`)?.focus({preventScroll:true});}
      else if(showLoading && detail)root.querySelector('#os-detail-title')?.focus({preventScroll:true});
    }catch(error){
      if(request!==sequence||!active())return;
      data=null;detail=null;status='load_failed';render();
    }finally{clearTimeout(timeout);if(requestTimer===timeout)requestTimer=null;}
  }
  function click(event){
    const button=event.target.closest('button');if(!button||!root.contains(button))return;
    if(button.dataset.category){state.category=button.dataset.category;render();root.querySelector(`#os-tab-${state.category}`)?.focus();}
    else if(button.dataset.repo){state.scroll=host.scrollTop;state.windowScroll=window.scrollY;state.focus=button.dataset.repo;state.id=button.dataset.repo;host.scrollTop=0;window.scrollTo(0,0);load();}
    else if(button.dataset.action==='back'){state.id=null;detail=null;load(true,true);}
    else if(button.dataset.action==='retry')load();
  }
  function input(event){if(event.target.id==='os-search'){state.search=event.target.value;results();}if(event.target.id==='os-filter'){state.filter=event.target.value;results();}}
  function keydown(event){
    if(!event.target.dataset.category)return;
    const ids=['all',...categories.map(c=>c[0])], i=ids.indexOf(state.category);
    const index={ArrowRight:(i+1)%ids.length,ArrowLeft:(i+ids.length-1)%ids.length,Home:0,End:ids.length-1}[event.key];
    if(index===undefined)return;event.preventDefault();state.category=ids[index];render();root.querySelector(`#os-tab-${state.category}`)?.focus();
  }
  function mount(target){
    if(host===target&&active())return;
    leave();host=target;root=document.createElement('div');root.className='screen ilson-opensource';host.replaceChildren(root);
    root.addEventListener('click',click);root.addEventListener('input',input);root.addEventListener('change',input);root.addEventListener('keydown',keydown);
    chrome();load();
  }
  function leave(){cancel();host=null;root=null;data=null;detail=null;}
  window.IlsonOpensource={mount,leave};
})();
