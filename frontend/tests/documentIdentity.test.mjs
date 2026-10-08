import {test} from 'node:test';
import assert from 'node:assert/strict';
import {chatTurnIdentity,documentIdentityLabel,documentReferenceText} from '../.tmp_graph_test_dist/documentIdentityModel.js';

test('explicit unadopted audit stays distinct from human corrections throughout handoff',()=>{
  const doc=Object.freeze({message_id:69,filename:'reviewed.md',author:'user',audit_author:'Codex',adoption_status:'not_user_adopted'});
  assert.equal(documentIdentityLabel(doc),'Codex 修订稿 · 尚未采用');
  const text=documentReferenceText(doc);
  assert.match(text,/message_id=69\nfilename=reviewed.md/);
  assert.match(text,/Codex 修订稿 · 尚未采用/);
  assert.doesNotMatch(text,/人工修订|你采用|停止|审批/);
  assert.match(text,/继续研究/);
});

test('saved answers, accepted suggestions, manual edits and named authors keep separate identities',()=>{
  assert.equal(documentIdentityLabel({author:'user',capture_message_id:3}),'AI 回答原样保存');
  assert.equal(documentIdentityLabel({revision_kind:'saved_answer'}),'AI 回答原样保存');
  assert.equal(documentIdentityLabel({revision_kind:'accepted_suggestion'}),'已采用的修订稿');
  assert.equal(documentIdentityLabel({parent_filename:'first.md'}),'人工修订稿');
  assert.equal(documentIdentityLabel({author:'assistant'}),'AI 保存的研究稿');
  assert.equal(documentIdentityLabel({author:'user',audit_author:'张老师'}),'张老师 修订稿');
  assert.equal(documentIdentityLabel({adoption_status:'not_user_adopted'}),'修订草稿 · 尚未采用');
});

test('chat turns show the writer and adoption state of saved research artifacts',()=>{
  assert.deepEqual(chatTurnIdentity('user',{audit_author:'Codex',adoption_status:'not_user_adopted'}),
    {label:'Codex 修订稿 · 尚未采用',avatar:'C',own:false});
  assert.deepEqual(chatTurnIdentity('user',{revision_kind:'saved_answer'}),
    {label:'AI 回答存档',avatar:'AI',own:false});
  assert.deepEqual(chatTurnIdentity('user',{revision_kind:'accepted_suggestion'}),
    {label:'你',avatar:'你',own:true});
  assert.deepEqual(chatTurnIdentity('assistant'),
    {label:'研究助手',avatar:'AI',own:false});
});
