/* LINK-ing admin interface. Changes only management behavior; preserves original layout. */
(() => {
  'use strict';
  renderAssignments = () => {}; // Legacy demo management list is replaced by the DB-backed list.
  let token = null; // never store the admin secret in localStorage or HTML
  let directory = {persons:[], tasks:[], works:[], edges:[]};
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const displayTime = value => value ? new Date(value).toLocaleString('ko-KR') : '미연동';
  async function request(path, options={}) {
    const response = await fetch(path, {cache:'no-store',credentials:'same-origin',...options,
      headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(token?{'X-Admin-Token':token}:{}),...(currentUserRole==='manager'?{'X-Demo-Role':'manager'}:{}),...(options.headers||{})}});
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
  window.activateManagerWorkspace=async function(role){
    token=null;
    currentUserRole=role;
    applyRoleAccess();
    const manager=role==='manager',admin=role==='admin';
    $('admin-sync-section').classList.toggle('hidden',!admin);
    $('manager-assignment-section').classList.toggle('hidden',!manager);
    $('manager-history-section').classList.toggle('hidden',!manager);
    $('management-title').textContent=admin?'Slack 연동 관리':'팀원 업무 배정';
    $('admin-sync-button').disabled=!admin;
    $('admin-assign-button').disabled=!manager;
    if(!manager&&!admin)return;
    setMainView('manage');
    if(admin){
      const section=$('admin-sync-section');
      let form=$('admin-auth-form');
      if(!form){
        form=document.createElement('form');form.id='admin-auth-form';
        form.innerHTML='<label class="block text-[12px] font-bold">관리자 비밀번호<input id="admin-password" type="password" autocomplete="current-password" class="mt-2 w-full rounded-xl border px-3 h-11"/></label><button class="mt-3 rounded-xl bg-[#191F28] px-4 py-2 text-white">관리자 인증</button><p id="admin-auth-status" class="mt-2 text-[12px]" aria-live="polite"></p>';
        section.prepend(form);
        form.onsubmit=async event=>{
          event.preventDefault();token=$('admin-password').value;$('admin-password').value='';
          try{await request('/api/admin/validate');$('admin-auth-status').textContent='관리자 인증 완료';$('admin-sync-button').disabled=false;}
          catch(error){token=null;$('admin-sync-button').disabled=true;$('admin-auth-status').textContent=error.message;}
        };
      }
      $('admin-password').value='';$('admin-auth-status').textContent='Slack 연동 전에 관리자 인증을 완료하세요.';
      $('admin-sync-button').disabled=true;
    }
    if(manager){
      try{await loadDirectory();await loadAssignments();}
      catch(error){$('admin-assignment-list').textContent='업무 목록 조회 실패: '+error.message;}
    }
  };
  async function loadDirectory(){
    const data=await request('/api/demo/data');
    directory={persons:data.persons||[],tasks:data.tasks||[],works:data.works||[],edges:data.edges||[]};
    const personLabel=p=>`${p.team||p.team_name||p.department||p.department_name||'팀 미확인'} / ${p.employee_id||p.employee_no||p.staff_id||p.person_id} / ${p.name||'이름 미확인'}`;
    $('admin-person-options').innerHTML=directory.persons.map(p=>`<option value="${escapeHtml(personLabel(p))}"></option>`).join('');
    const resolvePerson=input=>{
      const value=String(input.value||'').trim();
      const person=directory.persons.find(p=>value===personLabel(p)||value===p.person_id||value===p.name);
      input.dataset.personId=person?.person_id||'';
      return person?.person_id||'';
    };
    const renderWorks=()=>{
      const sourceId=resolvePerson($('admin-source-person'));
      const owned=new Set(directory.edges.filter(e=>e.source_type==='Person'&&e.source_id===sourceId&&e.target_type==='Task'&&e.relation==='OWNER').map(e=>e.target_id));
      const open=new Set(directory.tasks.filter(t=>String(t.status||'').toLowerCase()!=='completed').map(t=>t.task_id));
      const workIds=new Set(directory.edges.filter(e=>e.source_type==='Work'&&e.target_type==='Task'&&e.relation==='HAS_TASK'&&owned.has(e.target_id)&&open.has(e.target_id)).map(e=>e.source_id));
      const works=directory.works.filter(w=>workIds.has(w.work_id));
      $('admin-work').innerHTML=sourceId
        ? '<option value="">배정할 Work를 선택하세요</option>'+works.map(w=>`<option value="${escapeHtml(w.work_id)}">${escapeHtml(w.title||w.work_id)}</option>`).join('')
        : '<option value="">인계자를 먼저 선택하세요</option>';
      if(sourceId&&!works.length)$('admin-work').innerHTML='<option value="">미완료 Work가 없습니다</option>';
    };
    for(const id of ['admin-source-person','admin-assignee']){
      const input=$(id);
      input.oninput=()=>{resolvePerson(input);if(id==='admin-source-person')renderWorks();};
      input.onchange=()=>{resolvePerson(input);if(id==='admin-source-person')renderWorks();};
    }
    renderWorks();
  }
  async function loadAssignments(){
    const rows=(await request('/api/manager/assignments')).assignments||[];
    const personId=id=>directory.persons.find(x=>x.person_id===id)?.name||id;
    const taskId=id=>directory.tasks.find(x=>x.task_id===id)?.title||id;
    const workForTask=id=>{const link=directory.edges.find(e=>e.source_type==='Work'&&e.target_type==='Task'&&e.relation==='HAS_TASK'&&e.target_id===id);return directory.works.find(w=>w.work_id===link?.source_id)?.title||'Work 미확인';};
    $('admin-assignment-list').innerHTML = rows.length ? rows.map(x=>`<div class="rounded-xl border border-[#EEF0F3] px-4 py-3 flex flex-wrap justify-between gap-3"><span><b>${escapeHtml(workForTask(x.task_id))}</b><span class="block mt-1 text-[11px] text-[#8B95A1]">${escapeHtml(taskId(x.task_id))}</span> → ${escapeHtml(personId(x.assignee_id))}</span><span class="text-[#8B95A1]">${escapeHtml(displayTime(x.assigned_at))} · ${escapeHtml(x.status)}</span></div>`).join('') : '<div class="text-[#8B95A1]">배정 내역이 없습니다.</div>';
  }
  window.runAdminSync = async () => {
    if(currentUserRole!=='admin'||!token)return;
    const button=$('admin-sync-button'),output=$('admin-sync-result');
    const days=Number($('admin-sync-days')?.value||14);
    button.disabled=true;output.textContent=`최근 ${days}일 기준 · Supabase 업무 데이터 확인 중…`;
    try {
      const db=await request('/api/demo/data');
      output.textContent=`최근 ${days}일 · Supabase 조회 완료 · Work ${db.works?.length||0}건 / Task ${db.tasks?.length||0}건 · ML 학습 시작…`;
      const response=await fetch('/api/demo/slack-link',{method:'POST',credentials:'same-origin',headers:{'X-Admin-Token':token}});
      if(!response.ok){
        let detail='';
        try{detail=(await response.json()).detail||'';}catch(_error){}
        throw new Error(detail||('학습 시작 실패 (HTTP '+response.status+')'));
      }
      if(!response.body)throw new Error('학습 진행 응답이 없습니다');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',completed=false;
      while(true){
        const next=await reader.read();if(next.done)break;
        buffer+=decoder.decode(next.value,{stream:true});
        const lines=buffer.split('\n');buffer=lines.pop()||'';
        for(const line of lines){
          if(!line.trim())continue;
          const event=JSON.parse(line);
          if(event.status==='failed')throw new Error(event.error||'ML 학습 실패');
          if(event.status==='completed')completed=true;
          if(event.status==='running')output.textContent=`ML 모델 학습 중 · ${event.progress_percent||0}%`;
        }
      }
      if(buffer.trim()){const last=JSON.parse(buffer);if(last.status==='completed')completed=true;if(last.status==='failed')throw Error(last.error||'학습 실패');}
      if(!completed)throw new Error('학습 완료 응답을 받지 못했습니다');
      output.textContent='Supabase 연동 및 ML 모델 학습 완료';
      if(window.refreshMlTrainingStatus)await window.refreshMlTrainingStatus();
    }catch(err){output.textContent='연동 실패 · '+err.message;}
    finally{button.disabled=false;}
  };
  window.createAdminAssignment = async () => {
    if(currentUserRole!=='manager')return;
    const button=$('admin-assign-button'); button.disabled=true; $('admin-assign-result').textContent='업무 배정 저장 중…';
    try {
      const sourcePersonId=$('admin-source-person').dataset.personId||'';
      const assigneeId=$('admin-assignee').dataset.personId||'';
      const workId=$('admin-work').value;
      if(!sourcePersonId)throw new Error('인계자를 검색 결과에서 선택하세요.');
      if(!assigneeId)throw new Error('인수자를 선택하세요.');
      if(sourcePersonId===assigneeId)throw new Error('인계자와 인수자는 달라야 합니다.');
      if(!workId)throw new Error('배정할 Work를 선택하세요.');
      const result=await request('/api/manager/assignments',{method:'POST',body:JSON.stringify({work_id:workId,source_person_id:sourcePersonId,assignee_id:assigneeId})});
      $('admin-assign-result').textContent=`배정 저장 완료 · 미완료 세부 업무 ${result.task_ids?.length||0}건을 인수자에게 배정했습니다.`;
      await loadAssignments();
      return result;
    } catch(err){$('admin-assign-result').textContent=err.message;}
    finally {button.disabled=false;}
  };
  loadMeta();
})();


