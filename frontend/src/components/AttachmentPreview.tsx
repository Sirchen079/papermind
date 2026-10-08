import {documentIdentityLabel} from '../pages/documentIdentityModel';
import {useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {ChatAttachment,DocumentGenerationRequest,DocumentInput,SavedDocumentReference,Source,WebSource} from '../api';
import {useWorkspace} from '../workspaceContext';
import {createReviewRequest,type LibraryReviewDetail,type ReviewSource} from '../reviewsApi';
import {supportLabels} from '../researchApi';
import {artifactReference,attachmentPassage,exactResearchArtifact,type ArtifactReference} from '../pages/attachmentPreviewModel';
import {Drawer} from './ui/Drawer';
import {MarkdownContent} from './MarkdownContent';
import {ChatWebSources} from './ChatWebSources';
import {SavedPaperSources} from './SavedPaperSources';
import {researchScopeKind} from '../pages/sourcePresentationModel';
import {X} from '../icons';
import {DocumentGenerationContext} from './DocumentGenerationContext';
import {DocumentInputs} from './DocumentInputs';

type Preview={title:string;description:string;content:string;note?:string;sources:Source[];web:WebSource[];review?:LibraryReviewDetail;generationRequest?:DocumentGenerationRequest|null;inputDocuments?:DocumentInput[]};
type Actions={onOpenPaper:(id:number,page?:number)=>void;onOpenDocument:(ref:SavedDocumentReference)=>void};

function ArtifactPreview({reference,passage,onClose,onOpenPaper,onOpenDocument}:{reference:ArtifactReference;passage:string;onClose:()=>void}&Actions) {
  const {api,researchApi,base}=useWorkspace();
  const request=useMemo(()=>createReviewRequest(base),[base]);
  const [preview,setPreview]=useState<Preview|null>(null),[error,setError]=useState(''),[reload,setReload]=useState(0);
  const [sourceId,setSourceId]=useState<number|null>(null),[source,setSource]=useState<ReviewSource|null>(null),[sourceError,setSourceError]=useState(''),[sourceReload,setSourceReload]=useState(0);
  const sourcePanel=useRef<HTMLElement>(null);
  useEffect(()=>{if(sourceId!==null)sourcePanel.current?.scrollIntoView({block:'nearest'});},[sourceId]);
  const [filter,setFilter]=useState(''),[page,setPage]=useState(0);
  useEffect(()=>{
    let active=true;setPreview(null);setError('');
    async function read():Promise<Preview> {
      if(reference.kind==='document') {
        const doc=await api.getSavedDocument(reference.message_id,reference.filename);
        return {title:doc.filename,description:`${documentIdentityLabel(doc)} · ${new Date(doc.created_at).toLocaleString()} · ${doc.conversation_title}`,
          content:doc.content,sources:doc.sources,web:doc.web_sources??[],generationRequest:doc.generation_request,inputDocuments:doc.input_documents,note:doc.newer_versions.length?'已有后续修订；这里显示本轮关联的版本。':undefined};
      }
      if(reference.kind==='research') {
        const task=await researchApi.get(reference.task_id),artifact=exactResearchArtifact(task,reference.version);
        return {title:task.question,description:`论文研究 v${artifact.version} · ${supportLabels[artifact.support_status]??artifact.support_status} · ${artifact.adopted?'已采用':'草稿'}`,
          content:artifact.content,web:[],sources:artifact.evidence_snapshot.map(e=>({paper_id:e.paper_id,title:e.title,snippet:e.quote,locator:`${e.ref} · ${e.locator}`,pages:e.page?[e.page]:[],material_kind:researchScopeKind(e.scope)})),
          note:task.artifact&&task.artifact.version!==artifact.version?`已有 v${task.artifact.version}；这里保留本轮关联的 v${artifact.version}。`:artifact.review_note||undefined};
      }
      const review=await request<LibraryReviewDetail>('/'+encodeURIComponent(reference.review_id));
      return {title:review.question,description:`专题综述 · 打开时为 v${review.version} · ${review.stage}`,
        content:review.content||review.sections.map(s=>`## ${s.title}\n\n${s.warning?'> '+s.warning+'\n\n':''}${s.content}`).join('\n\n'),
        note:`此链接关联持续更新的任务，AI 读取时会使用当时的内容。${!review.content?'当前显示已保存的章节草稿。':''}`,
        sources:[],web:[],review};
    }
    read().then(value=>{if(active)setPreview(value);}).catch(e=>{if(active)setError(e instanceof Error?e.message:'读取失败，请重试。');});
    return()=>{active=false;};
  },[api,researchApi,request,reference,reload]);
  useEffect(()=>{
    let active=true;setSource(null);setSourceError('');
    if(reference.kind==='review'&&sourceId!==null)request<ReviewSource>(`/${encodeURIComponent(reference.review_id)}/papers/${sourceId}`)
      .then(value=>{if(active)setSource(value);}).catch(e=>{if(active)setSourceError(e.message);});
    return()=>{active=false;};
  },[request,reference,sourceId,sourceReload]);
  function openPaper(id:number,page?:number){onClose();onOpenPaper(id,page);}
  const sourceRows=source?.evidence.map(e=>({paper_id:source.paper_id,title:source.title,snippet:e.quote,locator:e.locator,material_kind:researchScopeKind(e.scope),pages:[e.page,...(e.segments??[]).map(s=>s.page)].filter((p):p is number=>p!==undefined)}))??[];
  const filtered=preview?.review?.papers.filter(p=>!filter||p.title.toLowerCase().includes(filter.toLowerCase())||String(p.paper_id)===filter.replace(/^P/i,''))??[];
  return createPortal(<Drawer open title="关联成果" onClose={onClose} width="max-w-3xl"><div className="min-w-0 space-y-4" data-attachment-artifact>
    {passage&&<section className="rounded-lg border border-[var(--border)] p-3 space-y-2" aria-label="本轮待核查选文"><h4 className="text-sm font-medium">本轮待核查选文</h4><blockquote className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-sm">{passage}</blockquote></section>}
    {!preview&&!error&&<p role="status">正在读取已保存内容…</p>}
    {error&&<div role="alert" className="space-y-2"><p className="break-words text-sm">{error}</p><button className="btn-ghost" onClick={()=>setReload(n=>n+1)}>重试读取</button></div>}
    {preview&&<>
      <h4 className="break-words font-semibold">{preview.title}</h4><p className="text-xs text-muted">{preview.description}</p>
      {preview.note&&<p className="text-sm text-muted">{preview.note}</p>}
      <DocumentGenerationContext request={preview.generationRequest} onNavigate={onClose}/>
      <DocumentInputs documents={preview.inputDocuments} onOpen={ref=>{onClose();onOpenDocument(ref);}}/>
      {reference.kind==='document'&&<button className="btn-ghost" onClick={()=>{onClose();onOpenDocument(reference);}}>查看文档、修订与选文</button>}
      {reference.kind!=='document'&&<a className="btn-ghost inline-block" onClick={onClose} href={reference.kind==='research'?`#research?task=${encodeURIComponent(reference.task_id)}`:`#research?mode=review&review=${encodeURIComponent(reference.review_id)}`}>打开研究任务</a>}
      <article aria-label="关联成果正文">{preview.content?<MarkdownContent content={preview.content} onPaperCitation={id=>setSourceId(id)}/>:<p className="text-sm text-muted">尚未保存正文，可先查看已有的论文材料。</p>}</article>
      {sourceId!==null&&<section ref={sourcePanel} className="rounded-lg border border-[var(--border)] p-3 space-y-3" aria-label="引用来源">
        <div className="flex items-center justify-between"><h4 className="text-sm font-medium">[P{sourceId}] 引用来源</h4><button className="btn-ghost" onClick={()=>setSourceId(null)}>收起来源</button></div>
        {reference.kind==='review'?<>
          {sourceError?<p role="alert">{sourceError}<button className="btn-ghost" onClick={()=>setSourceReload(n=>n+1)}>重试来源</button></p>:!source?<p role="status">正在读取来源…</p>:<><MarkdownContent content={source.analysis}/><SavedPaperSources expanded sources={sourceRows} onOpenPaper={openPaper}/>{!sourceRows.length&&<p className="text-sm text-muted">此材料没有保存原文片段。</p>}</>}
        </>:preview.sources.some(s=>s.paper_id===sourceId)?<SavedPaperSources expanded sources={preview.sources.filter(s=>s.paper_id===sourceId)} onOpenPaper={openPaper}/>:<p className="text-sm text-muted">此版本未保存该论文的来源片段。<button className="btn-ghost" onClick={()=>openPaper(sourceId)}>打开论文</button></p>}
      </section>}
      <SavedPaperSources sources={preview.sources} onOpenPaper={openPaper}/><ChatWebSources sources={preview.web}/>
      {preview.review&&<section className="space-y-3" aria-label="专题综述材料">
        <h4 className="text-sm font-medium">论文材料（{preview.review.papers.length} 篇）</h4><input className="input w-full" aria-label="查找关联论文" placeholder="按标题或论文编号查找" value={filter} onChange={e=>{setFilter(e.target.value);setPage(0);}}/>
        {filtered.slice(page*20,page*20+20).map(p=><button key={p.paper_id} className="btn-ghost block w-full break-words text-left" onClick={()=>setSourceId(p.paper_id)}>[P{p.paper_id}] {p.title}</button>)}
        <div className="flex gap-2"><button className="btn-ghost" disabled={!page} onClick={()=>setPage(n=>n-1)}>上一页</button><button className="btn-ghost" disabled={(page+1)*20>=filtered.length} onClick={()=>setPage(n=>n+1)}>下一页</button></div>
      </section>}
      {!preview.sources.length&&!preview.web.length&&!preview.review&&<p className="text-xs text-muted">此版本没有保存可回查的来源片段。</p>}
    </>}
  </div></Drawer>,document.body);
}

export function AttachmentChip({attachment:a,onRemove,...actions}:{attachment:ChatAttachment;onRemove?:()=>void}&Actions) {
  const [expanded,setExpanded]=useState(false);
  const reference=useMemo(()=>artifactReference(a),[a]);
  const {base}=useWorkspace();
  return <div className="chat-attachment rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-left text-xs max-w-full">
    <div className="flex min-w-0 items-center gap-1">
      <button type="button" className="chat-attachment-preview flex min-w-0 items-center gap-2" onClick={()=>setExpanded(!expanded)} title={`查看 ${a.name}`} aria-expanded={expanded}>
        {a.kind==='image'&&<img src={a.data_url} alt="" className="h-7 w-9 rounded object-contain"/>}
        <span className="max-w-[220px] truncate">{a.name}</span><span className="shrink-0 text-faint">{reference?'成果引用':a.kind==='text'?`${a.text.length} 字符`:'图片'}</span>
      </button>
      {onRemove&&<button type="button" className="chat-attachment-remove btn-ghost" aria-label={`移除 ${a.name}`} title={`移除 ${a.name}`} onClick={onRemove}><X size={13}/></button>}
    </div>
    {expanded&&(reference?<ArtifactPreview key={base+JSON.stringify(reference)} reference={reference} passage={attachmentPassage(a)} onClose={()=>setExpanded(false)} {...actions}/>:<div className="chat-attachment-content">{a.kind==='image'?<>
      {a.paper_page&&<div className="mb-2 flex flex-wrap items-center gap-2"><span className="text-faint">带入时保存的 PDF 第 {a.paper_page.page} 页原图</span><button type="button" className="btn-ghost text-xs" onClick={()=>actions.onOpenPaper(a.paper_page!.paper_id,a.paper_page!.page)}>打开当前 PDF 第 {a.paper_page.page} 页</button></div>}
      <img src={a.data_url} alt={a.name} className="max-h-64 max-w-full object-contain"/>
    </>:<><p className="mb-2 text-faint">按提取的文字发送；PDF、Word 中的图表请另附截图。</p><pre className="max-h-48 overflow-auto whitespace-pre-wrap">{a.text}</pre></>}</div>)}
  </div>;
}
