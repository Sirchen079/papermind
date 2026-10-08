import {useEffect,useMemo,useRef,useState} from 'react';
import {useWorkspace} from '../workspaceContext';
import {createReviewRequest,type ReviewChanges as Changes,type ReviewSource,type ReviewEntry} from '../reviewsApi';
import {MarkdownContent} from './MarkdownContent';

export function ReviewChanges({reviewId,version,revisions,papers,disabled,onEdit,onSource,onPaperCitation}:{reviewId:string;version:number;revisions:{version:number}[];papers:ReviewEntry[];disabled:boolean;onEdit:(id:string,version:number)=>void;onSource:(source:ReviewSource)=>void;onPaperCitation:(id:number)=>void}){
  const {base}=useWorkspace();const request=useMemo(()=>createReviewRequest(base),[base]);
  const [open,setOpen]=useState(false),[selected,setSelected]=useState(version),[data,setData]=useState<Changes|null>(null),[error,setError]=useState('');
  const generation=useRef(0);
  useEffect(()=>{setSelected(version);setData(null);setError('');},[reviewId,version,base]);
  useEffect(()=>{
    const g=++generation.current;setData(null);setError('');if(!open)return;
    request<Changes>(`/${reviewId}/revisions/${selected}/changes`).then(value=>{if(g===generation.current)setData(value);}).catch(e=>{if(g===generation.current)setError(e.message);});
    return()=>{++generation.current;};
  },[request,reviewId,selected,version,open]);
  function showSource(pid:number){
    if(!data?.snapshot){onPaperCitation(pid);return;}
    const saved=data.evidence.filter(e=>e.paper_id===pid),paper=papers.find(p=>p.paper_id===pid);
    onSource({paper_id:pid,title:saved.find(e=>e.paper_title)?.paper_title??paper?.title??`论文 ${pid}`,status:'done',coverage:'',analysis:'',warning:'',reused:false,evidence:saved,
      context_note:saved.length?`v${data.version} 修订时保存的材料；研究笔记单独标明版本。`:`v${data.version} 未保存这篇论文的修订材料，可打开论文核对。`});
  }
  return <details className="card space-y-4" onToggle={e=>{if(e.target===e.currentTarget)setOpen(e.currentTarget.open);}}>
    <summary className="cursor-pointer font-semibold">查看修改对照</summary>
    <p className="text-sm text-muted">查看已保存版本的改动，对照来源，再按需继续修改。查看对照不调用模型。</p>
    <label className="block text-sm">对照版本<select className="input ml-2" aria-label="对照版本" value={selected} onChange={e=>setSelected(Number(e.target.value))}>{revisions.map(r=><option key={r.version} value={r.version}>v{r.version}{r.version===version?'（当前）':''}</option>)}</select></label>
    {error&&<p role="alert" className="text-sm text-red-600">{error}</p>}
    {open&&!data&&!error&&<p role="status">正在读取修改…</p>}
    {data&&<><p className="text-sm">v{data.base_version} → v{data.version} · {data.changes.length} 处改动{data.current_version!==data.version?` · 当前正文为 v${data.current_version}`:''}</p>
      {!data.snapshot&&<p className="text-xs text-muted">此版本提供正文差异；未记录当时的 AI 修改说明与材料快照，来源入口显示当前保存的论文材料。</p>}
      {!data.changes.length&&<p className="text-sm text-muted">本次未修改正文段落；文献清单或材料范围可能已更新。</p>}
      {data.changes.map((change,i)=><details className="border-t pt-3 space-y-3" style={{borderColor:'var(--border)'}} key={change.id}>
        <summary className="cursor-pointer break-words">{i+1}. {(change.after||change.before).replace(/\s+/g,' ').slice(0,100)}</summary>
        {change.reason&&<div className="text-sm"><p className="text-xs text-muted mb-1">AI 修改说明</p><MarkdownContent content={change.reason} onPaperCitation={showSource}/></div>}
        <div className="grid gap-4 lg:grid-cols-2"><div className="min-w-0"><p className="text-xs text-muted mb-2">修改前 · v{data.base_version}</p>{change.before?<MarkdownContent content={change.before} onPaperCitation={showSource}/>:<p className="text-sm text-muted">新增内容</p>}</div><div className="min-w-0"><p className="text-xs text-muted mb-2">修改后 · v{data.version}</p>{change.after?<MarkdownContent content={change.after} onPaperCitation={showSource}/>:<p className="text-sm text-muted">已删除</p>}</div></div>
        <div className="flex flex-wrap gap-2">{change.paper_ids.map(pid=><button className="btn-ghost text-xs" key={pid} onClick={()=>showSource(pid)}>查看 [P{pid}] 来源</button>)}{change.current_block_id?<button className="btn-primary text-xs" disabled={disabled} onClick={()=>onEdit(change.current_block_id!,data.current_version)}>继续修改这一段</button>:<span className="text-xs text-muted">该处已变化或涉及多个段落，可在“按段修改”中选择当前正文。</span>}</div>
      </details>)}
    </>}
  </details>;
}
