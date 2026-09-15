import { useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { usePaperDraft } from './usePaperDraft';

const empty={target:'',requestId:''};
export function CopyWikiPanel({id,number}:{id:string;number:number}){
  const {workspace,workspaces,wikiApi,refresh}=useWorkspace();
  const [draft,setDraft,clearDraft]=usePaperDraft(`${id}:${number}`,empty,'wiki-copy');
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [result,setResult]=useState<{workspace:string;name:string;page:string}|null>(null);
  const targets=workspaces.filter(w=>w.id!==workspace.id&&!w.archived&&w.available!==false);
  async function copy(e:React.FormEvent){
    e.preventDefault();if(busy)return;
    const target=targets.find(w=>w.id===draft.target);if(!target)return;
    const submitted={...draft,requestId:draft.requestId||crypto.randomUUID()};setDraft(submitted);setBusy(true);setError('');
    try{const copied=await wikiApi.copy(id,{request_id:submitted.requestId,target_workspace:target.id,number});clearDraft(submitted);setResult({workspace:target.id,name:target.name,page:copied.page_id});}
    catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <details onToggle={e=>{if(e.currentTarget.open)refresh().catch(()=>{});}}>
    <summary className="cursor-pointer text-sm">复制 v{number} 到其他项目</summary>
    <p className="text-sm text-muted mt-2">将此版本的正文和引用快照复制为独立候选。原项目之后的修改继续保存在原项目，目标项目可另行补充材料。</p>
    <form onSubmit={copy} className="flex flex-wrap gap-2 mt-3"><select aria-label="专题副本的目标项目" required disabled={busy} className="input min-w-0 flex-1" value={draft.target} onChange={e=>{setDraft({target:e.target.value,requestId:crypto.randomUUID()});setResult(null);}}><option value="">选择目标项目</option>{targets.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select><button className="btn-secondary" disabled={busy||!targets.some(w=>w.id===draft.target)}>{busy?'正在复制…':'复制专题快照'}</button></form>
    {error&&<p role="alert" className="text-sm mt-2">{error}</p>}{result&&<p role="status" className="text-sm mt-2">已复制到“{result.name}”。<a className="underline ml-2" href={`?workspace=${encodeURIComponent(result.workspace)}#wiki?page=${encodeURIComponent(result.page)}`}>打开副本</a></p>}
  </details>;
}
