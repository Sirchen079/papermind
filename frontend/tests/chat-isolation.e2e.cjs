// Browser-side fixtures only: no real chat, deletion or model requests.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const base=process.env.PAPERMIND_TEST_BASE||'http://127.0.0.1:4289';
 assert.ok(['http://127.0.0.1:4289','http://127.0.0.1:4291'].includes(base));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],sent=[],aborted=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('requestfailed',r=>{if(r.url().endsWith('/messages/stream'))aborted.push(r.url());});
  const rows=new Map([[901,{id:901,title:'旧对话 A',messages:[{role:'user',content:'OLD_HISTORY_A',model:''}]}],[902,{id:902,title:'旧对话 B',messages:[{role:'user',content:'HISTORY_B',model:''}]}]]);
  let next=903,slowHistory=false,failHistory=false,creationDelay=0;
  if(process.env.PAPERMIND_TEST_DIST==='1')await page.route(base+'/',route=>route.fulfill({contentType:'text/html',body:fs.readFileSync(path.resolve(__dirname,'../dist/index.html'),'utf8')}));
  await page.route('**/api/settings',route=>route.fulfill({json:{getting_started_v1:JSON.stringify({version:1,status:'completed',step:5})}}));
  await page.route('**/api/chat/conversations**',async route=>{
   const req=route.request(),url=new URL(req.url()),match=url.pathname.match(/conversations\/(\d+)(.*)/);
   if(!match){if(req.method()==='POST'){await sleep(creationDelay);const row={id:next++,title:'新对话 '+(next-1),messages:[]};rows.set(row.id,row);return route.fulfill({json:row});}return route.fulfill({json:[...rows.values()]});}
   const id=Number(match[1]),tail=match[2],row=rows.get(id);
   if(tail==='/messages/stream'){
    const body=req.postDataJSON();sent.push({id,...body});
    if(body.content.startsWith('SLOW'))await sleep(1300);
    const content='ANSWER_'+body.content;
    if(row)row.messages.push({role:'user',content:body.content,model:''},{role:'assistant',content,model:'fixture'});
    return route.fulfill({contentType:'text/event-stream',body:`event: done\ndata: ${JSON.stringify({content,model:'fixture',sources:[]})}\n\n`}).catch(()=>{});
   }
   if(req.method()==='DELETE'){rows.delete(id);return route.fulfill({status:204});}
   if(id===901&&slowHistory)await sleep(800);
   if(id===901&&failHistory)return route.fulfill({status:500,body:'fixture load failure'});
   return route.fulfill({json:row});
  });
  await page.goto(base+'/#chat');
  const nav=page.locator('.conversation-list'),input=page.getByLabel('向论文库提问',{exact:true}),send=page.getByRole('button',{name:'发送',exact:true});
  const fresh=async()=>{await nav.getByRole('button',{name:'+ 新建对话',exact:true}).click();await page.getByText('想从哪篇论文聊起？',{exact:true}).waitFor();await page.waitForFunction(()=>{const el=document.querySelector('textarea[aria-label="向论文库提问"]');return el&&!el.disabled&&el.value==='';});};
  const select=title=>nav.getByRole('button',{name:title,exact:true}).click();
  await select('旧对话 A');await page.getByText('OLD_HISTORY_A',{exact:true}).waitFor();
  await input.fill('UNSENT_OLD_DRAFT');creationDelay=200;
  await nav.getByRole('button',{name:'+ 新建对话',exact:true}).dblclick();
  await page.getByText('想从哪篇论文聊起？',{exact:true}).waitFor();
  assert.equal(next,904,'Double click creates one conversation');assert.equal(await input.inputValue(),'');assert.equal(await page.getByText('OLD_HISTORY_A',{exact:true}).count(),0);
  creationDelay=0;await input.fill('NEW_REQUEST');await send.click();await page.getByText('ANSWER_NEW_REQUEST',{exact:true}).waitFor();assert.deepEqual(sent.at(-1),{id:903,content:'NEW_REQUEST'});
  slowHistory=true;await select('旧对话 A');assert.equal(await input.isDisabled(),true);assert.equal(await page.getByText('ANSWER_NEW_REQUEST',{exact:true}).count(),0);
  await select('旧对话 B');await page.getByText('HISTORY_B',{exact:true}).waitFor();await sleep(900);assert.equal(await page.getByText('OLD_HISTORY_A',{exact:true}).count(),0);
  slowHistory=false;failHistory=true;await select('旧对话 A');await page.getByRole('alert').filter({hasText:'无法加载对话'}).waitFor();assert.equal(await input.isDisabled(),true);
  failHistory=false;await page.getByRole('button',{name:'重试',exact:true}).click();await page.getByText('OLD_HISTORY_A',{exact:true}).waitFor();
  await input.fill('SLOW_OLD_REQUEST');await send.click();await page.waitForFunction(()=>document.querySelector('button[title="停止生成"]'));
  await fresh();await input.fill('FAST_NEW_REQUEST');await send.click();await page.getByText('ANSWER_FAST_NEW_REQUEST',{exact:true}).waitFor();await sleep(1400);
  assert.equal(await page.getByText('ANSWER_SLOW_OLD_REQUEST',{exact:true}).count(),0);assert.ok(aborted.length>=1,'New conversation aborts old request');
  await input.fill('SLOW_LEAVE_PAGE');await send.click();await sleep(100);await page.getByRole('button',{name:'首页',exact:true}).click();await sleep(1400);assert.ok(aborted.length>=2,'Leaving chat aborts request');
  const papers=await(await page.request.get(base+'/api/papers?limit=1')).json();assert.ok(papers.items.length,'Use preview with a synthetic PDF');const paper=papers.items[0];
  await page.getByRole('button',{name:'论文库',exact:true}).click();await page.getByText(paper.title,{exact:true}).first().click();await page.getByRole('button',{name:'就这篇论文提问',exact:true}).click();
  await page.getByRole('button',{name:'退出论文上下文',exact:true}).waitFor();const paperConversation=next-1;
  await input.fill('PAPER_QUESTION');await send.click();await page.getByText('ANSWER_PAPER_QUESTION',{exact:true}).waitFor();assert.deepEqual(sent.at(-1),{id:paperConversation,content:'PAPER_QUESTION',paper_id:paper.id});
  await input.fill('OLD_PAPER_DRAFT');await fresh();assert.equal(await input.inputValue(),'');assert.equal(await page.getByRole('button',{name:'退出论文上下文',exact:true}).count(),0);
  await input.fill('BLANK_AFTER_PAPER');await send.click();await page.getByText('ANSWER_BLANK_AFTER_PAPER',{exact:true}).waitFor();assert.deepEqual(sent.at(-1),{id:next-1,content:'BLANK_AFTER_PAPER'});
  await select('旧对话 B');assert.equal(await page.getByRole('button',{name:'退出论文上下文',exact:true}).count(),0);
  await select('新对话 '+paperConversation);await page.getByRole('button',{name:'退出论文上下文',exact:true}).waitFor();await page.getByRole('button',{name:'退出论文上下文',exact:true}).click();
  await input.fill('DETACHED_PAPER');await send.click();await page.getByText('ANSWER_DETACHED_PAPER',{exact:true}).waitFor();assert.deepEqual(sent.at(-1),{id:paperConversation,content:'DETACHED_PAPER'});
  await input.fill('DRAFT_BEFORE_DELETE');await nav.getByRole('button',{name:'删除对话「新对话 '+paperConversation+'」',exact:true}).click();await page.getByRole('alertdialog').getByRole('button',{name:'删除',exact:true}).click();await page.getByText('开始一个新对话',{exact:true}).waitFor();await fresh();assert.equal(await input.inputValue(),'');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:'new chat clears draft/history/paper, double create, loading gate/retry, out-of-order loads, stream cancellation on new/navigation, independent paper entry, scoped restore/detach, deletion reset',requests:sent.length,aborted:aborted.length,page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
