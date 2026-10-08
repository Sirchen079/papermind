import { useEffect, useRef, useState } from 'react';
import { localToken } from '../api';
import { useWorkspace } from '../workspaceContext';

const PRESETS = [
  { name: 'Ollama', url: 'http://127.0.0.1:11434/v1' },
  { name: 'LM Studio', url: 'http://127.0.0.1:1234/v1' },
  { name: 'llama.cpp', url: 'http://127.0.0.1:8080/v1' },
];
type Discovery = {base_url:string; models:{id:string;name:string}[]};

export function LocalModelsPanel({onChanged}:{onChanged:()=>Promise<void>}) {
  const {base} = useWorkspace();
  const [name,setName]=useState('Ollama'),[url,setUrl]=useState(PRESETS[0].url),[key,setKey]=useState('');
  const [found,setFound]=useState<Discovery|null>(null),[chat,setChat]=useState(''),[embedding,setEmbedding]=useState('');
  const [context,setContext]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[error,setError]=useState('');
  const generation=useRef(0);
  useEffect(()=>{++generation.current;setFound(null);setChat('');setEmbedding('');setKey('');setBusy(false);setMessage('');setError('');return()=>{++generation.current;};},[base]);
  function reset(){setFound(null);setChat('');setEmbedding('');setMessage('');setError('');}
  async function request(path:string,body:object){
    const r=await fetch(base+'/local-models/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':localToken()},body:JSON.stringify(body)});
    const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'本机模型请求未完成，请检查填写的信息。');return value;
  }
  async function discover(){
    const current=++generation.current;setBusy(true);reset();
    try{const result:Discovery=await request('discover',{base_url:url,api_key:key||undefined});if(current===generation.current)setFound(result);}
    catch(e){if(current===generation.current)setError((e as Error).message);}
    finally{if(current===generation.current)setBusy(false);}
  }
  async function connect(){
    const current=++generation.current;setBusy(true);setError('');setMessage('');
    try{
      await request('connect',{name,base_url:url,api_key:key||undefined,chat_model:chat||undefined,embedding_model:embedding||undefined,chat_context_window:context?Number(context):undefined});
      if(current===generation.current){setMessage('已连接到当前项目。可以开始问答或为论文建立索引。');setKey('');await onChanged();}
    }catch(e){if(current===generation.current)setError((e as Error).message);}
    finally{if(current===generation.current)setBusy(false);}
  }
  return <section className="card space-y-4" aria-label="本机 AI 设置">
    <div><h2 className="text-lg font-semibold">连接本机 AI</h2><p className="mt-1 text-sm text-muted">使用本机运行的文本模型与向量模型。先在模型软件中下载模型并开启 API 服务，再在这里选择用途。</p></div>
    <div className="flex flex-wrap gap-2">{PRESETS.map(p=><button key={p.name} className={name===p.name?'btn-primary':'btn-ghost'} disabled={busy} onClick={()=>{setName(p.name);setUrl(p.url);setKey('');reset();}}>{p.name}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">本机服务地址<input className="input mt-1 w-full" value={url} disabled={busy} onChange={e=>{setUrl(e.target.value);reset();}}/></label>
      <label className="text-sm">访问密钥（服务未设置时留空）<input className="input mt-1 w-full" type="password" autoComplete="off" value={key} disabled={busy} onChange={e=>{setKey(e.target.value);reset();}}/></label>
    </div>
    <button className="btn-ghost" disabled={busy||!url.trim()} onClick={discover}>{busy?'正在连接…':'检测本机模型'}</button>
    {found&&<div className="space-y-3">
      <p className="text-sm text-muted">已连接服务，发现 {found.models.length} 个模型。{!found.models.length&&'请先在模型软件中下载或加载模型，再重新检测。'}</p>
      {!!found.models.length&&<>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">文本 AI<select className="input mt-1 w-full" value={chat} disabled={busy} onChange={e=>setChat(e.target.value)}><option value="">保持当前文本模型</option>{found.models.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <label className="text-sm">向量检索<select className="input mt-1 w-full" value={embedding} disabled={busy} onChange={e=>setEmbedding(e.target.value)}><option value="">保持当前向量模型</option>{found.models.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        </div>
        {chat&&<label className="block text-sm">文本模型实际运行的上下文长度（可选）<input className="input mt-1 w-full" type="number" min={1} step={1} value={context} disabled={busy} placeholder="与本地模型软件中的设置一致" onChange={e=>setContext(e.target.value)}/></label>}
        <p className="text-sm text-muted">仅替换这里选中的用途。离线使用时请选择已经下载到本机的模型；本机服务列表也可能包含云端模型。翻译、OCR 和重排序的独立模型在下方设置。</p>
        <button className="btn-primary" disabled={busy||(!chat&&!embedding)||(!!context&&(!Number.isInteger(Number(context))||Number(context)<1))} onClick={connect}>连接并用于当前项目</button>
      </>}
    </div>}
    {error&&<p role="alert" className="text-sm text-red-600">{error}</p>}
    {message&&<p role="status" className="text-sm">{message}</p>}
  </section>;
}
