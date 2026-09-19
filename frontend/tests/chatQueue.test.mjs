import test from 'node:test';
import assert from 'node:assert/strict';
import { appendQueued, nextQueued, finishQueued } from '../.tmp_graph_test_dist/chatQueueModel.js';
const item = id => ({id, state:'waiting', text:id, extra:{model_config_id:2, attachments:[{name:'x'}]}});
test('multiple queued turns preserve FIFO and material snapshots', () => {
  const a=item('a'), b=item('b'); const queue=appendQueued(appendQueued([],a),b);
  assert.deepEqual(queue.map(q=>q.id),['a','b']);
  assert.equal(nextQueued(queue,false,false),a);
  assert.equal(nextQueued(finishQueued(queue,'a'),false,false),b);
  assert.equal(queue[0].extra.model_config_id,2);
});
test('paused, clarification, busy and uncertain acceptance block dispatch', () => {
  const queue=[item('a'), item('b')];
  assert.equal(nextQueued(queue,true,false),undefined);
  assert.equal(nextQueued(queue,false,true),undefined);
  assert.equal(nextQueued([{...queue[0],state:'sending'},queue[1]],false,false),undefined);
});
test('removal and late acknowledgement do not remove a different turn', () => {
  const queue=[item('a'),item('b'),item('c')];
  assert.deepEqual(finishQueued(queue,'b').map(q=>q.id),['a','c']);
  assert.deepEqual(finishQueued(finishQueued(queue,'a'),'a').map(q=>q.id),['b','c']);
});
test('queue limit preserves all existing entries', () => {
  const queue=Array.from({length:10},(_,i)=>item(String(i)));
  assert.throws(()=>appendQueued(queue,item('overflow')),/10/);
  assert.equal(queue.length,10);
});
