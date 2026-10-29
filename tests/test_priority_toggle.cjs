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
assert(adapter.includes("<span>후속 업무</span>"));
assert(adapter.includes("window.linkingSetTaskPriorityFilter=(key,value)=>"));
assert(adapter.includes("후속 업무 많은 순"));
assert(adapter.includes("roleAssignments"));
assert(adapter.includes("a.rank-b.rank"));
assert(adapter.includes("b.score-a.score"));
assert(!adapter.includes("linkingSelectedPriorityTaskId"));
assert(html.includes('demo_adapter.js?v=20261029-priority-role-filter-sort'));

console.log('PASS: Work/Task toggle, handover roles, downstream counts, filters, sorting, pagination');
