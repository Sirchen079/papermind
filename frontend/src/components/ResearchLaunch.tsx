import { useEffect, useRef, useState } from 'react';
import type { Paper } from '../api';
import { useWorkspace } from '../workspaceContext';
import type { NavLocation } from '../pages/navigationModel';

const starters = [
  {label:'比较方法差异',question:'比较这些论文的方法、适用条件与效果，说明各自适合什么场景，并给出你的推荐。'},
  {label:'抓住论文重点',question:'总结这些论文要解决的问题、主要贡献与局限，列出对应的原文依据。'},
  {label:'找出可追问的方向',question:'根据这些论文的局限与尚未解决的问题，提出值得进一步验证的研究问题，说明依据并给出第一步验证方案。'},
];

export default function ResearchLaunch({papers,onNavigate}:{papers:Paper[];onNavigate?:(target:NavLocation|string)=>void}) {
  const {api}=useWorkspace();
  const [question,setQuestion]=useState('');
  const [selected,setSelected]=useState<number[]>([]);
  const [starting,setStarting]=useState(false);
  const [startError,setStartError]=useState('');
  const startingRef=useRef(false);
  const aliveRef=useRef(true);
  useEffect(()=>{aliveRef.current=true;return()=>{aliveRef.current=false;};},[]);
  const input=useRef<HTMLTextAreaElement>(null);
  async function continueResearch(){
    if(!question.trim()||startingRef.current)return;
    startingRef.current=true;setStarting(true);setStartError('');
    try{
      const conversation=selected.length?await api.createPaperDiscussion(selected):await api.createConversation();
      if(aliveRef.current)onNavigate?.({page:'chat',params:{conversation:String(conversation.id),question:question.trim()}});
    }catch(e){if(aliveRef.current)setStartError((e as Error).message);}
    finally{startingRef.current=false;if(aliveRef.current)setStarting(false);}
  }
  return <section className="rd-launch" aria-label="从问题开始研究">
      <div className="rd-launch-heading"><span aria-hidden="true">＋</span><div><h2>从问题开始研究</h2><p>选择论文，带着问题进入研究对话。</p></div></div>
      <form className="launch-composer" onSubmit={e=>{e.preventDefault();continueResearch();}}>
        <textarea ref={input} aria-label="从首页提出研究问题" rows={2} maxLength={2000} value={question} disabled={starting} onChange={e=>setQuestion(e.target.value)} placeholder="这次，想弄清什么？"/>
        <div className="launch-composer-footer"><span>{selected.length?'已选 '+selected.length+' 篇 · ':''}带入对话，确认后发送</span><button className="btn-primary" disabled={!question.trim()||starting} type="submit">{starting?'正在带入…':'开始研究'} <span aria-hidden="true">→</span></button></div>
      </form>
      {startError&&<p role="alert" className="text-sm text-red-600">{startError}；问题和选材仍保留，可重试。</p>}
      <div className="launch-starters" aria-label="快捷研究问题">{starters.map(item=><button key={item.label} aria-pressed={question===item.question} disabled={starting} onClick={()=>{setQuestion(item.question);input.current?.focus();}}>{item.label}<span aria-hidden="true">↗</span></button>)}</div>
      {papers.length>0&&<details className="launch-materials"><summary>选择研究材料 <span>最近 {papers.length} 篇{selected.length?' · 已选 '+selected.length+' 篇':''}</span></summary><div>{papers.map(paper=><label key={paper.id} className={selected.includes(paper.id)?'is-selected':''}><input type="checkbox" disabled={starting} checked={selected.includes(paper.id)} onChange={()=>setSelected(ids=>ids.includes(paper.id)?ids.filter(id=>id!==paper.id):[...ids,paper.id])}/><span>{paper.title||'未命名论文'}</span></label>)}</div></details>}
      <button className="launch-review-link" onClick={()=>onNavigate?.({page:'research',params:{mode:'review'}})}>批量精读 · 卡片 · 综述 <span aria-hidden="true">↗</span></button>
  </section>;
}
