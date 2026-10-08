import { useEffect, useRef, useState } from 'react';
import { localToken } from '../api';
import { useWorkspace } from '../workspaceContext';
import { useConfirm } from './ui/ConfirmDialog';

type Model = {id:string;name:string;kind:'chat'|'embedding';context_window:number;bytes:number;state:string;error:string;available:boolean};
type Status = {engine_available:boolean;engine_version:string;models:Model[]};
const LABELS:Record<string,string>={starting:'正在加载',ready:'运行中',stopped:'未运行',error:'启动失败'};

export function ManagedModelsPanel({onChanged}:{onChanged:()=>Promise<void>}) {
  const {base}=useWorkspace();const confirm=useConfirm();
  const [status,setStatus]=useState<Status|null>(null),[file,setFile]=useState<File|null>(null);
  const [kind,setKind]=useState('chat'),[context,setContext]=useState(8192),[progress,setProgress]=useState<number|null>(null);
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState('');
  const fileInput=useRef<HTMLInputElement>(null),generation=useRef(0),upload=useRef<XMLHttpRequest|null>(null);
  async function request(path:string,method='GET'){
    const r=await fetch(base+'/managed-models'+path,{method,headers:{'X-Local-Token':localToken()}});
    const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'本地模型操作未完成');return value;
  }
  useEffect(()=>{
    const g=++generation.current;setStatus(null);setError('');setMessage('');setBusy('');setProgress(null);
    async function load(){try{const data=await request('');if(g===generation.current)setStatus(data);}catch(e){if(g===generation.current)setError((e as Error).message);}}
    void load();const timer=setInterval(load,3000);
    return()=>{++generation.current;clearInterval(timer);upload.current?.abort();};
  },[base]);
  async function act(model:Model,verb:'start'|'stop'|'use'|'remove'){
    if(verb==='remove'&&!await confirm({title:'移除本地模型',message:'将删除应用保管的模型副本，所有项目将无法继续使用它。原始导入文件保留。',confirmText:'移除',variant:'danger'}))return;
    const g=generation.current;setBusy(model.id);setError('');setMessage('');
    try{
      await request('/'+model.id+(verb==='remove'?'':'/'+verb),verb==='remove'?'DELETE':'POST');
      if(g!==generation.current)return;
      const refreshed=await request('');if(g!==generation.current)return;setStatus(refreshed);
      if(verb==='use'){await onChanged();if(g===generation.current)setMessage('已设为当前项目的'+(model.kind==='chat'?'文本模型':'向量模型')+'，下次使用时会自动启动。');}
    }catch(e){if(g===generation.current)setError((e as Error).message);}
    finally{if(g===generation.current)setBusy('');}
  }
  function importFile(){
    if(!file)return;const g=generation.current;setBusy('import');setError('');setMessage('');setProgress(0);
    const body=new FormData();body.append('file',file);body.append('kind',kind);body.append('context_window',String(context));
    const xhr=new XMLHttpRequest();upload.current=xhr;xhr.open('POST',base+'/managed-models/import');xhr.setRequestHeader('X-Local-Token',localToken());
    xhr.upload.onprogress=e=>{if(g===generation.current&&e.lengthComputable)setProgress(Math.round(e.loaded/e.total*100));};
    xhr.onload=async()=>{
      if(g!==generation.current)return;
      try{const value=JSON.parse(xhr.responseText);if(xhr.status>=400)throw new Error(typeof value.detail==='string'?value.detail:'模型导入失败');
        const refreshed=await request('');if(g!==generation.current)return;setStatus(refreshed);setFile(null);if(fileInput.current)fileInput.current.value='';setMessage('模型已保存在本机，可以启动或用于当前项目。');
      }catch(e){if(g===generation.current)setError((e as Error).message);}
      finally{if(g===generation.current){setBusy('');setProgress(null);}}
    };
    xhr.onerror=()=>{if(g===generation.current){setError('导入连接中断，请重试。');setBusy('');setProgress(null);}};
    xhr.send(body);
  }
  return <section className="card space-y-4" aria-label="内置本地模型">
    <div><h2 className="text-lg font-semibold">本地模型库</h2><p className="mt-1 text-sm text-muted">直接导入单文件 GGUF 模型，由 PaperMind 在本机运行。模型供各项目共用，用途在当前项目选择。</p></div>
    {status&&!status.engine_available&&<p role="alert" className="text-sm text-red-600">当前运行版本缺少推理引擎，请安装包含本地引擎的版本。</p>}
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm sm:col-span-2">导入模型文件<input ref={fileInput} type="file" accept=".gguf" className="input mt-1 w-full" disabled={!!busy} onChange={e=>setFile(e.target.files?.[0]??null)}/></label>
      <label className="text-sm">模型用途<select aria-label="导入模型用途" className="input mt-1 w-full" value={kind} disabled={!!busy} onChange={e=>{setKind(e.target.value);setContext(e.target.value==='embedding'?2048:8192);}}><option value="chat">文本生成</option><option value="embedding">向量检索</option></select></label>
      <label className="text-sm">运行上下文长度<input type="number" min={1} step={1} className="input mt-1 w-full" value={context} disabled={!!busy} onChange={e=>setContext(Number(e.target.value))}/></label>
    </div>
    <p className="text-sm text-muted">导入会保存一份模型副本。当前使用 CPU 推理，首次加载需要一些时间；模型大小和上下文长度影响内存占用。</p>
    <button className="btn-primary" disabled={!file||!!busy||!Number.isInteger(context)||context<1} onClick={importFile}>{progress===null?'导入到本地模型库':progress===100?'正在校验与保存…':`正在导入 ${progress}%`}</button>
    {error&&<p role="alert" className="text-sm text-red-600 break-words">{error}</p>}
    {message&&<p role="status" className="text-sm">{message}</p>}
    {status?.models.map(model=><article key={model.id} className="space-y-2 border-t pt-3" aria-label={model.name}>
      <div className="flex flex-wrap justify-between gap-2"><h3 className="font-medium break-all">{model.name}</h3><span className="text-sm text-muted">{LABELS[model.state]??model.state}</span></div>
      <p className="text-sm text-muted">{model.kind==='chat'?'文本生成':'向量检索'} · {(model.bytes/1024**3).toFixed(2)} GB · {model.context_window.toLocaleString()} 上下文</p>
      {(!model.available||model.error)&&<p className="text-sm text-red-600">{model.error||'模型文件缺失，请重新导入。'}</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={!!busy||!model.available||!status.engine_available} onClick={()=>act(model,'use')}>{busy===model.id?'正在处理…':'用于当前项目'}</button>
        {model.state==='ready'||model.state==='starting'?<button className="btn-ghost" disabled={!!busy} onClick={()=>act(model,'stop')}>停止</button>:<button className="btn-ghost" disabled={!!busy||!model.available||!status.engine_available} onClick={()=>act(model,'start')}>启动</button>}
        <button className="btn-ghost" disabled={!!busy} onClick={()=>act(model,'remove')}>移除模型</button>
      </div>
    </article>)}
    {status&&!status.models.length&&<p className="text-sm text-muted">还没有导入模型。已有 Ollama 或 LM Studio 的用户，也可以使用下方的本机服务连接。</p>}
  </section>;
}
