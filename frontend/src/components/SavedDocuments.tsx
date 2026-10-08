import {documentIdentityLabel} from '../pages/documentIdentityModel';
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {useApi} from '../workspaceContext';
import type {SavedChatDocument,SavedChatDocumentDetail,SavedDocumentReference} from '../api';
import {Drawer} from './ui/Drawer';
import {MarkdownContent} from './MarkdownContent';
import {ChatWebSources} from './ChatWebSources';
import {SavedPaperSources} from './SavedPaperSources';
import {DocumentGenerationContext} from './DocumentGenerationContext';
import {DocumentInputs} from './DocumentInputs';

export function SavedDocuments({onClose,onUse,onOpenConversation,onPaperCitation,onOpenPaper,initialDocument}:{onClose:()=>void;onUse:(doc:SavedChatDocumentDetail,passage?:string)=>void;onOpenConversation?:(id:number)=>void;onPaperCitation:(doc:SavedChatDocumentDetail,id:number)=>void;onOpenPaper:(id:number,page?:number)=>void;initialDocument?:SavedDocumentReference|null}) {
  const api=useApi();
  const [query,setQuery]=useState(''),[previous,setPrevious]=useState(false),[offset,setOffset]=useState(0);
  const [items,setItems]=useState<SavedChatDocument[]>([]),[next,setNext]=useState<number|null>(null),[total,setTotal]=useState(0);
  const [selected,setSelected]=useState<SavedDocumentReference|null>(initialDocument??null),[document,setDocument]=useState<SavedChatDocumentDetail|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState('');
  const [reload,setReload]=useState(0);
  const [trail,setTrail]=useState<SavedDocumentReference[]>([]);
  function openDocument(ref:SavedDocumentReference){
    if(selected)setTrail(items=>[...items,selected]);
    setDocument(null);setSelected(ref);
  }
  const contentRef=useRef<HTMLDivElement>(null);
  const [passage,setPassage]=useState('');
  useEffect(()=>{
    setPassage('');
    const updateSelection=()=>{
      const selection=window.document.getSelection(),container=contentRef.current;
      if(!container||!selection?.rangeCount||selection.isCollapsed){setPassage('');return;}
      const range=selection.getRangeAt(0);
      setPassage(container.contains(range.startContainer)&&container.contains(range.endContainer)?selection.toString().trim():'');
    };
    window.document.addEventListener('selectionchange',updateSelection);
    return()=>window.document.removeEventListener('selectionchange',updateSelection);
  },[document]);
  useEffect(()=>{
    let active=true;setLoading(true);setError('');
    const timer=setTimeout(()=>{
      const request=selected?api.getSavedDocument(selected.message_id,selected.filename).then(result=>{if(active)setDocument(result);}):
        api.listSavedDocuments(query,offset,previous).then(result=>{if(active){setItems(result.items);setNext(result.next_offset);setTotal(result.total);}});
      request.catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    },selected?0:200);
    return()=>{active=false;clearTimeout(timer);};
  },[api,query,offset,previous,selected,reload]);
  return createPortal(<Drawer open onClose={onClose} title="已保存文档" width="max-w-3xl"><div className="space-y-4">
    <p className="text-sm text-muted">查找当前研究空间各次对话保存的文档，带到当前对话继续研究。</p>
    {selected?<div className="flex flex-wrap gap-2">
      {!!trail.length&&<button type="button" className="btn-ghost" onClick={()=>{setDocument(null);setSelected(trail[trail.length-1]);setTrail(items=>items.slice(0,-1));}}>返回上一份文档</button>}
      <button type="button" className="btn-ghost" onClick={()=>{setSelected(null);setDocument(null);setTrail([]);}}>返回文档列表</button>
    </div>:<>
      <input className="input w-full" aria-label="搜索已保存文档" placeholder="按文件名、主题或正文关键词查找" value={query} onChange={e=>{setQuery(e.target.value);setOffset(0);}}/>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={previous} onChange={e=>{setPrevious(e.target.checked);setOffset(0);}}/>包括已被后续修订替代的版本</label>
    </>}
    {loading&&<p role="status" className="text-sm text-muted">正在读取文档…</p>}
    {error&&<div role="alert" className="text-sm text-[var(--danger)]">{error}<button className="btn-ghost" onClick={()=>setReload(n=>n+1)}>重试读取</button></div>}
    {!selected&&!loading&&!error&&<>
      <p className="text-xs text-muted">{total} 份文档</p>
      {!items.length&&<p className="text-sm">没有找到文档。可在回答下方点击“保存为文档”，也可以让 AI 整理并保存研究稿。</p>}
      {items.map(item=><button type="button" className="card block w-full space-y-2 text-left" key={`${item.message_id}:${item.filename}`} onClick={()=>{setDocument(null);setSelected(item);}}>
        <p className="break-all font-medium">{item.filename}</p>
        <p className="text-xs text-muted">{documentIdentityLabel(item)}{item.superseded?' · 已有替代版本':''} · {new Date(item.created_at).toLocaleString()} · {item.conversation_title}</p>
        <p className="line-clamp-3 break-words text-sm text-muted">{item.snippet}</p>
      </button>)}
      <div className="flex gap-2"><button className="btn-ghost" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-20))}>上一页</button><button className="btn-ghost" disabled={next==null} onClick={()=>setOffset(next!)}>下一页</button></div>
    </>}
    {selected&&document&&!loading&&!error&&<>
      <p className="break-all font-medium">{document.filename}</p>
      <p className="text-xs text-muted">{documentIdentityLabel(document)} · {document.conversation_title}</p>
      <DocumentGenerationContext request={document.generation_request} onNavigate={onClose}/>
      <DocumentInputs documents={document.input_documents} onOpen={openDocument}/>
      {!!document.newer_versions?.length&&<section aria-label="后续修订" className="rounded-lg border border-[var(--border)] p-3 space-y-2">
        <p className="text-sm">{document.newer_versions.length===1?'这份文档已有后续修订。':'这份文档有多个后续版本。'}</p>
        <p className="text-xs text-muted">可查看修订稿后继续研究，当前版本仍可用于历史对照。</p>
        {document.newer_versions.map(version=><button type="button" className="btn-ghost block w-full text-left" key={`${version.message_id}:${version.filename}`} onClick={()=>openDocument(version)}>
          <span className="block break-all text-sm">查看修订稿 · {version.filename}</span><span className="block text-xs text-muted">{documentIdentityLabel(version)} · {version.conversation_title} · {new Date(version.created_at).toLocaleString()}</span>
        </button>)}
      </section>}
      <div className="flex flex-wrap gap-2"><button className="btn-primary" onClick={()=>onUse(document)}>加入当前对话</button>{onOpenConversation&&<button className="btn-ghost" onClick={()=>onOpenConversation(document.conversation_id)}>打开原对话</button>}<a className="btn-ghost" href={document.download_url} download>下载文档</a></div>
      <div className="sticky top-0 z-10 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
        {passage?<div className="space-y-2">
          <p className="line-clamp-2 break-words text-sm" aria-label="待核查选文">{passage}</p>
          <div className="flex flex-wrap items-center gap-2"><button type="button" className="btn-primary text-xs" onPointerDown={e=>e.preventDefault()} onClick={()=>onUse(document,passage)}>核查选中内容</button><span className="text-xs text-muted">已选中 {passage.length} 字</span><button type="button" className="btn-ghost text-xs" onClick={()=>{window.document.getSelection()?.removeAllRanges();setPassage('');}}>取消选文</button></div>
        </div>:<p className="text-xs text-muted">选中正文中的一段，可带着文档和来源继续核查。</p>}
      </div>
      <div ref={contentRef} aria-label="已保存文档正文"><MarkdownContent content={document.content} onPaperCitation={id=>onPaperCitation(document,id)}/></div>
      <SavedPaperSources sources={document.sources} onOpenPaper={onOpenPaper}/>
      <ChatWebSources sources={document.web_sources??[]}/>
    </>}
  </div></Drawer>,window.document.body);
}
