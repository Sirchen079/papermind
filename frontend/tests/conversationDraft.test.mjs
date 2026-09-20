import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function url(code){return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');}
function compile(path){return ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;}
const storageModel=url(compile('../src/pages/draftStorageModel.ts'));
const {readConversationContext:read,saveConversationContext:save,restoreConversationContext:restore}=await import(url(compile('../src/pages/conversationDraftModel.ts').replace("'./draftStorageModel'",JSON.stringify(storageModel))));

test('selected paper sets survive reload and cannot inherit a single-paper excerpt', () => {
  const data = new Map();
  const storage = {getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value)};
  const group = {paperId: 1, paperTitle: 'A', selectedText: null, papers: [{id: 1, title: 'A'}, {id: 2, title: 'B'}]};
  save(storage, 'group-app', 'A', 10, group);
  assert.deepEqual(read(storage, 'group-app', 'A', 10), group);
  assert.equal(read(storage, 'group-app', 'B', 10), null);
  assert.equal(restore({paperId: 1, paperTitle: 'A', selectedText: 'stale quote'}, group).selectedText, null);
  assert.deepEqual(restore(group, {...group, papers: [{id: 1, title: 'renamed A'}]}).papers, [{id: 1, title: 'renamed A'}]);
});

test('unsent excerpts survive switches and reloads with same IDs in separate projects',()=>{
  const data=new Map();
  const storage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)};
  const a={paperId:1,paperTitle:'A evidence',selectedText:'Excerpt A'};
  const b={paperId:1,paperTitle:'B evidence',selectedText:'Excerpt B'};
  save(storage,'app1','A',1,a);save(storage,'app1','B',1,b);
  assert.deepEqual(read(storage,'app1','A',1),a);
  assert.deepEqual(read(storage,'app1','B',1),b);
  assert.equal(read(storage,'app1','A',2),null);
  assert.equal(read(storage,'app2','A',1),null);
  save(storage,'app1','A',1,{...a,selectedText:null});
  assert.equal(read(storage,'app1','A',1).selectedText,null);
  assert.equal(read(storage,'app1','B',1).selectedText,'Excerpt B');
  assert.equal(restore(b,{paperId:2,paperTitle:'Changed material',selectedText:null}).selectedText,null);
  assert.equal(restore(b,null),null);
});

test('full storage retains excerpts through remounts; malformed saved data is ignored',()=>{
  const full={getItem:()=>null,setItem:()=>{throw new Error('Quota full');},removeItem:()=>{throw new Error('Quota full');}};
  const ctx={paperId:4,paperTitle:'Research',selectedText:'Keep this excerpt'};
  assert.equal(save(full,'full','A',1,ctx),false);
  assert.deepEqual(read(full,'full','A',1),ctx);
  assert.equal(read(full,'full','B',1),null);
  assert.equal(read({getItem:()=>'{broken'},'broken','A',1),null);
  assert.equal(read({getItem:()=>JSON.stringify({paperId:'1',paperTitle:null,selectedText:42})},'malformed','A',1),null);
});
