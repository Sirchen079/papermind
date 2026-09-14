// Only run against an isolated empty preview or frozen package smoke server.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
function samplePdf(){
 const stream='BT /F1 18 Tf 50 760 Td (PaperMind Onboarding Example) Tj 0 -36 Td /F1 11 Tf (Synthetic paper for learning import and notes. No real study.) Tj ET';
 const objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
 let pdf='%PDF-1.4\n';const offsets=[0];
 objects.forEach((o,i)=>{offsets.push(Buffer.byteLength(pdf));pdf+=`${i+1} 0 obj\n${o}\nendobj\n`;});
 const xref=Buffer.byteLength(pdf);pdf+=`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n ').join('\n')}\ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
 return Buffer.from(pdf);
}
(async()=>{
 const browser=await chromium.launch({headless:true});
 const base=process.env.PAPERMIND_TEST_BASE||'http://127.0.0.1:4290';
 assert.ok(['http://127.0.0.1:4290','http://127.0.0.1:4291'].includes(base),'Only isolated preview/smoke ports are allowed');
 const output=path.resolve(__dirname,'../../.research-dev',base.endsWith(':4291')?'package-smoke':'');fs.mkdirSync(output,{recursive:true});
 try{
 const page=await browser.newPage({viewport:{width:1280,height:960}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 assert.equal((await(await page.request.get(base+'/api/providers')).json()).length,0,'Use the empty onboarding preview, without any provider');
 const existing=await(await page.request.get(base+'/api/papers?limit=20')).json();
 for(const paper of existing.items){assert.equal(paper.title,'onboarding-example.pdf','Refusing to reset non-fixture papers');assert.ok((await page.request.delete(base+'/api/papers/'+paper.id)).ok());}
 await page.request.delete(base+'/api/settings/getting_started_v1');
 await page.goto(base);
 const guide=page.getByRole('region',{name:'新手引导'});
 await page.getByRole('button',{name:'带我开始',exact:true}).waitFor();
 assert.equal(await page.getByRole('navigation',{name:'主导航'}).getByRole('button').count(),4);
 assert.equal(await page.getByText('科研准备度',{exact:true}).count(),0);
 await page.screenshot({path:path.join(output,'onboarding-welcome-desktop.png')});
 await page.getByRole('button',{name:'先自己看看',exact:true}).click();
 await guide.waitFor({state:'hidden'});await page.reload();
 await page.getByRole('heading',{name:'这次，想弄清什么？',exact:true}).waitFor();assert.equal(await guide.count(),0);
 await page.getByRole('button',{name:'使用指南',exact:true}).click();
 await page.getByRole('button',{name:'开始新手引导',exact:true}).click();
 await guide.getByRole('heading',{name:/入门 1\/6/}).waitFor();
 await page.route('**/api/settings/getting_started_v1',route=>route.request().method()==='PUT'?route.fulfill({status:500,body:'test failed save'}):route.continue());
 await guide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();
 await guide.getByRole('alert').waitFor();assert.equal(await guide.getByRole('heading',{name:/入门 1\/6/}).count(),1);
 await page.unroute('**/api/settings/getting_started_v1');
 await guide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();
 await guide.getByRole('heading',{name:/入门 2\/6/}).waitFor();await page.reload();
 await guide.getByRole('heading',{name:/入门 2\/6/}).waitFor();
 await guide.getByRole('button',{name:'打开一篇论文',exact:true}).click();
 const importer=page.getByRole('dialog',{name:'导入论文',exact:true});await importer.waitFor();
 await importer.getByRole('button',{name:'关闭抽屉',exact:true}).click();
 await guide.getByText(/还没有论文/).waitFor();
 await guide.getByRole('button',{name:'上一步',exact:true}).click();
 await guide.getByRole('button',{name:'去导入 PDF',exact:true}).click();
 await importer.locator('input[type=file]').setInputFiles({name:'onboarding-example.pdf',mimeType:'application/pdf',buffer:samplePdf()});
 const detail=page.getByRole('dialog',{name:'onboarding-example.pdf',exact:true});
 await detail.waitFor({timeout:30000});
 await detail.getByRole('button',{name:'阅读',exact:true}).click();
 const reader=page.getByRole('dialog',{name:'阅读 PDF',exact:true});await reader.waitFor();
 await reader.locator('canvas').first().waitFor({timeout:30000});
 await reader.getByRole('button',{name:'退出阅读',exact:true}).click();
 await detail.getByRole('tab',{name:'笔记 & 摘录',exact:true}).click();
 await detail.getByPlaceholder('添加阅读笔记',{exact:true}).fill('我的第一条学习笔记：这是一份合成示例。');
 await detail.getByRole('button',{name:'添加笔记',exact:true}).click();
 await detail.getByText('我的第一条学习笔记：这是一份合成示例。',{exact:true}).waitFor();
 await detail.getByRole('button',{name:'关闭',exact:true}).click();
 await guide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();
 await guide.getByRole('heading',{name:/入门 2\/6/}).waitFor();
 await guide.getByRole('button',{name:'稍后再学',exact:true}).click();await guide.waitFor({state:'hidden'});
 const fresh=await browser.newPage({viewport:{width:1280,height:960}});
 fresh.on('pageerror',e=>errors.push(e.message));
 await fresh.goto(base);await fresh.getByRole('button',{name:'使用指南',exact:true}).click();
 await fresh.getByRole('button',{name:'继续上次引导',exact:true}).click();
 const freshGuide=fresh.getByRole('region',{name:'新手引导'});await freshGuide.getByRole('heading',{name:/入门 2\/6/}).waitFor();
 await freshGuide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();await freshGuide.getByRole('heading',{name:/入门 3\/6/}).waitFor();
 await freshGuide.getByRole('button',{name:'打开模型设置',exact:true}).click();await fresh.getByLabel('接口类型',{exact:true}).waitFor();
 await freshGuide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();await freshGuide.getByRole('heading',{name:/入门 4\/6/}).waitFor();
 await freshGuide.getByRole('button',{name:'试着填写一个问题',exact:true}).click();
 await fresh.getByLabel('研究问题',{exact:true}).waitFor();assert.equal(await fresh.getByLabel('研究问题',{exact:true}).inputValue(),'这些论文的方法有什么不同？');
 assert.equal((await(await fresh.request.get(base+'/api/research/tasks')).json()).length,0,'Guide must not start model calls or create research');
 for(let step=4;step<6;step++){await freshGuide.getByRole('button',{name:'我学会了，下一步',exact:true}).click();await freshGuide.getByRole('heading',{name:new RegExp('入门 '+(step+1)+'/6')}).waitFor();}
 await freshGuide.getByRole('button',{name:'我学会了，结束引导',exact:true}).click();await freshGuide.waitFor({state:'hidden'});
 await fresh.reload();await fresh.getByRole('button',{name:'使用指南',exact:true}).click();await fresh.getByText(/入门说明已学完/).waitFor();
 await fresh.getByLabel('搜索操作说明',{exact:true}).fill('备份');assert.equal(await fresh.getByRole('button',{name:'打开模型设置与备份',exact:true}).count(),0); // collapsed content stays hidden
 await fresh.locator('summary').filter({hasText:'模型设置与备份'}).click();await fresh.getByRole('button',{name:'打开模型设置与备份',exact:true}).waitFor();
 await fresh.getByLabel('搜索操作说明',{exact:true}).fill('');
 await fresh.getByRole('button',{name:'从第一步开始',exact:true}).click();await freshGuide.getByRole('heading',{name:/入门 1\/6/}).waitFor();
 for(const width of [1280,736,360]){await fresh.setViewportSize({width,height:960});await fresh.waitForTimeout(300);assert.ok(await fresh.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await fresh.screenshot({path:path.join(output,'onboarding-active-'+width+'.png')});}
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({checks:'fresh welcome, skip, resume across page contexts, save failure, real PDF import without AI, note save, missing-paper fallback, settings route, sample question without calls, completion, replay, help search, responsive layout',page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
