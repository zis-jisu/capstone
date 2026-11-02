const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const path=require('path');
const code=fs.readFileSync(path.join(__dirname,'../frontend/agent_db_ui.js'),'utf8');
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this._text='';this.classList={contains:()=>false};}
 append(...nodes){this.children.push(...nodes)}
 replaceChildren(...nodes){this.children=[...nodes];this._text=''}
 set textContent(v){this._text=String(v);this.children=[]}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('')}
 focus(){}
}
async function scenario(config,result,status=200){
 const elements=Object.fromEntries(['ask-input','ask-submit','chat-box','agent-data-status','ask-modal'].map(id=>[id,new Element()]));
 const requests=[];let selected='TASK-00080';
 const context={document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag),createTextNode:text=>{const n=new Element('#text');n.textContent=text;return n}},
  openAsk(){},agentCurrentTask:()=>({name:'테스트 업무'}),agentCurrentTaskId:()=>selected,
  agentTaskContext:()=>[{task_id:selected,name:'테스트 업무'}],toast(){},console,Date,Error,Number,
  fetch:async(url,options={})=>{requests.push({url,...options});return url==='/api/chat/config'?{ok:true,json:async()=>config}:{ok:status===200,status,json:async()=>result}}};
 context.window=context;vm.createContext(context);vm.runInContext(code,context);
 return {context,elements,requests,select:id=>selected=id,send:async q=>{elements['ask-input'].value=q;await context.sendAgentQuestion()}};
}
(async()=>{
 const db={db_enabled:true,endpoint:'/api/chat/db',mode:'db_slack_task'};
 const ok={answer:'**완료** <img src=x onerror=alert(1)> [S1]',mode:'db_slack_task',llm_called:true,sources:[{id:'S1',type:'slack_message',message_id:'C1:1',author_name:'테스트',text:'<script>원문</script>'}]};
 const s=await scenario(db,ok);await s.send('완료된 작업은?');
 let posts=s.requests.filter(x=>x.method==='POST');let payload=JSON.parse(posts[0].body);
 assert.strictEqual(posts[0].url,'/api/chat/db');assert.strictEqual(posts[0].credentials,'same-origin');
 assert.deepStrictEqual(Object.keys(payload).sort(),['history','question','task_id']);
 const card=s.elements['chat-box'].children[1];
 assert(card.textContent.includes('완료'));assert(card.textContent.includes('<script>원문</script>'));
 const answer=card.children[1];assert(answer.children.some(n=>n.tag==='strong'));assert(answer.children.some(n=>n.tag==='#text'&&n.textContent.includes('<img')));
 await s.send('다음은?');posts=s.requests.filter(x=>x.method==='POST');assert.strictEqual(JSON.parse(posts[1].body).history.length,2);
 s.select('TASK-00079');await s.send('다른 업무는?');posts=s.requests.filter(x=>x.method==='POST');assert.strictEqual(JSON.parse(posts[2].body).history.length,0);
 console.log('PASS DB payload, same-origin credentials, safe rendering, source display, scoped history');
 const denied=await scenario(db,{detail:'Task access denied'},403);await denied.send('원문?');
 assert(denied.elements['chat-box'].textContent.includes('조회 권한'));assert.strictEqual(denied.elements['ask-input'].disabled,false);
 console.log('PASS access errors and input recovery');
 const fallback=await scenario({db_enabled:false,endpoint:'/api/chat',mode:'frontend_context'}, {answer:'테스트',mode:'frontend_context'});
 await fallback.send('상태?');const fallbackPost=fallback.requests.find(x=>x.method==='POST');assert.strictEqual(fallbackPost.url,'/api/chat');assert(Array.isArray(JSON.parse(fallbackPost.body).tasks));
 console.log('PASS explicit frontend mode compatibility');
 const draft=await scenario(db,ok);draft.select('draft-1');await draft.send('상태?');assert(!draft.requests.some(x=>x.method==='POST'));
 console.log('PASS unsaved Task is not sent to DB');
 const failed=await scenario(db,ok);failed.context.fetch=async()=>({ok:false});await failed.send('상태?');assert(failed.elements['chat-box'].textContent.includes('연결 설정'));
 console.log('PASS config failure does not silently fall back');
 const demo=await scenario({db_enabled:true,endpoint:'/api/chat/db/demo',mode:'db_slack_demo',demo_people:{'원이정':'U0C20G9MRML'}},ok);
 demo.elements['handover-login-account']=new Element();demo.elements['handover-login-account'].value='원이정';
 await demo.send('원문?');const dp=JSON.parse(demo.requests.find(x=>x.method==='POST').body);
 assert.strictEqual(dp.demo_person_id,'U0C20G9MRML');assert(!dp.tasks);
 console.log('PASS shared-account demo sends explicit simulated role');
})().catch(error=>{console.error(error);process.exitCode=1});
