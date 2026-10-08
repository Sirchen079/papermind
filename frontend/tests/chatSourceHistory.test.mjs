import {test} from 'node:test';
import assert from 'node:assert/strict';
import {paperSourceHistory} from '../.tmp_graph_test_dist/chatSourceHistoryModel.js';

test('a later saved comparison can reopen earlier method pages without presenting them as current reading',()=>{
 const method={paper_id:245,source_type:'full_text',snippet:'RIND',excerpt:'Method conditions',pages:[3,4]};
 const overview={...method,excerpt:'Overview',pages:[1]};
 const messages=[{id:10,sources:[method]},{id:11,sources:[method]},{id:12,sources:[overview]},{id:13,sources:[{...method,excerpt:'Future reading',pages:[8]}]}];
 const result=paperSourceHistory(messages,12,245);
 assert.deepEqual(result,{current:[overview],earlier:[method]});
 assert.equal(messages[0].sources[0],method);
 assert.deepEqual(paperSourceHistory(messages,10,245),{current:[method],earlier:[]});
});

test('current carry wins duplicates while older versions and other locations stay separately readable',()=>{
 const a={paper_id:1,source_type:'full_text',snippet:'same opening',excerpt:'original',pages:[2]};
 const b={...a,excerpt:'updated'};
 const c={...a,pages:[3]};
 const wrongPaper={...a,paper_id:2};
 const carried={...b,carried_from_message:4};
 const messages=[{id:1,sources:[a,b,c,wrongPaper]},{id:2,sources:[carried]}];
 assert.deepEqual(paperSourceHistory(messages,2,1),{current:[carried],earlier:[a,c]});
 assert.deepEqual(paperSourceHistory(messages,99,1),{current:[],earlier:[]});
 assert.deepEqual(paperSourceHistory(messages,2,99),{current:[],earlier:[]});
});

test('an old short source and a citation with only historical sources remain available',()=>{
 const old={paper_id:1,snippet:'legacy short quote'};
 const messages=[{id:1,sources:[old]},{id:2}];
 assert.deepEqual(paperSourceHistory(messages,2,1),{current:[],earlier:[old]});
 assert.deepEqual(paperSourceHistory([],2,1),{current:[],earlier:[]});
});
