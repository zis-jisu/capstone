const fs=require('fs'),vm=require('vm'),assert=require('assert');
const index=fs.readFileSync('frontend/index.html','utf8'),adapter=fs.readFileSync('frontend/demo_adapter.js','utf8');
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const component=index.slice(index.indexOf('function renderRelatedContacts('),index.indexOf('function renderDetail('));
const context={escSvg:escape};vm.runInNewContext(component,context);
const content=context.renderRelatedContacts({contacts:[{name:'관련자',team:'Marketing',email:'test@example.com',phone_number:'010-0000-0000'}]});
assert(content.includes('test@example.com'));assert(content.includes('010-0000-0000'));assert(content.includes('Marketing'));assert(content.includes('mailto:'));assert(content.includes('tel:'));
assert(context.renderRelatedContacts({contacts:[{name:'<script>',team:'Sales'}]}).includes('&lt;script&gt;'));
assert(context.renderRelatedContacts({contacts:[{name:'미등록'}]}).includes('미등록'));
assert(index.indexOf("{id:'contacts'")>index.indexOf("{id:'people'"));
// Related people are scoped to the selected Task and its Events, deduplicated by ID.
const start=adapter.indexOf('      const eventIds=new Set(evs'),end=adapter.indexOf('      const next =',start);
const related={id:'T1',evs:[{event_id:'E1',speaker_id:'AUTHOR'}],edges:[{source_type:'Person',source_id:'KIM',target_id:'T1'},{source_type:'Person',source_id:'KIM',target_id:'T1'},{source_type:'Person',source_id:'OTHER',target_id:'TO'}],peopleMap:new Map([['KIM',{name:'김지수'}],['AUTHOR',{name:'작성자'}],['OTHER',{name:'다른 업무'}]])};
vm.runInNewContext(adapter.slice(start,end)+';globalThis.result=contacts;',related);assert.equal(related.result.length,2);assert(!related.result.some(x=>x.name==='다른 업무'));
// Person node metadata shows the department; relationship labels remain on edges.
const graph=adapter.slice(adapter.indexOf('    renderPeopleGraph = function(t)'),adapter.indexOf('    const openTaskIds='));
const task={name:'선택 업무'},graphContext={TASKS:{T1:task},participantLinks:[{source_id:'KIM',target_id:'T1',relation:'OWNER'}],deps:[],taskMap:new Map(),peopleMap:new Map([['KIM',{name:'김지수',team:'Marketing'}]]),html:escape,shortText:String};
vm.runInNewContext(graph,graphContext);const svg=graphContext.renderPeopleGraph(task);const person=svg.match(/<g class="graph-node person">[\s\S]*?<\/g>/)[0];assert(person.includes('Marketing'));assert(!person.includes('OWNER'));
console.log('PASS: contact fields, missing values, safe rendering, selected-Task scope, department-only person metadata');
