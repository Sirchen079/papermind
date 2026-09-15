// Only the isolated synthetic preview. Navigation is checked without model calls.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const base='http://127.0.0.1:4289',out=path.resolve(__dirname,'../../.research-dev/launch');fs.mkdirSync(out,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];let writes=0;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/research/tasks**',route=>{if(route.request().method()!=='GET'){writes++;return route.abort();}return route.continue();});
  await page.goto(base);await page.getByRole('heading',{name:'这次，想弄清什么？',exact:true}).waitFor();
  const result=page.getByRole('complementary',{name:'接着上次的发现',exact:true});
  await result.getByRole('button',{name:'打开结果，接着推敲',exact:true}).waitFor();
  const tasks=await(await page.request.get(base+'/api/research/tasks')).json();const task=await(await page.request.get(base+'/api/research/tasks/'+tasks[0].id)).json();
  assert.equal(await result.locator('h2').textContent(),task.question);
  assert.equal(await result.locator('.launch-result-excerpt').textContent(),task.artifact.content);
  assert.ok((await page.getByRole('button',{name:'选论文，继续',exact:true}).boundingBox()).y<500,'primary action should be on the first screen');
  assert.equal(await page.locator('.journal-masthead').count(),0);
  assert.equal(await page.locator('.reading-desk').count(),0,'reading decoration stays collapsed');
  await page.screenshot({path:path.join(out,'home-light.png')});
  await page.getByRole('button',{name:'比较方法差异',exact:true}).click();
  const question=await page.getByLabel('从首页提出研究问题',{exact:true}).inputValue();assert.match(question,/适用条件/);
  await page.locator('.launch-materials summary').click();await page.locator('.launch-materials input').first().check();
  const title=await page.locator('.launch-materials label').first().locator('span').textContent();
  await page.getByRole('button',{name:'继续研究',exact:true}).click();await page.getByLabel('研究问题',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('研究问题',{exact:true}).inputValue(),question);
  await page.waitForFunction(()=>document.querySelectorAll('.paper-option.is-selected').length===1);
  assert.equal(await page.locator('.paper-option.is-selected span').textContent(),title);
  assert.equal(writes,0,'templates and material handoff must not start model work');
  await page.goto(base);await result.getByRole('button',{name:'打开结果，接着推敲',exact:true}).click();
  await page.waitForURL(/task=/);assert.ok(decodeURIComponent(page.url()).includes(task.id));
  await page.getByLabel('当前研究判断',{exact:true}).waitFor();
  await page.goto(base);await result.getByRole('button',{name:'打开结果，接着推敲',exact:true}).waitFor();
  await page.getByRole('button',{name:'切换到深色模式',exact:true}).click();await page.waitForTimeout(250);await page.screenshot({path:path.join(out,'home-dark.png')});
  await page.getByRole('button',{name:'切换到浅色模式',exact:true}).click();await page.setViewportSize({width:360,height:960});await page.waitForTimeout(250);
  assert.ok((await page.getByRole('button',{name:'选论文，继续',exact:true}).boundingBox()).y<500);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'home-mobile.png')});
  // Empty and failed result requests must not invent saved work or block asking a question.
  let mode='empty';await page.route('**/api/research/tasks',route=>mode==='error'?route.fulfill({status:503,body:'Unavailable'}):route.fulfill({json:[]}));
  await page.goto(base);await result.getByText('先有一份可推敲的回答。',{exact:true}).waitFor();assert.equal(await result.locator('.launch-result-excerpt').count(),0);
  await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:path.join(out,'home-empty-results.png')});
  mode='error';await page.reload();await result.getByRole('button',{name:'重新加载研究',exact:true}).waitFor();
  await page.getByRole('button',{name:'抓住论文重点',exact:true}).click();assert.ok(await page.getByRole('button',{name:'选论文，继续',exact:true}).isEnabled());
  mode='empty';await result.getByRole('button',{name:'重新加载研究',exact:true}).click();await result.getByText('先有一份可推敲的回答。',{exact:true}).waitFor();
  assert.equal(writes,0);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks:'first-screen action, question template with selected-paper handoff, exact saved result and task, empty/error/retry, no model calls, mobile and dark',page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
