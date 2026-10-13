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
