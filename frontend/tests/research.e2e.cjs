// Run separately against the isolated synthetic preview, using an existing Playwright runtime.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const output=path.resolve(__dirname,'../../.research-dev');
 fs.mkdirSync(output,{recursive:true});
 try {
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:4289/#research');
 await page.getByLabel('研究问题',{exact:true}).fill('合成示例 A 与 B 的评测结果可以直接排名吗？');
 await page.getByLabel('合成示例 A · 稀疏检索',{exact:true}).check();
 await page.getByLabel('合成示例 B · 稠密检索',{exact:true}).check();
 await page.getByRole('button',{name:'开始研究',exact:true}).click();
 await page.waitForFunction(()=>location.hash.includes('task='));
 const taskId=new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('task');
 let task;
 for(let n=0;n<80;n++){
   task=await (await page.request.get('http://127.0.0.1:4289/api/research/tasks/'+taskId)).json();
   if(task.status!=='running'&&task.status!=='draft')break;
   await page.waitForTimeout(1500);
 }
 assert.ok(task.steps.synthesis,JSON.stringify({status:task.status,error:task.error}));
 await page.reload();
 await page.getByLabel('当前研究判断').waitFor();
 await page.getByLabel('当前研究判断').fill('合成材料中 A 使用 S1，B 使用 S2，不能直接排名。');
 await page.getByRole('button',{name:'保存判断',exact:true}).click();
 await page.getByText('当前版本已保存；新修订需要重新核对。',{exact:true}).waitFor();
 await page.getByText('原文能支持这句话吗？',{exact:true}).click();
 await page.getByLabel('支持关系',{exact:true}).selectOption('supported');
 await page.getByLabel('核对依据与限制').fill('来源显示划分不同，只支持不能直接比较，不证明任何方法更优。');
 await page.getByRole('button',{name:'保存本次核对',exact:true}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('p')].some(p=>p.textContent.includes('研究者已核对支持关系')&&p.textContent.includes('草稿')));
 await page.getByRole('button',{name:'保存组会素材',exact:true}).click();
 await page.getByText('组会素材 · 使用当前版本',{exact:true}).waitFor();
 await page.getByText('组会素材 · 使用当前版本',{exact:true}).click();
 const downloadPromise=page.waitForEvent('download');
 await page.getByRole('button',{name:'导出 Markdown',exact:true}).click();
 const download=await downloadPromise;
 assert.equal(download.suggestedFilename(),'research-meeting.md');
 assert.match(fs.readFileSync(await download.path(),'utf8'),/研究者已核对支持关系/);
 await page.getByText('组会素材 · 使用当前版本',{exact:true}).click();
 await page.getByLabel('当前研究判断').fill('A 显著优于 B。');
 await page.getByText(/修订尚未保存 · 支持关系将回到待核对/).waitFor();
 await page.reload();
 assert.equal(await page.getByLabel('当前研究判断').inputValue(),'A 显著优于 B。');
 await page.getByRole('button',{name:'保存判断',exact:true}).click();
 await page.getByText('组会素材 · 判断已更新，请重新核对后保存',{exact:true}).waitFor();
 await page.getByRole('button',{name:'保存组会素材',exact:true}).click();
 task=await (await page.request.get('http://127.0.0.1:4289/api/research/tasks/'+taskId)).json();
 assert.equal(task.artifact.support_status,'pending');
 assert.match(task.reuse[0].content,/待核对/);
 assert.doesNotMatch(task.reuse[0].content,/研究者已核对支持关系/);
 await page.getByRole('button',{name:'目前足够，留在这里',exact:true}).click();
 await page.waitForFunction(()=>document.body.innerText.includes('停止原因：目前足够'));
 assert.equal(await page.getByRole('button',{name:'保留验证计划',exact:true}).isDisabled(),true);
 for(const width of [1280,1024,360]){
   await page.setViewportSize({width,height:900});
   await page.waitForTimeout(300);
   if(width<1024)assert.ok(await page.locator('aside').first().evaluate(el=>el.getBoundingClientRect().right<=1));
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(output,'research-ui-'+width+'.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({task_id:taskId,model:'configured live provider',checks:'create, live generation, persistence, review, revision invalidation, local unsaved recovery, stale reuse, stop, desktop/mobile layout',page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
