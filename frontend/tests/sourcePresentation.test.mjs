import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupPaperSources,groupWebSources,materialLabel,materialKind,researchScopeKind} from '../.tmp_graph_test_dist/sourcePresentationModel.js';

test('read passages are prominent while search-only candidates remain accessible',()=>{
  const discovery={paper_id:1,title:'Read paper',source_type:'metadata',retrieved_by:'search_library',snippet:'abstract'};
  const other={...discovery,paper_id:2,title:'Candidate'};
  const original={...discovery,source_type:'full_text',pages:[11],excerpt:'Assumes no noise'};
  const inputs=[Object.freeze(discovery),Object.freeze(other),Object.freeze(original)];
  const before=JSON.stringify(inputs);const grouped=groupPaperSources(inputs);
  assert.deepEqual(grouped.map(g=>[g.key,g.papers.map(p=>p.paper_id)]),[['original_text',[1]],['abstract_metadata',[2]]]);
  assert.deepEqual(grouped[0].papers[0].sources,[discovery,original]);
  assert.equal(JSON.stringify(inputs),before);
});
test('saved candidate rereads retain their original kind and historical unknowns are not promoted',()=>{
  assert.equal(materialKind({source_type:'metadata',retrieved_by:'read_saved_document',material_kind:'discovery'}),'discovery');
  assert.equal(materialKind({source_type:'summary',retrieved_by:'get_paper'}),'abstract_metadata');
  assert.equal(materialKind({source_type:'saved_excerpt'}),'unknown');
  assert.equal(materialLabel({source_type:'generated_analysis'}),'AI 生成的论文分析');
  assert.equal(materialLabel({source_type:'excerpt'}),'个人摘录');
  assert.equal(researchScopeKind('excerpt'),'research_record');
  assert.equal(researchScopeKind('full_text_span'),'original_text');
  assert.equal(researchScopeKind('abstract'),'abstract_metadata');
  assert.equal(researchScopeKind('unknown_scope'),'unknown');
});
test('web search records and metadata are not presented as article passages',()=>{
  const query={source_type:'web',material_kind:'discovery',excerpt:'zero results'};
  const metadata={source_type:'web',content_region:'scholarly_metadata'};
  const page={source_type:'web',material_kind:'webpage'};
  const groups=groupWebSources([query,metadata,page]);
  assert.deepEqual(groups.map(g=>[g.key,g.sources]),[['content',[page]],['discovery',[query,metadata]]]);
  assert.deepEqual(groupPaperSources([]),[]);assert.deepEqual(groupWebSources([]),[]);
});
