import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/pages/activityModel.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {observeActivity,emptyActivity}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('background completion stays associated with origin project and survives a reload',()=>{
  const running={key:'a:wiki:same-id',active:true,stamp:'1:running'};
  const existing={key:'b:wiki:same-id',active:false,stamp:'0:done'};
  let state=observeActivity(emptyActivity,[running,existing]);
  assert.deepEqual(state.unread,[]);
  state=observeActivity(JSON.parse(JSON.stringify(state)),[{...running,active:false,stamp:'2:done'},existing]);
  assert.deepEqual(state.unread,['a:wiki:same-id']);
  state=observeActivity(state,[{...running,active:true,stamp:'3:running'},existing]);
  assert.deepEqual(state.unread,[]);
});
