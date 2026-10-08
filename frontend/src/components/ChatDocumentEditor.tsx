import {useState} from 'react';
import {createPortal} from 'react-dom';
import {useApi} from '../workspaceContext';
import {usePaperDraft} from './usePaperDraft';
import {Drawer} from './ui/Drawer';
import {MarkdownContent} from './MarkdownContent';

export function ChatDocumentEditor({conversationId,filename,content,onClose,onSaved}:{conversationId:number;filename:string;content:string;onClose:()=>void;onSaved:()=>void}) {
  const api=useApi();
  const [draft,setDraft,clearDraft,storageError]=usePaperDraft(`${conversationId}:${filename}`,{content},'chat-document');
  const [saving,setSaving]=useState(false),[error,setError]=useState(''),[preview,setPreview]=useState(false);
  async function save(){
    setSaving(true);setError('');const submitted={...draft};
    try{await api.reviseChatDocument(conversationId,filename,submitted.content);clearDraft(submitted);onSaved();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setSaving(false);}
  }
  return createPortal(<Drawer open onClose={()=>{if(!saving)onClose();}} title="修改研究文档" width="max-w-3xl">
    <div className="space-y-4">
      <p className="break-all text-sm font-medium">{filename}</p>
      <p className="text-sm text-muted">保存为新版本，原稿保留。后续对话会使用你的修订稿。</p>
      <div className="flex gap-2"><button type="button" className="btn-ghost text-xs" onClick={()=>setPreview(!preview)}>{preview?'继续编辑':'预览排版'}</button></div>
      {preview?<div className="card"><MarkdownContent content={draft.content}/></div>:<textarea aria-label="研究文档正文" className="input min-h-[55vh] w-full resize-y font-mono text-sm" value={draft.content} disabled={saving} onChange={e=>setDraft({content:e.target.value})}/>}
      {storageError&&<p role="alert" className="text-sm text-[var(--danger)]">草稿暂时无法保存在浏览器中，请先保存新版本再关闭。</p>}
      {error&&<p role="alert" className="text-sm text-[var(--danger)]">{error}</p>}
      <div className="flex flex-wrap gap-2"><button type="button" className="btn-primary" disabled={saving||!draft.content.trim()||draft.content===content} onClick={()=>void save()}>{saving?'保存中…':'保存新版本'}</button><button type="button" className="btn-ghost" disabled={saving} onClick={onClose}>关闭</button></div>
    </div>
  </Drawer>,document.body);
}
