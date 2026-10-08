import { useEffect, useRef, useState } from 'react';
import type { Paper } from '../api';
import { activityLabels, workKindLabels, workDate, type RecentWork } from '../pages/activityModel';
import { useWorkspace } from '../workspaceContext';
import { parseHash, type NavLocation } from '../pages/navigationModel';
import { Sparkles } from '../icons';

const starters = [
  {label:'比较方法差异',question:'比较这些论文的方法、适用条件与局限，并指出哪些结果不能直接比较。'},
  {label:'抓住论文重点',question:'总结这些论文要解决的问题、主要贡献与局限，列出对应的原文依据。'},
  {label:'找出可追问的方向',question:'根据这些论文的局限与尚未解决的问题，提出值得进一步验证的研究问题，并说明依据和不确定性。'},
];

export default function ResearchLaunch({papers,onNavigate}:{papers:Paper[];onNavigate?:(target:NavLocation|string)=>void}) {
  const {api}=useWorkspace();
  const [question,setQuestion]=useState('');
  const [selected,setSelected]=useState<number[]>([]);
  const [recent,setRecent]=useState<RecentWork[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState(false);
  const [attempt,setAttempt]=useState(0);
  const [starting,setStarting]=useState(false);
  const [startError,setStartError]=useState('');
  const startingRef=useRef(false);
  const aliveRef=useRef(true);
  useEffect(()=>{aliveRef.current=true;return()=>{aliveRef.current=false;};},[]);
  const input=useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    setLoading(true);setError(false);setRecent([]);
    async function refresh(){
      try{const result=await api.recentWork();if(alive){setRecent(result.items);setError(false);}}
      catch{if(alive)setError(true);}
      finally{if(alive){setLoading(false);timer=setTimeout(refresh,15000);}}
    }
    refresh();return()=>{alive=false;clearTimeout(timer);};
  },[api,attempt]);
  async function continueResearch(){
    if(!question.trim()||startingRef.current)return;
    startingRef.current=true;setStarting(true);setStartError('');
    try{
      const conversation=selected.length?await api.createPaperDiscussion(selected):await api.createConversation();
      if(aliveRef.current)onNavigate?.({page:'chat',params:{conversation:String(conversation.id),question:question.trim()}});
    }catch(e){if(aliveRef.current)setStartError((e as Error).message);}
    finally{startingRef.current=false;if(aliveRef.current)setStarting(false);}
  }
  return <section className="research-launch" aria-label="研究起点">
    <div className="launch-main">
      <p className="launch-eyebrow"><Sparkles size={15}/> 从问题到有依据的回答</p>
      <h1>这次，想弄清什么？</h1>
      <p className="launch-description">让 AI 先整理与比较，把精力留给你的判断。</p>
      <form className="launch-composer" onSubmit={e=>{e.preventDefault();continueResearch();}}>
        <textarea ref={input} aria-label="从首页提出研究问题" rows={3} maxLength={2000} value={question} disabled={starting} onChange={e=>setQuestion(e.target.value)} placeholder="例如：这些方法在噪声、振幅误差和实际数据下各有什么限制？"/>
        <div className="launch-composer-footer"><span>{selected.length?`已选 ${selected.length} 篇论文`:'在当前项目论文库中按需查找'}</span><button className="btn-primary" disabled={!question.trim()||starting} type="submit">{starting?'正在带入…':'进入研究对话'} <span aria-hidden="true">→</span></button></div>
      </form>
      {startError&&<p role="alert" className="text-sm text-red-600">{startError}；问题和选材仍保留，可重试。</p>}
      <div className="launch-starters" aria-label="快捷研究问题">{starters.map(item=><button key={item.label} aria-pressed={question===item.question} disabled={starting} onClick={()=>{setQuestion(item.question);input.current?.focus();}}>{item.label}<span aria-hidden="true">↗</span></button>)}</div>
      {papers.length>0?<details className="launch-materials"><summary>顺手选好材料 <span>最近 {papers.length} 篇{selected.length?` · 已选 ${selected.length} 篇`:''}</span></summary><div>{papers.map(paper=><label key={paper.id} className={selected.includes(paper.id)?'is-selected':''}><input type="checkbox" disabled={starting} checked={selected.includes(paper.id)} onChange={()=>setSelected(ids=>ids.includes(paper.id)?ids.filter(id=>id!==paper.id):[...ids,paper.id])}/><span>{paper.title||'未命名论文'}</span></label>)}</div></details>:<button className="launch-import" onClick={()=>onNavigate?.({page:'library',params:{import:'pdf'}})}>手头有 PDF？直接导入 <span aria-hidden="true">↗</span></button>}
      <p className="launch-note">问题和选材一起带入，可补充要求后发送，并持续追问、比较和修订。</p>
      <button className="btn-ghost text-sm mt-3" onClick={()=>onNavigate?.({page:'research',params:{mode:'review'}})}>需要逐篇整理一批论文？进入专题综述 →</button>
    </div>
    <aside className="launch-result" aria-label="接着上次的发现">
      <div className="launch-result-heading"><span>接着上次的发现</span><span className="launch-result-mark" aria-hidden="true">↗</span></div>
      {error&&<div role="alert" className="launch-placeholder"><p>{recent.length?'暂时无法刷新，以下为上次加载的记录。':'上次的研究暂时没能加载。'}</p><button className="btn-ghost mt-3" onClick={()=>setAttempt(n=>n+1)}>重新加载研究</button></div>}
      {loading?<p role="status" className="launch-placeholder">正在找回上次的研究…</p>:recent.length>0?<>
        <p className="launch-note mt-3">本项目的最近工作，打开后接着推进。</p>
        <ul className="launch-work-list">{recent.map(item=><li key={item.key}>
          <button className="launch-work" onClick={()=>onNavigate?.(parseHash(item.route))}>
            <span className="launch-work-meta"><span>{workKindLabels[item.kind]||item.kind} · {activityLabels[item.status]||item.status}</span><span>{workDate(item.time)}</span></span>
            <span className="launch-work-title">{item.title}</span><span className="launch-work-arrow" aria-hidden="true">→</span>
          </button>
        </li>)}</ul>
      </>:!error?<>
        <h2>先有一份可推敲的回答。</h2>
        <p className="launch-result-intro">AI 围绕你的问题和材料整理：</p>
        <ul className="launch-deliverables"><li><span>01</span><div><strong>回答草稿</strong><p>贡献、差异或局限，围绕问题展开。</p></div></li><li><span>02</span><div><strong>原文依据</strong><p>引用对应的材料片段，方便回看。</p></div></li><li><span>03</span><div><strong>还不确定的地方</strong><p>看清哪些判断需要继续验证。</p></div></li></ul>
        <p className="launch-note">研究结果会留在这里，下次直接接着推进。</p>
      </>:null}
    </aside>
  </section>;
}
