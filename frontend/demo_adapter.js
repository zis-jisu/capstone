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
      const eventIds=new Set(evs.map(e=>e.event_id));
      const contactIds=new Set(edges.filter(e=>e.source_type==='Person'&&(e.target_id===id||eventIds.has(e.target_id))).map(e=>e.source_id));
      for(const e of evs)for(const key of ['speaker_id','slack_user_id','actor_id','recipient_id'])if(e[key])contactIds.add(e[key]);
      const contacts=[...contactIds].map(personId=>peopleMap.get(personId)).filter(Boolean).sort((a,b)=>String(a.name).localeCompare(String(b.name),'ko'));
      const next = t.next_action || (t.status === 'completed' ? '완료된 업무입니다.' : '다음 할 일 확인 필요');
      const prereqs = [...new Set(evs.map(e => e.prerequisite).filter(Boolean))];
      const depTitles = deps.filter(e => e.source_id === id).map(e => taskMap.get(e.target_id)?.title).filter(Boolean);
      const caution = prereqs.length ? prereqs.join(' · ') : 'Slack 근거에서 별도 선행조건이 확인되지 않았습니다.';
      const deadline = t.deadline_text || (t.deadline_at ? String(t.deadline_at).slice(0,16).replace('T',' ') : '미정');
      const recent = evs.length ? evs[evs.length - 1].slack_ts : '0';
      TASKS[id] = {
        name: html(t.title), sourceName:String(t.title || ''), status: html(statusText(t.status)), risk:null, deadline:html(deadline), updated:Number(recent),
        type: ownerIds.length > 1 || collaboratorIds.length > 0 ? 'collab':'solo', owner:html(owners[0] || '담당자 미확인'),
        contacts, people: collaborators.map(html), next:html(next), after:[], blocker:html(prereqs[0] || '명시된 차단 사유 없음'),
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

  renderPriorityOverview = function () {
    const area=root.getElementById('priority-overview');if(!area)return;
    const esc=html, round=n=>n==null?'미산정':Math.round(n)+'점';
    const getRank=t=>t.priorityRank!=null&&Number.isFinite(Number(t.priorityRank))&&Number(t.priorityRank)>0?Number(t.priorityRank):null;
    const getScore=t=>t.priorityScore!=null&&Number.isFinite(Number(t.priorityScore))?Number(t.priorityScore):null;
    const status=t=>t.status==='완료'?'done':t.status==='진행 중'?'active':t.status==='대기'?'waiting':'other';
    const dependencies=window.linkingWorkDependencies||[];
    const items=PROJECTS.map(work=>{
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
        return '<button type="button" data-flow-task-id="'+esc(id)+'" aria-pressed="'+String(id===selectedTaskId)+'" class="w-full flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors '+(id===selectedTaskId?'border-[#5D6CFF] bg-[#F3F5FF]':'border-[#E8ECF1] bg-white hover:border-[#B0BEFF]')+'"><span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full" style="background:'+st.bg+';color:'+st.fg+'"><span class="material-symbols-outlined text-[18px]">'+st.icon+'</span></span><span class="min-w-0 flex-1"><span class="block text-[13px] font-semibold text-[#191F28]">'+esc(task.name)+'</span>'+(['active','waiting'].includes(status(task))&&task.deadline&&task.deadline!=='미정'?'<span class="mt-1 block text-[11px] text-[#6B7684]">마감 '+esc(task.deadline)+'</span>':'')+'</span><span class="shrink-0 text-[11px] font-bold" style="color:'+st.fg+'">'+esc(st.label)+'</span><span class="material-symbols-outlined shrink-0 text-[17px] text-[#8894A7]">chevron_right</span></button>';
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
    area.innerHTML='<div class="flex items-center justify-between gap-3"><h2 class="text-[17px] font-bold">업무 진행 흐름</h2><span class="text-[11px] text-[#8B95A1]">Work 선택 · Task 클릭 시 상세 표시</span></div>'+ 
      '<div class="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4"><div class="lg:col-span-2 space-y-2">'+items.map((item,i)=>
      '<div data-work-priority="'+i+'" onmouseenter="linkingShowPriorityTasks('+i+')" onfocusin="linkingShowPriorityTasks('+i+')" class="rounded-xl border border-[#E5E8EB] bg-white hover:border-[#3182F6]"><button type="button" onclick="linkingChooseWork('+i+')" class="w-full p-3 text-left" aria-label="'+esc(item.work.name)+' 흐름 보기"><div class="flex items-start justify-between gap-2"><div class="min-w-0 text-[13px] leading-5 font-bold">'+(i+1)+'. '+esc(item.work.name)+'</div><span class="shrink-0 text-[11px] font-semibold text-[#3182F6]">'+(item.rank!=null?item.rank+'위 · ':'')+round(item.score)+'</span></div><div class="mt-3 flex items-center gap-3"><div class="h-1.5 flex-1 rounded-full bg-[#E8EBF0] overflow-hidden"><div class="h-full rounded-full bg-[#438763]" style="width:'+pct(item)+'%"></div></div><span class="text-[11px] shrink-0 text-[#6B7684]">완료 '+item.done+'/'+item.tasks.length+'</span></div></button></div>').join('')+
      '</div><div id="work-priority-tasks" class="lg:col-span-3 rounded-xl border border-[#EDF0F4] bg-[#FAFBFC] p-4"><p class="text-[12px] text-[#8B95A1]">Work를 선택하면 Task 흐름이 표시돼요.</p></div></div>';
    if(items.length){
      const requested=window.linkingSelectedWorkId||(state.project!=='all'?state.project:null);
      const position=items.findIndex(item=>item.work.id===requested);
      window.linkingShowPriorityTasks(position>=0?position:0);
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
