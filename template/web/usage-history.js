'use strict';
(() => {
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const api=async(action,body)=>{const options={credentials:'same-origin',cache:'no-store'};if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body);}const response=await fetch('/api/usage-history/'+action,options),data=await response.json();if(!response.ok)throw Error(data.error||'기록을 확인하지 못했습니다.');return data;};
  const num=v=>v===null||v===undefined?'확인 불가':Number(v).toLocaleString('ko-KR');
  const labels={off:'꺼짐',on_no_data:'켜짐 · 아직 관측된 기록 없음',on:'켜짐',partial:'일부 기록 · 누락/지원하지 않는 형식이 있습니다'};
  const syncLabels={disabled:'자동 공유 꺼짐',ready:'연결됨 · 전송 대기',synced:'연결됨 · 동기화됨',retry_pending:'연결됨 · 전송 재시도 대기',revoke_pending:'연결 해제·서버 삭제 대기',deleted:'연결 해제·서버 삭제 확인',needs_attention:'전송 중지 · 연결/버전 확인 필요'};
  async function mount(host){
    const root=node('section',undefined,'screen wide usage-history');root.setAttribute('aria-label','내 AI 사용 기록');host.replaceChildren(root);
    let data,tool='combined',year=new Date().getFullYear(),busy=false;
    const run=async(action,body)=>{if(busy)return;busy=true;try{data=await api(action,body);render();}catch(e){status.textContent=e.message;status.className='callout callout-danger';}finally{busy=false;}};
    const status=node('p','','uh-muted');status.setAttribute('role','status');
    const button=(title,fn)=>{const b=node('button',title,'btn btn-ghost');b.type='button';b.onclick=fn;return b;};
    const dangerButton=(title,fn)=>{const b=button(title,fn);b.className='btn btn-danger';return b;};
    function render(){
      root.replaceChildren();
      const heading=node('header',undefined,'h1row uh-heading'),titles=node('div');
      titles.append(node('div','일 · 자동화·컴퓨터 현황','eyebrow'),node('h1','내 AI 사용 기록','title'));
      const refresh=button('새로 수집',()=>run('collect',{}));refresh.className='btn btn-primary';heading.append(titles,refresh);root.append(heading,status);
      status.textContent=`로컬 기록 ${labels[data.state]} · ${syncLabels[data.sync_state]||'공유 상태 확인 필요'} · 시간대 ${data.timezone}`;
      status.className='chip uh-status';
      root.append(node('p','선택한 실습 범위에서 관측한 숫자입니다. 사용 시간·생산성·출석·계정 전체 사용량을 뜻하지 않습니다.','callout'));
      if(!data.source_available&&data.enabled)root.append(node('p','선택한 폴더의 로그를 아직 찾지 못했습니다. 폴더를 옮겼거나 로그가 삭제되면 확인되지 않을 수 있습니다.','callout'));
      if(data.revoke_pending)root.append(node('p','업로드는 중지했습니다. 서버 삭제 완료를 아직 확인하지 못했습니다. 연결된 사이트에서 본인 자료 삭제도 요청할 수 있습니다.','callout callout-danger'));
      const actions=node('div',undefined,'uh-controls');
      if(data.enabled)actions.append(button('로컬 기록 끄기',()=>run('off',{})));
      actions.append(button('JSON 내려받기',async()=>{try{const payload=await api('export',{});const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download='ilson-usage-summary.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){status.textContent=e.message;}}));
      if(data.linked)actions.append(dangerButton('연결 해제·서버 삭제',()=>run('unlink',{})),button('지금 동기화',()=>run('sync',{})));
      actions.append(dangerButton('로컬 파생 기록 삭제',()=>{if(confirm('기록을 끄고 이 기능의 로컬 파생 기록을 삭제합니다. 공급자 로그와 이미 공유한 서버 자료는 별도입니다. 삭제할까요?'))run('delete-local',{});}));root.append(actions);
      if(!data.enabled){
        const setup=node('details');setup.open=data.state==='off';setup.append(node('summary','실습 범위 확인하고 기록 켜기'));
        const controls=node('div',undefined,'uh-controls'),workspace=node('input'),zone=node('input'),backfill=node('input'),date=node('input'),consent=node('input');
        workspace.type='text';workspace.placeholder='내 홈 안의 실습 폴더 절대 경로';workspace.size=42;zone.value=data.timezone==='UTC'?'Asia/Seoul':data.timezone;backfill.type=consent.type='checkbox';date.type='date';
        for(const [title,input] of [['실습 폴더',workspace],['IANA 시간대',zone],['남아 있는 과거 기록도 불러오기 (별도 선택)',backfill],['과거 시작일',date],['아래 개인정보 안내를 읽고 로컬 수집에 동의합니다',consent]]){const label=node('label',title+' ');label.append(input);controls.append(label);}
        controls.append(button('선택 범위로 켜기',()=>{if(!consent.checked){status.textContent='개인정보 안내를 읽고 직접 동의해 주세요.';return;}if(backfill.checked&&!date.value){status.textContent='불러올 시작 날짜를 선택하세요.';return;}run('on',{workspace:workspace.value,timezone:zone.value,backfill_from:backfill.checked?date.value:null,consent:true});}));
        setup.className='card uh-details';setup.append(controls,node('p',data.privacy,'uh-muted'));root.append(setup);
      }
      const tabs=node('div',undefined,'seg uh-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','사용 도구');
      const tabButtons=[];
      for(const [id,title] of [['combined','통합'],['claude_code','Claude Code'],['codex','Codex · 준비 중']]){const b=button(title,()=>{tool=id;render();});b.className=tool===id?'on':'';b.id='uh-tab-'+id;b.setAttribute('aria-controls','uh-panel');b.setAttribute('role','tab');b.setAttribute('aria-selected',String(tool===id));b.tabIndex=tool===id?0:-1;b.disabled=id==='codex';b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();tool=e.key==='Home'?'combined':e.key==='End'?'claude_code':tool==='combined'?'claude_code':'combined';render();root.querySelector('[role=tab][aria-selected=true]').focus();}};tabButtons.push(b);tabs.append(b);}root.append(tabs);
      const panel=node('div');panel.id='uh-panel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','uh-tab-'+tool);root.append(panel);
      const m=tool==='combined'?data.totals:data.tools[tool],dl=node('dl',undefined,'uh-metrics');
      const facts=[['사용한 날짜',num(m.active_days)+'일'],['관측 세션',num(m.sessions)],['본인 대화',num(m.turns)+'회'],['현재 연속 사용',num(m.current_streak)+'일'],['최장 연속 사용',num(m.longest_streak)+'일'],['최근 30일',`${num(m.recent_30_days.active_days)}일 · ${num(m.recent_30_days.turns)}회`],['피크 날짜 · 대화 기준',m.peak_day||'기록 없음'],['피크 월 · 대화 기준',m.peak_month||'기록 없음']];
      if(tool!=='combined'){facts.push(['가장 많이 사용한 모델',m.most_used_model||'확인 불가'],['입력 토큰',num(m.input_tokens)],['출력 토큰',num(m.output_tokens)],['캐시 읽기 토큰',num(m.cache_read_tokens)],['캐시 생성 토큰',num(m.cache_creation_tokens)]);const c=m.estimated_cost;facts.push(['목록가 비용 · 추정',c.usd_min===null?'확인 불가':`$${c.usd_min.toFixed(4)} ~ $${c.usd_max.toFixed(4)}${c.partial?' · 일부만 계산':''}`]);}
      facts.forEach(([k,v])=>{const item=node('div',undefined,'card metric-card');item.append(node('dt',k),node('dd',v));dl.append(item);});panel.append(dl);
      if(tool!=='combined'){const p=node('p',`추정 가격표 ${data.price_table.checked_at} · ${data.price_table.cache_write_assumption} · 실제 구독 청구액과 다릅니다. `,'uh-muted'),a=node('a','Anthropic 공식 가격표');a.href=data.price_table.source;a.target='_blank';a.rel='noreferrer';p.append(a);root.append(p);}
      const mapCard=node('section',undefined,'card uh-map-card'),mapHeading=node('div',undefined,'uh-map-heading');mapHeading.append(node('h2','날짜별 사용'));panel.append(mapCard);
      const years=node('select');years.setAttribute('aria-label','히트맵 연도');const currentYear=Number(data.today.slice(0,4));for(let y=currentYear;y>=currentYear-1;y--){const o=node('option',y+'년');o.value=y;o.selected=y===year;years.append(o);}years.onchange=()=>{year=Number(years.value);render();};mapHeading.append(years);mapCard.append(mapHeading);
      const grouped=new Map();for(const row of data.daily.filter(r=>tool==='combined'||r.tool===tool)){const v=grouped.get(row.date)||{sessions:0,turns:0,tokens:0,partial:false};v.sessions+=row.sessions;v.turns+=row.turns;v.tokens+=['input_tokens','output_tokens','cache_read_tokens','cache_creation_tokens'].reduce((s,k)=>s+(row[k]||0),0);v.partial ||= row.quality==='partial';grouped.set(row.date,v);}
      const wrap=node('div',undefined,'uh-map-scroll'),months=node('div',undefined,'uh-months');for(let month=1;month<=12;month++)months.append(node('span',month+'월'));wrap.append(months);
      const map=node('div',undefined,'uh-heatmap');map.setAttribute('role','group');map.setAttribute('aria-label',year+'년 날짜별 사용. 방향키로 하루/한 주 이동');const selected=node('p','날짜에 초점을 맞추면 건수와 관측 상태를 읽을 수 있습니다.','uh-muted');selected.setAttribute('aria-live','polite');
      const start=new Date(Date.UTC(year,0,1));start.setUTCDate(start.getUTCDate()-start.getUTCDay());const end=new Date(Date.UTC(year+1,0,1));end.setUTCDate(end.getUTCDate()+6-end.getUTCDay());
      const peak=Math.max(1,...Array.from(grouped.values(),v=>tool==='combined'?v.turns:v.tokens));const cells=[];
      for(let dt=new Date(start);dt<end;dt.setUTCDate(dt.getUTCDate()+1)){const day=dt.toISOString().slice(0,10),v=grouped.get(day),inside=dt.getUTCFullYear()===year&&day<=data.today;const value=v?(tool==='combined'?v.turns:v.tokens):0;const level=value>0?Math.min(4,Math.max(1,Math.ceil(value/peak*4))):0;const label=day+(v?` · 관측 세션 ${v.sessions} · 본인 대화 ${v.turns}회${tool==='combined'?'':' · 토큰 '+v.tokens}${v.partial?' · 일부 기록':''}`:' · 미관측');const cell=button('',()=>{selected.textContent=label;});cell.className='uh-day';cell.dataset.level=level;cell.dataset.unknown=String(!v);cell.title=label;cell.setAttribute('aria-label',label);cell.tabIndex=cells.length===0?0:-1;if(!inside){cell.style.visibility='hidden';cell.disabled=true;}cell.onfocus=()=>{selected.textContent=label;};cells.push(cell);map.append(cell);}
      const first=cells.find(c=>!c.disabled);if(first){cells[0].tabIndex=-1;first.tabIndex=0;}
      cells.forEach((cell,i)=>{cell.onkeydown=e=>{const delta={ArrowUp:-1,ArrowDown:1,ArrowLeft:-7,ArrowRight:7,Home:-i,End:cells.length-1-i}[e.key];if(delta===undefined)return;e.preventDefault();let n=Math.max(0,Math.min(cells.length-1,i+delta));while(cells[n]?.disabled&&n>0&&n<cells.length-1)n+=delta<0?-1:1;if(!cells[n]?.disabled){cell.tabIndex=-1;cells[n].tabIndex=0;cells[n].focus();}};});
      const gridRow=node('div',undefined,'uh-grid-row'),weekdays=node('div',undefined,'uh-weekdays');weekdays.setAttribute('aria-hidden','true');for(const name of ['일','월','화','수','목','금','토'])weekdays.append(node('span',name));gridRow.append(weekdays,map);wrap.append(gridRow);mapCard.append(wrap);const legend=node('div',undefined,'uh-legend');legend.append(node('span','적음'));for(let i=0;i<5;i++){const square=node('i');square.setAttribute('aria-hidden','true');legend.append(square);}legend.append(node('span','많음 · 채운 칸=관측값 (0 포함) · 빈 점선=미관측 · 날짜별 텍스트 제공'));mapCard.append(legend,selected);
      const details=node('details'),tableWrap=node('div',undefined,'uh-table-scroll'),table=node('table',undefined,'data-table'),thead=node('thead'),tr=node('tr');details.className='card uh-details';details.append(node('summary','날짜별 숫자 표'));for(const h of ['날짜','관측 세션','본인 대화','상태']){const th=node('th',h);th.scope='col';tr.append(th);}thead.append(tr);table.append(thead);const tbody=node('tbody');for(const [day,v] of [...grouped].sort((a,b)=>b[0].localeCompare(a[0]))){const r=node('tr');for(const text of [day,v.sessions,v.turns,v.partial?'일부 기록':'관측값'])r.append(node('td',text));tbody.append(r);}table.append(tbody);tableWrap.append(table);details.append(tableWrap);panel.append(details);
      const preview=node('details');preview.append(node('summary','연결 전에 전송 JSON 전체 보기'));preview.append(node('p','연결 전 enrollment_id/consent_id는 null이며, 연결 후 사이트가 발급한 가명 UUID로 채워집니다. 본문·경로는 포함되지 않습니다.','uh-muted'),node('pre',JSON.stringify(data.preview,null,2)));preview.className='card uh-details';root.append(preview);
      if(!data.linked&&data.enabled){const link=node('details');link.append(node('summary','강의 사이트에 별도 동의하고 연결'));const controls=node('div',undefined,'uh-controls'),url=node('input'),code=node('input'),consent=node('input');url.type='url';url.placeholder='승인된 강의 사이트 주소 (배포 prefix 포함)';url.size=42;code.type='password';code.autocomplete='off';code.maxLength=12;consent.type='checkbox';for(const [title,input] of [['사이트 주소',url],['사이트에서 받은 일회 코드',code],['위 JSON과 개인정보 안내를 확인하고 Jake에게 공유합니다',consent]]){const label=node('label',title+' ');label.append(input);controls.append(label);}controls.append(button('공유에 동의하고 연결',()=>{if(!consent.checked||!preview.open){status.textContent='전송 JSON 전체를 열어 확인하고 공유에 동의하세요.';return;}run('link',{base_url:url.value,code:code.value,consent:true,preview_revision:data.preview.revision});code.value='';}));link.className='card uh-details';link.append(controls,node('p',data.privacy,'uh-muted'));root.append(link);}
      root.append(node('p','F8 계정 한도는 상태줄의 최신 5시간/7일 한도 값입니다. 이 일별 기록·토큰 장부와 따로 확인하세요. 로그 누락은 미사용을 뜻하지 않습니다.','callout'));
    }
    root.append(status);await run('summary');
  }
  window.IlsonUsage={mount};
})();
