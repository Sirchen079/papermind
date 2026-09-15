import { useState } from 'react';
import { Shell } from '../components/layout/Shell';
import type { GettingStartedController } from '../components/GettingStarted';
import { LESSONS } from './onboardingModel';
import type { NavLocation } from './navigationModel';

const TOOLS: {name:string;purpose:string;how:string;target:NavLocation}[] = [
  {name:'论文库',purpose:'保存论文原文、查找文献、继续阅读和做笔记。',how:'点击论文打开详情；用搜索找标题，用阅读状态整理待读论文。',target:{page:'library',params:{}}},
  {name:'论文研究',purpose:'围绕一个问题整理或比较 1–5 篇论文。',how:'选论文、填写问题、开始研究；生成后对照原文，保存自己的结论。',target:{page:'research',params:{}}},
  {name:'论文问答',purpose:'临时问一个问题，或请 AI 解释一段内容。',how:'从论文详情点击“就这篇论文提问”，再输入问题；重要发现可以保存为笔记或想法。对话支持 Markdown 标题、列表、表格、代码高亮，以及 $...$ 行内公式、$$...$$ 独立公式和 LaTeX 的 \\(...\\)、\\[...\\] 写法。复制回答保留原始语法。',target:{page:'chat',params:{}}},
  {name:'论文对照表',purpose:'把论文的方法、数据、结果和局限放在一张表里看。',how:'在论文库切换到“论文对照表”（原审阅矩阵），逐篇填写；AI 建议也需要你核对。',target:{page:'library',params:{view:'matrix'}}},
  {name:'课题与章节',purpose:'按写作章节组织已经读过的论文。',how:'在论文库切换到“课题与章节”，建立结构并关联论文。只是读论文时可以先不建。',target:{page:'library',params:{view:'thesis'}}},
  {name:'研究建议',purpose:'查看系统找到的新论文和可能相关的内容。',how:'在“更多工具”打开，阅读建议后选择是否采用；它是发现线索的入口。',target:{page:'suggestions',params:{}}},
  {name:'研究想法',purpose:'保存自己的研究点子和后续处理状态。',how:'打开“更多工具 → 研究想法”，记录点子；也可以从论文问答中保存发现。',target:{page:'ideas',params:{}}},
  {name:'关系图谱',purpose:'探索论文、概念和论断之间的联系。',how:'有了论文和分析内容后，在“更多工具”打开图谱；点击节点查看相关论文。',target:{page:'graph',params:{}}},
  {name:'模型设置与备份',purpose:'连接 AI 服务、设置检索能力、备份本地资料。',how:'先设置对话模型即可使用摘要和论文研究；其他配置按需展开阅读。备份操作也在设置中。',target:{page:'settings',params:{}}},
  {name:'自定义技能',purpose:'复用你自己定义的 AI 处理方式，适合熟悉基础流程以后使用。',how:'在“更多工具”打开“自定义技能”，查看技能说明，再决定是否启用或编辑。',target:{page:'skills',params:{}}},
];

export default function Help({guide,onNavigate}:{guide:GettingStartedController;onNavigate:(target:NavLocation|string)=>void}) {
  const [query,setQuery]=useState('');
  const selected=TOOLS.filter(item=>`${item.name}${item.purpose}${item.how}`.includes(query.trim()));
  return <Shell max="narrow"><div className="space-y-5">
    <div><h1 className="text-xl font-semibold">使用指南</h1><p className="text-sm text-muted mt-2">不知道先做什么，就从一篇论文开始。其他功能需要时再学。</p></div>
    <section className="card space-y-3"><h2 className="font-semibold">跟着做一遍</h2><p className="text-sm text-muted">导入一篇 → 阅读记录 → 围绕问题研究 → 核对与导出。每一步都能跳到实际操作页面。</p>
      <div className="flex flex-wrap gap-2"><button className="btn-primary" disabled={guide.busy} onClick={async()=>{if(await guide.start(guide.state?.status==='completed'?0:guide.state?.step??0))onNavigate('home');}}>{guide.state?.status==='completed'?'重新学习':guide.state&&guide.state.step>0?'继续上次引导':'开始新手引导'}</button><button className="btn-ghost" disabled={guide.busy} onClick={async()=>{if(await guide.start(0))onNavigate('home');}}>从第一步开始</button></div>
      {guide.state?.status==='completed'&&<p className="text-sm text-muted">入门说明已学完。这里可以随时查用法，不代表已完成实际研究。</p>}
      {guide.error&&<p role="alert" className="text-sm text-[var(--danger)]">{guide.error}</p>}
      {guide.hint&&<p role="status" className="text-sm text-muted">{guide.hint}</p>}
    </section>
    <section className="space-y-2"><h2 className="font-semibold">基础操作</h2>{LESSONS.map((lesson,index)=><details key={lesson.id} className="card"><summary className="cursor-pointer font-medium">{index+1}. {lesson.title}</summary><p className="text-sm text-muted mt-3">{lesson.purpose}</p><ol className="list-decimal pl-5 text-sm mt-3 space-y-2">{lesson.instructions.map(text=><li key={text}>{text}</li>)}</ol><button className="btn-ghost mt-3" disabled={guide.busy} onClick={()=>guide.go(lesson)}>{lesson.action}</button></details>)}</section>
    <section className="space-y-3"><h2 className="font-semibold">这些功能分别用来做什么？</h2><input className="input w-full" aria-label="搜索操作说明" placeholder="例如：笔记、对照表、备份" value={query} onChange={e=>setQuery(e.target.value)}/>{selected.map(item=><details className="card" key={item.name}><summary className="cursor-pointer font-medium">{item.name}<span className="block text-sm font-normal text-muted mt-1">{item.purpose}</span></summary><p className="text-sm mt-3">{item.how}</p><button className="btn-ghost mt-3" onClick={()=>onNavigate(item.target)}>打开{item.name}</button></details>)}{!selected.length&&<p className="text-sm text-muted">没有匹配的说明，试试更短的关键词。</p>}</section>
  </div></Shell>;
}