/* Marketing handover database-backed UI demonstration; account switching is simulated, not authorization. */
(() => {
 'use strict';
 const TEAM=['김지수','박서연','최민준'], ACCOUNT=['원이정','김지수','박서연','최민준','팀장','관리자'];
 const PERSON_IDS={'원이정':'U0C20G9MRML','김지수':'U0C22C8M742','박서연':'U0C6WSR5275','최민준':'U0C38J2MUF4'};
 const API='/api/demo/handover-requests';
 const WORK_ID='WORK-00020', WORK_TITLE='신차 출시 캠페인 콘텐츠 현지화 및 배포 준비';
 const CASE_TASKS=[
  ['TASK-00077','본사 캠페인 패키지 v3 변경사항 확인'],
  ['TASK-00078','국내 사양·기술 표현 검증'],
  ['TASK-00079','국내용 원고 제목·CTA 확정'],
  ['TASK-00080','딜러 이미지·UTM·배포 대상 준비 및 포털 반영']
 ];
 let actor='원이정';
 // v2 resets UI-only approvals created before the priority POST/storage flow existed.
 const DEMO_MANAGER_KEY='linking_manager_ui_approvals_v2';
 function managerApprovals(){try{return JSON.parse(localStorage.getItem(DEMO_MANAGER_KEY)||'{}')}catch{return {}}}
 function saveManagerApproval(id,status){const rows=managerApprovals();rows[id]=status;localStorage.setItem(DEMO_MANAGER_KEY,JSON.stringify(rows));}
 let verifiedMode=false;
 let authToken=null;
 const el=id=>document.getElementById(id);
 const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 async function api(path='',method='GET',data=null){
  const res=await fetch(API+path,{method,credentials:'same-origin',cache:'no-store',headers:{...(data?{'Content-Type':'application/json'}:{}),...(authToken?{'X-Handover-Access-Token':authToken}:{})},body:data?JSON.stringify(data):undefined});
  if(!res.ok)throw new Error('인수인계 서버 요청 실패 (HTTP '+res.status+')');
  return res.json();
 }
 async function load(){return (await api()).requests.map(r=>({
  id:r.request_id,requester:'원이정',owner:'김지수',workId:r.work_id,
  title:WORK_TITLE,status:(!verifiedMode&&r.status==='pending'&&managerApprovals()[r.request_id])||r.status,approvedBy:(!verifiedMode&&r.status==='pending'&&managerApprovals()[r.request_id])?'팀장 (UI 시연)':Object.keys(PERSON_IDS).find(name=>PERSON_IDS[name]===r.approved_by)||r.approved_by||'-',
  requesterId:r.requester_id,sourceId:r.source_person_id
 }));}
 async function updateInboxBadge(){
  const badge=el('handover-inbox-count');if(!badge)return;
  try{
   const rows=await load();
   const personId=PERSON_IDS[actor];
   const count=rows.filter(r=>r.status==='pending'&&(
    actor==='팀장' ? !verifiedMode :
    actor==='김지수' ? r.sourceId===personId : r.requesterId===personId
   )).length;
   badge.textContent=count>9?'9+':String(count);
   badge.classList.toggle('hidden',!count);
   badge.classList.toggle('flex',!!count);
  }catch(_error){badge.classList.add('hidden');badge.classList.remove('flex');}
 }
  function panel(title,body){
  let node=el('handover-demo-panel');
  if(!node){node=document.createElement('div');node.id='handover-demo-panel';node.className='fixed inset-0 z-[110] hidden items-center justify-center bg-black/40 p-4';document.body.appendChild(node);}
  node.innerHTML='<section role="dialog" aria-modal="true" class="w-full max-w-[750px] max-h-[88vh] overflow-y-auto rounded-[24px] bg-white p-6 shadow-2xl"><header class="flex justify-between gap-3"><div><div class="text-[11px] text-[#3182F6] font-bold">시연 모드</div><h2 class="mt-2 text-[21px] font-bold">'+safe(title)+'</h2></div><button id="handover-demo-close" class="h-9 w-9 rounded-xl border" aria-label="닫기">×</button></header><div class="mt-5">'+body+'</div></section>';
  node.classList.remove('hidden');node.classList.add('flex');
  el('handover-demo-close').onclick=closePanel;
 }
 function approvalBadge(status){
  const labels={approved:'승인 완료',pending:'승인 대기',rejected:'반려'};
  const colors={approved:'bg-[#E8F8F0] text-[#008B5E] border-[#B9E9D1]',
                pending:'bg-[#FFF4DF] text-[#B76500] border-[#F6D9A5]',
                rejected:'bg-[#FFF0F0] text-[#D44949] border-[#F6C9C9]'};
  return '<span class="inline-flex shrink-0 items-center rounded-xl border px-3 py-1.5 text-[12px] font-bold '+(colors[status]||'bg-[#F2F4F6] text-[#6B7684] border-[#E5E8EB]')+'">'+safe(labels[status]||status||'상태 미확인')+'</span>';
 }
 function closePanel(){const n=el('handover-demo-panel');if(n){n.classList.add('hidden');n.classList.remove('flex');}}
 function message(s){if(typeof toast==='function')toast(s);else alert(s);}
 function selectedWork(){return (IMPORT_DATA[importState.person]||[]).some(g=>g.project===WORK_TITLE&&g.tasks.every(t=>importState.selected.has(g.project+'::'+t)));}
 // Work titles and tasks from provided BMW synthetic Slack dataset (demo-only).
 const RELATED_PERSON_WORKS={
  '박서연':[
   {project:'신차 출시 캠페인 콘텐츠 현지화 및 배포 준비',tasks:['본사 원본 최신본 확인','국내 사양 및 필수 표기 검증','원고 제목 및 CTA 표현 검토','딜러 배포 자료 준비']},
   {project:'전기차 배터리 보증 딜러 설명 자료',tasks:['경쟁사 비교·배터리 보증 초안 취합','보증 조건·기술 표현·딜러 FAQ 검토','보증·기술·딜러 검토 반영 및 설명 자료 확정','딜러 배포·질문 회수']}
  ],
  '최민준':[
   {project:'딜러 고객 초청 시승 행사 성과 분석 및 후속 캠페인 선정',tasks:['딜러별 참가자·상담 전환 데이터 취합','누락 딜러·이전 행사 성과 기준 확인','성과 우수 딜러·고객군 선정','후속 캠페인 대상 확정·공유']},
   {project:'월간 딜러 피드백 보고',tasks:['딜러 질문·불만·처리 상태 월간 취합','보증 확인 건·기술 검토 건 분류','지난 보고서 양식에 이번 달 결과 반영','월간 보고서 배포·미결 건 이월']}
  ]
 };
 function seed(){
  if(typeof IMPORT_DATA==='undefined')return;
  const groups=IMPORT_DATA['김지수']||(IMPORT_DATA['김지수']=[]);
  if(!groups.some(g=>g.project===WORK_TITLE))groups.unshift({project:WORK_TITLE,tasks:CASE_TASKS.map(x=>x[1])});
  for(const [name,works] of Object.entries(RELATED_PERSON_WORKS)){
   const existing=IMPORT_DATA[name]||(IMPORT_DATA[name]=[]);
   for(const w of works)if(!existing.some(x=>x.project===w.project))existing.push({project:w.project,tasks:[...w.tasks]});
  }
 }
 async function received(){
  if(actor==='팀장'){
   panel('인수받은 업무','<div class="rounded-xl bg-[#F8F9FA] p-5 text-[13px]">팀장 시연 계정에는 인수받은 업무가 없습니다.</div>');
   return;
  }
  const personId=PERSON_IDS[actor];
  if(!personId)return message('현재 사용자 정보를 확인할 수 없습니다.');
  try{
   // Only the recipient's own incoming handovers. Never show the owner's sent approvals.
   const rows=(await load()).filter(r=>r.requesterId===personId);
   panel('인수받은 업무',rows.length?rows.map(r=>'<div class="mb-3 rounded-2xl border border-[#E5E8EB] p-4"><div class="flex items-center justify-between gap-2"><b>'+safe(r.owner)+'님의 업무</b>'+approvalBadge(r.status)+'</div><div class="mt-2 text-[13px]">'+safe(r.title)+'</div>'+(r.status==='approved'?'<button data-open="'+safe(r.id)+'" class="mt-3 rounded-xl bg-[#3182F6] px-4 py-2 text-[12px] font-bold text-white">이어받은 업무 보기</button>':'')+'</div>').join(''):'<div class="rounded-xl bg-[#F8F9FA] p-5 text-[13px]">아직 인수받은 업무가 없습니다.</div>');
   el('handover-demo-panel').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>viewWork(b.dataset.open));
  }catch(e){message(e.message)}
 }
  async function viewWork(id){
  let r;try{r=(await load()).find(x=>x.id===id&&x.status==='approved'&&x.requesterId===PERSON_IDS[actor]);}
  catch(e){return message(e.message)}
  if(!r)return message('승인된 인수인계만 확인 가능합니다.');
  showGate('approved');
  closePanel();
  if(PROJECTS.some(p=>p.id===r.workId)){
   state.project=r.workId;state.task=PROJECTS.find(p=>p.id===r.workId).tasks.find(t=>TASKS[t]?.status!=='완료')||PROJECTS.find(p=>p.id===r.workId).tasks[0];state.filter=null;
   const select=el('project-select');if(select)select.value=r.workId;
   if(typeof setMainView==='function')setMainView('briefing');
   render();
   message('김지수에게 이어받은 WORK-00020을 표시했습니다.');
  }else{
   panel('이어받은 업무','<div class="rounded-xl bg-[#F2F7FF] p-4 font-bold">'+safe(r.title)+'</div><div class="mt-3 space-y-3">'+CASE_TASKS.map((t,i)=>'<div class="rounded-xl border p-3"><div class="text-[11px] text-[#8B95A1]">'+safe(t[0])+' · '+(i<2?'완료':i===2?'진행 중':'대기')+'</div><div class="font-bold">'+safe(t[1])+'</div></div>').join('')+'</div><div class="mt-3 text-[12px] text-[#8B95A1]">첨부 WORK-00020 시연 데이터입니다. 현재 DB Work에 이 항목이 없습니다.</div>');
  }
 }
  async function inbox(){
  if(actor==='원이정'||actor==='박서연'||actor==='최민준')return received();
  let all;try{all=(await load()).filter(r=>actor==='팀장'?!verifiedMode:r.sourceId===PERSON_IDS[actor]);}
  catch(e){return message(e.message)}
  const pending=all.filter(r=>r.status==='pending');
  updateInboxBadge();
  let body=pending.length?pending.map(r=>'<div class="mb-3 rounded-2xl border p-4"><div class="font-bold">'+safe(r.requester)+' → '+safe(r.owner)+'</div><div class="mt-2 text-[13px]">'+safe(r.title)+'</div><div class="mt-3 flex gap-2"><button data-verify="'+safe(r.id)+'" class="rounded-xl bg-[#3182F6] px-4 py-2 text-[12px] font-bold text-white">유비키 인증</button><button data-reject="'+safe(r.id)+'" class="rounded-xl border px-4 py-2 text-[12px]">반려</button></div></div>').join(''):'<div class="rounded-xl bg-[#F8F9FA] p-5 text-[13px]">대기 중인 인수인계 요청이 없습니다.</div>';
  const done=all.filter(r=>r.status!=='pending');
  if(done.length)body+='<h3 class="mt-5 mb-2 font-bold">처리 이력</h3>'+done.map(r=>'<div class="flex items-center justify-between gap-3 border-b py-3 text-[12px]"><span>'+safe(r.requester)+' → '+safe(r.owner)+' · '+safe(r.approvedBy)+'</span>'+approvalBadge(r.status)+'</div>').join('');
  panel(actor==='팀장'?'팀장 인수인계 승인함 (UI 시연 전용)':'김지수 인수인계 승인함',body);
  el('handover-demo-panel').querySelectorAll('[data-verify]').forEach(b=>b.onclick=()=>verify(b.dataset.verify));
  el('handover-demo-panel').querySelectorAll('[data-reject]').forEach(b=>b.onclick=()=>decide(b.dataset.reject,'rejected'));
 }
  async function verify(id){
  let r;try{r=(await load()).find(x=>x.id===id&&x.status==='pending');}
  catch(e){return message(e.message)}
  if(!r||(actor==='팀장'?verifiedMode:PERSON_IDS[actor]!==r.sourceId))return message('승인할 수 없는 요청입니다.');
  panel(actor==='팀장'?'팀장 승인 시연 (DB 미반영)':'유비키 인증','<div class="rounded-2xl bg-[#F2F7FF] p-6 text-center"><div class="text-[38px]">🔑</div><h3 class="mt-3 text-[17px] font-bold">보안키 터치 시연</h3><p class="mt-2 text-[12px] text-[#6B7684]">보안키 확인 절차를 시연하는 화면입니다.</p><button id="handover-confirm" class="mt-5 rounded-xl bg-[#3182F6] px-5 py-3 text-white font-bold">인증 확인 · 승인</button></div>');
  el('handover-confirm').onclick=()=>decide(id,'approved');
 }
  async function decide(id,status){
   if(actor==='팀장'&&!verifiedMode){
    let request;
    try{request=(await load()).find(r=>r.id===id&&r.status==='pending');}
    catch(e){return message(e.message)}
    if(!request)return message('처리할 인수인계 요청을 찾을 수 없습니다.');
    saveManagerApproval(id,status);
    updateInboxBadge();
    await inbox();
    if(status==='approved'){
     try{
      if(typeof window.refreshMlPriorities!=='function')throw new Error('우선순위 API 연결을 찾을 수 없습니다');
      const priority=await window.refreshMlPriorities(request.sourceId);
      if(!priority.matchedTaskIds.length)throw new Error('업무 원소유자의 ML 결과와 매핑된 Task가 없습니다');
      message('팀장 승인 완료 · 업무 원소유자의 ML 우선순위를 저장하고 Task에 반영했습니다.');
     }catch(priorityError){
      message('팀장 승인은 완료됐지만 우선순위 반영에 실패했습니다: '+priorityError.message);
     }
    }else message('팀장 반려 UI 시연이 완료됐습니다.');
    return;
   }
   const actorId=PERSON_IDS[actor];
   let request;
   try{request=(await load()).find(r=>r.id===id&&r.status==='pending');}
   catch(e){return message(e.message)}
   if(!actorId||!request||request.sourceId!==actorId)return message('처리 권한이 없습니다.');
   try{
    const decision=await api('/'+encodeURIComponent(id)+'/decision','POST',{actor_id:actorId,status});
    updateInboxBadge();
    await inbox();
    if(status==='approved'){
     try{
      if(decision.priority_error)throw new Error(decision.priority_error);
      const priority=decision.priorities
       ? window.applyMlPriorityResult(actorId,decision.priorities)
       : await window.refreshMlPriorities(actorId);
      if(!priority.matchedTaskIds.length)throw new Error('김지수의 ML 결과와 매핑된 프론트 Task가 없습니다');
      message('DB 승인 완료 · 김지수의 ML 우선순위를 저장하고 Task에 반영했습니다.');
     }catch(priorityError){
      message('DB 승인은 완료됐지만 우선순위 산출에 실패했습니다: '+priorityError.message);
     }
    }else message('DB에 반려 상태를 저장했습니다.');
   }
   catch(e){message(e.message)}
  }
  function switchActor(next){
  if(!ACCOUNT.includes(next))return;
  actor=next;closePanel();if(typeof closeImport==='function')closeImport();
  updateInboxBadge();
  const loginChoice=el('handover-login-account');if(loginChoice)loginChoice.value=actor;

  if(typeof setMainView==='function')setMainView('briefing');
  message(actor+' UI로 전환했습니다. 실제 로그인 변경은 아닙니다.');
 }
 const originalOpen=openImport;
 openImport=function(){
  if(actor==='김지수'||actor==='팀장')return inbox();
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
  if(importState.step===1){name.textContent='인수인계 승인 요청';const supported=importState.person==='김지수';btn.textContent=supported?'인수인계 요청 보내기':'관련 Work 확인 (시연)';btn.onclick=supported?requestImportApproval:()=>message('박서연·최민준은 현재 Work 목록 시연만 지원하며, 승인 요청은 김지수의 WORK-00020만 연결되어 있습니다.');}
  else {name.textContent='승인 대기';summary.textContent='김지수님이 승인해야 업무를 이어받을 수 있어요.';btn.textContent='요청 상태 확인';btn.onclick=()=>{closeImport();received()};}
 };
 requestImportApproval=async function(){
  if(actor!=='원이정'||importState.person!=='김지수')return message('이번 시연은 원이정 → 김지수 요청 기준입니다.');
  if(!selectedWork())return message('김지수의 WORK-00020을 선택해 주세요.');
  const btn=el('import-action-btn');if(btn)btn.disabled=true;
  try{
   await api('','POST',{requester_id:PERSON_IDS['원이정'],source_person_id:PERSON_IDS['김지수'],work_id:WORK_ID});
   updateInboxBadge();
   importState.step=2;importState.approved=false;renderImportFlow();
   showGate('pending');
   message('Supabase에 인수인계 요청을 저장했습니다. 김지수 UI에서 승인하세요.');
  }catch(e){message(e.message)}
  finally{if(btn)btn.disabled=false}
 };
 // Header actions are authored in index.html in a single four-button row.
 const existingInbox=el('handover-demo-inbox'),existingReceived=el('handover-demo-received');
 el('handover-demo-logout').onclick=()=>{authToken=null;window.activateManagerWorkspace('employee');if(verifiedMode){window.clearVerifiedDemoData?.();window.location.assign('/api/demo/auth/logout');return;}closePanel();if(typeof closeImport==='function')closeImport();el('login-screen').classList.remove('hidden');};
 if(existingInbox)existingInbox.onclick=inbox;
 if(existingReceived)existingReceived.onclick=received;
 const steps=document.querySelectorAll('#import-steps [data-step] div:last-child');
 ['업무 선택','승인 요청','승인 확인','업무 확인'].forEach((x,i)=>{if(steps[i])steps[i].textContent=x});
 const sub=document.querySelector('#import-modal p');
 if(sub)sub.textContent='같은 팀 구성원의 Work를 선택해 인수인계를 요청합니다. 승인 전에는 업무가 전달되지 않습니다.';
 seed();
 updateInboxBadge();
 window.setInterval(updateInboxBadge,15000);
 // Completed Tasks are intentionally excluded from the operational detail list.
 const loginSelect=el('handover-login-account');
 if(loginSelect){
  loginSelect.addEventListener('change',()=>{
   const label=el('handover-login-role');
   if(label)label.textContent=loginSelect.value==='팀장'?'팀장':loginSelect.value==='관리자'?'관리자':'일반사원';
  });
 }

 // Fail closed: an unapproved recipient must not see imported Work on the dashboard.
 // This is presentation gating only; server-side per-user authentication remains TODO.
 const gateStyle=document.createElement('style');
 gateStyle.textContent='#briefing-view.handover-locked > :not(#handover-approval-gate){display:none!important}';
 document.head.appendChild(gateStyle);
 function showGate(mode){
  const briefing=el('briefing-view');
  if(!briefing)return;
  const management=actor==='팀장'||actor==='관리자';
  const locked=management||mode!=='approved';
  briefing.classList.toggle('handover-locked',locked);
  let gate=el('handover-approval-gate');
  if(!gate){
   gate=document.createElement('section');
   gate.id='handover-approval-gate';
   gate.className='rounded-[24px] border border-[#E5E8EB] bg-white px-6 py-12 text-center shadow-sm';
   briefing.prepend(gate);
  }
  gate.classList.toggle('hidden',!locked);
  if(locked){
   const configs={
    checking:{icon:'sync',tag:'상태 확인 중',title:'인수인계 상태 확인 중',description:'김지수님의 업무 승인 기록을 확인하고 있습니다.',action:'요청 내역 확인'},
    empty:{icon:'inventory_2',tag:'요청 전',title:'아직 이어받은 업무가 없어요',description:'상단 돋보기에서 같은 팀 담당자를 검색해 인수인계를 요청할 수 있어요.',action:'김지수 업무 요청하기'},
    pending:{icon:'hourglass_top',tag:'승인 대기',title:'김지수님의 승인을 기다리고 있어요',description:'김지수님이 승인하면 업무 흐름이 나타납니다. 팀장 승인은 UI 시연으로만 표시됩니다.',action:'요청 상태 확인'},
    rejected:{icon:'block',tag:'요청 반려',title:'인수인계 요청이 반려됐어요',description:'업무는 표시되지 않습니다. 필요한 경우 김지수님에게 다시 요청해 주세요.',action:'다시 요청하기'},
    error:{icon:'wifi_off',tag:'확인 실패',title:'승인 상태를 불러오지 못했어요',description:'승인 여부를 확인할 수 없어 업무를 숨겼습니다. 다시 조회해 주세요.',action:'요청 내역 확인'}
   };
   const config=management
    ?{icon:'assignment_ind',tag:'인수 내역 없음',title:'자동으로 표시되는 인수인계 업무가 없습니다',description:'관리 메뉴에서 담당 역할의 기능을 이용하세요.'}
    :actor==='김지수'&&mode!=='approved'&&mode!=='error'&&mode!=='checking'
    ?{icon:'inventory_2',tag:'인수 내역 없음',title:'아직 인수받은 업무가 없어요',description:'김지수님이 다른 구성원에게서 승인받아 인수한 업무가 없습니다.'}
    :configs[mode]||configs.empty;
   gate.innerHTML='<div class="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#F2F7FF] text-[#3182F6]"><span class="material-symbols-outlined text-[30px]">'+config.icon+'</span></div>'+
   '<div class="mt-5"><span class="inline-flex rounded-full bg-[#F2F7FF] px-3 py-1.5 text-[11px] font-bold text-[#1B64DA]">'+config.tag+'</span></div>'+
   '<h2 class="mt-4 text-[22px] font-bold text-[#191F28]">'+config.title+'</h2>'+
   '<p class="mx-auto mt-3 max-w-[470px] text-[13px] leading-6 text-[#6B7684]">'+config.description+'</p>'+
   '<div class="mt-7"><button id="handover-gate-refresh" class="rounded-xl border border-[#DDE3EA] bg-white px-5 py-3 text-[13px] font-bold text-[#4E5968]">승인 상태 새로고침</button></div>';
   el('handover-gate-refresh').onclick=()=>refreshGate();
  }
  const header=el('header-kicker');
  if(header&&actor!=='팀장')header.textContent='인수받은 업무';
  const heading=el('header-title');
  if(heading&&actor!=='팀장')heading.textContent=locked?'인수받은 업무 없음':'인수받은 업무';
 }
 async function refreshGate(){
  if(actor==='팀장'||actor==='관리자'){showGate('empty');return;}
  const requesterId=PERSON_IDS[actor];
  if(!requesterId){showGate('empty');return;}
  showGate('checking');
  try{
   const records=(await load()).filter(r=>r.requesterId===requesterId);
   const approved=records.some(r=>r.status==='approved');
   const pending=records.some(r=>r.status==='pending');
   const rejected=records.some(r=>r.status==='rejected');
   if(approved&&verifiedMode&&authToken&&typeof window.loadVerifiedDemoData==='function')await window.loadVerifiedDemoData(authToken);
   showGate(approved?'approved':pending?'pending':rejected?'rejected':'empty');
   if(approved&&typeof render==='function')render();
  }catch(e){showGate('error');message('승인 상태를 확인하지 못했습니다. '+e.message);}
 }
 function updateSidebarIdentity(){
  const label=el('sidebar-user-name'),idLabel=el('sidebar-user-id'),avatar=el('sidebar-user-avatar');
  if(label)label.textContent=actor;
  if(idLabel)idLabel.textContent=PERSON_IDS[actor]||'시연용 계정 · Slack ID 없음';
  if(avatar)avatar.textContent=actor.slice(0,1);
 }
 const previousEnterApp=enterApp;
 let authConfigPromise;
 function showLoginError(detail){
  const notice=el('login-error');
  if(notice){notice.textContent=detail;notice.classList.remove('hidden');}
  else alert(detail);
 }
 async function checkLoginConfig(){
  const res=await fetch('/api/demo/auth/config',{credentials:'same-origin',cache:'no-store'});
  if(!res.ok)throw new Error('로그인 설정 조회 실패 (HTTP '+res.status+')');
  const config=await res.json();
  verifiedMode=!!config.verified_mode;
  const fields=el('verified-login-fields');
  if(fields)fields.classList.add('hidden');
  const selector=el('handover-login-account');
  if(selector)selector.parentElement?.classList.toggle('hidden',verifiedMode);
  const btn=el('login-submit');
  if(btn)btn.textContent=verifiedMode?'Slack으로 로그인':'로그인하기';
  return config;
 }
 authConfigPromise=checkLoginConfig().catch(error=>{
   // The next click retries. Do not silently swallow a failed config lookup.
   showLoginError('로그인 설정 확인 실패: '+error.message);
   throw error;
 });
 // Consume startup failure; actual click retries independently.
 authConfigPromise.catch(()=>{});
 enterApp=async function(){
  const loginBtn=el('login-submit'),error=el('login-error');
  if(loginBtn)loginBtn.disabled=true;
  if(error)error.classList.add('hidden');
  try{
    await checkLoginConfig();
    if(verifiedMode){
      const res=await fetch('/api/demo/auth/me',{credentials:'same-origin',cache:'no-store'});
      if(!res.ok)throw new Error('Slack 로그인 확인 실패 (HTTP '+res.status+')');
      const identity=await res.json();
      if(!identity.authenticated){
        window.location.assign('/api/demo/auth/slack/start');
        return;
      }
      actor=Object.keys(PERSON_IDS).find(name=>PERSON_IDS[name]===identity.person_id);
      if(!actor)throw new Error('등록되지 않은 Slack 사용자입니다.');
      if(typeof window.loadVerifiedDemoData!=='function')throw new Error('업무 데이터 모듈이 로드되지 않았습니다.');
      await window.loadVerifiedDemoData('');
    }else{
      const selection=el('handover-login-account')?.value||'원이정';
      actor=ACCOUNT.includes(selection)?selection:'원이정';
    }
    updateSidebarIdentity();
    if(typeof window.setPersonalWorkActor==='function')window.setPersonalWorkActor(actor);
    currentUserRole=!verifiedMode&&actor==='팀장'?'manager':!verifiedMode&&actor==='관리자'?'admin':'employee';
    closePanel();
    showGate('checking');
    previousEnterApp();
    if(typeof window.activateManagerWorkspace==='function')
      await window.activateManagerWorkspace(currentUserRole);
    if(isManagementRole()){
      setMainView('manage');
    }else if(actor==='김지수'){
      setMainView('briefing');
      await refreshGate();
    }else if(actor==='원이정'||actor==='박서연'||actor==='최민준'){
      await refreshGate();
    }
    const role=el('handover-login-role');
    if(role)role.textContent=actor==='팀장'?'팀장':actor==='관리자'?'관리자':'일반사원';
  }catch(err){
    console.error('Login error',err);
    showLoginError('로그인 실패: '+(err?.message||'알 수 없는 오류'));
  }finally{
    if(loginBtn)loginBtn.disabled=false;
  }
 };
 const firstOpenTask=Object.keys(TASKS).find(id=>TASKS[id]?.status!=='완료');
 if(firstOpenTask&&TASKS[state.task]?.status==='완료')state.task=firstOpenTask;
 if(typeof renderTaskList==='function'&&Object.keys(TASKS).length)renderTaskList();
})();

