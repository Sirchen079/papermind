import { useEffect, useState } from 'react';
import type { Provider, SharedConnection } from '../api';
import { useApi, useWorkspace } from '../workspaceContext';

export function SharedConnectionsPanel({providers,onChanged}:{providers:Provider[];onChanged:()=>Promise<void>}){
  const api=useApi();
  const {workspace}=useWorkspace();
  const [connections,setConnections]=useState<SharedConnection[]>([]);
  const [selected,setSelected]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [editing,setEditing]=useState<SharedConnection|null>(null);
  const [form,setForm]=useState({name:'',base_url:'',api_key:'',enabled:true});
  useEffect(()=>{let alive=true;api.sharedConnections().then(rows=>{if(alive)setConnections(rows);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[api,providers]);
  async function act(action:()=>Promise<unknown>,message:string){
    if(busy)return;setBusy(true);setError('');setNotice('');
    try{await action();setConnections(await api.sharedConnections());await onChanged();setNotice(message);}
    catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  async function save(e:React.FormEvent){
    e.preventDefault();if(!editing)return;
    const body:Record<string,unknown>={expected_version:editing.version,name:form.name,base_url:form.base_url,enabled:form.enabled};
    if(form.api_key)body.api_key=form.api_key;
    await act(async()=>{await api.updateSharedConnection(editing.id,body);setEditing(null);setForm({name:'',base_url:'',api_key:'',enabled:true});},'共享连接已更新。');
  }
  return <section className="card space-y-4" aria-labelledby="shared-connections-heading">
    <div><h2 id="shared-connections-heading" className="text-lg">共享模型连接</h2><p className="text-sm text-muted mt-1">共享 API 地址、访问凭证与初始模型列表。各项目分别选择模型、记录用量，也可转为项目专用连接。</p></div>
    {error&&<p role="alert" className="text-sm" style={{color:'var(--danger)'}}>{error}<button className="btn-subtle ml-2" disabled={busy} onClick={()=>act(async()=>{setConnections(await api.sharedConnections());setEditing(null);setForm({name:'',base_url:'',api_key:'',enabled:true});},'连接列表已刷新。需要继续修改时，请重新打开编辑以读取最新配置。')}>刷新连接列表</button></p>}
    {notice&&<p role="status" className="text-sm">{notice}</p>}
    <div className="flex flex-wrap items-center gap-2">
      <select className="input flex-1 min-w-48" aria-label="选择要共享的项目连接" value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy}>
        <option value="">选择当前项目已有的专用连接</option>
        {providers.filter(p=>!p.shared_connection_id).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <button className="btn-secondary" disabled={busy||!selected} onClick={()=>act(async()=>{await api.shareProvider(Number(selected));setSelected('');},'连接已共享，其他项目可以选用了。')}>设为共享连接</button>
    </div>
    {connections.length===0&&!error&&<p className="text-sm text-muted">还没有共享连接。先添加一个模型提供商并选好模型，再在这里共享。</p>}
    {connections.map(connection=>{
      const local=providers.find(p=>p.shared_connection_id===connection.id);
      return <div key={connection.id} className="rounded-lg border border-[var(--border)] p-3 space-y-2">
        <div className="flex flex-wrap items-center gap-2"><strong>{connection.name}</strong><span className="chip">{connection.type}</span><span className="text-xs text-muted">{connection.enabled?'可用':'已停用'} · v{connection.version}</span></div>
        <p className="text-xs text-muted break-all">{connection.base_url||'提供商默认地址'} · {connection.models.length} 个初始模型</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary text-sm" disabled={busy||!!local||!connection.enabled} onClick={()=>act(()=>api.attachConnection(connection.id),`已在“${workspace.name}”关联此连接。`)}>{local?'当前项目已关联':'用于当前项目'}</button>
          <button className="btn-ghost text-sm" disabled={busy} onClick={()=>{setEditing(connection);setForm({name:connection.name,base_url:connection.base_url||'',api_key:'',enabled:!!connection.enabled});setError('');}}>编辑共享连接</button>
          {local&&<button className="btn-ghost text-sm" disabled={busy} onClick={()=>act(()=>api.detachConnection(local.id),'已转为项目专用连接，后续可单独编辑。')}>转为项目专用</button>}
        </div>
      </div>;
    })}
    {editing&&<form onSubmit={save} className="rounded-lg p-3 space-y-3" style={{background:'var(--surface-2)'}}>
      <h3>编辑“{editing.name}”</h3><p className="text-sm text-muted">保存会更新所有仍在引用此连接的项目。已启动的请求保留原配置。</p>
      <label className="block text-sm">共享连接名称<input className="input mt-1 block w-full" required maxLength={120} value={form.name} onChange={e=>setForm({...form,name:e.target.value})} disabled={busy}/></label>
      <label className="block text-sm">共享 API 地址<input className="input mt-1 block w-full" value={form.base_url} onChange={e=>setForm({...form,base_url:e.target.value})} disabled={busy}/></label>
      <label className="block text-sm">新的共享 API Key（留空保留原值）<input className="input mt-1 block w-full" type="password" autoComplete="off" value={form.api_key} onChange={e=>setForm({...form,api_key:e.target.value})} disabled={busy}/></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={e=>setForm({...form,enabled:e.target.checked})} disabled={busy}/>启用此共享连接</label>
      <div className="flex gap-2"><button className="btn-primary" disabled={busy||!form.name.trim()}>保存共享修改</button><button type="button" className="btn-ghost" disabled={busy} onClick={()=>{setEditing(null);setForm({name:'',base_url:'',api_key:'',enabled:true});}}>取消</button></div>
    </form>}
  </section>;
}
