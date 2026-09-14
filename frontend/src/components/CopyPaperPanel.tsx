import { useState } from 'react';
import type { Paper } from '../api';
import { useApi, useWorkspace } from '../workspaceContext';
import { usePaperDraft } from './usePaperDraft';

const empty = { target:'', includeNotes:false, requestId:'' };

export function CopyPaperPanel({paper}:{paper:Paper}) {
  const api=useApi();
  const {workspace,workspaces,refresh}=useWorkspace();
  const [draft,setDraft,clearDraft,storageError]=usePaperDraft(paper.id,empty,'copy-to-workspace');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [copied,setCopied]=useState<{name:string;id:string;paperId:number}|null>(null);
  const targets=workspaces.filter(w=>w.id!==workspace.id&&!w.archived&&w.available!==false);
  function change(next:typeof empty){setDraft({...next,requestId:crypto.randomUUID().replace(/-/g,'')});setError('');setCopied(null);}
  async function copy(event:React.FormEvent){
    event.preventDefault();if(busy)return;
    const target=targets.find(w=>w.id===draft.target);if(!target)return;
    const submitted={...draft,requestId:draft.requestId||crypto.randomUUID().replace(/-/g,'')};
    setDraft(submitted);setBusy(true);setError('');setCopied(null);
    try{
      const result=await api.copyPaperToWorkspace(paper.id,{target_workspace:target.id,request_id:submitted.requestId,include_notes:submitted.includeNotes});
      clearDraft(submitted);setCopied({name:target.name,id:target.id,paperId:result.paper_id});
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <details className="mb-5 rounded-lg border border-[var(--border)] p-3" onToggle={e=>{if(e.currentTarget.open)refresh().catch(()=>{});}}>
    <summary className="cursor-pointer font-semibold">复制到其他研究项目</summary>
    <p className="text-sm text-muted mt-3">复制书目信息、PDF（如有）和已解析文本。两边的记录与文件分别保存，研究评价和会话继续保留在各自项目。</p>
    {targets.length===0?<p className="text-sm mt-3">请先在项目管理中创建或恢复一个目标项目。</p>:<form onSubmit={copy} className="space-y-3 mt-3">
      <label className="block text-sm">目标研究项目<select className="input block w-full mt-1" required value={draft.target} disabled={busy} onChange={e=>change({...draft,target:e.target.value})}><option value="">选择目标项目</option>{targets.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.includeNotes} disabled={busy} onChange={e=>change({...draft,includeNotes:e.target.checked})}/>同时复制已保存的笔记与摘录</label>
      <button className="btn-secondary text-sm" disabled={busy||!targets.some(w=>w.id===draft.target)}>{busy?'正在复制…':'复制资料'}</button>
    </form>}
    {storageError&&<p className="text-sm mt-2">这次复制的选项暂存在当前窗口。</p>}
    {error&&<p role="alert" className="text-sm mt-2" style={{color:'var(--danger)'}}>{error}</p>}
    {copied&&<p role="status" className="text-sm mt-3">已复制到“{copied.name}”（论文 #{copied.paperId}）。<a className="underline ml-2" href={`?workspace=${encodeURIComponent(copied.id)}#library`}>打开目标论文库</a></p>}
  </details>;
}
