import { useRef, useState } from 'react';
import { Blocks, X } from '../icons';
import { useWorkspace } from '../workspaceContext';
import { workspaceRequest } from '../workspaceApi';

export function WorkspaceMenu(){
  const {workspace,workspaces,switchTo,refresh}=useWorkspace();
  const dialog=useRef<HTMLDialogElement>(null);
  const [editing,setEditing]=useState<string|null>(null);
  const [name,setName]=useState('');
  const [goal,setGoal]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  function open(){setError('');setEditing(null);setName('');setGoal('');dialog.current?.showModal();}
  async function save(event:React.FormEvent){
    event.preventDefault();if(busy)return;setBusy(true);setError('');
    try{
      const row=await workspaceRequest(editing?'/'+editing:'',{name,goal},editing?'PATCH':'POST');
      await refresh();dialog.current?.close();if(!editing)switchTo(row.id);
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  async function archive(id:string,archived:boolean){
    if(busy)return;setBusy(true);setError('');
    try{await workspaceRequest('/'+id,{archived},'PATCH');await refresh();}
    catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <>
    <button className="nav-link" aria-label={`研究项目：${workspace.name}`} title={`切换或管理研究项目 · ${workspace.name}`} onClick={open}>
      <Blocks size={18}/><span className="sidebar-copy truncate">{workspace.name}</span>
    </button>
    <dialog ref={dialog} className="workspace-dialog card w-[min(92vw,620px)] max-h-[85vh] overflow-auto" aria-labelledby="workspace-dialog-title" onCancel={e=>{if(busy)e.preventDefault();}}>
      <div className="flex items-center justify-between gap-4 mb-4"><h2 id="workspace-dialog-title" className="text-xl">研究项目</h2><button className="btn-subtle p-2" aria-label="关闭项目管理" disabled={busy} onClick={()=>dialog.current?.close()}><X size={18}/></button></div>
      <p className="text-sm text-muted mb-4">每个项目分别保存论文、会话与研究成果。切换后，正在运行的任务仍归属于原项目。</p>
      <div className="space-y-2 mb-6">{workspaces.map(w=><div className="flex items-center gap-2 border-b border-[var(--border)] pb-2" key={w.id}>
        <button className="btn-ghost flex-1 min-w-0 text-left" disabled={busy} onClick={()=>{dialog.current?.close();switchTo(w.id);}}><span className="truncate">{w.name}</span>{w.id===workspace.id&&<span className="text-xs text-muted ml-2">当前</span>}{!!w.archived&&<span className="text-xs text-muted ml-2">已归档</span>}{w.available===false&&<span className="text-xs text-muted ml-2">需恢复</span>}</button>
        <button className="btn-subtle text-xs" disabled={busy} onClick={()=>{setEditing(w.id);setName(w.name);setGoal(w.goal);}}>编辑</button>
        <button className="btn-subtle text-xs" disabled={busy} onClick={()=>archive(w.id,!w.archived)}>{w.archived?'恢复':'归档'}</button>
      </div>)}</div>
      <form onSubmit={save} className="space-y-3">
        <div className="flex gap-3 items-center"><h3>{editing?'编辑项目信息':'新建研究项目'}</h3>{editing&&<button type="button" className="btn-subtle text-xs" onClick={()=>{setEditing(null);setName('');setGoal('');}}>改为新建</button>}</div>
        <label className="block text-sm">项目名称<input className="input block w-full mt-1" value={name} onChange={e=>setName(e.target.value)} required maxLength={120} disabled={busy}/></label>
        <label className="block text-sm">研究目标（可稍后补充）<textarea className="input block w-full mt-1" rows={3} value={goal} onChange={e=>setGoal(e.target.value)} maxLength={6000} disabled={busy}/></label>
        {error&&<p role="alert" className="text-sm" style={{color:'var(--danger)'}}>{error}</p>}
        <button className="btn-primary" disabled={busy||!name.trim()}>{busy?'正在保存…':editing?'保存项目信息':'创建项目'}</button>
      </form>
    </dialog>
  </>;
}
