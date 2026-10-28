/* 고객 입력은 textContent 또는 HTML 이스케이프만 사용한다. 인라인 이벤트는 만들지 않는다. */
'use strict';
let state, tab='employees', busy=false;
let loading=null, generation=0, timer=null, authExpired=false;
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const button=(label,action,id='')=>`<button data-action="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
function message(value,error=false){$('message').textContent=value;$('message').className=error?'error':'';}
function invalidate(){generation++;if(loading){loading.controller.abort();loading=null;}}
async function api(path,body,signal){
  const response=await fetch('/api/workspace'+path,{signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  if(response.status===401){authExpired=true;throw Error('관리자 연결이 만료되었습니다. 입력은 보존했습니다. ilson open으로 다시 연결한 뒤 이 창으로 돌아오세요.');}
  const data=await response.json();if(!response.ok)throw Error(data.error||'요청을 완료하지 못했습니다.');return data;
}
async function refresh(){
  if(loading)return loading.promise;
  const ticket=++generation,controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
  const run=(async()=>{try{
    const next=await api('/people',undefined,controller.signal);
    if(ticket!==generation||document.hidden)return;
    const changed=JSON.stringify(state)!==JSON.stringify(next);state=next;
    if(changed||tab==='jobs')await render(true);
    if($('sync-status'))$('sync-status').textContent='목록이 최신 상태입니다.';
  }finally{clearTimeout(timeout);if(loading?.ticket===ticket)loading=null;}})();
  loading={ticket,controller,promise:run};return run;
}
function schedule(){clearTimeout(timer);if(!document.hidden&&!authExpired)timer=setTimeout(poll,2000);}
async function poll(){try{if(!document.hidden&&!busy&&tab!=='jobs')await refresh();}catch(error){if($('sync-status'))$('sync-status').textContent=authExpired?error.message:'목록을 갱신하지 못했습니다. 입력을 보존하고 다시 연결합니다.';}finally{schedule();}}
document.addEventListener('visibilitychange',()=>{invalidate();clearTimeout(timer);if(!document.hidden){authExpired=false;poll();}});
function options(items,selected,empty){return `<option value="">${empty}</option>`+items.map(item=>`<option value="${esc(item.id)}"${item.id===selected?' selected':''}>${esc(item.name)}</option>`).join('');}
function employeeCard(e){const dept=state.departments.find(d=>d.id===e.department_id);const skills=state.assignments.filter(a=>a.employee_id===e.id).map(a=>state.skills.find(s=>s.id===a.skill_id)).filter(Boolean);return `<article class="card"><h3>${esc(e.name)} ${e.active?'':'<small>비활성</small>'}</h3><span class="badge">${esc(dept?.name||'미배치')}</span><p>${esc(e.role)}</p><p>${skills.length?skills.map(s=>`<span class="badge">${esc(s.name)}${s.active?'':' · 비활성'}</span>`).join(''):'할당된 스킬 없음'}</p><div class="actions">${button('편집','edit',e.id)}${button('스킬 할당','assign',e.id)}${button('업무 요청','run',e.id)}${button('삭제','delete',e.id)}</div></article>`;}
async function render(preserveEditor=false){
  const renderTicket=++generation;
  const focused=document.activeElement;
  const focusKey=focused?.dataset?.action?{action:focused.dataset.action,id:focused.dataset.id}:null;
  const viewFocused=focusKey&&$('view').contains(focused);
  document.querySelectorAll('[data-tab]').forEach(b=>{if(b.dataset.tab===tab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(!preserveEditor)$('editor').replaceChildren();
  if(tab==='employees')$('view').innerHTML=`<div class="actions">${button('직원 추가','add')}</div><p class="notice">직원 업무는 역할과 활성 스킬을 반영한 문서·답변 작성입니다. 웹 검색, 파일 변경, 프로그램 실행, SNS 발행 권한은 부여하지 않습니다.</p><div class="grid">${state.employees.map(employeeCard).join('')||'<p class="empty">아직 직원이 없습니다. 첫 직원을 추가하세요.</p>'}</div>`;
  if(tab==='departments'){
    function tree(parent){return `<ul class="org">${state.departments.filter(d=>d.parent_id===parent).map(d=>`<li><article class="card"><h3>${esc(d.name)}</h3><p>${state.employees.filter(e=>e.department_id===d.id).map(e=>esc(e.name)).join(' · ')||'배치된 직원 없음'}</p>${button('편집','edit',d.id)} ${button('삭제','delete',d.id)}</article>${tree(d.id)}</li>`).join('')}</ul>`;}
    $('view').innerHTML=`${button('부서 추가','add')}<p>직원 편집에서 부서를 선택해 배치하세요. 부서 편집에서 상위 부서를 정할 수 있습니다.</p>${state.departments.length?tree(''):'<p class="empty">아직 부서가 없습니다.</p>'}<article class="card"><h3>미배치</h3><p>${state.employees.filter(e=>!e.department_id).map(e=>esc(e.name)).join(' · ')||'미배치 직원 없음'}</p></article>`;
  }
  if(tab==='skills')$('view').innerHTML=`${button('직접 추가 / SKILL.md 가져오기','add')}<p class="notice">텍스트 지침만 설치합니다. 프로그램·지원 파일·설치 후크·원격 URL은 가져오거나 실행하지 않습니다. 신뢰하는 지침인지 본문을 확인하세요. 비활성화·해제는 다음 실행부터 반영하며 이미 실행 중인 업무는 시작 시 지침을 사용합니다.</p><h2>설치된 스킬</h2><div class="grid">${state.skills.map(s=>`<article class="card"><h3>${esc(s.name)}</h3><span class="badge">${s.active?'활성':'비활성'}</span><p>${esc(s.description)}</p><details><summary>지침 본문</summary><pre>${esc(s.body)}</pre></details><div class="actions">${button('편집','edit',s.id)}${button(s.active?'비활성화':'활성화','toggle',s.id)}${button('제거','delete',s.id)}</div></article>`).join('')||'<p class="empty">설치된 스킬이 없습니다.</p>'}</div><h2>제공 스킬</h2><div class="grid">${state.catalog.map(s=>`<article class="card"><h3>${esc(s.name)}</h3><p>${esc(s.description)}</p><details><summary>설치할 지침 확인</summary><pre>${esc(s.body)}</pre></details>${button('설치','install',s.id)}</article>`).join('')}</div>`;
  if(tab==='jobs'){
    $('view').textContent='업무 기록을 불러오는 중…';const jobs=(await api('/jobs')).jobs.filter(j=>j.kind==='employee');if(tab!=='jobs'||renderTicket!==generation)return;
    const labels={queued:'대기',running:'진행 중',done:'완료',failed:'실패'};
    $('view').innerHTML=`${button('새로 고침','refresh')}<div class="grid">${jobs.map(j=>`<article class="card"><h3>${esc(j.title)}</h3><p>${labels[j.status]||esc(j.status)}</p>${j.error?`<p class="error">${esc(j.error)}</p>`:''}${button('결과·적용 스킬 보기','result',j.id)}</article>`).join('')||'<p class="empty">아직 요청한 직원 업무가 없습니다.</p>'}</div>`;
  }
  if(viewFocused){const replacement=Array.from($('view').querySelectorAll('[data-action]')).find(b=>b.dataset.action===focusKey.action&&b.dataset.id===focusKey.id);replacement?.focus({preventScroll:true});}
}
function edit(id){const kind=tab;const requestId=kind==='employees'&&!id?crypto.randomUUID():null;const item=state[tab].find(e=>e.id===id)||{};let fields=`<label for="name">이름</label><input id="name" name="name" maxlength="80" required value="${esc(item.name)}">`;
  if(tab==='employees')fields+=`<label for="role">역할과 업무 범위</label><textarea id="role" name="role" maxlength="2000" required>${esc(item.role)}</textarea><label for="department_id">소속 부서</label><select id="department_id" name="department_id">${options(state.departments,item.department_id,'미배치')}</select>`;
  if(tab==='departments')fields+=`<label for="parent_id">상위 부서</label><select id="parent_id" name="parent_id">${options(state.departments.filter(d=>d.id!==id),item.parent_id,'최상위')}</select>`;
  if(tab==='skills')fields+=`<label for="description">어떤 업무에 쓰나요?</label><input id="description" name="description" maxlength="400" required value="${esc(item.description)}"><label for="skill-file">SKILL.md 파일에서 본문 가져오기 (선택)</label><input id="skill-file" type="file" accept=".md,text/markdown,text/plain"><label for="body">스킬 지침</label><textarea id="body" name="body" maxlength="24000" required>${esc(item.body)}</textarea><small>머리말은 한 줄 name·description만 허용합니다. 본문을 검토하고 저장하세요.</small>`;
  if(tab!=='departments')fields+=`<label><input name="active" type="checkbox"${item.active!==0?' checked':''}> 활성</label>`;
  showForm(`${id?'편집':'추가'}`,fields,async form=>{const data=Object.fromEntries(new FormData(form));if(id){data.id=id;data.expected=item;}else if(requestId)data.request_id=requestId;if(kind!=='departments')data.active=form.elements.active.checked;await api(`/people/${kind}/save`,data);});
  $('skill-file')?.addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>96000)throw Error('파일은 96KB 이하로 선택하세요.');const value=await file.text();if(value.length>24000)throw Error('본문은 24,000자 이하로 입력하세요.');$('body').value=value;}catch(error){message(error.message,true);}});
}
function showForm(title,fields,save){$('editor').innerHTML=`<form><h2>${esc(title)}</h2>${fields}<div class="actions"><button type="submit" class="primary">저장 / 요청</button>${button('취소','cancel')}</div></form>`;const form=$('editor').querySelector('form');form.addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;invalidate();const submit=form.querySelector('[type=submit]');submit.disabled=true;try{await save(form);$('editor').replaceChildren();message('처리했습니다.');await refresh();}catch(error){message(error.message,true);}finally{busy=false;submit.disabled=false;}});$('editor').scrollIntoView({behavior:'smooth',block:'start'});form.querySelector('input,textarea,select')?.focus();}
async function action(name,id){
  if(name==='cancel')return $('editor').replaceChildren();
  if(name==='add'||name==='edit')return edit(id);
  if(name==='refresh')return refresh();
  if(name==='assign'){
    const selected=state.assignments.filter(a=>a.employee_id===id).map(a=>a.skill_id);
    return showForm('직원 스킬 할당',`<fieldset><legend>최대 10개 선택 · 모두 해제 가능</legend>${state.skills.map(s=>`<label><input type="checkbox" name="skills" value="${esc(s.id)}"${selected.includes(s.id)?' checked':''}> ${esc(s.name)}${s.active?'':' (비활성)'}</label>`).join('')||'<p>스킬 화면에서 먼저 설치하세요.</p>'}</fieldset>`,form=>api('/people/assign',{employee_id:id,skill_ids:new FormData(form).getAll('skills')}));
  }
  if(name==='run')return showForm('직원에게 업무 요청','<p>텍스트 결과를 작성합니다. 도구 실행·검색·발행은 하지 않습니다. 대기 중 변경된 역할과 활성 스킬은 실행 직전에 반영됩니다.</p><label for="brief">요청 내용과 참고 자료</label><textarea id="brief" name="brief" maxlength="4000" required></textarea>',async form=>{await api('/people/run',{employee_id:id,brief:form.elements.brief.value});tab='jobs';});
  if(name==='result'){const job=await api('/jobs/'+id);$('editor').replaceChildren();const title=document.createElement('h2');title.textContent='업무 결과';const pre=document.createElement('pre');pre.textContent=job.result?`${job.result.employee_name}\n적용 스킬: ${job.result.applied_skills.map(s=>s.name).join(', ')||'없음'}\n\n${job.result.text}`:(job.error||'아직 완료되지 않았습니다. 새로 고침으로 확인하세요.');$('editor').append(title,pre);return;}
  if(name==='delete'){if(!confirm(tab==='skills'?'스킬을 제거하고 모든 직원의 할당을 해제할까요? 실행 중 업무에는 이미 전달된 지침이 남습니다.':'삭제할까요? 진행 업무·소속 참조가 있으면 삭제가 제한됩니다.'))return;await api(`/people/${tab}/delete`,{id});}
  if(name==='toggle'){const skill=state.skills.find(s=>s.id===id);await api('/people/skills/save',{...skill,active:!skill.active,expected:skill});}
  if(name==='install')await api('/people/install',{catalog_id:id});
  message('처리했습니다.');await refresh();
}
document.addEventListener('click',async event=>{const target=event.target.closest('button');if(!target||busy||(!target.dataset.tab&&!target.dataset.action))return;invalidate();busy=true;try{if(target.dataset.tab){tab=target.dataset.tab;message('');if(state)await render();}else if(state)await action(target.dataset.action,target.dataset.id);}catch(error){message(error.message,true);}finally{busy=false;schedule();}});
poll();
