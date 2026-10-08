import { useEffect, useMemo, useRef, useState } from 'react';
import { useApi, useWorkspace, workspaceDraftKey } from '../workspaceContext';
import { Shell } from '../components/layout/Shell';
import { MarkdownContent } from '../components/MarkdownContent';
import { ReviewChanges } from '../components/ReviewChanges';
import { ReviewMap } from '../components/ReviewMap';
import { ReviewParagraphEditor } from '../components/ReviewParagraphEditor';
import {createReviewRequest,type LibraryReviewDetail as Review,type ReviewSource as Source} from '../reviewsApi';
import type { NavLocation } from './navigationModel';
import type { Paper } from '../api';

const labels:Record<string,string>={draft:'待开始',running:'正在生成',ready:'已生成',partial:'部分完成',paused:'已暂停',needs_input:'等待材料或模型',done:'已分析',fallback:'保留已有材料',missing:'缺少可读材料',pending:'待分析'};

export default function LibraryReview({params,onNavigate,onOpenPaper}:{params:Record<string,string>;onNavigate:(target:NavLocation|string)=>void;onOpenPaper:(id:number,page?:number)=>void}) {
  const {base,workspace}=useWorkspace();const api=useApi();
  const [history,setHistory]=useState<Review[]>([]),[job,setJob]=useState<Review|null>(null);
  const [topic,setTopic]=useState(''),[whole,setWhole]=useState(true),[selected,setSelected]=useState<number[]>([]);
  const [query,setQuery]=useState(''),[offset,setOffset]=useState(0),[items,setItems]=useState<Paper[]>([]),[total,setTotal]=useState(0);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[filter,setFilter]=useState(''),[page,setPage]=useState(0);
  const [source,setSource]=useState<Source|null>(null),[editor,setEditor]=useState<string|null>(null),[editVersion,setEditVersion]=useState(0);
  const [editSelection,setEditSelection]=useState<{id:string;version:number;request:number}|null>(null);
  const editRequest=useRef(0);
  const [oldVersion,setOldVersion]=useState<{version:number;content:string}|null>(null);
  const id=params.review;const current=useRef(id);current.current=id;const generation=useRef(0);const editorRef=useRef(editor);editorRef.current=editor;
  const requestId=useRef(crypto.randomUUID());
  const request=useMemo(()=>createReviewRequest(base),[base]);
  useEffect(()=>{let alive=true;request<Review[]>('').then(x=>{if(alive)setHistory(x);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[request,id,job?.status]);
  useEffect(()=>{
    let alive=true;const timer=setTimeout(()=>api.listPapers(30,offset,query).then(r=>{if(alive){setItems(r.items);setTotal(r.total);}}).catch(e=>{if(alive)setError(e.message);}),200);
    return()=>{alive=false;clearTimeout(timer);};
  },[api,query,offset]);
  useEffect(()=>{
    const g=++generation.current;setJob(null);setSource(null);setEditor(null);setOldVersion(null);setEditSelection(null);setError('');setBusy(false);setPage(0);setFilter('');setSelected([]);requestId.current=crypto.randomUUID();
    if(!id)return;
    request<Review>('/'+id).then(x=>{if(g!==generation.current)return;setJob(x);
      try {const saved=localStorage.getItem(workspaceDraftKey(workspace.id,'review-edit-'+id));if(saved){const draft=JSON.parse(saved);setEditor(draft.content);setEditVersion(draft.version);}}catch{/* editor still usable */}
    }).catch(e=>{if(g===generation.current)setError(e.message);});
    return()=>{++generation.current;};
  },[id,request,workspace.id]);
  useEffect(()=>{
    if(!id||job?.status!=='running')return;
    let alive=true,pending=false;const timer=setInterval(async()=>{if(pending)return;pending=true;try{const next=await request<Review>('/'+id);if(alive)setJob(next);}catch(e){if(alive)setError((e as Error).message);}finally{pending=false;}},2500);
    return()=>{alive=false;clearInterval(timer);};
  },[id,job?.status,request]);
  useEffect(()=>{if(!id||editor===null)return;try{localStorage.setItem(workspaceDraftKey(workspace.id,'review-edit-'+id),JSON.stringify({content:editor,version:editVersion}));}catch{setError('本机草稿暂时无法保存，请下载或保存编辑。');}},[editor,editVersion,id,workspace.id]);
  async function action(name:string,body:unknown={}) {
    if(!id)return;const g=generation.current;const submitted=editor;setBusy(true);setError('');
    try{const next=await request<Review>('/'+id+'/'+name,body);if(g!==generation.current)return;setJob(next);
      if(name==='content'){setEditVersion(next.version);if(editorRef.current===submitted){setEditor(null);try{localStorage.removeItem(workspaceDraftKey(workspace.id,'review-edit-'+id));}catch{/* saved remotely */}}}
    }catch(e){if(g===generation.current)setError((e as Error).message);}finally{if(g===generation.current)setBusy(false);}
  }
  async function create(){const g=generation.current;setBusy(true);setError('');try{
    const next=await request<Review>('',{request_id:requestId.current,question:topic,paper_ids:selected,whole_library:whole});
    if(g!==generation.current)return;onNavigate({page:'research',params:{mode:'review',review:next.id}});
    await request('/'+next.id+'/run',{});if(current.current===next.id)setJob(await request<Review>('/'+next.id));
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function showSource(pid:number){const g=generation.current;try{const next=await request<Source>(`/${id}/papers/${pid}`);if(g===generation.current)setSource(next);}catch(e){setError((e as Error).message);}}
  async function continueResearch(){
    if(!job||busy)return;const g=generation.current;setBusy(true);setError('');
    try{const conversation=await api.createConversation();if(g!==generation.current)return;
      onNavigate({page:'chat',params:{conversation:String(conversation.id),review:job.id}});
    }catch(e){if(g===generation.current)setError((e as Error).message);}finally{if(g===generation.current)setBusy(false);}
  }
  function download(text:string,name:string,type='text/markdown'){const url=URL.createObjectURL(new Blob([text],{type:type+';charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function coverage(){try{const res=await fetch(`${base}/reviews/${id}/export?kind=coverage`);if(!res.ok)throw new Error('覆盖清单下载失败');download(await res.text(),'综述材料清单.jsonl','application/x-ndjson');}catch(e){setError((e as Error).message);}}
  const filtered=(job?.papers??[]).filter(p=>!filter||p.title.toLowerCase().includes(filter.toLowerCase())||String(p.paper_id)===filter);
  const running=job?.status==='running';
  const picker=<div className="space-y-3"><input className="input w-full" aria-label="搜索综述论文" placeholder="搜索论文" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0);}}/>
    <div className="flex flex-wrap gap-2"><button className="btn-ghost" onClick={()=>setSelected(old=>Array.from(new Set([...old,...items.map(p=>p.id)])).slice(0,1000))}>选择本页</button><button className="btn-ghost" onClick={()=>setSelected([])}>清空选择</button><span className="text-sm text-muted">已选 {selected.length} 篇</span></div>
    <div className="grid gap-2 md:grid-cols-2">{items.map(p=><label className="paper-option" key={p.id}><input type="checkbox" checked={selected.includes(p.id)} disabled={!selected.includes(p.id)&&selected.length>=1000} onChange={()=>setSelected(old=>old.includes(p.id)?old.filter(x=>x!==p.id):[...old,p.id])}/><span className="break-words">{p.title??`论文 ${p.id}`}</span></label>)}</div>
    <div className="flex gap-3"><button className="btn-ghost" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</button><span className="text-sm text-muted">共 {total} 篇</span><button className="btn-ghost" disabled={offset+30>=total} onClick={()=>setOffset(offset+30)}>下一页</button></div></div>;
  return <Shell max="wide"><div className="space-y-6">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="page-title">专题综述</h1><p className="page-subtitle mt-2">从最多 1000 篇论文中梳理研究路线、比较结果，形成可以继续修改的综述。</p></div><div className="flex gap-2"><button className="btn-ghost" onClick={()=>onNavigate({page:'research',params:{}})}>少量论文比较</button><button className="btn-ghost" onClick={()=>onNavigate({page:'research',params:{mode:'review'}})}>新建综述</button></div></div>
    {error&&<p className="card text-red-600" role="alert">{error}</p>}
    {!id&&<section className="research-composer space-y-5"><p className="text-sm text-muted">内置 Nature Writing · Oh My Paper：先组织论证，再分章写作与整篇修订。</p><label className="block">综述主题与关注问题<textarea className="input w-full mt-2" aria-label="综述主题" rows={3} value={topic} onChange={e=>{setTopic(e.target.value);requestId.current=crypto.randomUUID();}} placeholder="例如：梳理检索增强生成的方法演进，比较检索、证据利用与评测方式。"/></label>
      <div className="flex gap-4"><label><input type="radio" checked={whole} onChange={()=>setWhole(true)}/> 当前整个论文库</label><label><input type="radio" checked={!whole} onChange={()=>setWhole(false)}/> 自选论文</label></div>
      {!whole&&picker}<p className="text-sm text-muted">逐篇保存进度，可暂停后继续。部分论文缺少全文时会使用摘要并说明范围，其他材料正常生成。首次分析会产生模型调用费用，后续优先复用已有结果。</p>
      <button className="btn-primary" disabled={busy||!topic.trim()||(!whole&&!selected.length)} onClick={create}>{busy?'正在创建…':'开始整理综述'}</button>
    </section>}
    {id&&!job&&!error&&<p role="status">正在读取任务…</p>}
    {job&&<>
      <section className="card space-y-3"><h2 className="text-lg font-semibold">{job.question}</h2><p role="status">{job.stage}</p>
        <div className="flex flex-wrap items-center gap-3"><button className="btn-ghost" disabled={busy} onClick={continueResearch}>与 AI 继续研究</button><span className="text-sm text-muted">带上已保存的分析和草稿，继续比较、追问或讨论下一步。</span></div>
        {job.content&&<p className="text-sm text-muted">新增论文或修改论文笔记后，点击更新即可沿当前正文修改相关段落，复用未变的分析；已有版本可在历史中查看。</p>}
        <p className="text-xs text-muted">论文材料整理进度 · 完成后继续综合与写作</p>
        <progress className="w-full" aria-label="论文材料整理进度" value={job.counts.total-job.counts.pending} max={job.counts.total||1}/><p className="text-sm text-muted">共 {job.counts.total} 篇 · 已分析 {job.counts.done} · 保留材料 {job.counts.fallback} · 缺少材料 {job.counts.missing} · 复用 {job.counts.reused}</p>
        {job.error&&<p className="text-sm text-amber-700">{job.error}</p>}<div className="flex flex-wrap gap-2">{running?<button className="btn-ghost" disabled={busy} onClick={()=>action('stop')}>暂停</button>:<button className="btn-primary" disabled={busy} onClick={()=>action('run')}>{job.content?'更新综述 / 重试未完成内容':'继续生成'}</button>}
          <button className="btn-ghost" disabled={!job.content} onClick={()=>download(job.content,'专题综述.md')}>下载综述</button><button className="btn-ghost" onClick={coverage}>下载材料清单</button>
          {!running&&job.content&&editor===null&&<button className="btn-ghost" onClick={()=>{setEditor(job.content);setEditVersion(job.version);}}>编辑正文</button>}</div>
      </section>
      {editor!==null&&<section className="card space-y-3"><p className="text-sm">正在编辑 v{editVersion}，当前版本 v{job.version}。编辑时仍可下载本机草稿。</p><textarea className="input w-full font-mono" aria-label="综述正文编辑" rows={24} value={editor} onChange={e=>setEditor(e.target.value)}/><div className="flex gap-2"><button className="btn-primary" disabled={busy||running} onClick={()=>action('content',{content:editor,expected_version:editVersion})}>保存版本</button><button className="btn-ghost" onClick={()=>download(editor,'综述编辑草稿.md')}>下载草稿</button></div></section>}
      {!!job.sections.length&&<details className="card space-y-4" open={!job.content}>
        <summary>已保存的章节草稿 · {job.sections.length} 章</summary>
        <p className="text-sm text-muted">{running?'章节会随生成逐步更新，尚未更新的章节可能沿用已有草稿。修订完成后的综述单独保存。':'这是分章写作时保存的草稿；最终修订可能调整结构和措辞。'}</p>
        <button className="btn-ghost" onClick={()=>download('# 章节草稿\n\n'+job.sections.map(s=>'## '+s.title+'\n\n'+(s.warning?'> 处理提示：'+s.warning+'\n\n':'')+s.content).join('\n\n'),'综述章节草稿.md')}>下载章节草稿</button>
        {job.sections.map(s=><article className="space-y-3 border-t pt-4" style={{borderColor:'var(--border)'}} key={s.id}><h2 className="text-lg font-semibold">{s.title}</h2>{s.warning&&<p className="text-sm" style={{color:'var(--warning)'}}>处理提示：{s.warning}</p>}<MarkdownContent content={s.content} onPaperCitation={showSource}/></article>)}
      </details>}
      {job.content&&<ReviewChanges reviewId={job.id} version={job.version} revisions={job.revisions} papers={job.papers} disabled={!!running||editor!==null} onEdit={(id,version)=>setEditSelection({id,version,request:++editRequest.current})} onSource={setSource} onPaperCitation={showSource}/>}
      {job.content&&<article className="card"><MarkdownContent content={job.content} onPaperCitation={showSource}/></article>}
      {job.content&&<ReviewParagraphEditor selection={editSelection} reviewId={job.id} version={job.version} disabled={running||editor!==null} onSaved={async()=>{const g=generation.current;const next=await request<Review>('/'+job.id);if(g===generation.current)setJob(next);}}/>}
      {!!job.writing_skills?.length&&<details className="card space-y-3"><summary>写作技能与论证依据</summary><p className="text-sm text-muted">本次实际加载：{[...new Set(job.writing_skills.map(s=>s.id+(s.version?' v'+s.version:'')))].join(' · ')}</p>{job.writing_skills.some(s=>s.stage)&&<p className="text-sm text-muted">按阶段选用规范：{[...new Set(job.writing_skills.map(s=>({plan:'论证规划',intro:'开篇写作','related-work':'主题比较',discussion:'综合讨论',edit:'正文修订',update:'局部更新',synthesis:'材料归纳',outline:'章节组织'}[s.stage||'']||s.stage)).filter(Boolean))].join('、')}。完整技能保留在技能库中，本次请求按上下文容量选取原文段落。</p>}{job.writing_notes&&<MarkdownContent content={job.writing_notes}/>}</details>}
      {job.revisions.length>1&&<details className="card"><summary>历史版本</summary>{job.revisions.map(v=><button className="btn-ghost" key={v.version} onClick={async()=>{const g=generation.current;try{const old=await request<{version:number;content:string}>(`/${id}/revisions/${v.version}`);if(g===generation.current)setOldVersion(old);}catch(e){if(g===generation.current)setError((e as Error).message);}}}>v{v.version}</button>)}{oldVersion&&<><button className="btn-ghost" onClick={()=>download(oldVersion.content,`综述-v${oldVersion.version}.md`)}>下载 v{oldVersion.version}</button><button className="btn-primary" disabled={busy||running||editor!==null||oldVersion.content===job.content} onClick={()=>action(`revisions/${oldVersion.version}/restore`,{expected_version:job.version})}>恢复为当前版本</button><MarkdownContent content={oldVersion.content}/></>}</details>}
      {!running&&<details className="card space-y-3"><summary>加入新论文，更新这份综述</summary>{picker}<button className="btn-primary" disabled={busy||!selected.length} onClick={()=>action('papers',{paper_ids:selected})}>加入所选论文</button></details>}
      <ReviewMap reviewId={job.id} onOpenPaper={onOpenPaper}/>
      <section className="card space-y-3"><h2 className="text-lg">论文分析与来源</h2><p className="text-sm text-muted">正文的 [P编号] 对应下方记录；可搜索编号查看当时使用的原文片段与研究笔记。</p><input className="input w-full" placeholder="搜索标题或 P 后的编号" aria-label="筛选综述来源" value={filter} onChange={e=>{setFilter(e.target.value.replace(/^P/i,''));setPage(0);}}/>
        {filtered.slice(page*20,page*20+20).map(p=><button key={p.paper_id} className="shelf-paper w-full text-left" onClick={()=>showSource(p.paper_id)}><span className="shelf-paper-content"><span>[P{p.paper_id}] {p.title}</span><span className="shelf-paper-meta">{labels[p.status]}{p.warning?' · '+p.warning:''}</span></span></button>)}
        <div className="flex gap-2"><button className="btn-ghost" disabled={!page} onClick={()=>setPage(page-1)}>上一页</button><button className="btn-ghost" disabled={(page+1)*20>=filtered.length} onClick={()=>setPage(page+1)}>下一页</button></div>
      </section>
      {source&&<aside aria-label="综述来源材料" className="card fixed right-4 top-16 bottom-4 z-50 w-[min(520px,calc(100vw-32px))] overflow-y-auto shadow-xl space-y-4"><div className="flex justify-between gap-3"><h2 className="min-w-0 break-words">[P{source.paper_id}] {source.title}</h2><button className="btn-ghost shrink-0 whitespace-nowrap" onClick={()=>setSource(null)}>关闭</button></div><button className="btn-ghost" onClick={()=>onOpenPaper(source.paper_id)}>打开论文</button><p className="text-sm text-muted">{source.context_note}</p><MarkdownContent content={source.analysis}/>{source.evidence.map((e,i)=><blockquote key={i} className="border-l-2 pl-3 text-sm whitespace-pre-wrap"><div className="flex flex-wrap items-center gap-2"><p className="text-muted">{e.locator}</p>{e.scope==='researcher_note'&&<span className="text-xs text-muted">分析时保存的笔记版本；不代表已核对或采用</span>}{[...new Set([e.page,...(e.segments??[]).map(s=>s.page)].filter((p):p is number=>typeof p==='number'&&Number.isInteger(p)&&p>0))].map(p=><button key={p} className="btn-ghost text-xs" onClick={()=>onOpenPaper(source.paper_id,p)}>查看 PDF 第 {p} 页</button>)}</div>{e.quote}</blockquote>)}</aside>}
    </>}
    <section className="space-y-2"><h2 className="text-lg">最近综述</h2>{history.map(r=><button key={r.id} className="shelf-paper w-full text-left" onClick={()=>onNavigate({page:'research',params:{mode:'review',review:r.id}})}>{r.question}<span className="ml-3 text-sm text-muted">{labels[r.status]}</span></button>)}</section>
  </div></Shell>;
}
