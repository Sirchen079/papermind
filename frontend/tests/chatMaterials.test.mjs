import {test} from 'node:test';
import assert from 'node:assert/strict';
import {appendPageAttachment} from '../.tmp_graph_test_dist/chatMaterialsModel.js';

const page=(n=7,image='one')=>({name:'page.png',kind:'image',data_url:image,paper_page:{paper_id:367,page:n,pdf_sha256:'pdf',image_sha256:image}});
test('adding an original page retains existing attachments, queue and selected workflow',()=>{
  const note=Object.freeze({name:'note.md',kind:'text',data_url:'',text:'manual correction'});
  const queue=Object.freeze([{id:'pending',text:'earlier question'}]);
  const prior=Object.freeze({attachments:Object.freeze([note]),queue,workflow:'review-revision'});
  const item=Object.freeze(page());
  const result=appendPageAttachment(prior,item);
  assert.deepEqual(result.attachments,[note,item]);
  assert.equal(result.queue,queue);assert.equal(result.workflow,'review-revision');
  assert.equal(prior.attachments.length,1);
});
test('repeated carry action deduplicates the exact page snapshot; changed pages or PDFs remain distinct',()=>{
  const original=page();const prior={attachments:[original],queue:[]};
  assert.equal(appendPageAttachment(prior,{...original,name:'renamed'}),prior);
  assert.equal(appendPageAttachment(prior,page(8)).attachments.length,2);
  assert.equal(appendPageAttachment(prior,page(7,'changed-image')).attachments.length,2);
  assert.equal(appendPageAttachment(prior,{...original,paper_page:{...original.paper_page,pdf_sha256:'new-pdf'}}).attachments.length,2);
});
test('capacity failure leaves every draft item intact, while an exact duplicate still succeeds',()=>{
  const prior=Object.freeze({attachments:Object.freeze([page(1),page(2),page(3),page(4)]),queue:[]});
  assert.throws(()=>appendPageAttachment(prior,page(5)),/4 个附件/);
  assert.equal(prior.attachments.length,4);
  assert.equal(appendPageAttachment(prior,page(4)),prior);
  assert.throws(()=>appendPageAttachment(prior,{kind:'text',data_url:''}),/原页图片/);
});