/* ML bridge: calls LINK-ing same-origin server, never sends the ML API key to browsers. */
(() => {
  'use strict';
  const personId = name => ({'원이정':'U0C20G9MRML','김지수':'U0C22C8M742','박서연':'U0C6WSR5275','최민준':'U0C38J2MUF4'})[name] || null;
  const PRIORITY_STORAGE_KEY='linking_ml_priorities_v2';
  const normalizeTaskName=value=>String(value??'').normalize('NFKC').toLocaleLowerCase('ko-KR').replace(/[^0-9a-z가-힣]/g,'');
  const readPriorityStore=()=>{
    try{return JSON.parse(localStorage.getItem(PRIORITY_STORAGE_KEY)||'{"byTaskId":{},"byTaskName":{}}')}
    catch{return {byTaskId:{},byTaskName:{}}}
  };
  const writePriorityStore=store=>localStorage.setItem(PRIORITY_STORAGE_KEY,JSON.stringify(store));
  const priorityRows=result=>{
    const rows=[];
    const visit=(value,key='',depth=0)=>{
      if(value==null||depth>6)return;
      if(Array.isArray(value)){value.forEach((item,index)=>visit(item,item?.task_id||item?.id||String(index),depth+1));return;}
      if(typeof value==='number'&&key){rows.push([key,{score:value}]);return;}
      if(typeof value!=='object')return;
      const hasTask=value.task_id||value.taskId||value.id||value.task_name||value.task?.task_id||value.task?.title;
      const hasPriority=['final_priority_score','priority_score','score','priority','final_priority_rank','priority_rank','rank','ranking'].some(field=>value[field]!=null);
      if(hasPriority&&(hasTask||key)){rows.push([value.task_id||value.taskId||value.id||value.task?.task_id||key,value]);return;}
      Object.entries(value).forEach(([childKey,child])=>visit(child,childKey,depth+1));
    };
    visit(result);
    return rows;
  };
  window.restoreMlPriorities=()=>{
    const store=readPriorityStore();
    for(const [taskId,task] of Object.entries(TASKS||{})){
      const value=store.byTaskId?.[taskId]||store.byTaskName?.[normalizeTaskName(task.sourceName||task.name)];
      if(!value)continue;
      TASKS[taskId].risk=value.score;
      TASKS[taskId].priorityScore=value.score;
      TASKS[taskId].priorityRank=value.rank;
    }
  };
  const getStatus = async () => {
    const r=await fetch('/api/ml/training',{credentials:'same-origin',cache:'no-store'});
    if(!r.ok)throw Error('학습 상태 조회 실패 (HTTP '+r.status+')');
    return r.json();
  };
  const renderStatus = status => {
    const el=document.getElementById('model-meta');if(!el)return;
    const date=status.model_trained_at || status.last_result?.model_trained_at || status.last_result?.trained_at || status.latest_model?.trained_at;
    if(status.status==='running'||status.status==='queued'){
      el.textContent='모델 학습 중 · '+Number(status.progress_percent||0).toFixed(1)+'%';
    } else if(date){
      el.textContent='최신 모델 학습 · '+new Date(date).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'});
    } else el.textContent=status.status==='failed'?'모델 학습 실패':'모델 학습 이력 없음';
  };
  window.refreshMlTrainingStatus=async()=>{const status=await getStatus();renderStatus(status);return status;};
  let trainingPromise=null;
  window.startMlTraining=()=>{
    if(trainingPromise)return trainingPromise;
    trainingPromise=(async()=>{
      const r=await fetch('/api/admin/ml/training',{method:'POST',credentials:'same-origin'});
      if(!r.ok)throw Error('모델 학습 요청 실패 (HTTP '+r.status+')');
      if(!r.body)throw Error('학습 진행 스트림을 읽을 수 없습니다');
      const reader=r.body.getReader(),decoder=new TextDecoder();let buffer='',final=null;
      while(true){
        const {done,value}=await reader.read();if(done)break;
        buffer+=decoder.decode(value,{stream:true});
        const lines=buffer.split('\n');buffer=lines.pop()||'';
        for(const line of lines){
          if(!line.trim())continue;
          const info=JSON.parse(line);final=info;renderStatus(info);
          if(info.status==='failed')throw Error(info.error||'모델 학습 실패');
        }
      }
      if(buffer.trim()){final=JSON.parse(buffer);renderStatus(final);}
      const status=await window.refreshMlTrainingStatus();
      if(status.status!=='completed' && final?.status!=='completed')throw Error('학습 완료 상태를 확인하지 못했습니다');
      return status;
    })().finally(()=>{trainingPromise=null;});
    return trainingPromise;
  };
  window.applyMlPriorityResult=(target,result)=>{
    const id=personId(target)||target;
    if(!id)throw Error('우선순위 대상의 Slack person_id가 필요합니다');
    window.mlPriorityResult=result;
    document.getElementById('ml-priority-results')?.remove();
    const taskEntries=Object.entries(TASKS||{});
    const taskIdByName=new Map(taskEntries.map(([taskId,task])=>[normalizeTaskName(task.sourceName||task.name),taskId]));
    const numberOrNull=value=>value==null||value===''?null:(Number.isFinite(Number(value))?Number(value):null);
    const normalized=priorityRows(result).map(([sourceTaskId,value])=>({
      sourceTaskId:String(value?.task_id??value?.taskId??value?.id??value?.task?.task_id??sourceTaskId),
      taskName:value?.task_name??value?.taskName??value?.title??value?.name??value?.task?.title??value?.task?.name??(/^TASK[-_]/i.test(String(sourceTaskId))?'':String(sourceTaskId)),
      score:numberOrNull(value?.final_priority_score??value?.priority_score??value?.score??value?.priority??value?.value),
      rank:numberOrNull(value?.final_priority_rank??value?.priority_rank??value?.rank??value?.ranking??value?.order),
    })).filter(value=>value.score!=null||value.rank!=null);
    const byScore=normalized.filter(value=>value.score!=null).sort((a,b)=>b.score-a.score);
    byScore.forEach((value,index)=>{if(value.rank==null)value.rank=index+1;});
    const fuzzyTaskId=name=>{
      const wanted=normalizeTaskName(name);if(!wanted)return null;
      const exact=taskIdByName.get(wanted);if(exact)return exact;
      const candidates=taskEntries.map(([taskId,task])=>[taskId,normalizeTaskName(task.sourceName||task.name)])
        .filter(([,candidate])=>candidate.length>=5&&(candidate.includes(wanted)||wanted.includes(candidate)))
        .sort((a,b)=>Math.abs(a[1].length-wanted.length)-Math.abs(b[1].length-wanted.length));
      return candidates[0]?.[0]||null;
    };
    const matched=normalized.map(value=>[
      TASKS?.[value.sourceTaskId] ? value.sourceTaskId : fuzzyTaskId(value.taskName), value,
    ]).filter(([taskId,value])=>taskId&&TASKS?.[taskId]&&value.rank!=null);
    window.mlPriorityTaskIdsByPerson=window.mlPriorityTaskIdsByPerson||{};
    for(const taskId of window.mlPriorityTaskIdsByPerson[id]||[]){
      if(TASKS?.[taskId]){
        TASKS[taskId].risk=null;
        TASKS[taskId].priorityRank=null;
        TASKS[taskId].priorityScore=null;
      }
    }
    const store=readPriorityStore();store.byTaskId=store.byTaskId||{};store.byTaskName=store.byTaskName||{};
    for(const value of normalized){
      const saved={personId:id,sourceTaskId:value.sourceTaskId,taskName:value.taskName,score:value.score,rank:value.rank,savedAt:new Date().toISOString()};
      if(value.sourceTaskId)store.byTaskId[value.sourceTaskId]=saved;
      if(value.taskName)store.byTaskName[normalizeTaskName(saved.taskName)]=saved;
    }
    for(const [taskId,value] of matched){
      const saved={personId:id,sourceTaskId:value.sourceTaskId,taskName:value.taskName,score:value.score,rank:value.rank,savedAt:new Date().toISOString()};
      store.byTaskId[taskId]=saved;
      store.byTaskName[normalizeTaskName(TASKS[taskId].sourceName||TASKS[taskId].name)]=saved;
    }
    writePriorityStore(store);window.mlPriorityByTask=store.byTaskId;
    window.restoreMlPriorities();
    window.mlPriorityTaskIdsByPerson[id]=matched.map(([taskId])=>taskId);
    if(typeof window.updateBriefingSummary==='function')window.updateBriefingSummary();
    if(typeof window.render==='function')window.render();
    return {result,matchedTaskIds:matched.map(([taskId])=>taskId)};
  };
  window.refreshMlPriorities=async(target)=>{
    const id=personId(target)||target;
    if(!id)throw Error('우선순위 대상의 Slack person_id가 필요합니다');
    const r=await fetch('/api/ml/priorities',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({person_id:id})});
    if(!r.ok)throw Error('우선순위 산출 실패 (HTTP '+r.status+')');
    return window.applyMlPriorityResult(id,await r.json());
  };
  const originalSync=window.runAdminSync;
  if(typeof originalSync==='function')window.runAdminSync=async(...args)=>{
    await originalSync(...args);
    const result=document.getElementById('admin-sync-result');
    if(false && result?.textContent?.startsWith('수집 성공')){
      try{await window.startMlTraining();result.textContent+=' · ML 학습 완료 (DB의 최신 그래프 기준)';}
      catch(e){result.textContent+=' · ML 학습 요청 실패: '+e.message;}
    }
  };
  const originalAssignment=window.createAdminAssignment;
  if(typeof originalAssignment==='function')window.createAdminAssignment=async(...args)=>{
    const assigneeId=document.getElementById('admin-assignee')?.dataset.personId;
    const assignment=await originalAssignment(...args);
    if(document.getElementById('admin-assign-result')?.textContent?.startsWith('배정 저장 완료')){
      try{
        if(assignment?.priority_error)throw new Error(assignment.priority_error);
        const priority=assignment?.priorities
          ? window.applyMlPriorityResult(assigneeId,assignment.priorities)
          : await window.refreshMlPriorities(assigneeId);
        if(!priority.matchedTaskIds.length)throw new Error('ML 결과와 일치하는 Task를 찾지 못했습니다');
        document.getElementById('admin-assign-result').textContent+=` · 선택 인수자 ML 우선순위 ${priority.matchedTaskIds.length}건 반영`;
      }
      catch(e){document.getElementById('admin-assign-result').textContent+=' · 우선순위 산출 실패: '+e.message;}
    }
  };
  const originalPrepare=window.confirmSenderExport;
  if(typeof originalPrepare==='function')window.confirmSenderExport=function(...args){
    const ret=originalPrepare.apply(this,args);
    if(typeof senderDraft!=='undefined' && senderDraft?.confirmedAt){
      window.refreshMlPriorities(senderDraft.owner).catch(e=>{
        if(typeof window.toast==='function')window.toast('인수인계 준비 후 우선순위 산출 실패: '+e.message);
      });
    }
    return ret;
  };
  window.refreshMlTrainingStatus().catch(()=>{
    const el=document.getElementById('model-meta');if(el)el.textContent='모델 학습 상태 조회 불가';
  });
  // Recover older approvals whose ML response arrived before the browser-side
  // mapper supported the deployed response shape.
  window.setTimeout(async()=>{
    if(Object.values(TASKS||{}).some(task=>Number(task.priorityRank)>0))return;
    try{
      const response=await fetch('/api/demo/handover-requests',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)return;
      const rows=(await response.json()).requests||[];
      const people=[...new Set(rows.filter(row=>row.status==='approved').map(row=>row.approved_by||row.source_person_id).filter(Boolean))];
      for(const id of people)await window.refreshMlPriorities(id);
    }catch(_error){}
  },1200);
})();
