const fs=require('fs'),vm=require('vm'),assert=require('assert');
const admin=fs.readFileSync('frontend/admin_adapter.js','utf8');
const demo=fs.readFileSync('frontend/demo_adapter.js','utf8');
const html=fs.readFileSync('frontend/index.html','utf8');
(async()=>{
 // Only selected Work IDs are requested, even when the source has more Works.
 const selectedCode=admin.slice(admin.indexOf(' function selectedImportWorks(){'),admin.indexOf(' async function selectCatalogPerson'));
 const requestCode=admin.slice(admin.indexOf(' requestImportApproval=async function(){'),admin.indexOf(' // Header actions'));
 const rows=[{workId:'W1',project:'One',tasks:['A','B']},{workId:'W2',project:'Two',tasks:['C']},{workId:'W3',project:'Three',tasks:['D']}];
 for(const chosen of [1,2]){
  const posts=[],context={IMPORT_DATA:{'김지수':rows},importState:{person:'김지수',selected:new Set(chosen===1?['W1::A','W1::B']:['W1::A','W1::B','W2::C'])},PERSON_IDS:{'원이정':'WON','김지수':'KIM'},actor:'원이정',importWorkKeys:g=>g.tasks.map(t=>g.workId+'::'+t),el:()=>({disabled:false}),setActiveWorkIds(ids){context.active=ids},load:async()=>[],api:async(path,method,data)=>posts.push(data),updateInboxBadge(){},renderImportFlow(){},refreshGate:async()=>{},message(){}};
  vm.runInNewContext(selectedCode+requestCode,context);await context.requestImportApproval();
  assert.equal(posts.length,chosen);assert.deepEqual(posts.map(x=>x.work_id),chosen===1?['W1']:['W1','W2']);
 }
 // The persisted selected scope filters historical approvals during refresh.
 const gateCode=admin.slice(admin.indexOf(' async function refreshGate(){'),admin.indexOf(' function updateSidebarIdentity'));
 let loaded;const gate={actor:'원이정',PERSON_IDS:{'원이정':'WON'},showGate(){},activeWorkIds:()=>['W2'],setActiveWorkIds(){},load:async()=>[{workId:'W1',requesterId:'WON',status:'approved'},{workId:'W2',requesterId:'WON',status:'approved'}],window:{loadApprovedHandovers:async ids=>loaded=ids},PROJECTS:[{id:'W2'}],render(){},message(e){throw Error(e)}};
 vm.runInNewContext(gateCode,gate);await gate.refreshGate();assert.equal(loaded.length,1);assert.equal(loaded[0],'W2');
 // One press executes approval; repeated clicks during a request do not duplicate it.
 const verify=admin.slice(admin.indexOf(' const approvalInFlight='),admin.indexOf('  async function decide(id,status)'));
 let count=0,finish;const verifyContext={el:()=>({querySelectorAll:()=>[]}),decide:async()=>{count++;await new Promise(r=>finish=r)}};
 vm.runInNewContext(verify,verifyContext);const first=verifyContext.verify('request');await verifyContext.verify('request');assert.equal(count,1);finish();await first;
 // Display grammar preserves actor labels, future intent and negative polarity.
 const nominal=html.slice(html.indexOf('function nominalizeTimelineText('),html.indexOf('function timelineItems('));const grammar={};vm.runInNewContext(nominal,grammar);
 for(const [input,expected] of [['김지수 · 국내 인증 수치를 확정하다','김지수 · 국내 인증 수치를 확정'],['확인되는 대로 연락하다','확인되는 대로 연락'],['원고를 수정하고 있습니다.','원고를 수정 중'],['자료를 공유할 예정입니다.','자료를 공유 예정'],['자료를 배포하지 않다','자료를 배포하지 않음'],['원고를 확정해야 합니다','원고를 확정 필요']])assert.equal(grammar.nominalizeTimelineText(input),expected);
 // Dependency node is above selected Task; fifth participant is below it.
 const graphCode=demo.slice(demo.indexOf('    renderPeopleGraph = function(t)'),demo.indexOf('    const openTaskIds='));
 const task={name:'Selected'},graph={TASKS:{T1:task},participantLinks:[],deps:[{source_id:'T1',target_id:'T2'}],taskMap:new Map([['T2',{title:'Prerequisite'}]]),peopleMap:new Map(),html:String,shortText:String};
 vm.runInNewContext(graphCode,graph);const svg=graph.renderPeopleGraph(task);assert(svg.includes('y="74" text-anchor="middle">선행 Task'));assert(svg.includes('y="244" text-anchor="middle">선택한 Task'));assert(svg.includes('M 375 203 L 375 87'));
 console.log('PASS: 1/N Work requests, historical approval isolation, single-click approval, noun endings, dependency position');
})().catch(error=>{console.error(error);process.exitCode=1});
