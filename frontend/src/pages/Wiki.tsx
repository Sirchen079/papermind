import { useCallback, useEffect, useState } from 'react';
import { useApi, useWorkspace } from '../workspaceContext';
import type { WikiPage, WikiSummary, WikiRevision } from '../wikiApi';
import type { Paper } from '../api';
import type { NavLocation } from './navigationModel';
import { usePaperDraft } from '../components/usePaperDraft';
import { Shell } from '../components/layout/Shell';
import { PageHeader } from '../components/ui/PageHeader';
import { MarkdownContent } from '../components/MarkdownContent';
import { CopyWikiPanel } from '../components/CopyWikiPanel';

const supportLabels:Record<string,string>={pending:'待核对',supported:'已核对支持关系',partial:'部分支持',unsupported:'来源不支持',unclear:'仍不明确'};
const jobLabels:Record<string,string>={queued:'等待生成',running:'正在整理',done:'候选已保存',failed:'更新失败',interrupted:'上次更新中断',conflict:'生成期间有其他修改'};
const scopeLabels:Record<string,string>={abstract:'论文摘要',full_text_span:'论文正文片段',excerpt:'研究者摘录',researcher_note:'研究者笔记',researcher_judgment:'研究判断',wiki_revision:'专题版本'};
const emptyDraft={version:-1,content:'',refs:'[]',review:'pending',note:'',requestId:''};
function refsFrom(raw:string):string[]{try{const value=JSON.parse(raw);return Array.isArray(value)?value.filter(v=>typeof v==='string'):[];}catch{return [];}}
function readingText(revision:WikiRevision){return revision.content.replace(/\[([WAP][a-f0-9]{24})\]/g,(match,ref)=>{const index=revision.references.indexOf(ref);return index<0?match:`[${index+1}]`;});}

