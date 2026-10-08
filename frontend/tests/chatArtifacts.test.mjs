import {test} from 'node:test';
import assert from 'node:assert/strict';
import {savedArtifacts} from '../.tmp_graph_test_dist/chatArtifactsModel.js';
test('successful saved research remains readable even when final answer only acknowledges it',()=>{
 const step={name:'save_paper_note',ok:true,args:{content:'完整比较与修改稿 [P38]'},result:JSON.stringify({ok:true,id:1,paper_id:38})};
 assert.deepEqual(savedArtifacts([step,step]),[{key:'save_paper_note:1',title:'已保存的论文笔记',content:step.args.content,paperId:38,downloadUrl:undefined}]);
 assert.equal(savedArtifacts([{...step,ok:false}]).length,0);
 assert.equal(savedArtifacts([{...step,result:'tool failed'}]).length,0);
 assert.equal(savedArtifacts([{...step,result:'null'}]).length,0);
});
test('document previews retain full text and only link to the local document endpoint',()=>{
 const step={name:'save_document',ok:true,args:{content:'original\n'.repeat(5000)},result:JSON.stringify({ok:true,filename:'draft.md',download_url:'/api/w/project/chat/documents/draft.md'})};
 const [artifact]=savedArtifacts([step]);assert.equal(artifact.content,step.args.content);
 assert.equal(artifact.downloadUrl,'/api/w/project/chat/documents/draft.md');
 const [invalid]=savedArtifacts([{...step,result:JSON.stringify({ok:true,filename:'draft.md',download_url:'https://example.test/draft'})}]);
 assert.equal(invalid.downloadUrl,undefined);
});

test('skill diagnostics remain visible on a failed content audit and are not editable documents',()=>{
 const id='a'.repeat(32),url=`/api/w/project/builtin-skills/runs/${id}/files/report.md`;
 const result={ok:true,run_id:id,action:'audit',audit_pass:false,paper_id:38,summary_md:'2 errors; original preserved',artifacts:[{name:'report.md',download_url:url}]};
 const [item]=savedArtifacts([{name:'audit_paper_card',ok:true,args:{note_id:1},result:JSON.stringify(result)}]);
 assert.equal(item.diagnostic,true);assert.equal(item.downloadUrl,url);assert.equal(item.filename,undefined);
 assert.equal(item.content,result.summary_md);assert.equal(item.paperId,38);
 result.ok=false;result.summary_md='script unavailable';result.artifacts[0].download_url='https://outside.invalid';
 const [failed]=savedArtifacts([{name:'audit_paper_card',ok:true,args:{},result:JSON.stringify(result)}]);
 assert.equal(failed.content,'script unavailable');assert.equal(failed.downloadUrl,undefined);
});
