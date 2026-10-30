import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildResearchDeskGraph } from '../.tmp_graph_test_dist/researchDeskModel.js';

test('首页关系图只展示当前地图中已存在的主题分配，不将同专题论文视为互相支撑', () => {
  const result = buildResearchDeskGraph({
    themes: [{id:'a',name:'方法'}, {id:'b',name:'边界'}],
    papers: [{paper_id:1,title:'甲',themes:['a']}, {paper_id:2,title:'乙',themes:['b']}, {paper_id:3,title:'丙',themes:[]}],
    assignments: {'1':{themes:['a','a','unknown']}, '2':{themes:[]}, '999':{themes:['b']}},
  });
  assert.deepEqual(result.edges, [{themeId:'a',paperId:1}]);
  assert.deepEqual(result.papers.map(p=>p.paper_id), [1]);
  assert.equal(result.linkedPaperCount, 1);
  assert.equal(result.totalPaperCount, 3);
});

test('主题或分配尚未生成时返回空图，不补造关系', () => {
  assert.equal(buildResearchDeskGraph({themes:[],papers:[{paper_id:1,title:'甲',themes:[]}]}).edges.length, 0);
  assert.equal(buildResearchDeskGraph(null).papers.length, 0);
});

test('图中论文数和主题数受限，仍报告真实关联总数', () => {
  const result = buildResearchDeskGraph({themes:['a','b','c','d'].map(id=>({id,name:id})),papers:Array.from({length:20},(_,i)=>({paper_id:i+1,title:String(i),themes:['a','b','c','d'][i%4].split()}))});
  assert.equal(result.themes.length, 3);
  assert.equal(result.papers.length, 6);
  assert.equal(result.linkedPaperCount, 20);
  assert.equal(result.hiddenPaperCount, 14);
  for(const edge of result.edges) assert.ok(result.themes.some(t=>t.id===edge.themeId) && result.papers.some(p=>p.paper_id===edge.paperId));
});
