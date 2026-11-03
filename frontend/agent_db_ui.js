/* Existing LINK-ing chat UI; credentials stay on the server. */
(() => {
  'use strict';
  let history = [], historyScope = '', busy = false, session = 0;
  const byId = id => document.getElementById(id);
  const originalOpen = window.openAsk;
  function contactContext(selected, taskId) {
    // Optional merger hook. Display context only; it never authorizes DB access.
    if(typeof window.linkingAgentContactContext==='function')return window.linkingAgentContactContext(taskId,selected);
    const work=typeof PROJECTS!=='undefined' ? PROJECTS.find(w=>(w.tasks||[]).includes(taskId)) : null;
    const sources=window.linkingApprovedWorkSources||{};
    const known=!!work&&Object.prototype.hasOwnProperty.call(sources,work.id)&&Array.isArray(sources[work.id]);
    return {current_person_id:byId('sidebar-user-id')?.textContent?.trim()||'',
      current_person_name:byId('sidebar-user-name')?.textContent?.trim()||'',absence_known:known,
      absent_people:known?sources[work.id].map(name=>({name})):[],
      candidates:(selected.roleAssignments||[]).map(p=>({person_id:p.personId||'',name:p.name,role:p.role}))};
  }
  function textBlock(node, text) {
    // Small safe Markdown subset: bold, line breaks. Never interpret model/raw HTML.
    node.replaceChildren();
    String(text || '').split(/(\*\*[^*\n]+\*\*)/g).forEach(part => {
      if (part.startsWith('**') && part.endsWith('**')) {
        const strong = document.createElement('strong'); strong.textContent = part.slice(2, -2); node.append(strong);
      } else node.append(document.createTextNode(part));
    });
  }
  async function config() {
    const response = await fetch('/api/chat/config', {credentials:'same-origin', cache:'no-store'});
    if (!response.ok) throw new Error('업무 Agent 연결 설정을 확인할 수 없습니다. 로그인 상태를 확인해 주세요.');
    return response.json();
  }
  function modeLabel(c) {
    return c.mode === 'local_db_export' ? '로컬 DB 복사본 · 실제 AI · 테스트 역할' :
      c.db_enabled ? 'DB 업무 · Slack 원문 기반' : '화면의 업무 정보 기반 · Slack 원문 미연결';
  }
  function appendSources(card, result) {
    const sources = (result.sources || []).filter(s => s.type === 'slack_message');
    if (!sources.length) return;
    const details = document.createElement('details'); details.className='mt-3 border-t border-[#EEF0F3] pt-3';
    const summary = document.createElement('summary'); summary.className='cursor-pointer text-[12px] font-bold text-[#3182F6]';
    summary.textContent='답변 근거 원문 '+sources.length+'개'; details.append(summary);
    for (const s of sources) {
      const block=document.createElement('div');block.className='mt-3 rounded-xl bg-[#F8F9FA] p-3';
      const title=document.createElement('div');title.className='font-semibold';title.textContent='['+s.id+'] '+(s.author_name || '작성자 미상');
      const meta=document.createElement('div');meta.className='mt-1 text-[11px] text-[#8B95A1] break-all';
      const parsed=s.timestamp_utc ? new Date(s.timestamp_utc) : null;
      meta.textContent=(parsed&&!Number.isNaN(parsed.getTime()) ? parsed.toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' (한국 시간)' : '작성 시각 미상')+' · '+s.message_id;
      const body=document.createElement('div');body.className='mt-2 whitespace-pre-wrap break-words';body.textContent=s.text || '';
      block.append(title,meta,body);if(s.text_truncated){const note=document.createElement('p');note.textContent='긴 원문의 일부입니다.';block.append(note)}details.append(block);
    }
    card.append(details);
  }
  window.openAsk = function() {
    session++; history=[];historyScope='';originalOpen();
    const status=byId('agent-data-status');status.textContent='업무 정보 연결 확인 중';
    config().then(c=>status.textContent=modeLabel(c)).catch(e=>status.textContent=e.message);
  };
  window.sendAgentQuestion = async function() {
    if (busy) return;
    const input=byId('ask-input'),button=byId('ask-submit'),question=input.value.trim();if(!question)return;
    const selected=agentCurrentTask(),taskId=agentCurrentTaskId(selected);
    if(!selected||!taskId)return toast('먼저 업무를 선택하세요.');
    const box=byId('chat-box'),turn=document.createElement('div'),card=document.createElement('div');
    turn.className='mt-4 text-[#191F28] font-medium';turn.textContent='Q. '+question;
    card.className='mt-2 rounded-2xl bg-white border border-[#EEF0F3] p-4';
    const label=document.createElement('div');label.className='text-[11px] font-bold text-[#3182F6]';label.textContent='업무 Agent · '+(selected.sourceName||selected.name||taskId);
    const answer=document.createElement('div');answer.className='mt-2 text-[13px] whitespace-pre-wrap break-words';answer.textContent='근거를 확인하고 답변을 생성하고 있습니다…';
    const source=document.createElement('div');source.className='mt-3 text-[11px] text-[#8B95A1]';
    card.append(label,answer,source);box.append(turn,card);busy=true;input.disabled=true;button.disabled=true;input.value='';
    const requestSession=session;
    try {
      const c=await config();byId('agent-data-status').textContent=modeLabel(c);
      const contacts=contactContext(selected,taskId);
      const scope=c.mode+':'+taskId+':'+(window.linkingLocalTestPersonId||'session')+':'+JSON.stringify(contacts);
      if(historyScope!==scope){history=[];historyScope=scope;}
      if(c.db_enabled&&!/^TASK-[A-Za-z0-9_-]+$/.test(taskId))throw Error('이 업무는 아직 DB에 저장되지 않았습니다. 저장된 업무를 선택해 주세요.');
      const payload={question,task_id:taskId,history:history.slice(-6)};
      if(!c.db_enabled){payload.tasks=agentTaskContext();payload.contact_context=contacts;}
      const headers={'Content-Type':'application/json'};
      if(c.mode==='local_db_export') {headers['X-Preview-Token']=c.csrf;payload.preview_person_id=window.linkingLocalTestPersonId||'U0C20G9MRML';}
      const response=await fetch(c.endpoint,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(payload)});
      const result=await response.json();
      if(!response.ok){const friendly={401:'Slack 로그인이 필요합니다. 로그인 후 다시 질문해 주세요.',403:'이 업무의 원문을 조회할 권한이 없습니다.',503:'업무 Agent 연결 설정이 준비되지 않았습니다.'};throw Error(friendly[response.status]||(typeof result.detail==='string'?result.detail:result.error)||'질문 처리에 실패했습니다.');}
      if(!result.answer)throw Error('Agent 응답이 비어 있습니다.');
      textBlock(answer,result.answer);
      source.textContent=(result.mode==='local_db_export'?'로컬 DB 복사본 · ':result.mode==='db_slack_task'?'DB 조회 · ':'화면 업무 정보 · ')+(result.llm_called===false?'AI 생성 없이 안내':'AI 답변');
      appendSources(card,result);
      if(result.messages_limited){const note=document.createElement('p');note.className='mt-2 text-[11px] text-[#8B95A1]';note.textContent='일부 최신 원문만 조회한 답변입니다.';card.append(note);}
      if(session===requestSession&&historyScope===scope){history.push({role:'user',content:question},{role:'assistant',content:result.answer});history=history.slice(-8);}
    }catch(e){answer.textContent='오류: '+e.message;source.textContent='연결 실패 · 답변을 생성하지 못했습니다.';}
    finally{busy=false;input.disabled=false;button.disabled=false;box.scrollTop=box.scrollHeight;if(!byId('ask-modal').classList.contains('hidden'))input.focus();}
  };
  window.linkingAgentUI={textBlock,appendSources,modeLabel,contactContext};
})();
