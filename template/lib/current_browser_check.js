// 읽기 전용 로그인 관측. 새로 연 탭만 닫으며 글·댓글·좋아요를 입력하지 않는다.
let p=null;
const out={login_state:'unknown',publish_access:'unknown'};
const ref=(view,role,names)=>{
  const lines=view.tree.split('\n').filter(l=>names.some(n=>l.includes('- '+role+' "'+n+'"'))&&l.includes('[ref='));
  return lines.length===1?lines[0].split('[ref=')[1].split(']')[0]:null;
};
const signedOut=view=>/- (?:link|button) "(?:Log in|Sign in|로그인|ログイン)"/.test(view.tree);
const zennProfile=view=>{
  const lines=view.tree.split('\n').filter(l=>l.includes('- link "')&&l.includes('@'+C.account+'"')&&l.includes('[ref='));
  return lines.length===1?lines[0].split('[ref=')[1].split(']')[0]:null;
};
try {
  // LinkedIn은 linkedin.getMe()(탭 밖 API 호출)를 부르면 1분 안에 세션이 끊겼다
  // (2026-09-28 실측, 9/25부터 발행 실패의 원인) — 관리자 화면만으로 판정한다.
  p=await openTab(C.url);
  if(C.platform==='qiita'||C.platform==='zenn'){
    let v=await snapshot(p,{selector:'header',interactive:true});
    const menu=C.platform==='qiita'?'ユーザーメニューを開く':'メニューを開く';
    let button=ref(v,'button',[menu]);
    if(!button){await sleep(1000);v=await snapshot(p,{selector:'header',interactive:true});button=ref(v,'button',[menu]);}
    if(!button){if(signedOut(v))out.login_state='login_required';}
    else {
      await p.locator(button).click();
      v=await snapshot(p,{selector:'header',interactive:true});
      const names=C.platform==='qiita'?['マイページ']:['@'+C.account];
      let profile=ref(v,'link',names)||(C.platform==='zenn'?zennProfile(v):null);
      for(let i=0;i<2&&!profile;i++){
        await sleep(700);v=await snapshot(p,{selector:'header',interactive:true});profile=ref(v,'link',names)||(C.platform==='zenn'?zennProfile(v):null);
        if(!profile&&ref(v,'button',[menu])){await p.locator(ref(v,'button',[menu])).click();v=await snapshot(p,{selector:'header',interactive:true});profile=ref(v,'link',names);}
      }
      if(profile)out.login_state=await p.locator(profile).getAttribute('href')==='/'+C.account?'ok':'account_mismatch';
      // 다른 Zenn 계정은 메뉴의 @표시 프로필을 확인한 뒤 불일치로 구분한다.
      else if(C.platform==='zenn'&&/- link "[^"\n]*@[^"\n]+"/.test(v.tree))out.login_state='account_mismatch';
    }
  } else if(C.platform==='x'){
    let v=await snapshot(p,{selector:'header',interactive:true});
    let profile=ref(v,'link',['Profile','프로필','プロフィール']);
    if(!profile){await sleep(1000);v=await snapshot(p,{interactive:true});profile=ref(v,'link',['Profile','프로필','プロフィール']);}
    if(profile)out.login_state=await p.locator(profile).getAttribute('href')==='/'+C.account?'ok':'account_mismatch';
    else if(signedOut(v))out.login_state='login_required';
  } else if(C.platform==='linkedin'){
    const v=await snapshot(p,{interactive:true});
    if(ref(v,'textbox',['콘텐츠 제작용 텍스트 에디터']) && new URL(p.url()).hostname==='www.linkedin.com' && new URL(p.url()).pathname.startsWith('/'+C.account+'/admin/')){
      out.login_state='ok';out.publish_access='confirmed';
    }
    else if(signedOut(v)||/^https:\/\/www\.linkedin\.com\/(?:uas\/login|login)(?:[/?#]|$)/.test(p.url()))out.login_state='login_required';
  }
} catch(e) {
  // HTTP 인증 거절만 로그인 필요로 구분한다. 네트워크/DOM 오류는 확인 불가.
  if(C.platform==='linkedin'&&[401,403].includes(e?.status||e?.statusCode))out.login_state='login_required';
} finally {
  if(p){try{await closeTab(p);}catch(e){}}
}
console.log('ILSON_HEALTH:'+JSON.stringify(out));
