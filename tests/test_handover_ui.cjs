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
  const posts=[],context={IMPORT_DATA:{'김지수':rows},importState:{person:'김지수',selected:new Set(chosen===1?['W1::A','W1::B']:['W1::A','W1::B','W2::C'])},PERSON_IDS:{'원이정':'WON','김지수':'KIM'},actor:'원이정',catalogLoading:false,importWorkKeys:g=>g.tasks.map(t=>g.workId+'::'+t),el:()=>({disabled:false}),setActiveWorkIds(ids){context.active=ids},load:async()=>[],api:async(path,method,data)=>{posts.push({path,method,data});return {created:data.work_ids.length}},updateInboxBadge(){},renderImportFlow(){},refreshGate:async()=>{},message(){}};
  vm.runInNewContext(selectedCode+requestCode,context);await context.requestImportApproval();
  assert.equal(posts.length,1);assert.equal(posts[0].path,'/bulk');assert.deepEqual(posts[0].data.work_ids,chosen===1?['W1']:['W1','W2']);
 }
 // Refresh restores all approved Work grants, including those approved on another device.
 const gateCode=admin.slice(admin.indexOf(' async function refreshGate(){'),admin.indexOf(' function updateSidebarIdentity'));
 let loaded;const gate={actor:'원이정',PERSON_IDS:{'원이정':'WON'},showGate(){},activeWorkIds:()=>['W2'],setActiveWorkIds(){},load:async()=>[{workId:'W1',requesterId:'WON',status:'approved'},{workId:'W2',requesterId:'WON',status:'approved'}],window:{loadApprovedHandovers:async ids=>loaded=ids},PROJECTS:[{id:'W2'}],render(){},message(e){throw Error(e)}};
 vm.runInNewContext(gateCode,gate);await gate.refreshGate();assert.deepEqual(Array.from(loaded),['W1','W2']);
 // Cached Work cards remain available while the latest catalog loads; stale responses cannot overwrite a new source.
 const catalogCode=admin.slice(admin.indexOf(' const catalogCache='),admin.indexOf(' async function received()'));
 let resolveCatalog;
 const nodes=new Map();
 const node=id=>{if(!nodes.has(id))nodes.set(id,{classList:{remove(){},add(){}},textContent:'',innerHTML:'',disabled:false});return nodes.get(id)};
 const catalog={AbortController,setTimeout,clearTimeout,PERSON_IDS:{'김지수':'KIM'},IMPORT_DATA:{'김지수':[{workId:'W1',project:'One',tasks:['A']}]},importState:{selected:new Set()},window:{},safe:String,el:node,selectImportPerson(name){catalog.importState.person=name},importWorkKeys:g=>g.tasks.map(t=>g.workId+'::'+t),renderImportTasks(){},renderImportFlow(){},fetch:()=>new Promise(r=>resolveCatalog=r)};
 vm.runInNewContext(catalogCode,catalog);const pendingCatalog=catalog.selectCatalogPerson('김지수');
 assert.equal(catalog.IMPORT_DATA['김지수'].length,1);assert.equal(node('import-action-btn').disabled,true);
 resolveCatalog({ok:true,json:async()=>({works:[{work_id:'W1',title:'One',tasks:[{title:'A'}]},{work_id:'W2',title:'Two',tasks:[{title:'B'}]}]})});await pendingCatalog;
 assert.equal(catalog.IMPORT_DATA['김지수'].length,2);assert.equal(node('import-action-btn').disabled,false);assert.equal(node('import-catalog-status').textContent,'Work 2개');
 catalog.fetch=async()=>({ok:false,status:503});await catalog.selectCatalogPerson('김지수');
 assert.equal(catalog.IMPORT_DATA['김지수'].length,2);assert(node('import-catalog-status').innerHTML.includes('다시 불러오기'));
 // One press executes approval; repeated clicks during a request do not duplicate it.
 const verify=admin.slice(admin.indexOf(' const approvalInFlight='),admin.indexOf('  async function decide(id,status)'));
 let count=0,finish;const verifyContext={el:()=>({querySelectorAll:()=>[]}),decide:async()=>{count++;await new Promise(r=>finish=r)}};
 vm.runInNewContext(verify,verifyContext);const first=verifyContext.verify('request');await verifyContext.verify('request');assert.equal(count,1);finish();await first;
 // Bulk approval submits the displayed rows once and reports rows processed elsewhere.
 const approvalButton={disabled:false,textContent:'전체 승인하기 (2건)'};
 const requests=[],messages=[];
 let finishBulk,refreshed=0;
 const bulkContext={actor:'김지수',PERSON_IDS:{'김지수':'KIM'},verifiedMode:false,
  api:(path,method,body)=>{requests.push({path,method,body});return new Promise(resolve=>{finishBulk=resolve})},
  inbox:async()=>{refreshed++},message:value=>messages.push(value),decide:async()=>{throw Error('Unexpected individual approval')}
 };
 vm.runInNewContext(verify,bulkContext);
 const visibleRequests=[{id:'one'},{id:'two'}];
 const bulk=bulkContext.approveAll(visibleRequests,approvalButton);
 assert(approvalButton.disabled);
 await bulkContext.approveAll(visibleRequests,approvalButton);
 await bulkContext.verify('one');
 assert.equal(requests.length,1);
 assert.equal(requests[0].path,'/bulk-decision');
 assert.deepEqual(requests[0].body.request_ids,['one','two']);
 finishBulk({approved:1,skipped:1});await bulk;
 assert(!approvalButton.disabled);assert.equal(refreshed,1);
 assert(messages[0].includes('1건 승인 완료'));assert(messages[0].includes('1건 제외'));
 // Display grammar preserves actor labels, future intent and negative polarity.
 const nominal=html.slice(html.indexOf('function nominalizeTimelineText('),html.indexOf('function timelineItems('));const grammar={};vm.runInNewContext(nominal,grammar);
 for(const [input,expected] of [['김지수 · 국내 인증 수치를 확정하다','김지수 · 국내 인증 수치를 확정'],['확인되는 대로 연락하다','확인되는 대로 연락'],['원고를 수정하고 있습니다.','원고를 수정 중'],['자료를 공유할 예정입니다.','자료를 공유 예정'],['자료를 배포하지 않다','자료를 배포하지 않음'],['원고를 확정해야 합니다','원고를 확정 필요']])assert.equal(grammar.nominalizeTimelineText(input),expected);
 // Dependency node is above selected Task; fifth participant is below it.
 const graphCode=demo.slice(demo.indexOf('    renderPeopleGraph = function(t)'),demo.indexOf('    const openTaskIds='));
 const task={name:'Selected'},graph={TASKS:{T1:task},participantLinks:[],deps:[{source_id:'T1',target_id:'T2'}],taskMap:new Map([['T2',{title:'Prerequisite'}]]),peopleMap:new Map(),html:String,shortText:String};
 vm.runInNewContext(graphCode,graph);const svg=graph.renderPeopleGraph(task);assert(svg.includes('y="74" text-anchor="middle">선행 Task'));assert(svg.includes('y="244" text-anchor="middle">선택한 Task'));assert(svg.includes('M 375 203 L 375 87'));
 console.log('PASS: 1/N Work requests, restored approval scope, single-click and bulk approval, noun endings, dependency position');
})().catch(error=>{console.error(error);process.exitCode=1});
