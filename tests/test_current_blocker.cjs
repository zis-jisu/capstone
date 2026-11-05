const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const code = fs.readFileSync('frontend/demo_adapter.js', 'utf8');
const start = code.indexOf('  const pendingDependencyTitles = ');
const end = code.indexOf('\n', code.indexOf('.map(task => task.title).filter(Boolean))];', start));
assert(start >= 0 && end > start);
const pending = vm.runInNewContext(code.slice(start, end) + '\npendingDependencyTitles', {});
const edges = [{source_id: 'TASK-00080', target_id: 'TASK-00079'},
               {source_id: 'TASK-00080', target_id: 'TASK-00078'}];
const tasks = new Map([
  ['TASK-00079', {title: '국내용 원고 제목·CTA 확정', status: 'in_progress'}],
  ['TASK-00078', {title: '국내 사양·기술 표현 검증', status: 'completed'}],
]);
assert.deepEqual(Array.from(pending('TASK-00080', edges, tasks)), ['국내용 원고 제목·CTA 확정']);
assert.doesNotMatch(code, /blocker:html\(explicitBlocker\|\|prereqs\[0\]/);
const latestLine = code.split('\n').find(line => line.includes('const latestEventPrerequisite = '));
const latest = vm.runInNewContext(latestLine + '\nlatestEventPrerequisite', {});
assert.equal(latest([
  {slack_ts: '1791288266.432589', prerequisite: '국내 인증 수치 확정'},
  {slack_ts: '1791289493.798879', prerequisite: 'UTM 링크와 배포 대상 목록 정리 완료'},
]), 'UTM 링크와 배포 대상 목록 정리 완료');
console.log('PASS: completed historical prerequisite is not a current blocker');
