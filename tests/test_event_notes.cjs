const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const adapter = fs.readFileSync('frontend/demo_adapter.js', 'utf8');
const index = fs.readFileSync('frontend/index.html', 'utf8');
const start = adapter.indexOf('  const notesForEvents = ');
const helper = adapter.slice(start, adapter.indexOf('\n  }));', start) + '\n  }));'.length);
const notesForEvents = vm.runInNewContext(helper + '\nnotesForEvents', {});
const notes = notesForEvents([
  {event_id: 'E1', slack_ts: '1791288266.432589', memo: null},
  {event_id: 'E2', slack_ts: '1791288886.674539', memo: ' 해당 원고 기준으로 준비 ', action: '딜러 배포 자료 준비'},
]);
assert.equal(notes.length, 1);
assert.equal(notes[0].text, '해당 원고 기준으로 준비');

const renderCode = index.slice(index.indexOf('function renderEventNotes('), index.indexOf('function renderDetail('));
const context = {escSvg: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')};
vm.runInNewContext(renderCode, context);
assert.match(context.renderEventNotes({notes}), /해당 원고 기준으로 준비/);
assert.match(context.renderEventNotes({notes: []}), /등록된 유의사항이 없습니다/);
assert.match(context.renderEventNotes({notes: [{text: '<script>', slackTs: null}]}), /&lt;script&gt;/);
assert.match(index, /id:'notes',label:'유의사항'/);
console.log('PASS: Event memo appears in the 유의사항 tab');
