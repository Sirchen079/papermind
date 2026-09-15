import { useCallback, useEffect, useMemo, useState } from 'react';
import App from './App';
import { createApi } from './api';
import { createResearchApi } from './researchApi';
import { createWikiApi } from './wikiApi';
import { WorkspaceContext, type Workspace } from './workspaceContext';
import { workspaceRequest, listWorkspaces } from './workspaceApi';
import { WorkspaceActivity } from './components/WorkspaceActivity';
function initialWorkspace(){
  const explicit=new URLSearchParams(window.location.search).get('workspace');
  if(explicit)return explicit;
  try{return localStorage.getItem('pm-last-workspace')||'legacy';}catch{return 'legacy';}
}
export default function WorkspaceRoot(){
  const [selected,setSelected]=useState(initialWorkspace);
  const [workspaces,setWorkspaces]=useState<Workspace[]>([]);
  const [error,setError]=useState('');
  const [loaded,setLoaded]=useState(false);
  const [newName,setNewName]=useState('');
  const [creating,setCreating]=useState(false);
  const refresh=useCallback(async()=>{setWorkspaces(await listWorkspaces());setLoaded(true);},[]);
  useEffect(()=>{refresh().catch(e=>setError(e.message));},[refresh]);
  const switchTo=useCallback((id:string)=>{
    if(id===selected)return;
    let route='#home';
    try {
      localStorage.setItem('pm-workspace-route-'+selected,window.location.hash);
      localStorage.setItem('pm-last-workspace',id);
      route=localStorage.getItem('pm-workspace-route-'+id)||'#home';
    }catch{/* Navigation remains available when optional storage is full. */}
    const url=new URL(window.location.href);url.searchParams.set('workspace',id);url.hash=route;
    window.history.pushState(null,'',url);
    setSelected(id);
  },[selected]);
  useEffect(()=>{
    const pop=()=>setSelected(new URLSearchParams(window.location.search).get('workspace')||'legacy');
    window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);
  },[]);
  const workspace=workspaces.find(w=>w.id===selected);
  const base='/api/w/'+encodeURIComponent(selected);
  const clients=useMemo(()=>({api:createApi(base),researchApi:createResearchApi(base),wikiApi:createWikiApi(base)}),[base]);
  useEffect(()=>{
    if(!workspace)return;
    const url=new URL(window.location.href);url.searchParams.set('workspace',selected);
    window.history.replaceState(null,'',url);
  },[workspace,selected]);
  if(!workspace || workspace.available===false)return <div className="p-8 max-w-xl mx-auto space-y-4">
    <h1 className="text-xl">PaperMind 研究项目</h1>
    {workspace&&<h2>{workspace.name}</h2>}
    <p role={error||workspace?.available===false?'alert':undefined}>{error||workspace?.unavailable_reason||(!loaded?'正在读取项目…':'这个项目当前不可用，请选择要打开的研究项目。')}</p>
    {(error||loaded)&&<button className="btn-primary" onClick={()=>{setError('');refresh().catch(e=>setError(e.message));}}>重新读取</button>}
    <div className="flex flex-wrap gap-2">{workspaces.map(w=><button className="btn-secondary" key={w.id} onClick={()=>switchTo(w.id)}>{w.name}{w.available===false?'（需恢复）':''}</button>)}</div>
    {loaded&&<form className="space-y-2" onSubmit={async e=>{
      e.preventDefault();if(creating)return;setCreating(true);setError('');
      try{const row=await workspaceRequest('',{name:newName});await refresh();setNewName('');switchTo(row.id);}
      catch(e:any){setError(e.message);}finally{setCreating(false);}
    }}><label className="block">新项目名称<input className="input block w-full" required maxLength={120} value={newName} disabled={creating} onChange={e=>setNewName(e.target.value)}/></label><button className="btn-secondary" disabled={creating||!newName.trim()}>{creating?'正在创建…':'创建独立研究项目'}</button></form>}
  </div>;
  return <WorkspaceContext.Provider value={{workspace,workspaces,base,...clients,switchTo,refresh}}>
    <App key={selected}/>
    <WorkspaceActivity/>
  </WorkspaceContext.Provider>;
}
