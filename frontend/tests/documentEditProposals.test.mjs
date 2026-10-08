import test from 'node:test';
import assert from 'node:assert/strict';
import {documentEditProposals} from '../.tmp_graph_test_dist/chatArtifactsModel.js';

const id='a'.repeat(32);
const step={name:'propose_document_edit',ok:true,args:{message_id:7,filename:'notes.md',before:'**Before**',after:'',reason:'Remove the unsupported sentence.'},
 result:JSON.stringify({ok:true,kind:'document_edit_proposal',applied:false,proposal_id:id,source_message_id:7,filename:'notes.md'})};

test('deletion proposal retains its exact source and is not duplicated by repeated events',()=>{
 assert.deepEqual(documentEditProposals([step,step]),[{id,filename:'notes.md',sourceMessageId:7,before:'**Before**',after:'',reason:'Remove the unsupported sentence.'}]);
});

test('failed, truncated, mismatched and unrelated tool results cannot become adoptable edits',()=>{
 const result=JSON.parse(step.result);
 const variants=[{...step,ok:false},{...step,name:'save_document'},{...step,result:step.result.slice(0,-3)},
  {...step,result:'null'},{...step,result:JSON.stringify({...result,filename:'other.md'})},
  {...step,result:JSON.stringify({...result,source_message_id:8})},{...step,result:JSON.stringify({...result,applied:true})},
  {...step,args:{...step.args,before:''}}];
 assert.deepEqual(documentEditProposals(variants),[]);
});
