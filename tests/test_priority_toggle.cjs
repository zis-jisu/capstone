const fs = require('fs');
const assert = require('assert');

const adapter = fs.readFileSync('frontend/demo_adapter.js', 'utf8');
const html = fs.readFileSync('frontend/index.html', 'utf8');

assert(adapter.includes("window.linkingSetPriorityView=view=>"));
assert(adapter.includes(">Work 흐름</button>"));
assert(adapter.includes(">Task 우선순위</button>"));
assert(adapter.includes("const pageSize=5"));
assert(adapter.includes("Task 우선순위 페이지"));
assert(adapter.includes("data-priority-task-id"));
assert(adapter.includes("<span>Work | Task</span>"));
assert(adapter.includes("<span>인계자 역할</span>"));
assert(!adapter.includes("sortHeader('name','Work | Task')"));
assert(!adapter.includes("sortHeader('source','인계자')"));
assert(!adapter.includes("sortHeader('role','인계자 역할')"));
assert(!adapter.includes("sortHeader('status','상태')"));
assert(adapter.includes("window.linkingSetTaskPriorityFilter=(key,value)=>"));
assert(adapter.includes("window.linkingSetTaskPrioritySort=key=>"));
assert(adapter.includes("window.linkingToggleTaskPriorityFilter=()=>"));
assert(adapter.includes("filter_alt"));
assert(adapter.includes("data-task-priority-filter"));
assert(adapter.includes("linkingPriorityFilterDismissBound"));
assert(adapter.includes("filterOpen||filterCount"));
assert(adapter.includes("sortHeader('downstream','후속 업무')"));
assert(!adapter.includes("linkingSetTaskPriorityFilter(\\'source\\'"));
assert(adapter.includes("roleAssignments"));
assert(adapter.includes("a.rank-b.rank"));
assert(adapter.includes("b.score-a.score"));
assert(!adapter.includes("linkingSelectedPriorityTaskId"));
assert(html.includes('demo_adapter.js?v=20261029-filter-dismiss-sort-cleanup'));

console.log('PASS: source tabs, sortable columns, filter popover, roles, downstream counts, pagination');
