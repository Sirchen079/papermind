// Synthetic preview on 4289 only. No model calls or library mutations.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const output=path.resolve(__dirname,'../../.research-dev/editorial');fs.mkdirSync(output,{recursive:true});
 await page.goto('http://127.0.0.1:4289/');await page.getByRole('heading',{name:'这次，想弄清什么？',exact:true}).waitFor();
 await page.locator('summary').filter({hasText:'翻看最近收藏'}).click();
 await page.locator('.reading-desk').scrollIntoViewIfNeeded();await page.mouse.move(0,0);
 const desk=page.locator('.reading-desk'),title=desk.locator('h2');
 await page.waitForFunction(()=>document.querySelector('.reading-desk')?.getAttribute('data-motion')==='running');
 const first=await title.textContent();assert.match(first,/合成示例/);
 const flow=desk.locator('.trace-flow');const before=await flow.evaluate(e=>getComputedStyle(e).strokeDashoffset);
 await page.waitForTimeout(350);assert.notEqual(await flow.evaluate(e=>getComputedStyle(e).strokeDashoffset),before);
 await page.waitForTimeout(800); // let the entry page turn settle before the still image
 await page.screenshot({path:path.join(output,'home.png')});
 await page.waitForFunction(first=>document.querySelector('.desk-paper h2')?.textContent!==first,first,{timeout:10000});
 await desk.getByRole('button',{name:'暂停书页轮播',exact:true}).click();await desk.locator('button').first().evaluate(e=>e.blur());await page.mouse.move(0,0);
 const second=await title.textContent();assert.notEqual(second,first);
 assert.equal(await flow.evaluate(e=>getComputedStyle(e).animationPlayState),'paused');
 await page.waitForTimeout(7500);assert.equal(await title.textContent(),second,'pause should keep the paper in place');
 await desk.getByRole('button',{name:'查看第 3 篇收藏',exact:true}).click();
 const selected=await title.textContent();assert.match(selected,/合成示例 A/);
 await desk.getByRole('button',{name:'继续书页轮播',exact:true}).click();await desk.locator('button').evaluateAll(elements=>elements.forEach(e=>e.blur()));await page.mouse.move(0,0);
 await page.waitForFunction(selected=>document.querySelector('.desk-paper h2')?.textContent!==selected,selected,{timeout:10000});
 // Hover pauses reading, while manual controls remain available.
 await desk.hover();await page.waitForFunction(()=>document.querySelector('.reading-desk')?.getAttribute('data-motion')==='paused');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('.reading-desk')?.getAttribute('data-motion')==='reduced');
 await desk.getByRole('button',{name:'查看第 2 篇收藏',exact:true}).click();const selectedTitle=await title.textContent();
 await desk.getByRole('button',{name:'打开这篇论文',exact:true}).click();await page.getByRole('dialog',{name:selectedTitle,exact:true}).waitFor();
 await page.getByRole('dialog',{name:selectedTitle,exact:true}).getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'切换到深色模式',exact:true}).click();await page.waitForTimeout(250);await page.screenshot({path:path.join(output,'home-dark.png')});
 await page.getByRole('button',{name:'切换到浅色模式',exact:true}).click();await page.setViewportSize({width:360,height:960});await page.waitForTimeout(250);
 assert.ok(await page.locator('main').evaluate(e=>e.scrollWidth<=e.clientWidth));await page.screenshot({path:path.join(output,'home-mobile.png')});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:'real paper carousel advances, pause, resume, manual selection, hover protection, reduced motion, opens selected paper, dark/mobile',page_errors:errors}));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
