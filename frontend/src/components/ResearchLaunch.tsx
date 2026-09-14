import { useEffect, useRef, useState } from 'react';
import type { Paper } from '../api';
import { statusLabels, supportLabels, type ResearchTask } from '../researchApi';
import { useWorkspace } from '../workspaceContext';
import type { NavLocation } from '../pages/navigationModel';
import { Sparkles } from '../icons';

const starters = [
  {label:'比较方法差异',question:'比较这些论文的方法、适用条件与局限，并指出哪些结果不能直接比较。'},
  {label:'抓住论文重点',question:'总结这些论文要解决的问题、主要贡献与局限，列出对应的原文依据。'},
  {label:'找出可追问的方向',question:'根据这些论文的局限与尚未解决的问题，提出值得进一步验证的研究问题，并说明依据和不确定性。'},
];

export default function ResearchLaunch({papers,onNavigate}:{papers:Paper[];onNavigate?:(target:NavLocation|string)=>void}) {
  const {researchApi}=useWorkspace();
  const [question,setQuestion]=useState('');
  const [selected,setSelected]=useState<number[]>([]);
  const [latest,setLatest]=useState<ResearchTask|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState(false);
  const [attempt,setAttempt]=useState(0);
  const input=useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{
    let alive=true;setLoading(true);setError(false);
    researchApi.list().then(tasks=>tasks.length?researchApi.get(tasks[0].id):null)
      .then(task=>{if(alive)setLatest(task);})
      .catch(()=>{if(alive)setError(true);})
      .finally(()=>{if(alive)setLoading(false);});
    return()=>{alive=false;};
  },[attempt]);
  function continueResearch(){
    if(question.trim())onNavigate?.({page:'research',params:{question:question.trim(),papers:selected.join(',')}});
  }
  return <section className="research-launch" aria-label="研究起点">
    <div className="launch-main">
      <p className="launch-eyebrow"><Sparkles size={15}/> 从问题到有依据的回答</p>
      <h1>这次，想弄清什么？</h1>
      <p className="launch-description">让 AI 先整理与比较，把精力留给你的判断。</p>
      <form className="launch-composer" onSubmit={e=>{e.preventDefault();continueResearch();}}>
        <textarea ref={input} aria-label="从首页提出研究问题" rows={3} maxLength={2000} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="例如：这几篇论文的方法，究竟差在哪里？"/>
        <div className="launch-composer-footer"><span>{selected.length?`已选 ${selected.length} 篇论文`:'用你选定的论文回答'}</span><button className="btn-primary" disabled={!question.trim()} type="submit">{selected.length?'继续研究':'选论文，继续'} <span aria-hidden="true">→</span></button></div>
      </form>
      <div className="launch-starters" aria-label="快捷研究问题">{starters.map(item=><button key={item.label} aria-pressed={question===item.question} onClick={()=>{setQuestion(item.question);input.current?.focus();}}>{item.label}<span aria-hidden="true">↗</span></button>)}</div>
      {papers.length>0?<details className="launch-materials"><summary>顺手选好材料 <span>最近 {papers.length} 篇{selected.length?` · 已选 ${selected.length} 篇`:''}</span></summary><div>{papers.map(paper=><label key={paper.id} className={selected.includes(paper.id)?'is-selected':''}><input type="checkbox" checked={selected.includes(paper.id)} onChange={()=>setSelected(ids=>ids.includes(paper.id)?ids.filter(id=>id!==paper.id):[...ids,paper.id])}/><span>{paper.title||'未命名论文'}</span></label>)}</div></details>:<button className="launch-import" onClick={()=>onNavigate?.({page:'library',params:{import:'pdf'}})}>手头有 PDF？直接导入 <span aria-hidden="true">↗</span></button>}
      <p className="launch-note">下一步确认论文与研究方式，再运行 AI。</p>
    </div>
    <aside className="launch-result" aria-label="接着上次的发现">
      <div className="launch-result-heading"><span>{latest?'接着上次的发现':'回答会长什么样'}</span><span className="launch-result-mark" aria-hidden="true">↗</span></div>
      {loading?<p role="status" className="launch-placeholder">正在找回上次的研究…</p>:error?<div className="launch-placeholder"><p>上次的研究暂时没能加载。</p><button className="btn-ghost mt-3" onClick={()=>setAttempt(n=>n+1)}>重新加载研究</button></div>:latest?<>
        <div className="launch-result-status"><span>{statusLabels[latest.status]??latest.status}</span>{latest.artifact&&<span>{supportLabels[latest.artifact.support_status]??latest.artifact.support_status}</span>}</div>
        <h2>{latest.question}</h2>
        <p className="launch-result-excerpt">{latest.artifact?.content||'这项研究已经保存，打开即可查看当前进度并继续。'}</p>
        <div className="launch-result-meta"><span>{latest.paper_ids.length} 篇材料</span>{latest.artifact&&<span>{latest.artifact.evidence_refs.length} 条引用 · v{latest.artifact.version}</span>}</div>
        <button className="launch-resume" onClick={()=>onNavigate?.({page:'research',params:{task:latest.id}})}>{latest.artifact?'打开结果，接着推敲':'打开研究，继续推进'} <span aria-hidden="true">→</span></button>
      </>:<>
        <h2>先有一份可推敲的回答。</h2>
        <p className="launch-result-intro">选好论文后，AI 围绕你的问题整理：</p>
        <ul className="launch-deliverables"><li><span>01</span><div><strong>回答草稿</strong><p>贡献、差异或局限，围绕问题展开。</p></div></li><li><span>02</span><div><strong>原文依据</strong><p>引用对应的材料片段，方便回看。</p></div></li><li><span>03</span><div><strong>还不确定的地方</strong><p>看清哪些判断需要继续验证。</p></div></li></ul>
        <p className="launch-note">研究结果会留在这里，下次直接接着推进。</p>
      </>}
    </aside>
  </section>;
}
