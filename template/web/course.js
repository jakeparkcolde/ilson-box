'use strict';
(() => {
  const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text);if(cls)el.className=cls;return el;};
  const main=document.getElementById('main'),nav=document.getElementById('sidebar');
  const pages=[['home','홈','/'],['approvals','승인함','/approval'],['reports','주간 리포트','/reports'],['usage-history','내 AI 사용 기록','/usage-history'],['replies','답글 초안','/replies']];
  let features=[],epoch=0,timer=null;
  const api=async(path,body)=>{const options={credentials:'same-origin',cache:'no-store'};if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body);}const response=await fetch(path,options),data=await response.json();if(!response.ok)throw Error(data.error||'요청을 완료하지 못했습니다.');return data;};
  const button=(label,fn,cls='btn btn-ghost')=>{const b=node('button',label,cls);b.type='button';b.onclick=fn;return b;};
  const textInput=(label,placeholder)=>{const wrapper=node('label',label,'course-label'),input=node('input');input.type='text';input.placeholder=placeholder;wrapper.append(input);return [wrapper,input];};
  function theme(){try{document.body.dataset.theme=localStorage.getItem('ilson-theme')||'dark';}catch{document.body.dataset.theme='dark';}}
  function navigation(current){
    nav.replaceChildren();const brand=node('div',undefined,'brand'),word=node('span','ILSON','brand-word');word.append(node('span','✦','brand-star'));brand.append(word);nav.append(brand,node('div','시작','nav-group'));
    pages.filter(([id])=>features.includes(id)).forEach(([id,label,path])=>{const b=button(label,()=>go(path),'nav-item'+(id===current?' on':''));if(id===current)b.setAttribute('aria-current','page');nav.append(b);});
    const foot=node('div',undefined,'side-user');foot.append(node('span','내 일손 · 강의판','course-name'),button('접속 종료',async()=>{try{await api('/api/logout',{});clearInterval(timer);main.textContent='접속을 종료했습니다. ilson open으로 다시 열어 주세요.';}catch(e){window.alert(e.message);}}),button('◐',()=>{const value=document.body.dataset.theme==='light'?'dark':'light';document.body.dataset.theme=value;try{localStorage.setItem('ilson-theme',value);}catch{}}));nav.append(foot);
  }
  function page(title,description){const root=node('section',undefined,'screen'),heading=node('header',undefined,'h1row'),wrap=node('div');wrap.append(node('div','내 일손 · 강의판','eyebrow'),node('h1',title,'title'));heading.append(wrap);root.append(heading,node('p',description,'course-notice'));main.replaceChildren(root);return root;}
  function card(root,title,body){const c=node('section',undefined,'card course-card');c.append(node('h2',title));if(body)c.append(node('p',body));root.append(c);return c;}
  function notice(root){const status=node('p','','course-status');status.setAttribute('role','status');root.append(status);return status;}
  async function render(){
    const own=++epoch,[id,title]=pages.find(p=>p[2]===location.pathname)||pages[0];navigation(id);document.body.classList.remove('m-nav-open');
    if(!features.includes(id)){main.textContent='이 화면은 현재 강의판에서 사용할 수 없습니다.';return;}
    if(id==='usage-history'){await window.IlsonUsage.mount(main,{course:true});return;}
    const root=page(title,({home:'실습 준비 상태와 저장된 문서를 확인하세요.',approvals:'Claude 대화에서 reports/pending 폴더에 Markdown 초안을 저장한 뒤, 여기에서 내용을 읽고 승인하거나 수정을 요청하세요.',reports:'저장된 주간 리포트를 읽는 화면입니다. 새 리포트는 터미널에서 ilson report weekly로 만드세요.',replies:'고객 글을 직접 붙여 넣어 답글 초안을 만듭니다. 내용을 확인한 뒤 판매자센터에서 직접 게시하세요.'})[id]),status=notice(root);
    const action=async(fn)=>{try{await fn();}catch(e){status.textContent=e.message;status.classList.add('course-error');}};
    if(id==='home'){
      const data=await api('/api/overview');if(own!==epoch)return;const c=card(root,data.box.company_name,'이용하지 않은 채 2시간이 지나면 관리 화면 서버가 꺼집니다. 다시 열 때는 ilson open, 직접 끌 때는 ilson admin stop을 실행하세요.');
      for(const check of data.checks){const row=node('div',undefined,'course-check'),detail=node('div');detail.append(node('strong',check.label),node('p',check.detail));row.append(detail,node('small',({ok:'확인됨',attention:'확인 필요',unknown:'확인 불가'})[check.state]||'확인 불가'));c.append(row);}
      root.append(node('p','사용 기록과 강사 공유는 각각 기본 꺼짐이며 별도 동의가 필요합니다.','course-notice'));
    }else if(id==='reports'){
      const data=await api('/api/reports');if(own!==epoch)return;const rows=data.reports.filter(r=>r.category==='주간 보고');if(!rows.length)card(root,'아직 주간 리포트가 없습니다.','터미널에서 ilson report weekly를 실행한 뒤 다시 열어 주세요.');
      const document=node('section',undefined,'card course-card');document.hidden=true;
      for(const row of rows){const c=card(root,row.title,new Date(row.updated_at).toLocaleString('ko-KR'));c.append(button('리포트 읽기',()=>action(async()=>{const report=await api('/api/reports/'+row.id);if(own!==epoch)return;document.replaceChildren(node('h2',report.title),node('pre',report.text,'course-document'));document.hidden=false;document.scrollIntoView({block:'nearest'});})));}root.append(document);if(data.limited)status.textContent=data.notice;
    }else if(id==='approvals'){
      const data=await api('/api/approvals');if(own!==epoch)return;
      const add=card(root,'저장된 초안','초안은 Claude 대화에서 직접 저장합니다. 승인하면 reports/approved로 옮기고 일지에 기록합니다. 수정 요청 뒤에는 Claude에서 고쳐 저장하고 새 요청을 추가하세요.');
      const [label,input]=textInput('초안 파일 이름','초안.md');add.append(label,button('대기함에 추가',()=>action(async()=>{await api('/api/approvals/create',{name:input.value});await render();}),'btn btn-primary'));
      for(const draft of data.drafts||[]){const row=node('div',undefined,'course-actions');row.append(node('span',draft.title),button('이 초안 추가',()=>action(async()=>{await api('/api/approvals/create',{name:draft.name});await render();})));add.append(row);}
      if(!data.requests.length)root.append(node('p','승인 요청이 없습니다.','course-notice'));
      const states={pending:'승인 대기',approved:'승인 접수',changed:'수정 요청 · 수정 후 새 요청 필요',rejected:'거절됨',expired:'기간 만료',executing:'실행 중',success:'승인본 보관 완료',failed:'실패',result_unknown:'결과 확인 필요'};
      for(const req of data.requests){const c=card(root,req.title,states[req.state]||'확인 필요');c.append(node('p','대상: '+Object.values(req.target).join(' / ')),node('pre',req.body));if(req.review_blocked)c.append(node('p','숨겨진 내용이 있습니다. 초안을 고쳐 다시 추가하세요.'));const actions=node('div',undefined,'course-actions');const entries=req.state==='pending'?[['승인','approve'],['수정 요청','change'],['거절','reject']]:req.state==='approved'&&req.execution==='received'?[['실행 확인','run'],['거절','reject']]:[];for(const [title,path] of entries){const b=button(title,()=>action(async()=>{if(['approve','run'].includes(path)&&!confirm('위 내용과 대상으로 승인본을 보관할까요?'))return;await api('/api/approvals/'+path,{id:req.id});await render();}));b.disabled=req.review_blocked&&['approve','run'].includes(path);actions.append(b);}c.append(actions);}
    }else if(id==='replies'){
      const c=card(root,'답글 초안','동의한 고객 글을 Claude로 보내며, 주문·배송·가격·분쟁 같은 내용은 직접 확인을 안내합니다.'),label=node('label','고객 글','course-label'),input=node('textarea');input.maxLength=3000;label.append(input);const consentLabel=node('label','입력한 내용을 Claude에 보내는 데 동의합니다. ','course-label'),consent=node('input');consent.type='checkbox';consentLabel.prepend(consent);const result=node('pre');c.append(label,consentLabel,button('초안 만들기',()=>action(async()=>{const answer=await api('/api/replies/draft',{text:input.value,consent:consent.checked});result.textContent=(answer.text?answer.text+'\n\n':'')+answer.message;}),'btn btn-primary'),result);
    }
  }
  async function go(path){history.pushState(null,'',path);try{await render();}catch(e){main.textContent=e.message;}}
  window.addEventListener('popstate',()=>render().catch(e=>{main.textContent=e.message;}));
  document.getElementById('mNavBtn').onclick=()=>document.body.classList.toggle('m-nav-open');document.getElementById('mNavBackdrop').onclick=()=>document.body.classList.remove('m-nav-open');theme();
  (async()=>{try{const params=new URLSearchParams(location.hash.slice(1));let token=params.get('token');if(location.hash)history.replaceState(null,'',location.pathname);if(token)await api('/api/session',{token});token=null;const session=await api('/api/session');features=session.features||[];await render();timer=setInterval(()=>api('/api/session').catch(()=>{clearInterval(timer);}),60000);}catch(e){main.textContent=e.message+' 터미널에서 ilson open으로 다시 열어 주세요.';}})();
})();
