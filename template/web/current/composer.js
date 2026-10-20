/* 작성·재작성은 초안만 만든다. 발행 승인은 운영 화면의 기존 결재 경로를 쓴다. */
const COMPOSE={accounts:[],post:null,busy:false};
async function snsCompose(id=''){
  try{
    const accounts=await api('/api/workspace/accounts');
    COMPOSE.accounts=accounts.accounts;COMPOSE.post=id?(await api('/api/workspace/posts')).posts.find(p=>p.id===id):null;
    if(id&&!COMPOSE.post)throw Error('수정할 초안을 찾을 수 없습니다.');
    const post=COMPOSE.post;
    const kst=post?.scheduled_at?new Date(Date.parse(post.scheduled_at)+9*3600000).toISOString().slice(0,16):'';
    document.getElementById('modals').innerHTML=`<div class="mini-compose-shade"><section class="sns-panel mini-compose" role="dialog" aria-modal="true" aria-labelledby="mini-compose-title">
      <div class="sns-head"><h2 id="mini-compose-title">${post?'초안 수정':'새 초안'}</h2><button class="btn btn-ghost" onclick="snsComposeClose()" aria-label="작성 창 닫기">닫기</button></div>
      <p class="sns-meta">내용을 준비한 뒤 운영 화면에서 검토·승인하세요.</p>
      <label>게시 계정<select id="mini-compose-account" ${post?'disabled':''}>${COMPOSE.accounts.map(a=>`<option value="${esc(a.id)}" ${a.id===post?.account_id?'selected':''}>${esc(SNS_PLATFORMS[a.platform]+' · '+a.username)}</option>`).join('')||'<option value="">계정을 먼저 연결하세요</option>'}</select></label>
      ${post?'':`<label>일손에게 초안 요청<textarea id="mini-compose-brief" rows="3" maxlength="4000" placeholder="누구에게 어떤 내용을 전달할지 적어주세요."></textarea></label><button class="btn btn-ghost" onclick="snsComposeDraft()">초안 작성 맡기기</button>`}
      <label>게시 본문<textarea id="mini-compose-text" rows="7" maxlength="2200">${esc(post?.text||'')}</textarea></label>
      <label>이미지 주소<input id="mini-compose-image" type="url" value="${esc(post?.image_url||'')}" placeholder="https://…"></label>
      <label>예약 시각 (한국 시간)<input id="mini-compose-time" type="datetime-local" value="${esc(kst)}"></label>
      <p class="sns-meta">예약 시각을 비워 두면 승인할 때 지금 발행을 선택할 수 있습니다.</p>
      <p id="mini-compose-status" role="status"></p>
      <div class="sns-connect-actions"><button class="btn btn-primary" onclick="snsComposeSave()">초안 저장</button><button class="btn btn-ghost" onclick="snsComposeClose()">취소</button></div>
    </section></div>`;
    document.getElementById(post?'mini-compose-text':'mini-compose-brief').focus();
  }catch(error){document.getElementById('modals').innerHTML=`<div class="mini-compose-shade"><section class="sns-panel mini-compose" role="dialog"><p>${esc(error.message)}</p><button class="btn btn-ghost" onclick="snsComposeClose()">닫기</button></section></div>`;}
}
function snsComposeClose(){if(!COMPOSE.busy)document.getElementById('modals').replaceChildren();}
async function snsComposeAction(run){
  if(COMPOSE.busy)return;COMPOSE.busy=true;
  const node=document.getElementById('mini-compose-status');node.textContent='저장하고 있습니다…';
  try{await run(node);}catch(error){node.textContent=error.message;}finally{COMPOSE.busy=false;}
}
async function snsComposeSave(){return snsComposeAction(async()=>{
  const at=document.getElementById('mini-compose-time').value;
  const payload={account_id:document.getElementById('mini-compose-account').value,text:document.getElementById('mini-compose-text').value,
    image_url:document.getElementById('mini-compose-image').value,scheduled_at:at?new Date(at+':00+09:00').toISOString():null};
  if(COMPOSE.post)payload.revision=COMPOSE.post.revision;
  const result=await api('/api/workspace/posts'+(COMPOSE.post?'/'+COMPOSE.post.id+'/edit':''),payload);
  document.getElementById('modals').replaceChildren();SNS_OPS.view='pending';SNS_OPS.record=result.id;await loadSnsOperations();
});}
async function snsComposeDraft(){return snsComposeAction(async(node)=>{
  const queued=await api('/api/workspace/draft',{account_id:document.getElementById('mini-compose-account').value,brief:document.getElementById('mini-compose-brief').value});
  node.textContent='작성 요청을 등록했습니다. 완료되면 승인 대기에 표시됩니다. 창을 닫아도 계속 처리합니다.';
  const check=async()=>{try{const job=await api('/api/workspace/jobs/'+queued.id);if(job.status==='done'){await loadSnsOperations();if(node.isConnected)node.textContent='초안이 준비됐습니다. 운영 화면의 승인 대기에서 검토하세요.';}else if(job.status==='failed'){if(node.isConnected)node.textContent=job.error;}else setTimeout(check,3000);}catch(error){if(node.isConnected)node.textContent=error.message;}};
  setTimeout(check,1500);
});}
document.addEventListener('keydown',event=>{if(event.key==='Escape')snsComposeClose();});
