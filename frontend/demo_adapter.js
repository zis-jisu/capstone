/* LINK-ing actual Supabase demo adapter. Keeps original HTML/layout unchanged. */
(() => {
  'use strict';
  let loaded = false;
  const root = document;
  const html = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const statuses = { completed:'완료', in_progress:'진행 중', waiting:'대기', planned:'대기', delayed:'지연', blocked:'차단', pending:'대기' };
  const statusText = s => statuses[String(s || '').trim().toLowerCase()] || s || '미확인';
  const byId = (arr, key) => new Map(arr.map(x => [x[key], x]));

  function attach(data) {
    const works = data.works || [], tasks = data.tasks || [], events = data.events || [];
    const edges = data.edges || [], persons = data.persons || [], messages = data.slack_messages || [];
    if (!works.length || !tasks.length) {
      PROJECTS.splice(0, PROJECTS.length);
      Object.keys(TASKS).forEach(k => delete TASKS[k]);
      Object.keys(SLACK_EVIDENCE).forEach(k => delete SLACK_EVIDENCE[k]);
      Object.keys(FILES).forEach(k => delete FILES[k]);
      PEOPLE.splice(0, PEOPLE.length);
      Object.keys(IMPORT_DATA).forEach(k => delete IMPORT_DATA[k]);
      const selector=root.getElementById('project-select');
      if(selector)selector.innerHTML='<option value="all">승인된 업무 없음</option>';
      state.project='all';state.task=null;loaded=true;
      render();
      return;
    }
    const workMap = byId(works, 'work_id'), taskMap = byId(tasks, 'task_id');
    const eventMap = byId(events, 'event_id'), msgMap = byId(messages, 'message_id');
    const msgBySlackTs = new Map(messages.filter(m => m.slack_ts).map(m => [String(m.slack_ts), m]));
    const peopleMap = byId(persons, 'person_id');
    const workLinks = edges.filter(e => e.relation === 'HAS_TASK');
    const eventLinks = edges.filter(e => e.relation === 'HAS_EVENT');
    const actorByEvent = new Map(edges
      .filter(e => e.relation === 'ACTOR' && e.source_type === 'Person' && e.target_type === 'Event')
      .map(e => [e.target_id, e.source_id]));
    const participantLinks = edges.filter(e => ['OWNER','COLLABORATOR','REVIEWER','APPROVER','RELATED'].includes(e.relation) && e.target_type === 'Task');
    const deps = edges.filter(e => e.relation === 'DEPENDS_ON' && e.source_type === 'Task' && e.target_type === 'Task');
    const workTasks = new Map(works.map(w => [w.work_id, workLinks.filter(e => e.source_id === w.work_id).map(e => e.target_id).filter(id => taskMap.has(id))]));
    const taskToWork = new Map(workLinks.map(e => [e.target_id, e.source_id]));
    const rowsByTask = new Map(tasks.map(t => [t.task_id, eventLinks.filter(e => e.source_id === t.task_id).map(e => eventMap.get(e.target_id)).filter(Boolean).sort((a,b) => Number(a.slack_ts || 0) - Number(b.slack_ts || 0))]));
    const names = ids => [...new Set(ids.map(id => peopleMap.get(id)?.name).filter(Boolean))];
    const messageForEvent = e => msgMap.get(e.source_id) || msgBySlackTs.get(String(e.slack_ts || ''));
    const authorForEvent = e => {
      const message = messageForEvent(e);
      const raw=message?.raw_json&&typeof message.raw_json==='object'?message.raw_json:{};
      const personId = e.speaker_id || e.slack_user_id || e.actor_id || message?.author_id || actorByEvent.get(e.event_id);
      const speaker = String(e.speaker || '').trim();
      const knownSpeaker = speaker && !/^(작성자\s*)?미확인$/.test(speaker);
      const messageAuthor=String(message?.author_name||raw.author_name||raw.user_name||raw.user?.real_name||'').trim();
      const knownMessageAuthor=messageAuthor&&!/^(작성자\s*)?미확인$/.test(messageAuthor);
      const actor=String(e.actor||'').trim();
      const knownActor=actor&&!/^(작성자\s*)?미확인$/.test(actor);
      return (knownSpeaker?speaker:'')||(knownMessageAuthor?messageAuthor:'')||peopleMap.get(personId)?.name||(knownActor?actor:'')||'작성자 미확인';
    };

    PROJECTS.splice(0, PROJECTS.length, ...works.map(w => ({ id: w.work_id, name: html(w.title), risk:null, tasks: workTasks.get(w.work_id) || [] })));
    Object.keys(TASKS).forEach(key => delete TASKS[key]);
    Object.keys(SLACK_EVIDENCE).forEach(key => delete SLACK_EVIDENCE[key]);
    Object.keys(FILES).forEach(key => delete FILES[key]);

    for (const t of tasks) {
      const id = t.task_id, evs = rowsByTask.get(id) || [];
      const ownerIds = participantLinks.filter(e => e.target_id === id && e.relation === 'OWNER').map(e => e.source_id);
      const collaboratorIds = participantLinks.filter(e => e.target_id === id && e.relation === 'COLLABORATOR').map(e => e.source_id);
      const otherIds = participantLinks.filter(e => e.target_id === id && e.relation !== 'OWNER').map(e => e.source_id);
      const owners = names(ownerIds), collaborators = names(otherIds);
      const next = t.next_action || (t.status === 'completed' ? '완료된 업무입니다.' : '다음 할 일 확인 필요');
      const prereqs = [...new Set(evs.map(e => e.prerequisite).filter(Boolean))];
      const depTitles = deps.filter(e => e.source_id === id).map(e => taskMap.get(e.target_id)?.title).filter(Boolean);
      const caution = prereqs.length ? prereqs.join(' · ') : 'Slack 근거에서 별도 선행조건이 확인되지 않았습니다.';
      const deadline = t.deadline_text || (t.deadline_at ? String(t.deadline_at).slice(0,16).replace('T',' ') : '미정');
      const recent = evs.length ? evs[evs.length - 1].slack_ts : '0';
      TASKS[id] = {
        name: html(t.title), sourceName:String(t.title || ''), status: html(statusText(t.status)), risk:null, deadline:html(deadline), updated:Number(recent),
        type: ownerIds.length > 1 || collaboratorIds.length > 0 ? 'collab':'solo', owner:html(owners[0] || '담당자 미확인'),
        people: collaborators.map(html), next:html(next), after:[], blocker:html(prereqs[0] || '명시된 차단 사유 없음'),
        caution:html(caution), history:evs.map(e => html(`${authorForEvent(e)} · ${e.action || e.subject || e.evidence}`)),
        flow:[html(statusText(t.status)), html(next), '완료 확인'], depends:depTitles.map(html), approval:'원문 근거 참조',
      };
      SLACK_EVIDENCE[id] = evs.map(e => {
        const message = messageForEvent(e);
        const raw = message?.text || e.evidence || '';
        const [channel, timestamp] = String(e.source_id).split(':');
        return {
          type:e.conversation_type === 'dm' ? 'dm':'channel', source:html(e.conversation_id || channel),
          time:html(e.slack_ts ? new Date(Number(e.slack_ts)*1000).toLocaleString('ko-KR') : ''), author:html(authorForEvent(e)), summary:html(e.action || e.subject || ''),
          original:html(raw), channel, timestamp, allowed:!!message && e.conversation_type !== 'dm',
        };
      });
      FILES[id] = [...new Map(evs.flatMap(e => (e.reference || '').split('\n').filter(v => /^https:\/\//.test(v)).map(url => [url,{name:'Slack 원문에 공유된 자료',location:url,icon:'link'}]))).values()];
    }

    PEOPLE.splice(0, PEOPLE.length, ...persons.map(p => p.name));
    Object.keys(IMPORT_DATA).forEach(key => delete IMPORT_DATA[key]);
    for (const p of persons) {
      const owned = participantLinks.filter(e => e.source_id === p.person_id && e.relation === 'OWNER').map(e => e.target_id);
      const wids = [...new Set(owned.map(tid => taskToWork.get(tid)).filter(Boolean))];
      IMPORT_DATA[p.name] = wids.map(wid => ({project:workMap.get(wid)?.title || wid, tasks:owned.filter(tid => taskToWork.get(tid) === wid).map(tid => taskMap.get(tid)?.title).filter(Boolean)}));
    }

    // '나의 업무' uses the two separately sourced BMW spreadsheet fixtures.
    // Keep them isolated from granted/imported Supabase handovers.
    // Actual transferred Works remain in PROJECTS and require approval.
    // Draw only grounded Supabase edges; do not fabricate an owner -> receiver handover link.
    renderPeopleGraph = function(t) {
      const taskId = Object.keys(TASKS).find(id => TASKS[id] === t);
      const rels = participantLinks.filter(e => e.target_id === taskId).slice(0,5);
      const dependencies = deps.filter(e => e.source_id === taskId);
      const line = (x1,y1,x2,y2,label) => `<g><path class="graph-edge primary" marker-end="url(#demo-arrow)" d="M ${x1} ${y1} L ${x2} ${y2}"></path><text class="graph-edge-label" x="${(x1+x2)/2}" y="${(y1+y2)/2-8}" text-anchor="middle">${html(label)}</text></g>`;
      const node = (x,y,name,meta,cls='') => `<g class="graph-node ${cls}"><rect x="${x-90}" y="${y-27}" width="180" height="54" rx="14"></rect><text class="title" x="${x}" y="${y-2}" text-anchor="middle">${html(shortText(name,18))}</text><text class="meta" x="${x}" y="${y+14}" text-anchor="middle">${html(meta)}</text></g>`;
      let svg = `<svg viewBox="0 0 760 360" role="img" aria-label="${html(t.name)} 실제 업무 관계"><defs><marker id="demo-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto"><polygon points="0 0,8 3.5,0 7" fill="#9AA5B1"></polygon></marker></defs>`;
      const places = [[110,100],[650,100],[110,260],[650,260],[375,45]];
      for (const [i,e] of rels.entries()) {
        const p=peopleMap.get(e.source_id), xy=places[i];
        if(!p) continue;
        svg += line(xy[0],xy[1],375,178,e.relation);
        svg += node(xy[0],xy[1],p.name,e.relation,'person');
      }
      if(dependencies.length){
        const dep = taskMap.get(dependencies[0].target_id);
        if(dep){svg += line(375,207,375,305,'DEPENDS_ON');svg += node(375,325,dep.title,'선행 Task','task');}
      }
      svg += node(375,178,t.name,'선택한 Task','task');
      svg += '</svg>';
      return `<div class="relationship-graph-wrap overflow-x-auto">${svg}</div><div class="mt-2 text-[10px] text-[#8B95A1]">Supabase edges의 담당자·검수자·협업자·선행 Task 관계만 표시합니다.</div>`;
    };
    const openTaskIds=new Set(tasks.filter(t=>String(t.status||'').toLowerCase()!=='completed').map(t=>t.task_id));
    const selector = root.getElementById('project-select');
    selector.innerHTML = `<option value="all">전체 업무 · 미완료 세부 업무 ${openTaskIds.size}건</option>` + works.map(w => `<option value="${html(w.work_id)}">${html(w.title)} · ${workTasks.get(w.work_id).filter(id=>openTaskIds.has(id)).length}건</option>`).join('');
    const selfSelector = root.getElementById('handover-project-select');
    selfSelector.innerHTML = HANDOVER_WORKS.map(w => `<option value="${html(w.id)}">${html(w.name)}</option>`).join('');
    window.updateBriefingSummary = function(){
      const values=Object.values(TASKS).filter(task=>task.status!=='완료');
      const collab=values.filter(task=>task.type==='collab').length;
      const ranked=values.filter(task=>task.priorityRank!=null&&Number(task.priorityRank)>0).length;
      const heading=root.getElementById('briefing-task-summary');
      const summary=root.getElementById('briefing-project-summary');
      const collabCount=root.getElementById('briefing-collab-count');
      const soloCount=root.getElementById('briefing-solo-count');
      if(heading)heading.textContent=`김지수님에게서 세부 업무 ${values.length}건을 인수받았어요`;
      if(summary)summary.textContent=`${PROJECTS.length}개 프로젝트 · ML 우선순위 연동 ${ranked}건`;
      if(collabCount)collabCount.textContent=`협업 업무 ${collab}`;
      if(soloCount)soloCount.textContent=`개인 업무 ${values.length-collab}`;
    };
    const kicker = root.getElementById('header-kicker');
    if (kicker) kicker.textContent = 'Slack MCP · LLM · Supabase 연동 시연';
    graphStorageMessage = `Supabase 그래프 · ${data.graph?.metadata?.num_nodes ?? '?'} 노드 · ${data.graph?.metadata?.num_edges ?? '?'} 관계`;
    state.project = 'all'; state.task = tasks.find(t=>String(t.status||'').toLowerCase()!=='completed')?.task_id||null; state.filter = null;
    state.detailTab = 'timeline';
    const pLabel = root.getElementById('project-label'); if (pLabel) pLabel.textContent = works[0].title;
    const hLabel = root.getElementById('handover-sync-time'); if(hLabel) hLabel.textContent = 'Supabase 최신 조회 · 데모';
    const hStatus = root.querySelector('#handover-view section:first-child .text-\\[11px\\].font-bold');
    if (hStatus) hStatus.textContent = 'Slack MCP 분석 데이터 · 시연';
    const top = root.querySelector('#import-modal p'); if(top) top.textContent = '저장된 실제 Slack 분석 결과에서 담당자와 Work를 선택합니다.';
    const agent = root.getElementById('ask-modal')?.querySelector('p'); if(agent) agent.textContent = '선택 업무의 DB 기록에 기반한 규칙형 데모 응답입니다. LLM Agent 연결은 별도입니다.';
    const keyTag = root.querySelector('header .bg-\\[\\#EAFBF4\\]'); if(keyTag) keyTag.textContent = '시연 접속';
    const priorities = root.getElementById('priority-overview');
    if(priorities) priorities.classList.remove('hidden');
    loaded = true;
    if(typeof window.restoreMlPriorities==='function')window.restoreMlPriorities();
    window.updateBriefingSummary();
    render();
    const details = root.getElementById('handover-project-select'); if(details && HANDOVER_WORKS.length) details.value = HANDOVER_WORKS[0].id;
    if (mainView === 'handover' && HANDOVER_WORKS.length) renderMyWork();
    if(typeof renderImportPeople === 'function') renderImportPeople();
  }

  renderPriorityOverview = function () {
    const el = root.getElementById('priority-overview'); if(!el) return;
    const ids=Object.keys(TASKS).filter(id=>TASKS[id]?.status!=='완료');
    const ranked=id=>TASKS[id].priorityRank!=null&&Number(TASKS[id].priorityRank)>0;
    const rankedCount=ids.filter(ranked).length;
    const ordered=[...ids].sort((a,b)=>{
      const byStatus=taskStatusRank(TASKS[a]?.status)-taskStatusRank(TASKS[b]?.status);
      if(byStatus)return byStatus;
      if(ranked(a)!==ranked(b))return ranked(a)?-1:1;
      if(ranked(a)&&ranked(b))return Number(TASKS[a].priorityRank)-Number(TASKS[b].priorityRank);
      return Number(TASKS[b].updated||0)-Number(TASKS[a].updated||0);
    });
    const subtitle=rankedCount
      ?`ML 우선순위 ${rankedCount}건 연동 · 미산정 ${ids.length-rankedCount}건`
      :'승인 완료 후 승인자의 ML 우선순위가 여기에 반영돼요.';
    el.innerHTML = `<div class="flex justify-between items-center gap-2"><div><h2 class="text-[16px] font-bold">현재 업무 ${ids.length}건</h2><p class="mt-1 text-[11px] text-[#8B95A1]">${subtitle}</p></div><button onclick="showAllTasks()" class="text-[12px] font-bold text-[#3182F6]">${ids.length}건 전체 보기 →</button></div><div class="mt-4 grid sm:grid-cols-2 xl:grid-cols-5 gap-2">${ordered.slice(0,5).map(id=>{const t=TASKS[id],project=projectForTask(id);return `<button onclick="openPriorityTask('${id}')" class="text-left rounded-2xl border border-[#EEF0F3] bg-white p-3"><div class="flex flex-wrap items-center justify-between gap-2"><span class="text-[11px] text-[#8B95A1]">${t.status}</span><span class="px-2 py-1 rounded-full text-[10px] font-bold ${riskBadge(t.risk)}">우선순위 ${priorityLabel(t)}</span></div><div class="mt-2 text-[10px] text-[#8B95A1]">${project?.name||'프로젝트 미확인'} · ${id}</div><div class="mt-1 text-[13px] font-bold">${t.name}</div><div class="mt-2 text-[10px] text-[#6B7684]">${t.deadline}</div></button>`}).join('')}</div>`;
  };

  // Open the original channel message, not a fabricated example.
  openSlackOriginal = function(taskId, i) {
    const e = SLACK_EVIDENCE[taskId]?.[i];
    if(!e) return;
    if(e.type==='dm' || !e.allowed) {toast('권한 또는 Slack 원문 연결 정보가 확인되지 않았어요.');return;}
    const ts = (e.timestamp || '').replace('.', '');
    if(!/^C[A-Z0-9]+$/.test(e.channel) || !/^\d{16}$/.test(ts)) {toast('Slack 메시지 링크가 확인되지 않았어요.');return;}
    window.open(`https://app.slack.com/archives/${e.channel}/p${ts}`, '_blank', 'noopener,noreferrer');
  };

  // Disable the mock YubiKey approval simulation: the backend demo uses HTTP Basic authentication.
  requestImportApproval = function() {
    if(!importState.person || !importState.selected.size) return toast('담당자와 업무를 선택하세요.');
    toast('YubiKey 승인 검증은 연결되지 않았습니다. 시연은 읽기 전용 데이터 조회만 지원합니다.');
  };
  const originalEnter = enterApp;
  enterApp = function() {
    if(!loaded && !isManagementRole()) return toast('업무 데이터를 불러오는 중입니다. 잠시 기다려주세요.');
    return originalEnter();
  };
  const loginButton = root.querySelector('#login-screen button');
  if(loginButton) loginButton.textContent = '시연 화면 열기';
  const loginTitle = root.querySelector('#login-screen h1');
  if(loginTitle) loginTitle.textContent = 'LINK-ing 업무 인수인계 시연';
  const loginHelp = root.querySelector('#login-screen p');
  if(loginHelp) loginHelp.textContent = '시연 접속은 Railway 서버 인증으로 보호됩니다. YubiKey 실제 인증은 연결 전입니다.';

  window.clearVerifiedDemoData = function() {
    PROJECTS.splice(0,PROJECTS.length);
    Object.keys(TASKS).forEach(k=>delete TASKS[k]);
    Object.keys(SLACK_EVIDENCE).forEach(k=>delete SLACK_EVIDENCE[k]);
    Object.keys(FILES).forEach(k=>delete FILES[k]);
    PEOPLE.splice(0,PEOPLE.length);
    // Keep standalone My Work demonstration fixtures across account switches.
    Object.keys(IMPORT_DATA).forEach(k=>delete IMPORT_DATA[k]);
    state.project='all';state.task=null;
  };
  window.loadVerifiedDemoData = async function(token) {
    const response = await fetch('/api/demo/data',{credentials:'same-origin',cache:'no-store',headers:{'X-Handover-Access-Token':token}});
    if(!response.ok)throw new Error('권한 확인 실패 (HTTP '+response.status+')');
    attach(await response.json());
  };
  window.reloadDemoData=()=>window.loadVerifiedDemoData('');
  fetch('/api/demo/auth/config',{credentials:'same-origin',cache:'no-store'})
    .then(async response => {if(!response.ok)throw new Error('인증 설정 조회 실패');return response.json();})
    .then(config => {
      if(config.verified_mode)return; // Requires signed-in, verified user before querying Work.
      return fetch('/api/demo/data',{credentials:'same-origin',cache:'no-store'})
        .then(async response=>{if(!response.ok)throw new Error('백엔드 연결 실패 (HTTP '+response.status+')');return response.json();})
        .then(attach);
    })
    .catch(err=>{
      console.error(err);
      const p=root.querySelector('#login-screen p');
      if(p)p.textContent='데이터 로딩 실패: '+err.message;
    });
})();
