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
    window.handoverWorkTitles={...(window.handoverWorkTitles||{}),...Object.fromEntries(works.map(w=>[w.work_id,w.title]))};
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
    // Directed dependency: source Task depends on target Task. Keep exact DB IDs.
    window.linkingWorkDependencies = deps.map(e => ({taskId:e.source_id, prerequisiteId:e.target_id}));
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
      const roleAssignments=participantLinks.filter(e=>e.target_id===id).map(e=>({
        personId:e.source_id,name:peopleMap.get(e.source_id)?.name||e.source_id,role:e.relation
      }));
      const eventIds=new Set(evs.map(e=>e.event_id));
      const contactIds=new Set(edges.filter(e=>e.source_type==='Person'&&(e.target_id===id||eventIds.has(e.target_id))).map(e=>e.source_id));
      for(const e of evs)for(const key of ['speaker_id','slack_user_id','actor_id','recipient_id'])if(e[key])contactIds.add(e[key]);
      const contacts=[...contactIds].map(personId=>peopleMap.get(personId)).filter(Boolean).sort((a,b)=>String(a.name).localeCompare(String(b.name),'ko'));
      const next = t.next_action || (t.status === 'completed' ? '완료된 업무입니다.' : '다음 할 일 확인 필요');
      const prereqs = [...new Set(evs.map(e => e.prerequisite).filter(Boolean))];
      const depTitles = deps.filter(e => e.source_id === id).map(e => taskMap.get(e.target_id)?.title).filter(Boolean);
      const caution = prereqs.length ? prereqs.join(' · ') : 'Slack 근거에서 별도 선행조건이 확인되지 않았습니다.';
      const explicitBlocker=String(t.blocker_reason||t.blocked_reason||'').trim();
      const rawDue=t.deadline_at||t.due_at;
      const preciseDue=rawDue && !Number.isNaN(Date.parse(rawDue)) ? new Date(rawDue).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true}) : null;
      const deadline=preciseDue || t.deadline_text || '미정';
      const recent = evs.length ? evs[evs.length - 1].slack_ts : '0';
      TASKS[id] = {
        name: html(t.title), sourceName:String(t.title || ''), status: html(statusText(t.status)), risk:null, deadline:html(deadline), deadlineAt:rawDue||null, updated:Number(recent),
        type: ownerIds.length > 1 || collaboratorIds.length > 0 ? 'collab':'solo', owner:html(owners[0] || '담당자 미확인'),
        contacts, people: collaborators.map(html), roleAssignments, next:html(next), after:[], blocker:html(explicitBlocker||prereqs[0] || '명시된 차단 사유 없음'),
        prerequisiteTexts:prereqs.map(html), explicitBlocker:html(explicitBlocker),
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
      const owned = participantLinks.filter(e => e.source_id === p.person_id && ['OWNER','REVIEWER','COLLABORATOR','APPROVER'].includes(e.relation)).map(e => e.target_id);
      const wids = [...new Set(owned.map(tid => taskToWork.get(tid)).filter(Boolean))];
      IMPORT_DATA[p.name] = wids.map(wid => ({workId:wid, project:workMap.get(wid)?.title || wid, tasks:(workTasks.get(wid)||[]).map(tid => taskMap.get(tid)?.title).filter(Boolean)}));
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
      let svg = `<svg viewBox="0 0 760 410" role="img" aria-label="${html(t.name)} 실제 업무 관계"><defs><marker id="demo-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto"><polygon points="0 0,8 3.5,0 7" fill="#9AA5B1"></polygon></marker></defs>`;
      const places = [[110,140],[650,140],[110,310],[650,310],[375,365]];
      for (const [i,e] of rels.entries()) {
        const p=peopleMap.get(e.source_id), xy=places[i];
        if(!p) continue;
        const from=xy[0]<375?[xy[0]+90,xy[1]]:xy[0]>375?[xy[0]-90,xy[1]]:[375,xy[1]-27];
        const to=xy[0]<375?[285,230]:xy[0]>375?[465,230]:[375,257];
        svg += line(from[0],from[1],to[0],to[1],e.relation);
        svg += node(xy[0],xy[1],p.name,p.team||'부서 미등록','person');
      }
      if(dependencies.length){
        const dep = taskMap.get(dependencies[0].target_id);
        if(dep){svg += line(375,203,375,87,'DEPENDS_ON');svg += node(375,60,dep.title,'선행 Task','task');}
      }
      svg += node(375,230,t.name,'선택한 Task','task');
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
      if(heading)heading.textContent=`${PROJECTS.length}건의 Work를 이어받았어요`;
      if(summary)summary.textContent=`현재 담당하는 Work의 업무 현황 · ML 우선순위 연동 ${ranked}건`;
      const ongoing=values.filter(task=>task.status==='진행 중').length;
      const waiting=values.filter(task=>['대기','차단','지연'].includes(task.status)).length;
      const stats=root.getElementById('received-work-stats');
      if(stats)stats.innerHTML=[['이어받은 Work',PROJECTS.length],['진행 중 Task',ongoing],['대기 Task',waiting]].map(([label,count])=>`<div class="rounded-xl bg-[#F7F8FA] px-3 sm:px-4 py-3"><div class="text-[11px] sm:text-[12px] text-[#6B7684]">${label}</div><div class="mt-2 text-[22px] leading-none font-bold text-[#191F28]">${count}<span class="ml-1 text-[11px] font-normal text-[#8B95A1]">건</span></div></div>`).join('');
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
    const agent = root.getElementById('ask-modal')?.querySelector('p'); if(agent) agent.textContent = '선택 업무의 DB 기록과 ML 우선순위 문맥을 LLM Agent에 전달합니다. Slack 원문 RAG는 아직 미연결입니다.';
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

  window.linkingSetOwnerTab=owner=>{
    window.linkingOwnerTab=['all','김지수','박보검'].includes(owner)?owner:'all';
    window.linkingTaskPriorityPage=1;
    window.linkingSelectedFlowTaskId=null;
    window.linkingSelectedFlowTaskWork=null;
    window.linkingSelectedWorkId=null;
    const detail=root.getElementById('briefing-task-section');
    if(detail)detail.style.display='none';
    renderPriorityOverview();
  };
  window.linkingSetPriorityView=view=>{
    window.linkingPriorityView=view==='task'?'task':'work';
    window.linkingTaskPriorityPage=1;
    renderPriorityOverview();
  };
  window.linkingSetTaskPriorityPage=page=>{
    window.linkingTaskPriorityPage=Math.max(1,Number(page)||1);
    renderPriorityOverview();
  };
  window.linkingSetTaskPriorityFilter=(key,value)=>{
    if(!['work','source','role','status'].includes(key))return;
    window.linkingTaskPriorityFilters={work:'all',source:'all',role:'all',status:'all',...(window.linkingTaskPriorityFilters||{}),[key]:value};
    window.linkingTaskPriorityFilterColumn=null;
    window.linkingTaskPriorityPage=1;
    renderPriorityOverview();
  };
  window.linkingToggleTaskColumnFilter=key=>{
    if(!['work','source','role','status'].includes(key))return;
    window.linkingTaskPriorityFilterColumn=window.linkingTaskPriorityFilterColumn===key?null:key;
    renderPriorityOverview();
  };
  window.linkingClearTaskPriorityFilter=key=>{
    if(!['work','source','role','status'].includes(key))return;
    window.linkingTaskPriorityFilters={work:'all',source:'all',role:'all',status:'all',...(window.linkingTaskPriorityFilters||{}),[key]:'all'};
    window.linkingTaskPriorityFilterColumn=null;
    window.linkingTaskPriorityPage=1;
    renderPriorityOverview();
  };
  window.linkingSetTaskPrioritySort=key=>{
    const current=window.linkingTaskPrioritySort||{key:null,direction:null};
    const defaults={rank:'asc',score:'desc',downstream:'desc',deadline:'asc'};
    if(!(key in defaults))return;
    if(current.key!==key)window.linkingTaskPrioritySort={key,direction:defaults[key]};
    else if(current.direction===defaults[key])window.linkingTaskPrioritySort={key,direction:defaults[key]==='asc'?'desc':'asc'};
    else window.linkingTaskPrioritySort={key:null,direction:null};
    window.linkingTaskPriorityPage=1;
    renderPriorityOverview();
  };
  renderPriorityOverview = function () {
    const area=root.getElementById('priority-overview');if(!area)return;
    const esc=html, round=n=>n==null?'미산정':Math.round(n)+'점';
    const getRank=t=>t.priorityRank!=null&&Number.isFinite(Number(t.priorityRank))&&Number(t.priorityRank)>0?Number(t.priorityRank):null;
    const getScore=t=>t.priorityScore!=null&&Number.isFinite(Number(t.priorityScore))?Number(t.priorityScore):null;
    const status=t=>t.status==='완료'?'done':t.status==='진행 중'?'active':t.status==='대기'?'waiting':'other';
    const dependencies=window.linkingWorkDependencies||[];
    const ownerTab=window.linkingOwnerTab||'all';
    const grantedSources=window.linkingApprovedWorkSources||{};
    const sourceWorks=PROJECTS.filter(work=>ownerTab==='all'||(grantedSources[work.id]||[]).includes(ownerTab));
    const items=sourceWorks.map(work=>{
      const tasks=work.tasks.map(id=>({id,task:TASKS[id]})).filter(x=>x.task);
      const pending=tasks.filter(x=>status(x.task)!=='done');
      const ranked=pending.filter(x=>getRank(x.task)!=null).sort((a,b)=>getRank(a.task)-getRank(b.task));
      const scored=pending.filter(x=>getScore(x.task)!=null).sort((a,b)=>getScore(b.task)-getScore(a.task));
      const lead=ranked[0]||scored[0]||null;
      const done=tasks.filter(x=>status(x.task)==='done').length;
      const taskIds=new Set(tasks.map(x=>x.id));
      const links=dependencies.filter(d=>taskIds.has(d.taskId)&&taskIds.has(d.prerequisiteId)&&d.taskId!==d.prerequisiteId);
      return {work,tasks,done,links,rank:lead?getRank(lead.task):null,score:lead?getScore(lead.task):null,lead};
    }).sort((a,b)=>{
      if(Boolean(a.lead)!==Boolean(b.lead))return a.lead?-1:1;
      if(a.rank!=null&&b.rank!=null&&a.rank!==b.rank)return a.rank-b.rank;
      if((a.rank!=null)!==(b.rank!=null))return a.rank!=null?-1:1;
      return (b.score??-Infinity)-(a.score??-Infinity);
    });
    window.linkingPriorityItems=items;
    const pct=item=>item.tasks.length?Math.round(item.done/item.tasks.length*100):0;
    const style=t=>status(t)==='done'?{bg:'#E5F5EA',fg:'#27834A',label:'완료',icon:'check_circle'}:status(t)==='active'?{bg:'#E7F0FF',fg:'#236AD6',label:'진행 중',icon:'play_circle'}:status(t)==='waiting'?{bg:'#FFF3E0',fg:'#A35C00',label:'대기',icon:'schedule'}:{bg:'#F1F3F6',fg:'#697586',label:t.status||'미확인',icon:'radio_button_unchecked'};
    const priorityView=window.linkingPriorityView==='task'?'task':'work';
    const viewToggle='<div role="group" aria-label="업무 보기 방식" class="inline-flex rounded-xl border border-[#DDE3EA] bg-[#F5F7FA] p-1">'+
      '<button type="button" onclick="linkingSetPriorityView(\'work\')" aria-pressed="'+String(priorityView==='work')+'" class="rounded-lg px-4 py-2 text-[12px] font-bold transition '+(priorityView==='work'?'bg-[#315FF4] text-white shadow-sm':'text-[#6B7684] hover:text-[#333D4B]')+'">Work 흐름</button>'+
      '<button type="button" onclick="linkingSetPriorityView(\'task\')" aria-pressed="'+String(priorityView==='task')+'" class="rounded-lg px-4 py-2 text-[12px] font-bold transition '+(priorityView==='task'?'bg-[#315FF4] text-white shadow-sm':'text-[#6B7684] hover:text-[#333D4B]')+'">Task 우선순위</button></div>';
    const flowOrder=item=>{
      // Kahn ordering of only grounded prerequisite links. Unlinked tasks are not presented as a sequential chain.
      const ids=new Set(item.tasks.map(x=>x.id));
      const incoming=new Map(item.tasks.map(x=>[x.id,0]));
      const outgoing=new Map(item.tasks.map(x=>[x.id,[]]));
      for(const e of item.links){incoming.set(e.taskId,incoming.get(e.taskId)+1);outgoing.get(e.prerequisiteId).push(e.taskId);}
      const indexed=new Map(item.tasks.map((x,i)=>[x.id,i]));
      const ready=item.tasks.filter(x=>!incoming.get(x.id)).map(x=>x.id);
      const sorted=[];
      while(ready.length){const id=ready.shift();sorted.push(id);for(const to of outgoing.get(id)){incoming.set(to,incoming.get(to)-1);if(!incoming.get(to))ready.push(to);}ready.sort((a,b)=>indexed.get(a)-indexed.get(b));}
      const byId=new Map(item.tasks.map(x=>[x.id,x]));
      const order=sorted.length===item.tasks.length?sorted:item.tasks.map(x=>x.id);
      return order.map(id=>byId.get(id));
    };
    const renderFlow=(item,selectedTaskId=null)=>{
      const ordered=flowOrder(item).filter(row=>!state.filter||row.task.type===state.filter);
      const selected=ordered.find(row=>row.id===selectedTaskId);
      const cards=ordered.map(({id,task})=>{
        const st=style(task);
        const activeOrWaiting=['active','waiting'].includes(status(task));
        const rawDeadline=String(task.deadline||'').trim();
        const hasDeadline=rawDeadline&&!['미정','마감일 미확인','미확인','없음','null'].includes(rawDeadline);
        const deadlineLabel=activeOrWaiting?(hasDeadline?'마감 '+esc(rawDeadline):'마감 미정'):'';
        const ownerLabel=task.owner||'담당자 미확인';
        const outstanding=(task.depends||[]).filter(title=>{
          const related=Object.values(TASKS).find(t=>t.sourceName===title||t.name===title);
          return !related||related.status!=='완료';
        });
        const blocker=String(task.explicitBlocker||'').trim();
        const prerequisites=task.prerequisiteTexts||[];
        const reason=blocker?'차단 사유: '+blocker:outstanding.length?'선행 업무: '+outstanding.join(' · '):prerequisites.length?'선행 조건: '+prerequisites.join(' · '):'';
        return '<button type="button" data-flow-task-id="'+esc(id)+'" aria-pressed="'+String(id===selectedTaskId)+'" class="w-full rounded-xl border px-4 py-3 text-left transition-colors '+(id===selectedTaskId?'border-[#5D6CFF] bg-[#F3F5FF]':'border-[#E8ECF1] bg-white hover:border-[#B0BEFF]')+'"><span class="flex items-center gap-3"><span class="shrink-0 inline-flex items-center justify-center rounded-full border px-3 py-1.5 text-[11px] font-bold" style="background:'+st.bg+';color:'+st.fg+';border-color:'+st.fg+'40">'+esc(st.label)+'</span><span class="min-w-0 flex-1 text-[13px] font-semibold text-[#191F28]">'+esc(task.name)+'</span>'+(activeOrWaiting?'<span class="shrink-0 text-[11px] font-medium text-[#6B7684] whitespace-nowrap">'+deadlineLabel+'</span>':'')+'<span class="material-symbols-outlined shrink-0 text-[17px] text-[#8894A7]">chevron_right</span></span><span class="mt-2 flex items-center gap-1.5 pl-1 text-[11px] text-[#6B7684]"><span class="material-symbols-outlined text-[15px]">person</span>'+esc(ownerLabel)+'</span>'+(reason&&status(task)!=='done'?'<span class="mt-1 block pl-1 text-[11px] text-[#A35C00]">'+esc(reason)+'</span>':'')+'</button>';
      }).join('')||'<div class="p-3 text-[12px] text-[#8B95A1]">해당 유형의 Task가 없습니다.</div>';
      return '<div class="flex flex-wrap items-center justify-between gap-2"><div><p class="text-[11px] text-[#8B95A1]">선택한 Work · Task 목록</p><h3 class="mt-1 text-[17px] font-bold">'+esc(item.work.name)+'</h3></div><span class="text-[12px] text-[#6B7684]">완료 '+item.done+'/'+item.tasks.length+'</span></div>'+
        '<div class="mt-4 space-y-2">'+cards+'</div>'+
        '<div class="mt-4 text-center text-[12px] text-[#8B95A1]">'+(selected?'아래에서 선택한 Task의 상세 정보를 확인하세요.':'상세내역을 보려면 Task를 클릭하세요')+'</div>';
    };
    window.linkingSelectFlowTask=id=>{
      const work=PROJECTS.find(p=>p.tasks.includes(id));
      if(!work||!TASKS[id])return;
      const section=root.getElementById('briefing-task-section');
      // Unhide FIRST; a downstream render exception must never leave details concealed.
      if(section){section.hidden=false;section.classList.remove('hidden');section.style.display='grid';}
      window.linkingSelectedWorkId=work.id;
      window.linkingSelectedFlowTaskId=id;
      window.linkingSelectedFlowTaskWork=work.id;
      state.project=work.id;
      state.task=id;
      state.detailTab='timeline';
      const selector=root.getElementById('project-select');
      if(selector)selector.value=work.id;
      // Render the original lower two-column detail directly, independently of the Work Flow redraw.
      try{
        renderTaskList();
      }catch(error){
        console.error('LINK-ing Task detail render failed',error);
        const list=root.getElementById('task-list');
        if(list)list.innerHTML='<p class="p-4 text-[13px] text-[#D92D20]">세부 업무 목록 표시 중 오류가 발생했어요.</p>';
        try{renderDetail();}catch(detailError){console.error('LINK-ing detail failed',detailError);}
      }
      if(section){section.style.display='grid';section.classList.remove('hidden');}
      const index=window.linkingPriorityItems?.findIndex(x=>x.work.id===work.id)??-1;
      if(index>=0)window.linkingShowPriorityTasks(index);
      const active=root.querySelector('[data-flow-task-id="'+id+'"]');
      if(active)active.setAttribute('aria-pressed','true');
      root.getElementById('briefing-task-section')?.scrollIntoView({behavior:'smooth',block:'start'});
    };
    if(!window.linkingFlowTaskClickBound){
      window.linkingFlowTaskClickBound=true;
      root.addEventListener('click',event=>{
        const trigger=event.target.closest?.('[data-flow-task-id]');
        if(!trigger)return;
        event.preventDefault();
        window.linkingSelectFlowTask(trigger.getAttribute('data-flow-task-id'));
      });
    }
    if(!window.linkingPriorityTableClickBound){
      window.linkingPriorityTableClickBound=true;
      root.addEventListener('click',event=>{
        const trigger=event.target.closest?.('[data-priority-task-id]');
        if(!trigger)return;
        event.preventDefault();
        window.linkingSelectFlowTask(trigger.getAttribute('data-priority-task-id'));
      });
    }
    if(!window.linkingPriorityFilterDismissBound){
      window.linkingPriorityFilterDismissBound=true;
      root.addEventListener('click',event=>{
        if(!window.linkingTaskPriorityFilterColumn||event.target.closest?.('[data-task-column-filter]'))return;
        window.linkingTaskPriorityFilterColumn=null;
        renderPriorityOverview();
      });
    }
    window.linkingShowPriorityTasks=i=>{
      const item=window.linkingPriorityItems?.[i],panel=root.getElementById('work-priority-tasks');
      if(!item||!panel)return;
      window.linkingActiveWorkIndex=i;
      root.querySelectorAll('[data-work-priority]').forEach((n,j)=>{n.classList.toggle('border-[#3182F6]',i===j);n.classList.toggle('bg-[#F2F7FF]',i===j);});
      panel.innerHTML=renderFlow(item,window.linkingSelectedFlowTaskWork===item.work.id?window.linkingSelectedFlowTaskId:null);
    };
    window.linkingChooseWork=i=>{
      const item=window.linkingPriorityItems?.[i];if(!item)return;
      window.linkingSelectedWorkId=item.work.id;
      window.linkingSelectedFlowTaskId=null;
      window.linkingSelectedFlowTaskWork=null;
      state.project=item.work.id;
      const section=root.getElementById('briefing-task-section');if(section)section.style.display='none';
      state.detailTab='timeline';
      const select=root.getElementById('project-select');if(select)select.value=item.work.id;
      const eligible=item.work.tasks.filter(id=>TASKS[id]&&(!state.filter||TASKS[id].type===state.filter));
      state.task=eligible.find(id=>TASKS[id].status!=='완료')||eligible[0]||null;
      renderTaskList();
      const updatedIndex=(window.linkingPriorityItems||[]).findIndex(row=>row.work.id===item.work.id);
      if(updatedIndex>=0)window.linkingShowPriorityTasks(updatedIndex);
    };
    window.openPriorityWork=id=>{
      const work=PROJECTS.find(w=>w.id===id);if(!work)return;
      state.project=id;state.filter=null;
      state.task=work.tasks.find(x=>TASKS[x]?.status!=='완료')||work.tasks[0]||null;
      const select=root.getElementById('project-select');if(select)select.value=id;
      render();root.getElementById('task-detail')?.scrollIntoView({behavior:'smooth',block:'start'});
    };
    const tabButtons=root.querySelectorAll('[data-owner-tab]');
    tabButtons.forEach(button=>{
      const active=button.dataset.ownerTab===ownerTab;
      button.setAttribute('aria-selected',String(active));
      button.classList.toggle('bg-white',active);
      button.classList.toggle('bg-[#F2F7FF]',!active);
      button.classList.toggle('text-[#1B64DA]',active);
      button.classList.toggle('border-[#93B8FF]',active);
    });
    if(window.linkingSelectedWorkId&&!items.some(x=>x.work.id===window.linkingSelectedWorkId)){
      window.linkingSelectedWorkId=null;
      window.linkingSelectedFlowTaskId=null;
      window.linkingSelectedFlowTaskWork=null;
      const detail=root.getElementById('briefing-task-section');
      if(detail)detail.style.display='none';
    }
    const heading='<div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="text-[17px] font-bold">'+(priorityView==='task'?'Task 우선순위':'업무 진행 흐름')+'</h2><p class="mt-1 text-[11px] text-[#8B95A1]">'+(priorityView==='task'?'인수받은 Task를 우선순위가 높은 순서로 보여드립니다.':'Work 선택 · Task 클릭 시 아래 상세 표시')+'</p></div>'+viewToggle+'</div>';
    if(priorityView==='task'){
      const roleName={OWNER:'담당',APPROVER:'승인',REVIEWER:'검토',COLLABORATOR:'협업',RELATED:'관련'};
      const allTaskRows=items.flatMap(item=>item.tasks.filter(row=>status(row.task)!=='done'&&(!state.filter||row.task.type===state.filter)).map(row=>{
        const sources=grantedSources[item.work.id]||[];
        const assignments=(row.task.roleAssignments||[]).filter(assignment=>sources.includes(assignment.name));
        const downstreamCount=dependencies.filter(link=>link.prerequisiteId===row.id&&TASKS[link.taskId]&&status(TASKS[link.taskId])!=='done').length;
        return {id:row.id,task:row.task,work:item.work,sources,assignments,downstreamCount,rank:getRank(row.task),score:getScore(row.task),originalIndex:item.work.tasks.indexOf(row.id)};
      }));
      const filters={work:'all',source:'all',role:'all',status:'all',...(window.linkingTaskPriorityFilters||{})};
      window.linkingTaskPriorityFilters=filters;
      const workOptions=[...new Map(allTaskRows.map(row=>[row.work.id,row.work.name])).entries()].map(([value,label])=>({value,label})).sort((a,b)=>a.label.localeCompare(b.label,'ko'));
      const sourceOptions=[...new Set(allTaskRows.flatMap(row=>row.sources))].sort((a,b)=>a.localeCompare(b,'ko'));
      const roleOptions=[...new Set(allTaskRows.flatMap(row=>row.assignments.map(assignment=>assignment.role)))].sort();
      const statusOptions=[...new Set(allTaskRows.map(row=>status(row.task)))].sort();
      const prioritySort=(a,b)=>{
        if(a.rank!=null&&b.rank!=null&&a.rank!==b.rank)return a.rank-b.rank;
        if((a.rank!=null)!==(b.rank!=null))return a.rank!=null?-1:1;
        if(a.score!=null&&b.score!=null&&a.score!==b.score)return b.score-a.score;
        if((a.score!=null)!==(b.score!=null))return a.score!=null?-1:1;
        return a.work.name.localeCompare(b.work.name,'ko')||a.originalIndex-b.originalIndex;
      };
      const deadlineValue=row=>{const value=Date.parse(String(row.task.deadlineAt||''));return Number.isFinite(value)?value:Number.MAX_SAFE_INTEGER;};
      const sortState=window.linkingTaskPrioritySort||{key:null,direction:null};
      window.linkingTaskPrioritySort=sortState;
      const filteredRows=allTaskRows.filter(row=>(filters.work==='all'||row.work.id===filters.work)&&(filters.source==='all'||row.sources.includes(filters.source))&&(filters.role==='all'||row.assignments.some(assignment=>assignment.role===filters.role))&&(filters.status==='all'||status(row.task)===filters.status));
      [...filteredRows].sort(prioritySort).forEach((row,index)=>{row.relativeRank=index+1;});
      const sortValue=(row,key)=>key==='rank'?row.relativeRank:key==='score'?(row.score??-Infinity):key==='downstream'?row.downstreamCount:key==='deadline'?deadlineValue(row):0;
      const taskRows=filteredRows.sort((a,b)=>{
        const leftMissing=sortState.key==='score'?a.score==null:sortState.key==='deadline'?deadlineValue(a)===Number.MAX_SAFE_INTEGER:false;
        const rightMissing=sortState.key==='score'?b.score==null:sortState.key==='deadline'?deadlineValue(b)===Number.MAX_SAFE_INTEGER:false;
        if(leftMissing!==rightMissing)return leftMissing?1:-1;
        const left=sortValue(a,sortState.key),right=sortValue(b,sortState.key);
        const compared=typeof left==='string'?left.localeCompare(right,'ko'):left-right;
        return (sortState.direction==='asc'?compared:-compared)||prioritySort(a,b);
      });
      window.linkingPriorityTaskRows=taskRows;
      const pageSize=5,pageCount=Math.max(1,Math.ceil(taskRows.length/pageSize));
      const page=Math.min(pageCount,Math.max(1,Number(window.linkingTaskPriorityPage)||1));
      window.linkingTaskPriorityPage=page;
      const pageRows=taskRows.slice((page-1)*pageSize,page*pageSize);
      const rows=pageRows.map((row,index)=>{
        const st=style(row.task),displayRank=row.relativeRank??((page-1)*pageSize+index+1),sourceLabel=row.sources.join(' · ')||'인계자 미확인';
        const roleLabel=row.assignments.length?[...new Set(row.assignments.map(assignment=>(roleName[assignment.role]||assignment.role)+' ('+assignment.role+')'))].join(' · '):'역할 미확인';
        const priority=row.score!=null?Math.round(row.score)+'점':row.rank!=null?row.rank+'위':'미산정';
        return '<button type="button" data-priority-task-id="'+esc(row.id)+'" class="grid w-full min-w-[1040px] grid-cols-[64px_minmax(260px,1fr)_110px_150px_90px_100px_100px_150px] items-center gap-3 border-t border-[#EEF0F3] px-4 py-4 text-left transition hover:bg-[#F7F9FF] focus:bg-[#F2F6FF] focus:outline-none"><span class="flex h-9 w-9 items-center justify-center rounded-full bg-[#F1F3F5] text-[13px] font-bold text-[#333D4B]">'+displayRank+'</span><span class="min-w-0"><strong class="block truncate text-[13px] text-[#191F28]">'+esc(row.task.name)+'</strong><span class="mt-1 block truncate text-[11px] text-[#8B95A1]">'+esc(row.work.name)+'</span></span><span class="truncate text-[12px] text-[#4E5968]">'+esc(sourceLabel)+'</span><span class="text-[11px] font-semibold text-[#4E5968]">'+esc(roleLabel)+'</span><span class="justify-self-start rounded-full border px-3 py-1.5 text-[11px] font-bold" style="background:'+st.bg+';color:'+st.fg+';border-color:'+st.fg+'40">'+esc(st.label)+'</span><strong class="text-[13px] '+(row.score!=null?'text-[#E5484D]':'text-[#6B7684]')+'">'+priority+'</strong><span class="text-center text-[12px] font-semibold text-[#4E5968]">'+row.downstreamCount+'건</span><span class="flex items-center justify-between gap-2 text-[11px] text-[#4E5968]"><span class="truncate">'+esc(row.task.deadline||'미정')+'</span><span class="material-symbols-outlined text-[17px] text-[#8B95A1]">chevron_right</span></span></button>';
      }).join('')||'<div class="px-6 py-16 text-center text-[13px] text-[#8B95A1]">표시할 미완료 Task가 없습니다.</div>';
      const pages=Array.from({length:pageCount},(_,i)=>i+1).map(number=>'<button type="button" onclick="linkingSetTaskPriorityPage('+number+')" aria-current="'+(number===page?'page':'false')+'" class="h-8 min-w-8 rounded-lg px-2 text-[12px] font-bold '+(number===page?'bg-[#315FF4] text-white':'text-[#6B7684] hover:bg-[#F2F4F6]')+'">'+number+'</button>').join('');
      const sortHeader=(key,label)=>{const active=sortState.key===key,arrow=active?(sortState.direction==='asc'?'↑':'↓'):'↕';return '<button type="button" onclick="linkingSetTaskPrioritySort(\''+key+'\')" aria-label="'+esc(label)+' 정렬" class="inline-flex items-center gap-1 text-left '+(active?'font-bold text-[#315FF4]':'hover:text-[#333D4B]')+'"><span>'+esc(label)+'</span><span class="text-[11px] '+(active?'text-[#315FF4]':'text-[#B0B8C1]')+'">'+arrow+'</span></button>';};
      const openFilter=window.linkingTaskPriorityFilterColumn;
      const filterChoices={
        work:[{value:'all',label:'전체 Work'},...workOptions],
        source:[{value:'all',label:'전체 인계자'},...sourceOptions.map(value=>({value,label:value}))],
        role:[{value:'all',label:'전체 역할'},...roleOptions.map(value=>({value,label:(roleName[value]||value)+' ('+value+')'}))],
        status:[{value:'all',label:'전체 상태'},...statusOptions.map(value=>({value,label:value==='done'?'완료':value==='active'?'진행 중':value==='waiting'?'대기':'기타'}))],
      };
      const filterTitles={work:'Work | Task',source:'인계자',role:'인계자 역할',status:'상태'};
      const filterHeader=(key,label)=>{const active=filters[key]!=='all',open=openFilter===key;return '<span data-task-column-filter class="inline-flex items-center gap-1"><span>'+esc(label)+'</span><button type="button" onclick="linkingToggleTaskColumnFilter(\''+key+'\')" aria-expanded="'+String(open)+'" aria-label="'+esc(label)+' 필터" class="inline-flex h-5 w-5 items-center justify-center text-[12px] font-black '+(active||open?'text-[#315FF4]':'text-[#9AA5B1] hover:text-[#4E5968]')+'">▼</button></span>';};
      const columnFilterPanel=openFilter?'<div data-task-column-filter class="min-w-[1040px] border-t border-[#E5E8EB] bg-white px-4 py-3"><div class="flex flex-wrap items-center gap-2"><strong class="mr-1 text-[11px] text-[#4E5968]">'+esc(filterTitles[openFilter])+' 필터</strong>'+filterChoices[openFilter].map(choice=>'<button type="button" onclick="linkingSetTaskPriorityFilter(\''+openFilter+'\',\''+esc(choice.value)+'\')" class="rounded-full border px-3 py-1.5 text-[11px] font-semibold '+(filters[openFilter]===choice.value?'border-[#315FF4] bg-[#315FF4] text-white':'border-[#DDE3EA] bg-white text-[#4E5968] hover:border-[#8EA6FF]')+'">'+esc(choice.label)+'</button>').join('')+'</div></div>':'';
      area.innerHTML=heading+'<div class="mt-3 overflow-hidden rounded-xl border border-[#E5E8EB] bg-white"><div class="overflow-x-auto"><div class="grid min-w-[1040px] grid-cols-[64px_minmax(260px,1fr)_110px_150px_90px_100px_100px_150px] gap-3 bg-[#F8F9FB] px-4 py-3 text-[11px] font-semibold text-[#6B7684]">'+sortHeader('rank','순위')+filterHeader('work','Work | Task')+filterHeader('source','인계자')+filterHeader('role','인계자 역할')+filterHeader('status','상태')+sortHeader('score','우선순위')+sortHeader('downstream','후속 업무')+sortHeader('deadline','마감')+'</div>'+columnFilterPanel+rows+'</div></div>'+
        '<div class="mt-4 flex flex-wrap items-center justify-between gap-3"><span class="text-[11px] text-[#8B95A1]">총 '+taskRows.length+'건 · 페이지당 5건</span><nav aria-label="Task 우선순위 페이지" class="flex items-center gap-1"><button type="button" onclick="linkingSetTaskPriorityPage('+(page-1)+')" '+(page===1?'disabled':'')+' class="h-8 rounded-lg px-3 text-[11px] font-bold text-[#6B7684] hover:bg-[#F2F4F6] disabled:cursor-not-allowed disabled:opacity-35">이전</button>'+pages+'<button type="button" onclick="linkingSetTaskPriorityPage('+(page+1)+')" '+(page===pageCount?'disabled':'')+' class="h-8 rounded-lg px-3 text-[11px] font-bold text-[#6B7684] hover:bg-[#F2F4F6] disabled:cursor-not-allowed disabled:opacity-35">다음</button></nav></div>';
    }else{
      area.innerHTML=heading+'<div class="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4"><div class="lg:col-span-2 space-y-2">'+items.map((item,i)=>
        '<div data-work-priority="'+i+'" class="rounded-xl border border-[#E5E8EB] bg-white hover:border-[#3182F6]"><button type="button" onclick="linkingChooseWork('+i+')" class="w-full p-3 text-left" aria-label="'+esc(item.work.name)+' 흐름 보기"><div class="flex items-start justify-between gap-2"><div class="min-w-0 text-[13px] leading-5 font-bold">'+(i+1)+'. '+esc(item.work.name)+'</div><span class="shrink-0 text-[11px] font-semibold text-[#3182F6]">'+(item.rank!=null?item.rank+'위 · ':'')+round(item.score)+'</span></div><div class="mt-3 flex items-center gap-3"><div class="h-1.5 flex-1 rounded-full bg-[#E8EBF0] overflow-hidden"><div class="h-full rounded-full bg-[#438763]" style="width:'+pct(item)+'%"></div></div><span class="text-[11px] shrink-0 text-[#6B7684]">완료 '+item.done+'/'+item.tasks.length+'</span></div></button></div>').join('')+
        '</div><div id="work-priority-tasks" class="lg:col-span-3 rounded-xl border border-[#EDF0F4] bg-[#FAFBFC] p-4"><p class="text-[12px] text-[#8B95A1]">Work를 선택하면 Task 흐름이 표시돼요.</p></div></div>';
    }
    if(priorityView==='work'&&items.length){
      const requested=window.linkingSelectedWorkId||(state.project!=='all'?state.project:null);
      const position=items.findIndex(item=>item.work.id===requested);
      window.linkingShowPriorityTasks(position>=0?position:0);
    }else if(priorityView==='work'&&!items.length){
      area.innerHTML=heading+'<div class="mt-4 rounded-xl bg-[#F8F9FA] px-6 py-14 text-center"><div class="text-[16px] font-bold text-[#333D4B]">'+html(ownerTab==='all'?'인수받은 업무가 없습니다.':ownerTab+'님에게 인수받은 업무가 없습니다.')+'</div><p class="mt-2 text-[12px] text-[#8B95A1]">승인된 인수인계 Work가 없습니다.</p></div>';
    }
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
  window.loadApprovedHandovers = async function(workIds) {
    const ids=[...new Set(workIds)];
    const response=await fetch('/api/demo/data?work_ids='+encodeURIComponent(ids.join(',')),{credentials:'same-origin',cache:'no-store'});
    if(!response.ok)throw new Error('승인 업무 조회 실패 (HTTP '+response.status+')');
    const data=await response.json(), allowed=new Set(workIds);
    const works=(data.works||[]).filter(w=>allowed.has(w.work_id));
    const taskIds=new Set((data.edges||[]).filter(e=>e.source_type==='Work'&&allowed.has(e.source_id)&&e.relation==='HAS_TASK').map(e=>e.target_id));
    const eventIds=new Set((data.edges||[]).filter(e=>e.source_type==='Task'&&taskIds.has(e.source_id)&&e.relation==='HAS_EVENT').map(e=>e.target_id));
    const events=(data.events||[]).filter(e=>eventIds.has(e.event_id));
    const sourceIds=new Set(events.map(e=>e.source_id));
    const nodeIds=new Set([...works.map(w=>w.work_id),...taskIds,...eventIds]);
    attach({...data,works,tasks:(data.tasks||[]).filter(t=>taskIds.has(t.task_id)),events,
      edges:(data.edges||[]).filter(e=>nodeIds.has(e.target_id)&&(nodeIds.has(e.source_id)||e.source_type==='Person')),
      slack_messages:(data.slack_messages||[]).filter(m=>sourceIds.has(m.message_id))});
  };
  window.reloadDemoData=()=>window.loadVerifiedDemoData('');
  // Do not fetch every employee's Work before login. Approved Work is scoped after login.
})();
