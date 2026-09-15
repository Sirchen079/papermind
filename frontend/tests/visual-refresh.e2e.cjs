// Isolated preview only. Exercises navigation and layout without invoking a model.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const out=path.resolve(__dirname,'../../.research-dev/visual-refresh');fs.mkdirSync(out,{recursive:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:4289';await page.goto(base);
 await page.getByRole('heading',{name:'这次，想弄清什么？',exact:true}).waitFor();
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.screenshot({path:path.join(out,'home-light.png')});
 let newTasks=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/api/research/tasks'))newTasks++;});
 await page.getByLabel('从首页提出研究问题',{exact:true}).fill('不同论文中的方法，适用条件有什么区别？');
 await page.getByRole('button',{name:'选论文，继续',exact:true}).click();
 await page.getByLabel('研究问题',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('研究问题',{exact:true}).inputValue(),'不同论文中的方法，适用条件有什么区别？');assert.equal(newTasks,0);
 await page.getByRole('button',{name:'收起侧栏',exact:true}).click();
 assert.equal(await page.locator('.app-sidebar').evaluate(e=>e.getBoundingClientRect().width),76);
 await page.reload();await page.getByRole('button',{name:'展开侧栏',exact:true}).waitFor();
 await page.getByRole('button',{name:'论文研究',exact:true}).click();await page.getByLabel('研究问题',{exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'research-collapsed.png')});
 await page.getByRole('button',{name:'展开侧栏',exact:true}).click();
 await page.getByLabel('研究问题',{exact:true}).fill('不同评测条件下，这些论文的结果可以直接比较吗？');
 await page.locator('.paper-option').first().click();assert.equal(await page.locator('.paper-option.is-selected').count(),1);await page.waitForTimeout(250);
 await page.screenshot({path:path.join(out,'research-light.png')});
 await page.getByRole('button',{name:'切换到深色模式',exact:true}).click();await page.waitForTimeout(250);await page.screenshot({path:path.join(out,'research-dark.png')});
 await page.getByRole('button',{name:'论文问答',exact:true}).click();await page.getByText('开始一个新对话',{exact:true}).waitFor();await page.waitForTimeout(250);
 await page.screenshot({path:path.join(out,'chat-dark.png')});
 // Mock an empty conversation so prompt selection cannot incur a model call.
 await page.route('**/api/chat/conversations',route=>route.fulfill({json:route.request().method()==='POST'?{id:999001,title:'界面示例'}:[{id:999001,title:'界面示例'}]}));
 await page.route('**/api/chat/conversations/999001',route=>route.fulfill({json:{id:999001,title:'界面示例',messages:[]}}));
 let modelCalls=0;await page.route('**/api/chat/conversations/999001/messages/**',route=>{modelCalls++;return route.abort();});
 await page.getByRole('button',{name:'+ 新建对话',exact:true}).last().click();
 await page.getByRole('button',{name:'比较几篇论文的方法',exact:true}).click();
 assert.equal(await page.getByLabel('向论文库提问',{exact:true}).inputValue(),'比较几篇论文的方法');assert.equal(modelCalls,0);
 await page.screenshot({path:path.join(out,'chat-composer-dark.png')});
 await page.getByRole('button',{name:'切换到浅色模式',exact:true}).click();
 await page.getByRole('button',{name:'论文库',exact:true}).click();await page.getByRole('heading',{name:'论文库',exact:true}).waitFor();await page.waitForTimeout(400);
 await page.screenshot({path:path.join(out,'library-light.png')});
 await page.getByRole('button',{name:'更多工具',exact:true}).click();await page.getByRole('button',{name:'关系图谱',exact:true}).waitFor();
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('heading',{name:'设置',exact:true}).waitFor();await page.screenshot({path:path.join(out,'settings-light.png')});
 for(const width of [1024,768,360]){
   await page.setViewportSize({width,height:900});await page.waitForTimeout(300);
   for(const route of ['home','research','library','chat','settings','help']){
     await page.goto(base+'/#'+route);await page.waitForTimeout(500);
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'document overflow '+route+width);
     assert.ok(await page.locator('main').evaluate(e=>e.scrollWidth<=e.clientWidth),'main overflow '+route+width);
     if(width===360)await page.screenshot({path:path.join(out,route+'-mobile.png')});
   }
 }
 await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.getByRole('button',{name:'论文研究',exact:true}).click();
 await page.getByLabel('研究问题',{exact:true}).waitFor();
 await page.waitForTimeout(250); // sidebar visibility follows its closing transition
 assert.ok(await page.locator('.app-sidebar').evaluate(e=>getComputedStyle(e).visibility==='hidden'));
 await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.waitForTimeout(300);await page.screenshot({path:path.join(out,'navigation-mobile.png')});
 await page.getByRole('button',{name:'关闭导航',exact:true}).click();
 assert.deepEqual(errors,[]);console.log(JSON.stringify({screenshots:out,checks:'home question handoff without model calls, reduced motion, sidebar persistence, primary and extra navigation, selected paper, themes, six routes at 1024/768/360, mobile navigation',page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
