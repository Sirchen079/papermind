import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

function sourceUrl(code){return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');}
function compile(path){return ts.transpileModule(readFileSync(new URL(path,import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;}
const errorModel=sourceUrl(compile('../src/pages/apiErrorModel.ts'));
const apiModule=await import(sourceUrl(compile('../src/api.ts').replace('"./pages/apiErrorModel"',JSON.stringify(errorModel))));
const researchModule=await import(sourceUrl(compile('../src/researchApi.ts').replace("'./pages/apiErrorModel'",JSON.stringify(errorModel))));
const wikiModule=await import(sourceUrl(compile('../src/wikiApi.ts').replace("'./pages/apiErrorModel'",JSON.stringify(errorModel))));

test('late callbacks, streams and research requests retain their originating workspace',async()=>{
  const urls=[];
  const original=globalThis.fetch;
  let finishA;
  globalThis.fetch=async url=>{
    urls.push(url);
    if(url.endsWith('/stream'))return new Response('event: done\ndata: {"content":"A"}\n\n');
    if(url==='/api/w/a/papers?limit=50&offset=0')return new Promise(resolve=>{finishA=()=>resolve(Response.json({items:[],total:0}));});
    return Response.json([]);
  };
  try{
    const a=apiModule.createApi('/api/w/a');
    const b=apiModule.createApi('/api/w/b');
    // Keep an A callback alive while B is used for the foreground workspace.
    const delayed=a.listPapers(50,0).then(()=>a.createConversation());
    await b.createConversation();
    assert.ok(finishA,'paper request must have started before the switch');
    finishA();await delayed;
    for await(const frame of a.streamMessage(1,'Question'))assert.equal(frame.data.content,'A');
    await researchModule.createResearchApi('/api/w/a').get('same-id');
    await wikiModule.createWikiApi('/api/w/a').get('same-id');
    assert.deepEqual(urls,[
      '/api/w/a/papers?limit=50&offset=0',
      '/api/w/b/chat/conversations',
      '/api/w/a/chat/conversations',
      '/api/w/a/chat/conversations/1/messages/stream',
      '/api/w/a/research/tasks/same-id',
      '/api/w/a/wiki/pages/same-id',
    ]);
  }finally{globalThis.fetch=original;}
});
