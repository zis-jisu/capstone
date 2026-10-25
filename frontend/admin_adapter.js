/* LINK-ing admin interface. Changes only management behavior; preserves original layout. */
(() => {
  'use strict';
  renderAssignments = () => {}; // Legacy demo management list is replaced by the DB-backed list.
  let token = null; // never store the admin secret in localStorage or HTML
  let directory = {persons:[], tasks:[]};
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const displayTime = value => value ? new Date(value).toLocaleString('ko-KR') : '미연동';
  async function request(path, options={}) {
    const response = await fetch(path, {cache:'no-store',credentials:'same-origin',...options,
      headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(token?{'X-Admin-Token':token}:{}),...(options.headers||{})}});
    if(!response.ok) throw new Error(response.status===403?'관리자 인증이 거부됐어요.':`요청 실패 (HTTP ${response.status})`);
    return response.json();
  }
  async function loadMeta(){
    try {
      const info = await request('/api/demo/meta');
      $('model-meta').textContent = info.model_trained_at
        ? `최신 모델 학습 · ${displayTime(info.model_trained_at)}  |  업무 분석 · ${displayTime(info.last_analyzed_at)}`
        : `모델 학습 날짜 미연동  |  업무 분석 · ${displayTime(info.last_analyzed_at)}`;
    } catch(err) { $('model-meta').textContent = '모델 학습 날짜 · 조회 불가'; }
  }
  function setAdmin(active){
    currentUserRole = active ? 'manager' : 'employee';
    applyRoleAccess();
    $('admin-toggle').textContent = active ? '관리자 모드 종료' : '관리자 모드';
    $('admin-toggle').classList.toggle('bg-[#F2F7FF]', active);
  }
  window.toggleAdminMode = async () => {
    if(token){token=null;setAdmin(false);setMainView('briefing');return;}
    const candidate=window.prompt('관리자 비밀번호를 입력하세요. (시연 로그인과 별도)');
    if(!candidate) return;
    token=candidate;
    try {
      await request('/api/admin/validate');
      setAdmin(true);setMainView('manage');
      await loadDirectory(); await loadAssignments();
    } catch(err) { token=null;setAdmin(false);toast(err.message); }
  };
  async function loadDirectory(){
    const data=await request('/api/demo/data');
    directory={persons:data.persons||[],tasks:data.tasks||[]};
    const persons=directory.persons.map(p=>`<option value="${escapeHtml(p.person_id)}">${escapeHtml(p.name)}</option>`).join('');
    $('admin-sync-person').innerHTML=persons;
    $('admin-assignee').innerHTML=persons;
    $('admin-task').innerHTML=directory.tasks.map(t=>`<option value="${escapeHtml(t.task_id)}">${escapeHtml(t.title)}</option>`).join('');
    if(directory.persons.some(p=>p.person_id==='U0C22C8M742'))$('admin-sync-person').value='U0C22C8M742';
  }
  async function loadAssignments(){
    const rows=(await request('/api/admin/assignments')).assignments||[];
    const personId=id=>directory.persons.find(x=>x.person_id===id)?.name||id;
    const taskId=id=>directory.tasks.find(x=>x.task_id===id)?.title||id;
    $('admin-assignment-list').innerHTML = rows.length ? rows.map(x=>`<div class="rounded-xl border border-[#EEF0F3] px-4 py-3 flex flex-wrap justify-between gap-3"><span><b>${escapeHtml(taskId(x.task_id))}</b> → ${escapeHtml(personId(x.assignee_id))}</span><span class="text-[#8B95A1]">${escapeHtml(displayTime(x.assigned_at))} · ${escapeHtml(x.status)}</span></div>`).join('') : '<div class="text-[#8B95A1]">배정 내역이 없습니다.</div>';
  }
  window.runAdminSync = async () => {
    const button=$('admin-sync-button'); button.disabled=true; $('admin-sync-result').textContent='Slack MCP 메시지 수집 중…';
    try {
      const r=await request('/api/admin/slack-collect',{method:'POST',body:JSON.stringify({person_id:$('admin-sync-person').value,days:Number($('admin-sync-days').value)})});
      $('admin-sync-result').textContent=`수집 성공 · 메시지 ${r.messages}건 / 작성자 ${r.people}명 / 채널 ${r.channels.length}개 / 경고 ${r.warnings}건 · DB 저장 및 LLM 재분석은 미실행`;
    } catch(err){ $('admin-sync-result').textContent=err.message; }
    finally {button.disabled=false;}
  };
  window.createAdminAssignment = async () => {
    const button=$('admin-assign-button'); button.disabled=true; $('admin-assign-result').textContent='업무 배정 저장 중…';
    try {
      await request('/api/admin/assignments',{method:'POST',body:JSON.stringify({task_id:$('admin-task').value,assignee_id:$('admin-assignee').value})});
      $('admin-assign-result').textContent='배정 저장 완료 · 원본 Task 담당자와 그래프는 그대로 유지됩니다.';
      await loadAssignments();
    } catch(err){$('admin-assign-result').textContent=err.message;}
    finally {button.disabled=false;}
  };
  loadMeta();
})();


