import test from 'node:test';
import assert from 'node:assert/strict';
import {parseGuide,nextLesson,LESSONS} from '../.tmp_graph_test_dist/onboardingModel.js';

test('new empty installation gets a welcome, existing library is not interrupted',()=>{
  assert.equal(parseGuide(null,0).status,'welcome');
  assert.equal(parseGuide(null,12).status,'paused');
});
test('saved skipped and completed choices survive an empty library and restart',()=>{
  for(const status of ['paused','completed'])assert.equal(parseGuide(JSON.stringify({version:1,status,step:3}),0).status,status);
});
test('resume preserves the current lesson and rejects corrupt or unsupported state',()=>{
  assert.equal(parseGuide(JSON.stringify({version:1,status:'active',step:4}),8).step,4);
  for(const raw of ['{','null','{"version":2,"status":"active","step":1}','{"version":1,"status":"active","step":99}'])assert.equal(parseGuide(raw,8).status,'paused');
});
test('last lesson finishes without an out-of-range step, prior lessons advance',()=>{
  assert.deepEqual(nextLesson({version:1,status:'active',step:0}),{version:1,status:'active',step:1});
  assert.deepEqual(nextLesson({version:1,status:'active',step:LESSONS.length-1}),{version:1,status:'completed',step:LESSONS.length-1});
});
test('first action goes directly to PDF import, and sample research does not start a run',()=>{
  assert.deepEqual(LESSONS[0].target,{page:'library',params:{import:'pdf'}});
  assert.equal(LESSONS[3].target.page,'research');
  assert.ok(LESSONS[3].target.params.question);
  assert.equal(LESSONS[3].target.params.run,undefined);
});
