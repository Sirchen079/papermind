import {useEffect,useRef,useState} from 'react';
import {useApi} from '../workspaceContext';
import type {PaperNote,NoteRevision,NoteHistory as History} from '../api';
import {MarkdownContent} from './MarkdownContent';

export function NoteHistory({note,onEdit,onPdfPage,kindLabel}:{note:PaperNote;onEdit:(revision:NoteRevision)=>void;onPdfPage?:(id:number,page:number)=>void;kindLabel:(kind:string)=>string}){
  const api=useApi();const [open,setOpen]=useState(false),[history,setHistory]=useState<History|null>(null),[revision,setRevision]=useState<NoteRevision|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const generation=useRef(0),reading=useRef(0);
  useEffect(()=>{const g=++generation.current;++reading.current;setHistory(null);setRevision(null);setError('');setBusy(false);
    if(open)api.noteHistory(note.paper_id,note.id).then(value=>{if(g===generation.current)setHistory(value);}).catch(e=>{if(g===generation.current)setError(e.message);});
    return()=>{++generation.current;++reading.current;};
  },[api,note.id,note.paper_id,note.version,open]);
  async function select(version:number){const g=generation.current,r=++reading.current;setError('');setBusy(true);setRevision(null);
    try{const value=await api.noteRevision(note.paper_id,note.id,version);if(g===generation.current&&r===reading.current)setRevision(value);}
    catch(e:any){if(g===generation.current&&r===reading.current)setError(e.message);}
    finally{if(g===generation.current&&r===reading.current)setBusy(false);}
  }
  async function more(){if(history?.next_offset==null)return;const g=generation.current;setBusy(true);
    try{const value=await api.noteHistory(note.paper_id,note.id,history.next_offset);if(g===generation.current)setHistory({...value,items:[...history.items,...value.items]});}
    catch(e:any){if(g===generation.current)setError(e.message);}
    finally{if(g===generation.current)setBusy(false);}
  }
  if((note.version??1)<2)return null;
  return <details className="mt-2 border-t pt-2 border-[var(--border)]" onToggle={e=>{if(e.target===e.currentTarget)setOpen(e.currentTarget.open);}}>
    <summary className="cursor-pointer">笔记历史 · 当前 v{note.version}</summary>
    <p className="text-muted my-2">旧内容保留在历史中。选用旧版会进入编辑框，保存后形成新版本。</p>
    {error&&<p role="alert" className="text-red-600">{error}</p>}
    {!history&&!error&&open&&<p role="status">正在读取历史…</p>}
    <div className="flex flex-wrap gap-2">{history?.items.map(item=><button className="btn-ghost text-xs" key={item.version} onClick={()=>select(item.version)} aria-pressed={revision?.version===item.version}>v{item.version} · {new Date(item.updated_at).toLocaleString()}</button>)}{history?.next_offset!=null&&<button className="btn-ghost text-xs" disabled={busy} onClick={more}>更早版本</button>}</div>
    {busy&&<p role="status">正在读取版本…</p>}
    {revision&&<div className="space-y-2 mt-2"><p>v{revision.version} → 当前 v{revision.current_version} · {revision.changes_to_current.length} 处正文变化</p>
      {revision.changes_to_current.map((change,index)=><div className="grid gap-3 border-t pt-2 border-[var(--border)]" style={{gridTemplateColumns:'repeat(auto-fit,minmax(min(100%,18rem),1fr))'}} key={index}>
        <div className="min-w-0"><p className="text-muted mb-1">历史 v{revision.version}</p>{change.before?<MarkdownContent content={change.before} images={false} paperId={note.paper_id} onPdfPage={onPdfPage}/>:<p>该版尚无此段</p>}</div>
        <div className="min-w-0"><p className="text-muted mb-1">当前 v{revision.current_version}</p>{change.after?<MarkdownContent content={change.after} images={false} paperId={note.paper_id} onPdfPage={onPdfPage}/>:<p>当前已删除</p>}</div>
      </div>)}
      <details><summary className="cursor-pointer">查看 v{revision.version} 完整正文</summary><p className="text-muted my-2">{kindLabel(revision.kind)}{revision.tags.length?' · '+revision.tags.join(', '):''}</p><MarkdownContent content={revision.content} images={false} paperId={note.paper_id} onPdfPage={onPdfPage}/></details>
      <button className="btn-ghost text-xs" onClick={()=>onEdit(revision)}>用此版本编辑</button>
    </div>}
  </details>;
}