/* Marketing handover UI DEMO only. Browser storage is NOT server authorization. */
(() => {
 'use strict';
 const TEAM=['김지수','박서연','최민준'], ACCOUNT=['원이정','김지수','팀장'];
 const KEY='linking_marketing_handover_demo_v1';
 const WORK_ID='WORK-00020', WORK_TITLE='신차 출시 캠페인 콘텐츠 현지화 및 배포 준비';
 const CASE_TASKS=[
  ['TASK-00077','본사 캠페인 패키지 v3 변경사항 확인'],
  ['TASK-00078','국내 사양·기술 표현 검증'],
  ['TASK-00079','국내용 원고 제목·CTA 확정'],
  ['TASK-00080','딜러 이미지·UTM·배포 대상 준비 및 포털 반영']
 ];
 let actor='원이정';
 const el=id=>document.getElementById(id);
 const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const load=()=>{try{const x=JSON.parse(localStorage.getItem(KEY)||'[]');return Array.isArray(x)?x:[]}catch{return []}};
 const store=x=>localStorage.setItem(KEY,JSON.stringify(x));
 function panel(title,body){
  let node=el('handover-demo-panel');
  if(!node){node=document.createElement('div');node.id='handover-demo-panel';node.className='fixed inset-0 z-[110] hidden items-center justify-center bg-black/40 p-4';document.body.appendChild(node);}
  node.innerHTML='<section role="dialog" aria-modal="true" class="w-full max-w-[750px] max-h-[88vh] overflow-y-auto rounded-[24px] bg-white p-6 shadow-2xl"><header class="flex justify-between gap-3"><div><div class="text-[11px] text-[#3182F6] font-bold">시연 모드 · 실제 계정 인증 아님</div><h2 class="mt-2 text-[21px] font-bold">'+safe(title)+'</h2></div><button id="handover-demo-close" class="h-9 w-9 rounded-xl border" aria-label="닫기">×</button></header><div class="mt-5">'+body+'</div></section>';
  node.classList.remove('hidden');node.classList.add('flex');
  el('handover-demo-close').onclick=closePanel;
 }
 function closePanel(){const n=el('handover-demo-panel');if(n){n.classList.add('hidden');n.classList.remove('flex');}}
 function message(s){if(typeof toast==='function')toast(s);else alert(s);}
 function selectedWork(){return (IMPORT_DATA[importState.person]||[]).some(g=>g.project===WORK_TITLE&&g.tasks.every(t=>importState.selected.has(g.project+'::'+t)));}
 function seed(){
  if(typeof IMPORT_DATA==='undefined')return;
  const groups=IMPORT_DATA['김지수']||(IMPORT_DATA['김지수']=[]);
  if(!groups.some(g=>g.project===WORK_TITLE))groups.unshift({project:WORK_TITLE,tasks:CASE_TASKS.map(x=>x[1])});
 }
 function received(){
  const rows=load().filter(r=>r.requester===actor);
  panel('나의 인수인계 요청',rows.length?rows.map(r=>'<div class="mb-3 rounded-2xl border border-[#E5E8EB] p-4"><div class="flex items-center justify-between gap-2"><b>'+safe(r.owner)+'님의 업무</b><span class="text-[12px]">'+({pending:'승인 대기',approved:'승인 완료',rejected:'반려'}[r.status]||r.status)+'</span></div><div class="mt-2 text-[13px]">'+safe(r.title)+'</div>'+(r.status==='approved'?'<button data-open="'+safe(r.id)+'" class="mt-3 rounded-xl bg-[#3182F6] px-4 py-2 text-[12px] font-bold text-white">이어받은 업무 보기</button>':'')+'</div>').join(''):'<div class="rounded-xl bg-[#F8F9FA] p-5 text-[13px]">요청 내역이 없습니다.</div>');
  el('handover-demo-panel').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>viewWork(b.dataset.open));
 }
 function viewWork(id){
  const r=load().find(x=>x.id===id&&x.status==='approved'&&x.requester===actor);
  if(!r)return message('승인된 인수인계만 확인 가능합니다.');
  closePanel();
  if(PROJECTS.some(p=>p.id===r.workId)){
   state.project=r.workId;state.task=PROJECTS.find(p=>p.id===r.workId).tasks[0];state.filter=null;
   const select=el('project-select');if(select)select.value=r.workId;
   if(typeof setMainView==='function')setMainView('briefing');
   render();
   message('김지수에게 이어받은 WORK-00020을 표시했습니다.');
  }else{
   panel('이어받은 업무','<div class="rounded-xl bg-[#F2F7FF] p-4 font-bold">'+safe(r.title)+'</div><div class="mt-3 space-y-3">'+CASE_TASKS.map((t,i)=>'<div class="rounded-xl border p-3"><div class="text-[11px] text-[#8B95A1]">'+safe(t[0])+' · '+(i<2?'완료':i===2?'진행 중':'대기')+'</div><div class="font-bold">'+safe(t[1])+'</div></div>').join('')+'</div><div class="mt-3 text-[12px] text-[#8B95A1]">현재 Supabase 조회 결과에는 이 Work가 없어 첨부 시나리오 예시를 표시합니다.</div>');
  }
 }
 function inbox(){
  if(actor==='원이정')return received();
  const all=load().filter(r=>actor==='팀장'||r.owner===actor);
  const pending=all.filter(r=>r.status==='pending');
  let body=pending.length?pending.map(r=>'<div class="mb-3 rounded-2xl border p-4"><div class="font-bold">'+safe(r.requester)+' → '+safe(r.owner)+'</div><div class="mt-2 text-[13px]">'+safe(r.title)+'</div><div class="mt-3 flex gap-2"><button data-verify="'+safe(r.id)+'" class="rounded-xl bg-[#3182F6] px-4 py-2 text-[12px] font-bold text-white">가상 YubiKey 승인</button><button data-reject="'+safe(r.id)+'" class="rounded-xl border px-4 py-2 text-[12px]">반려</button></div></div>').join(''):'<div class="rounded-xl bg-[#F8F9FA] p-5 text-[13px]">대기 중인 인수인계 요청이 없습니다.</div>';
  const done=all.filter(r=>r.status!=='pending');
  if(done.length)body+='<h3 class="mt-5 mb-2 font-bold">처리 이력</h3>'+done.map(r=>'<div class="border-b py-2 text-[12px]">'+safe(r.requester)+' → '+safe(r.owner)+' · '+(r.status==='approved'?'승인':'반려')+' · '+safe(r.approvedBy)+'</div>').join('');
  panel(actor==='팀장'?'팀 인수인계 승인함':'김지수 인수인계 승인함',body);
  el('handover-demo-panel').querySelectorAll('[data-verify]').forEach(b=>b.onclick=()=>verify(b.dataset.verify));
  el('handover-demo-panel').querySelectorAll('[data-reject]').forEach(b=>b.onclick=()=>decide(b.dataset.reject,'rejected'));
 }
 function verify(id){
  const r=load().find(x=>x.id===id&&x.status==='pending');
  if(!r||(actor!=='팀장'&&actor!==r.owner))return message('승인할 수 없는 요청입니다.');
  panel('가상 YubiKey 승인','<div class="rounded-2xl bg-[#F2F7FF] p-6 text-center"><div class="text-[38px]">🔑</div><h3 class="mt-3 text-[17px] font-bold">보안키 터치 시연</h3><p class="mt-2 text-[12px] text-[#6B7684]">실제 YubiKey 또는 WebAuthn 인증이 아닙니다.</p><button id="handover-confirm" class="mt-5 rounded-xl bg-[#3182F6] px-5 py-3 text-white font-bold">가상 보안키 터치 · 승인</button></div>');
  el('handover-confirm').onclick=()=>decide(id,'approved');
 }
 function decide(id,status){
  const rows=load(),r=rows.find(x=>x.id===id&&x.status==='pending');
  if(!r||(actor!=='팀장'&&actor!==r.owner))return message('처리 권한이 없습니다.');
  r.status=status;r.approvedBy=actor;r.decidedAt=new Date().toISOString();store(rows);inbox();
  message(status==='approved'?'승인 완료. 원이정 계정에서 업무를 확인하세요.':'요청을 반려했습니다.');
 }
 function switchActor(next){
  if(!ACCOUNT.includes(next))return;
  actor=next;closePanel();if(typeof closeImport==='function')closeImport();
  el('handover-demo-account').value=actor;
  const label=el('handover-demo-current');if(label)label.textContent=actor+' · BMW Marketing · 시연';
  if(typeof setMainView==='function')setMainView('briefing');
  message(actor+' UI로 전환했습니다. 실제 로그인 변경은 아닙니다.');
 }
 const originalOpen=openImport;
 openImport=function(){
  if(actor==='팀장')return inbox();
  seed();originalOpen();
  importState.person=null;importState.selected=new Set();importState.step=1;importState.approved=false;
  renderImportPeople();renderImportTasks();renderImportFlow();
 };
 renderImportPeople=function(){
  const q=(el('person-search')?.value||'').trim();
  const people=TEAM.filter(p=>p!==actor&&(!q||p.includes(q)));
  const holder=el('import-people');if(!holder)return;
  holder.innerHTML=people.map(p=>'<button data-team-person="'+safe(p)+'" class="w-full rounded-2xl border '+(importState.person===p?'border-[#3182F6] bg-[#F2F7FF]':'border-[#EEF0F3] bg-white')+' p-3 flex items-center gap-3 text-left"><span class="flex h-9 w-9 items-center justify-center rounded-full bg-[#E8F3FF] text-[#3182F6] font-bold">'+p.slice(0,1)+'</span><span><b class="text-[13px]">'+safe(p)+'</b><span class="block text-[11px] text-[#8B95A1]">BMW Marketing</span></span></button>').join('')||'<div class="p-3 text-[12px]">같은 팀 내 검색 결과가 없습니다.</div>';
  holder.querySelectorAll('[data-team-person]').forEach(b=>b.onclick=()=>{seed();selectImportPerson(b.dataset.teamPerson)});
 };
 const previousFlow=renderImportFlow;
 renderImportFlow=function(){
  previousFlow();
  const name=el('import-action-title'),summary=el('import-selection-summary'),btn=el('import-action-btn'),slack=el('slack-access-panel');
  if(slack)slack.classList.add('hidden');
  if(importState.step===1){name.textContent='인수인계 승인 요청';btn.textContent='인수인계 요청 보내기';btn.onclick=requestImportApproval;}
  else {name.textContent='승인 대기';summary.textContent='김지수 또는 팀장이 승인해야 업무를 이어받을 수 있어요.';btn.textContent='요청 상태 확인';btn.onclick=()=>{closeImport();received()};}
 };
 requestImportApproval=function(){
  if(actor!=='원이정'||importState.person!=='김지수')return message('이번 시연은 원이정 → 김지수 요청 기준입니다.');
  if(!selectedWork())return message('김지수의 WORK-00020을 선택해 주세요.');
  const rows=load();
  if(rows.some(r=>r.status==='pending'&&r.requester===actor&&r.owner==='김지수'&&r.workId===WORK_ID))return message('이미 승인 대기 중인 요청입니다.');
  rows.push({id:'request-'+Date.now(),requester:actor,owner:'김지수',workId:WORK_ID,title:WORK_TITLE,status:'pending',createdAt:new Date().toISOString()});
  store(rows);importState.step=2;importState.approved=false;renderImportFlow();message('승인 요청을 보냈습니다. 김지수 또는 팀장 UI에서 승인하세요.');
 };
 const header=el('header-kicker')?.parentElement?.parentElement;
 if(header&&!el('handover-demo-toolbar')){
  const bar=document.createElement('div');bar.id='handover-demo-toolbar';bar.className='flex flex-wrap items-center gap-2';
  bar.innerHTML='<span id="handover-demo-current" class="text-[11px] text-[#6B7684]">원이정 · BMW Marketing · 시연</span><select id="handover-demo-account" aria-label="시연 계정" class="h-9 rounded-xl border border-[#DDE3EA] bg-white px-2 text-[12px]"><option>원이정</option><option>김지수</option><option>팀장</option></select><button id="handover-demo-inbox" class="h-9 rounded-xl border border-[#DDE3EA] bg-white px-3 text-[12px] font-bold">요청·승인함</button><button id="handover-demo-received" class="h-9 rounded-xl border border-[#DDE3EA] bg-white px-3 text-[12px] font-bold">이어받은 업무</button>';
  header.appendChild(bar);
  el('handover-demo-account').onchange=e=>switchActor(e.target.value);
  el('handover-demo-inbox').onclick=inbox;
  el('handover-demo-received').onclick=()=>{if(actor==='원이정')received();else inbox();};
 }
 const steps=document.querySelectorAll('#import-steps [data-step] div:last-child');
 ['업무 선택','승인 요청','승인 확인','업무 확인'].forEach((x,i)=>{if(steps[i])steps[i].textContent=x});
 const sub=document.querySelector('#import-modal p');
 if(sub)sub.textContent='같은 팀 구성원의 Work를 선택해 인수인계를 요청합니다. 승인 전에는 업무가 전달되지 않습니다.';
 seed();
})();