export default function Wiki({params,onNavigate,onOpenPaper}:{params:Record<string,string>;onNavigate:(value:NavLocation|string)=>void;onOpenPaper:(id:number)=>void}){
  const {wikiApi,workspace}=useWorkspace();
  const [pages,setPages]=useState<WikiSummary[]>([]);
  const [query,setQuery]=useState('');
  const [archived,setArchived]=useState(false);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [draft,setDraft,clearDraft]=usePaperDraft(workspace.id,{title:'',requestId:''},'wiki-create');
  const refresh=useCallback(async()=>{setPages(await wikiApi.list(query,archived));},[wikiApi,query,archived]);
  useEffect(()=>{let alive=true;const timer=setTimeout(()=>wikiApi.list(query,archived).then(rows=>{if(alive)setPages(rows);}).catch(e=>{if(alive)setError(e.message);}),200);return()=>{alive=false;clearTimeout(timer);};},[wikiApi,query,archived]);
  async function create(e:React.FormEvent){
    e.preventDefault();if(busy)return;setBusy(true);setError('');
    const saved={...draft,requestId:draft.requestId||crypto.randomUUID()};setDraft(saved);
    try{const page=await wikiApi.create(saved.requestId,saved.title);clearDraft(saved);await refresh();onNavigate({page:'wiki',params:{page:page.id}});}catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <Shell className="space-y-5">
    <PageHeader title="专题知识" subtitle="围绕研究问题积累判断与证据，保留修订过程。"/>
    <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="card space-y-4 self-start">
        <label className="block text-sm">查找专题<input className="input w-full mt-1" value={query} onChange={e=>setQuery(e.target.value)}/></label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={archived} onChange={e=>setArchived(e.target.checked)}/>查看已归档专题</label>
        <div className="space-y-2">{pages.map(p=><button key={p.id} className="btn-ghost w-full text-left" aria-current={params.page===p.id?'page':undefined} onClick={()=>onNavigate({page:'wiki',params:{page:p.id}})}><span className="block break-words">{p.title}</span><span className="text-xs text-muted">{p.adopted_revision?`采用 v${p.adopted_revision}`:'尚未采用'}{p.latest_number?` · 最新 v${p.latest_number}`:''}</span></button>)}{pages.length===0&&<p className="text-sm text-muted">当前没有匹配的专题。</p>}</div>
        <form onSubmit={create} className="space-y-2 border-t border-[var(--border)] pt-3"><label className="block text-sm">新专题要回答什么问题？<textarea className="input w-full mt-1" rows={2} maxLength={300} required value={draft.title} disabled={busy} onChange={e=>setDraft({title:e.target.value,requestId:crypto.randomUUID()})}/></label><button className="btn-secondary" disabled={busy||!draft.title.trim()}>{busy?'正在创建…':'创建专题'}</button></form>
        {error&&<p role="alert" className="text-sm break-words">{error}</p>}
      </aside>
      {params.page?<Topic key={params.page} id={params.page} initialRevision={Number(params.revision)||null} onSelectRevision={number=>onNavigate({page:'wiki',params:{page:params.page,...(number===null?{}:{revision:String(number)})}})} onChanged={refresh} onOpenPaper={onOpenPaper}/>:<section className="card space-y-3 self-start"><h2 className="text-xl">让已有认识逐步积累</h2><p>可以从一个具体问题建页，添加论文生成候选，也可以把论文研究中的判断纳入专题。采用后的版本会供本项目问答按相关性检索。</p><p className="text-sm text-muted">材料变化检查在本机完成。点击“生成更新候选”才会调用模型。</p></section>}
    </div>
  </Shell>;
}

function Topic({id,initialRevision,onSelectRevision,onChanged,onOpenPaper}:{id:string;initialRevision:number|null;onSelectRevision:(number:number|null)=>void;onChanged:()=>Promise<void>;onOpenPaper:(id:number)=>void}){
  const api=useApi();const {wikiApi}=useWorkspace();
  const [page,setPage]=useState<WikiPage|null>(null);
  const number=initialRevision;
  const setNumber=onSelectRevision;
  const [historical,setHistorical]=useState<WikiRevision|null>(null);
  const [revisionError,setRevisionError]=useState('');
  const [revisionAttempt,setRevisionAttempt]=useState(0);
  useEffect(()=>{
    let alive=true;
    setHistorical(null);setRevisionError('');
    if(page&&number!==null&&number!==page.latest?.number&&number!==page.adopted?.number){
      wikiApi.revision(id,number).then(value=>{if(alive)setHistorical(value);}).catch(e=>{if(alive)setRevisionError(e.message);});
    }
    return()=>{alive=false;};
  },[wikiApi,id,number,page?.id,page?.latest?.number,page?.adopted?.number,revisionAttempt]);
  const [error,setError]=useState('');const [notice,setNotice]=useState('');const [busy,setBusy]=useState(false);
  const [draft,setDraft,clearDraft,storageError]=usePaperDraft(id,emptyDraft,'wiki-editor');
  const [paperQuery,setPaperQuery]=useState('');const [papers,setPapers]=useState<Paper[]>([]);
  const [materials,setMaterials,clearMaterials]=usePaperDraft(id,{ids:'[]',requestId:''},'wiki-materials');
  const selected:number[]=(()=>{try{return (JSON.parse(materials.ids) as unknown[]).filter((id):id is number=>typeof id==='number'&&Number.isInteger(id)&&id>0).slice(0,20);}catch{return [];}})();
  const setSelected=(value:number[]|((old:number[])=>number[]))=>{setMaterials({ids:JSON.stringify(typeof value==='function'?value(selected):value),requestId:crypto.randomUUID()});if(draft.version>=0)setDraft({...draft,requestId:crypto.randomUUID()});};
  const [retained,setRetained]=usePaperDraft(id,{job:'',requestId:'',version:-1},'wiki-retain');
  const [topicMaterials,setTopicMaterials,clearTopicMaterials]=usePaperDraft(id,{refs:'[]'},'wiki-topic-materials');
  const pageRefs:{page_id:string;number:number}[]=(()=>{try{return JSON.parse(topicMaterials.refs).filter((p:any)=>typeof p.page_id==='string'&&Number.isInteger(p.number)&&p.number>0).slice(0,5);}catch{return [];}})();
  const [relatedPages,setRelatedPages]=useState<WikiSummary[]>([]);
  useEffect(()=>{let alive=true;wikiApi.list().then(rows=>{if(alive)setRelatedPages(rows.filter(p=>p.id!==id&&p.adopted_revision));}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[wikiApi,id]);
  const [rename,setRename]=useState('');
  const refresh=useCallback(async()=>{const value=await wikiApi.get(id);setPage(value);return value;},[wikiApi,id]);
  useEffect(()=>{let alive=true;let timer:ReturnType<typeof setTimeout>;async function poll(){try{const value=await wikiApi.get(id);if(!alive)return;setPage(value);if(value.updates.some(j=>['queued','running'].includes(j.status)))timer=setTimeout(poll,1500);}catch(e:any){if(alive)setError(e.message);}}poll();return()=>{alive=false;clearTimeout(timer);};},[wikiApi,id,busy]);
  useEffect(()=>{let alive=true;const timer=setTimeout(()=>api.listPapers(20,0,paperQuery).then(result=>{if(alive)setPapers(result.items);}).catch(e=>{if(alive)setError(e.message);}),250);return()=>{alive=false;clearTimeout(timer);};},[api,paperQuery]);
  if(!page)return <section className="card"><p role={error?'alert':undefined}>{error||'正在读取专题…'}</p>{error&&<button className="btn-ghost" onClick={()=>refresh().catch(e=>setError(e.message))}>重新读取</button>}</section>;
  const current=page.latest;
  const view=number===null?(page.adopted||current):[page.latest,page.adopted,historical].find(r=>r?.number===number)||null;
  const editor=draft.version<0?{...emptyDraft,version:page.version,content:current?.content||'',refs:JSON.stringify(current?.references||[]),review:current?.support_status||'pending',note:current?.review_note||''}:draft;
  const selectedRefs=refsFrom(editor.refs);
  const dirty=draft.version>=0;
  const conflict=dirty&&draft.version!==page.version;
  const running=page.updates.some(j=>['queued','running'].includes(j.status));
  function edit(value:Partial<typeof emptyDraft>){setDraft({...editor,...value,requestId:crypto.randomUUID()});setNotice('');}
  async function act(action:()=>Promise<unknown>,message:string){if(busy)return;setBusy(true);setError('');setNotice('');try{await action();await refresh();await onChanged();setNotice(message);}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function save(){const submitted={...editor,requestId:editor.requestId||crypto.randomUUID()};setDraft(submitted);await act(async()=>{const value=await wikiApi.save(id,{request_id:submitted.requestId,expected_version:submitted.version,content:submitted.content,references:refsFrom(submitted.refs),paper_ids:selected,page_refs:pageRefs,cite_added:!!selected.length||!!pageRefs.length,support_status:submitted.review,review_note:submitted.note});clearDraft(submitted);clearMaterials(materials);clearTopicMaterials(topicMaterials);setNumber(value.latest?.number||null);},'修订已保存为新版本。');}
  async function retain(jobId:string){const submitted=retained.job===jobId&&retained.version===page!.version?retained:{job:jobId,requestId:crypto.randomUUID(),version:page!.version};setRetained(submitted);await act(async()=>{const result=await wikiApi.retain(jobId,{request_id:submitted.requestId,expected_version:submitted.version});setNumber(result.latest?.number||null);},'模型结果和引用已另存为候选。');}
  function loadVersion(revision:WikiRevision){setDraft({...emptyDraft,version:page!.version,content:revision.content,refs:JSON.stringify(revision.references),requestId:crypto.randomUUID()});setNotice('所选版本已载入编辑区，保存后会形成新的候选。');}
  return <section className="min-w-0 space-y-4">
    <div className="card space-y-3"><h2 className="text-xl break-words">{page.title}</h2><p className="text-sm text-muted">{page.adopted?`问答使用 v${page.adopted.number}`:'尚无采用版本，问答暂不检索此页'} · {page.archived?'已归档':'本项目专题'}</p>
      <details><summary className="cursor-pointer text-sm">专题信息与归档</summary><div className="flex flex-wrap gap-2 mt-2"><input aria-label="修改专题标题" className="input flex-1" value={rename} placeholder={page.title} maxLength={300} onChange={e=>setRename(e.target.value)}/><button className="btn-ghost" disabled={busy||!rename.trim()} onClick={()=>act(()=>wikiApi.patch(id,{expected_version:page.version,title:rename}),'专题标题已更新。')}>保存标题</button><button className="btn-ghost" disabled={busy||running} onClick={()=>act(()=>wikiApi.patch(id,{expected_version:page.version,archived:!page.archived}),page.archived?'专题已恢复。':'专题已归档。')}>{page.archived?'恢复专题':'归档专题'}</button></div></details>
      {page.copied_from&&<p className="text-sm text-muted">复制自“{page.copied_from.source_name}”的“{page.copied_from.source_title}”v{page.copied_from.source_revision}。跨项目引用保留复制时的快照。</p>}
      {error&&<p role="alert" className="text-sm break-words" style={{color:'var(--danger)'}}>{error}</p>}{notice&&<p role="status" className="text-sm">{notice}</p>}
      {!!page.changes.length&&<div className="text-sm space-y-1"><strong>{page.adopted?'当前采用版本':'最新版本'}的来源有变化</strong>{page.changes.map((c,i)=><p key={i}>{c.title}：{c.reason}</p>)}</div>}
      <button className="btn-ghost text-sm" disabled={busy} onClick={()=>act(async()=>{},'已检查本地来源变化。')}>检查来源变化</button>
    </div>
    {number!==null&&!view&&<div className="card space-y-2"><p role={revisionError?'alert':'status'}>{revisionError||`正在读取 v${number}…`}</p>{revisionError&&<button className="btn-ghost" onClick={()=>setRevisionAttempt(value=>value+1)}>重新读取此版本</button>}<button className="btn-ghost" onClick={()=>setNumber(null)}>查看当前采用版本</button></div>}
    {view&&<article className="card space-y-4">
      <div className="flex flex-wrap items-center gap-3"><label className="text-sm">阅读版本 <select className="input" value={view.number} onChange={e=>setNumber(Number(e.target.value))}>{page.history.map(r=><option key={r.number} value={r.number}>v{r.number} · {page.adopted_revision===r.number?'已采用':'候选/历史'} · {r.origin==='model'?'模型整理':r.origin==='copied'?'复制快照':'人工记录'}</option>)}</select></label><span className="chip">{supportLabels[view.support_status]}</span><a className="btn-ghost text-sm" href={wikiApi.exportUrl(id,view.number)}>导出此版本</a></div>
      <MarkdownContent content={readingText(view)}/>{view.change_note&&<p className="text-sm text-muted">变化说明：{view.change_note}</p>}{view.review_note&&<p className="text-sm">核对备注：{view.review_note}</p>}
      <div className="flex flex-wrap gap-2"><button className="btn-secondary" disabled={busy||dirty||page.archived||page.adopted_revision===view.number} onClick={()=>act(()=>wikiApi.adopt(id,page.version,view.number),'采用版本已更新。')}>{page.adopted_revision===view.number?'正在采用此版本':'采用这个版本'}</button><button className="btn-ghost" disabled={busy||page.archived} onClick={()=>loadVersion(view)}>载入编辑区</button></div>
      <details><summary className="cursor-pointer">查看此版本的引用快照（{view.references.length}）</summary><div className="space-y-3 mt-3">{view.evidence.filter(e=>view.references.includes(e.ref)).map(e=><div key={e.ref} className="border-l-2 border-[var(--border)] pl-3"><p className="text-sm">{e.title} · {e.locator} · {scopeLabels[e.scope]||e.scope}</p><p className="text-xs text-muted">证据 [{view.references.indexOf(e.ref)+1}]</p>{e.captured_from&&<p className="text-sm text-muted">来自“{e.captured_from.name}”的独立快照</p>}<blockquote className="whitespace-pre-wrap text-sm my-2">{e.quote}</blockquote>{e.paper_id&&<button className="btn-ghost text-xs" onClick={()=>onOpenPaper(e.paper_id!)}>打开原论文</button>}{!!e.underlying_evidence?.length&&<details><summary className="text-sm cursor-pointer">底层依据快照</summary>{e.underlying_evidence.map((s,i)=><p key={i} className="text-sm whitespace-pre-wrap mt-2">{s.title} · {s.locator}<br/>{s.quote}</p>)}</details>}</div>)}</div></details>
      <CopyWikiPanel key={`${id}:${view.number}`} id={id} number={view.number}/>
    </article>}
    {!page.archived&&<div className="card space-y-4">
      <h3 className="font-semibold">编辑与补充材料</h3>
      {conflict&&<div role="alert" className="text-sm space-y-2"><p>服务器已有修改，你的本机草稿仍保留。核对后可以将它另存为候选。</p><button className="btn-secondary" onClick={()=>edit({version:page.version})}>按当前版本另存这份草稿</button></div>}
      {storageError&&<p className="text-sm">浏览器暂时无法持久保存草稿，请在关闭窗口前保存正文。</p>}
      <label className="block text-sm">专题正文<textarea className="input block w-full mt-1" rows={10} maxLength={16000} value={editor.content} onChange={e=>edit({content:e.target.value,review:'pending',note:''})}/></label>
      {!!relatedPages.length&&<details><summary className="cursor-pointer text-sm">引用本项目其他专题（已选 {pageRefs.length}，每次最多 5 页）</summary><div className="space-y-2 mt-2">{relatedPages.map(p=>{const chosen=pageRefs.find(r=>r.page_id===p.id);return <label key={p.id} className="flex gap-2 text-sm"><input type="checkbox" checked={!!chosen} disabled={busy||(!chosen&&pageRefs.length>=5)} onChange={()=>{setTopicMaterials({refs:JSON.stringify(chosen?pageRefs.filter(r=>r.page_id!==p.id):[...pageRefs,{page_id:p.id,number:p.adopted_revision}])});if(draft.version>=0)edit({requestId:crypto.randomUUID()});}}/>{p.title} · v{chosen?.number||p.adopted_revision}</label>;})}</div><p className="text-xs text-muted mt-2">保存修订时纳入选定版本及底层依据。之后可以生成更新候选。</p></details>}
      <details><summary className="cursor-pointer text-sm">选择已有证据（{selectedRefs.length}）</summary><div className="space-y-2 mt-2 max-h-64 overflow-auto">{current?.evidence.map(e=><label key={e.ref} className="flex gap-2 text-sm"><input type="checkbox" checked={selectedRefs.includes(e.ref)} onChange={()=>edit({refs:JSON.stringify(selectedRefs.includes(e.ref)?selectedRefs.filter(r=>r!==e.ref):[...selectedRefs,e.ref]),review:'pending',note:''})}/><span>{e.title} · {e.locator}</span></label>)}</div></details>
      <details><summary className="cursor-pointer text-sm">本次补充论文（已选 {selected.length}，每批最多 20 篇）</summary><label className="block text-sm mt-3">检索项目论文<input className="input block w-full mt-1" value={paperQuery} onChange={e=>setPaperQuery(e.target.value)}/></label><div className="space-y-2 mt-3 max-h-60 overflow-auto">{papers.map(p=><label key={p.id} className="flex gap-2 text-sm"><input type="checkbox" checked={selected.includes(p.id)} disabled={!selected.includes(p.id)&&selected.length>=20} onChange={()=>setSelected(old=>old.includes(p.id)?old.filter(v=>v!==p.id):[...old,p.id])}/><span>{p.title}</span></label>)}</div><p className="text-xs text-muted mt-2">保存修订会加入选中论文的证据快照。专题可以通过多次补充持续积累材料。</p></details>
      <details><summary className="cursor-pointer text-sm">记录支持关系核对</summary><div className="space-y-2 mt-2"><select aria-label="专题支持关系" className="input" value={editor.review} onChange={e=>edit({review:e.target.value})}>{Object.entries(supportLabels).map(([v,label])=><option value={v} key={v}>{label}</option>)}</select><textarea aria-label="专题核对依据与限制" className="input block w-full" maxLength={3000} rows={3} value={editor.note} onChange={e=>edit({note:e.target.value})}/></div></details>
      <div className="flex flex-wrap gap-2"><button className="btn-primary" disabled={busy||conflict||!editor.content.trim()} onClick={save}>保存修订</button><button className="btn-secondary" disabled={busy||dirty||running||!!pageRefs.length} onClick={()=>act(()=>wikiApi.update(id,{request_id:crypto.randomUUID(),expected_version:page.version,paper_ids:selected}),'更新任务已提交，完成后会保留为候选版本。')}>{running?'正在生成候选…':'生成更新候选'}</button>{dirty&&<button className="btn-ghost" disabled={busy} onClick={()=>clearDraft(draft)}>丢弃本机编辑</button>}</div><p className="text-xs text-muted">模型会读取已保存正文与本轮材料，生成候选版本。人工修改先保存，再提交更新。</p>
    </div>}
    {!!page.updates.length&&<section className="card space-y-3"><h3 className="font-semibold">更新记录</h3>{page.updates.map(job=><div className="border-t border-[var(--border)] pt-3" key={job.id}><p className="text-sm">{jobLabels[job.status]||job.status}{job.revision_number?` · v${job.revision_number}`:''}</p>{job.error&&<p className="text-sm break-words mt-1">{job.error}</p>}{['failed','interrupted'].includes(job.status)&&<button className="btn-ghost text-sm" disabled={busy||running||page.archived} onClick={()=>act(()=>wikiApi.retry(job.id),'已重新提交更新任务。')}>重试这次更新</button>}{job.status==='conflict'&&job.result&&<details><summary className="cursor-pointer text-sm">查看保留的模型候选</summary><MarkdownContent content={job.result.content}/><button className="btn-secondary text-sm mt-2" disabled={busy||dirty||page.archived} onClick={()=>retain(job.id)}>将结果与引用另存为候选</button><p className="text-xs text-muted mt-2">另存后可载入编辑区继续核对，人工修订保留在历史中。</p></details>}</div>)}</section>}
  </section>;
}
