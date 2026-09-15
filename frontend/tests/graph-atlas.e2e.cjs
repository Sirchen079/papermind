// Isolated preview with read-only synthetic graph fixtures; no model calls.
const {chromium}=require(process.env.PAPERMIND_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const fixture={nodes:[
 {id:1,title:'合成图谱 · 检索增强生成',year:2024},{id:2,title:'合成图谱 · 文献证据定位',year:2025},{id:3,title:'合成图谱 · 多模态检索',year:2024},{id:4,title:'合成图谱 · 知识图谱推理',year:2023},{id:5,title:'合成图谱 · 评测条件对齐',year:2025},{id:6,title:'合成图谱 · 长文本理解',year:2024},{id:7,title:'合成图谱 · 方法可比性',year:2025},{id:8,title:'合成图谱 · 研究问题生成',year:2026}],
 edges:[{source:1,target:2,weight:4},{source:1,target:3,weight:2},{source:2,target:4,weight:3},{source:3,target:5,weight:1},{source:4,target:6,weight:2},{source:5,target:7,weight:3},{source:6,target:8,weight:2},{source:2,target:6,weight:1,edge_type:'citation'},{source:7,target:1,weight:1,edge_type:'citation'}]};
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),out=path.resolve(__dirname,'../../.research-dev/graph-atlas');fs.mkdirSync(out,{recursive:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:4289/#graph';
 const ready=()=>page.waitForFunction(()=>document.querySelector('.atlas-map')?._cyreg?.cy?.nodes().length>0);
 await page.goto(base);await ready();await page.waitForTimeout(400);
 assert.ok(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.zoom()*14>=8),'sparse graph labels remain readable');
 await page.screenshot({path:path.join(out,'actual-library.png')});
 await page.locator('.atlas-node-list button').first().click();const actualTitle=await page.locator('.atlas-selection h2').textContent();await page.getByRole('button',{name:'在库中打开',exact:true}).click();const actualDialog=page.getByRole('dialog',{name:actualTitle,exact:true});await actualDialog.waitFor();await actualDialog.getByRole('button',{name:'关闭',exact:true}).click();await page.goto(base);await ready();
 let mode='normal',lastURL='';await page.route('**/api/graph/**',route=>{
  lastURL=route.request().url();const url=new URL(lastURL);
  if(mode==='error')return route.fulfill({status:503,body:'Synthetic unavailable'});
  if(mode==='empty')return route.fulfill({json:{nodes:[],edges:[]}});
  if(url.pathname.endsWith('/concept'))return route.fulfill({json:{nodes:fixture.nodes.map((n,i)=>({id:n.id,name:n.title.replace('合成图谱 · ','合成概念 · '),type:['method','dataset','problem'][i%3],count:i+1})),edges:fixture.edges.map(e=>({...e,edge_type:e.edge_type?'hierarchy':'cooccurrence'}))}});
  if(url.pathname.endsWith('/claims'))return route.fulfill({json:{nodes:[{id:11,label:'合成论断 · 方法 A 的适用条件',paper_id:1,paper_title:'合成示例 A',text:'合成论断全文，仅用于界面检查。',source:'user',type:'main'},{id:12,label:'合成论断 · 不同划分不能排名',paper_id:2,type:'supporting',source:'ai'}],edges:[{source:11,target:12,weight:1,edge_type:'supports'}]}});
  return route.fulfill({json:{...fixture,edges:fixture.edges.filter(e=>!e.edge_type||url.searchParams.get('edge_types')?.includes('citation'))}});
 });
 await page.reload();await ready();await page.waitForTimeout(400);assert.ok(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.zoom()>=.7));await page.screenshot({path:path.join(out,'connected-paper.png')});
 await page.getByLabel('搜索节点',{exact:true}).fill('证据定位');await page.locator('.atlas-node-list button').first().click();await page.waitForTimeout(300);assert.match(await page.locator('.atlas-selection h2').textContent(),/证据定位/);
 assert.equal(await page.locator('.atlas-neighbors button').count(),3);
 await page.getByLabel('清空搜索',{exact:true}).click();
 const before=await page.getByLabel('图谱缩放比例',{exact:true}).textContent();await page.getByRole('button',{name:'放大图谱',exact:true}).click();assert.notEqual(await page.getByLabel('图谱缩放比例',{exact:true}).textContent(),before);
 // Pan/zoom and dragged node positions survive a theme change.
 const canvasBox=await page.locator('.atlas-map').boundingBox();const point=await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.$id('2').renderedPosition());const originalPosition=await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.$id('2').position());await page.mouse.move(canvasBox.x+point.x,canvasBox.y+point.y);await page.mouse.down();await page.mouse.move(canvasBox.x+point.x+28,canvasBox.y+point.y+18,{steps:8});await page.mouse.up();
 const prior=await page.locator('.atlas-map').evaluate(e=>{const cy=e._cyreg.cy;return {position:cy.$id('2').position(),zoom:cy.zoom(),pan:cy.pan()};});assert.notDeepEqual(prior.position,originalPosition);
 await page.getByRole('button',{name:'切换到深色模式',exact:true}).click();await ready();await page.waitForTimeout(400);
 const after=await page.locator('.atlas-map').evaluate(e=>{const cy=e._cyreg.cy;return {position:cy.$id('2').position(),zoom:cy.zoom(),pan:cy.pan()};});assert.deepEqual(after,prior);
 await page.getByRole('button',{name:'适配',exact:true}).click();await page.screenshot({path:path.join(out,'connected-dark.png')});
 await page.getByRole('button',{name:'切换到浅色模式',exact:true}).click();await page.getByLabel('显示引用关系',{exact:true}).uncheck();await ready();assert.equal(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.edges().length),7);
 await page.getByRole('button',{name:'概念图谱',exact:true}).click();await ready();await page.getByLabel('最少论文数',{exact:true}).fill('3');await page.waitForTimeout(400);assert.match(lastURL,/min_papers=3/);assert.match(page.url(),/mode=concept/);await page.screenshot({path:path.join(out,'concept.png')});
 await page.getByRole('button',{name:'论断图',exact:true}).click();await ready();await page.locator('.atlas-node-list button').first().click();await page.locator('.atlas-claim-text').waitFor();assert.match(await page.locator('.atlas-claim-text').textContent(),/合成论断全文/);
 assert.equal(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.edges()[0].style('target-arrow-shape')),'triangle');
 await page.getByRole('group',{name:'论断关系类型过滤'}).getByRole('button',{name:'矛盾',exact:true}).click();await ready();assert.equal(new URL(lastURL).searchParams.get('types'),'supports,extends');await page.screenshot({path:path.join(out,'claims.png')});
 await page.getByRole('group',{name:'论断关系类型过滤'}).getByRole('button',{name:'支持',exact:true}).click();await ready();await page.getByRole('group',{name:'论断关系类型过滤'}).getByRole('button',{name:'延伸',exact:true}).click();await ready();assert.equal(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.edges().length),0);
 await page.getByRole('button',{name:'论文图谱',exact:true}).click();await ready();
 for(const width of [1024,768,360]){await page.setViewportSize({width,height:960});await page.waitForTimeout(400);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.ok(await page.locator('.atlas-map').evaluate(e=>e.clientHeight>=400));if(width===360)await page.screenshot({path:path.join(out,'mobile.png')});}
 await page.getByLabel('搜索节点',{exact:true}).fill('没有的关键词');await page.getByText('没有匹配的节点，换个关键词试试。',{exact:true}).waitFor();
 mode='empty';await page.reload();await page.getByText('暂无可展示节点',{exact:true}).waitFor();await page.screenshot({path:path.join(out,'empty-mobile.png')});
 mode='error';await page.reload();await page.getByRole('alert').waitFor();mode='normal';await page.getByRole('button',{name:'重试',exact:true}).click();await ready();
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('.atlas-node-list button').first().click();assert.equal(await page.locator('.atlas-map').evaluate(e=>e._cyreg.cy.animated()),false);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:'actual sparse graph readability, connected fixtures, search and neighbors, zoom/theme position preservation, three modes and filters, arrow semantics, responsive/empty/error/retry/reduced motion',page_errors:errors}));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
