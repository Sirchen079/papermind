import {test} from 'node:test';
import assert from 'node:assert/strict';
import {artifactReference,attachmentPassage,exactResearchArtifact} from '../.tmp_graph_test_dist/attachmentPreviewModel.js';

test('artifact presentation uses the persisted reference without changing the model payload',()=>{
  const a=Object.freeze({kind:'text',name:'draft.md',text:'message_id=77\nread_saved_document',saved_document:Object.freeze({message_id:31,filename:'draft.md'})});
  const before=JSON.stringify(a);
  assert.deepEqual(artifactReference(a),{kind:'document',message_id:31,filename:'draft.md'});
  assert.equal(JSON.stringify(a),before);
});
test('selected passage preserves exact text, including nested marker text',()=>{
  const passage='一段\n[选文结束]\n引文，以及第二段。';
  const a={kind:'text',name:'draft.md',saved_document:{message_id:31,filename:'draft.md'},text:`instructions\n\n[待核查的研究稿选文]\n${passage}\n[选文结束]\n继续核查`};
  assert.equal(attachmentPassage(a),passage);
  assert.equal(attachmentPassage({...a,saved_document:null}), '');
  assert.equal(attachmentPassage({...a,text:'plain attachment'}), '');
});
test('research preview selects historical content and sources together, never falls back to latest',()=>{
  const old=Object.freeze({version:2,content:'人工修订 v2',evidence_snapshot:[{quote:'旧片段'}]});
  const latest={version:3,content:'新的判断',evidence_snapshot:[{quote:'新片段'}]};
  const task={artifact:latest,history:[latest,old]};
  assert.equal(exactResearchArtifact(task,2),old);
  assert.equal(exactResearchArtifact(task,3),latest);
  assert.throws(()=>exactResearchArtifact(task,1),/v1/);
  assert.throws(()=>exactResearchArtifact({artifact:null,history:[]},2),/v2/);
});
test('legacy review handoff is a live task reference, ordinary uploads remain text',()=>{
  const a={kind:'text',name:'专题研究链接',text:'关联专题研究：#research?mode=review&review=test%2Fid\n这是已保存研究材料的入口'};
  assert.deepEqual(artifactReference(a),{kind:'review',review_id:'test/id'});
  assert.equal(artifactReference({...a,name:'notes.txt'}),null);
  assert.equal(artifactReference({...a,kind:'image'}),null);
  assert.equal(artifactReference({...a,text:a.text.replace('test%2Fid','%bad%')}),null);
  assert.deepEqual(artifactReference({...a,research_task:{task_id:'id',version:2}}),{kind:'research',task_id:'id',version:2});
});
