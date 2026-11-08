/* Manual review and opt-in Q&A collection. No automatic publish button. */
window.IlsonReplies = (() => {
  const post = async (path, data) => {
    const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || '요청을 완료하지 못했습니다.');
    return result;
  };
  const val = id => document.getElementById(id).value;
  const message = (id, text) => { document.getElementById(id).textContent = text; };
  const screen = () => `<div style="padding:32px;max-width:880px;line-height:1.7">
    <h1>답글 초안</h1><p>고객 글을 확인하고 답글을 준비하세요. 리뷰와 플레이스 글은 직접 붙여 넣어 초안을 만든 뒤 판매자센터에서 직접 게시합니다.</p>
    <p>고객 이름·연락처·주문 정보가 포함될 수 있습니다. 내용을 직접 살펴 필요한 부분만 입력하세요. 자동으로 가려 주지는 않습니다.</p>
    <section><h2>직접 가져온 글</h2><label for="replyText">고객 글</label><br><textarea id="replyText" rows="6" maxlength="3000" style="width:100%"></textarea><br>
    <label><input id="replyConsent" type="checkbox"> 이 내용을 Claude로 보내 초안을 만드는 데 동의합니다.</label><br>
    <button type="button" onclick="IlsonReplies.make()">초안 만들기</button><p id="replyResult" role="status" style="white-space:pre-wrap"></p></section>
    <section><h2>네이버 상품 문의 연결</h2><p>상품 문의만 연결합니다. 애플리케이션과 문의 권한이 있어야 합니다. 연결 정보는 이 기기의 비공개 파일에 저장하며, 실제 연결은 별도 확인이 필요합니다. 수집한 문의와 초안은 이 기기의 비공개 폴더에 남으며 자동 삭제되지 않습니다.</p>
    <label><input id="replyInstallConsent" type="checkbox"> 네이버 연결에 필요한 bcrypt 4.3.0을 이 Box 전용 환경에 설치합니다.</label><br><button type="button" onclick="IlsonReplies.install()">네이버 연결 준비</button><p id="replyInstallResult" role="status"></p>
    <label>계정 별칭 <input id="replyAccount" maxlength="128" autocomplete="off"></label><br>
    <label>애플리케이션 ID <input id="replyClient" maxlength="512" autocomplete="off"></label><br>
    <label>애플리케이션 시크릿 <input id="replySecret" type="password" maxlength="512" autocomplete="new-password"></label><br>
    <label>인증 유형 <select id="replyType"><option value="SELF">내 스토어</option><option value="SELLER">판매자 지정</option></select></label><br>
    <label>판매자 ID (판매자 지정 시) <input id="replySeller" maxlength="512" autocomplete="off"></label><br>
    <button type="button" onclick="IlsonReplies.connect()">연결 정보 저장</button> <button type="button" onclick="IlsonReplies.disconnect()">연결 끊기</button><p id="replyConnectResult" role="status"></p>
    <p>수집할 기간을 시간대까지 입력하세요. 예: 2026-11-01T00:00:00+09:00</p>
    <label>시작 <input id="replyFrom" placeholder="2026-11-01T00:00:00+09:00"></label><br>
    <label>종료 <input id="replyTo" placeholder="2026-11-08T00:00:00+09:00"></label><br>
    <label><input id="replyCollectConsent" type="checkbox"> 이 기간의 상품 문의를 이 기기에 수집하는 데 동의합니다.</label><br>
    <button type="button" onclick="IlsonReplies.collect()">문의 가져오기</button><p id="replyCollectResult" role="status" style="white-space:pre-wrap"></p>
    <h3>예약 수집과 초안</h3><p>매일 오전 9시, 입력한 시작 시각부터 상품 문의를 확인합니다. 비공개 파일에 초안을 저장하며 자동 발송하지 않습니다.</p>
    <label><input id="replyScheduleConsent" type="checkbox"> 상품 문의를 예약 수집하고 Claude에 보내 초안을 만드는 데 동의합니다.</label><br>
    <button type="button" onclick="IlsonReplies.schedule(true)">예약 준비</button> <button type="button" onclick="IlsonReplies.schedule(false)">예약 수집 끄기</button> <button type="button" onclick="IlsonReplies.drafts()">저장된 초안 보기</button>
    <p id="replyScheduleResult" role="status" style="white-space:pre-wrap"></p><p id="replyDraftsResult" role="status" style="white-space:pre-wrap"></p>
    <h3>상품 문의 답변 승인 요청</h3><p>위에서 확인한 문의 번호와 답변을 입력하세요. 승인함에서 계정과 전문을 다시 확인해야 합니다. 다른 곳에서 답변했는지 발송 직전에 확인하지만, 조회 직후 동시에 게시되는 상황은 완전히 막을 수 없습니다.</p>
    <label>문의 번호 <input id="replyQuestionId" inputmode="numeric"></label><br>
    <label for="replyAnswer">답변 전문</label><br><textarea id="replyAnswer" rows="5" maxlength="2000" style="width:100%"></textarea><br>
    <button type="button" onclick="IlsonReplies.request()">승인 요청 만들기</button><p id="replyRequestResult" role="status"></p>
    <p>예약 수집은 기본적으로 꺼져 있습니다. 답변은 승인 연동과 검증이 끝나기 전 자동으로 발송하지 않습니다.</p></section></div>`;
  async function make(){
    message('replyResult','초안을 준비하고 있습니다.');
    try { const r=await post('/api/replies/draft',{text:val('replyText'),consent:document.getElementById('replyConsent').checked});message('replyResult',[r.text,r.message].filter(Boolean).join('\n\n')); }
    catch(e){message('replyResult',e.message);}
  }
  async function install(){
    message('replyInstallResult','연결 준비 중입니다. 잠시 기다려 주세요.');
    try { const r=await post('/api/replies/install',{consent:document.getElementById('replyInstallConsent').checked});message('replyInstallResult',r.message); }
    catch(e){message('replyInstallResult',e.message);}
  }
  async function connect(){
    const secret=val('replySecret'); document.getElementById('replySecret').value='';
    try { const r=await post('/api/replies/connection',{account:val('replyAccount'),client_id:val('replyClient'),client_secret:secret,type:val('replyType'),account_id:val('replySeller')});message('replyConnectResult',r.message); }
    catch(e){message('replyConnectResult',e.message);}
  }
  async function disconnect(){
    if(!window.confirm('이 계정의 연결 정보를 지우고 예약 수집을 끄시겠어요?')) return;
    try { const r=await post('/api/replies/disconnect',{account:val('replyAccount')});message('replyConnectResult',r.message); }
    catch(e){message('replyConnectResult',e.message);}
  }
  async function collect(){
    message('replyCollectResult','문의를 확인하고 있습니다.');
    try { const r=await post('/api/replies/collect',{account:val('replyAccount'),start:val('replyFrom'),end:val('replyTo'),consent:document.getElementById('replyCollectConsent').checked});message('replyCollectResult',`${r.count}건 확인\n`+r.questions.map(q=>`${q.id} · ${q.answered?'답변됨':'미답변'}\n${q.question}`).join('\n\n')); }
    catch(e){message('replyCollectResult',e.message);}
  }
  async function schedule(enabled){
    const consent=document.getElementById('replyScheduleConsent').checked;
    try { const r=await post('/api/replies/schedule',{enabled,account:val('replyAccount'),start:val('replyFrom'),collection_consent:consent,model_consent:consent});message('replyScheduleResult',r.message); }
    catch(e){message('replyScheduleResult',e.message);}
  }
  async function drafts(){
    try { const r=await post('/api/replies/drafts',{account:val('replyAccount')});message('replyDraftsResult',r.drafts.length?r.drafts.map(d=>`${d.id} · ${d.status==='draft'?'초안':'확인 필요'}\n${d.question}\n${d.body||''}`).join('\n\n'):'저장된 초안이 없습니다.'); }
    catch(e){message('replyDraftsResult',e.message);}
  }
  async function request(){
    try { const r=await post('/api/replies/request',{account:val('replyAccount'),question_id:val('replyQuestionId'),body:val('replyAnswer')});message('replyRequestResult',r.message); }
    catch(e){message('replyRequestResult',e.message);}
  }
  return {screen, make, install, connect, disconnect, collect, schedule, drafts, request};
})();
