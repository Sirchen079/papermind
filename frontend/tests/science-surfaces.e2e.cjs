// Visual and interaction checks against the isolated synthetic preview only.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const out=path.resolve(__dirname,'../../.research-dev/science-surfaces');fs.mkdirSync(out,{recursive:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:4289/');const shelves=page.locator('.home-recent-grid');await shelves.waitFor();await shelves.scrollIntoViewIfNeeded();
 const motif=shelves.locator('.research-motif');await motif.locator('.motif-flow').waitFor();await page.waitForFunction(()=>document.querySelector('.home-recent-grid .research-motif')?.classList.contains('has-arrived'));
 const flow=motif.locator('.motif-flow');const first=await flow.evaluate(e=>getComputedStyle(e).strokeDashoffset);await page.waitForTimeout(350);assert.notEqual(await flow.evaluate(e=>getComputedStyle(e).strokeDashoffset),first);
 await page.waitForTimeout(3800);assert.equal(await flow.evaluate(e=>e.getAnimations().filter(a=>a.playState==='running').length),0,'decorative flow settles after four seconds');
 await shelves.screenshot({path:path.join(out,'home-shelves.png')});
 const card=page.getByRole('region',{name:'最近导入',exact:true}).locator('.shelf-paper').first();await card.hover();await page.waitForTimeout(250);
 assert.notEqual(await card.evaluate(e=>getComputedStyle(e).transform),'none');assert.ok((await card.locator('.shelf-paper-abstract').textContent()).length>0);
 const paperTitle=await card.locator('.shelf-paper-title > span').first().textContent();await card.click();const dialog=page.getByRole('dialog',{name:paperTitle,exact:true});await dialog.waitFor();await dialog.getByRole('button',{name:'关闭',exact:true}).click();
 await page.goto('http://127.0.0.1:4289/');await shelves.waitFor();
 const tool=page.locator('.research-tool').first();await tool.locator('summary').click();await tool.locator('.reading-desk').waitFor();await tool.locator('summary').click();
 await page.locator('.research-tool').last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'home-tools.png')});
 await page.getByRole('button',{name:'切换到深色模式',exact:true}).click();await shelves.scrollIntoViewIfNeeded();await page.waitForTimeout(250);await shelves.screenshot({path:path.join(out,'home-shelves-dark.png')});
 await page.getByRole('button',{name:'切换到浅色模式',exact:true}).click();
 for(const route of ['chat','ideas','suggestions','skills','graph','research']){
  await page.goto('http://127.0.0.1:4289/#'+route);await page.waitForTimeout(650);await page.screenshot({path:path.join(out,route+'-desktop.png')});
 }
 for(const width of [1024,768,360]){
  await page.setViewportSize({width,height:960});
  for(const route of ['home','chat','ideas','suggestions','skills','graph','research']){
   await page.goto('http://127.0.0.1:4289/#'+route);await page.waitForTimeout(500);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'document overflow '+route+width);
   assert.ok(await page.locator('main').evaluate(e=>e.scrollWidth<=e.clientWidth),'main overflow '+route+width);
   if(width===360)await page.screenshot({path:path.join(out,route+'-mobile.png')});
  }
 }
 await page.goto('http://127.0.0.1:4289/');await shelves.waitFor();await shelves.scrollIntoViewIfNeeded();await shelves.screenshot({path:path.join(out,'home-shelves-mobile.png'),style:'.app-header { visibility: hidden; }'});
 await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await flow.evaluate(e=>getComputedStyle(e).animationName),'none');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:'visible-entry flow then settles, paper hover/real abstract/open, disclosure controls, shared empty states, seven routes at three widths, dark and reduced motion',page_errors:errors}));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
