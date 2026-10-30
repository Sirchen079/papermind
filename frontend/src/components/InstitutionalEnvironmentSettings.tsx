import { useEffect, useRef, useState } from 'react';
import type { InstitutionalEnvironment } from '../api';
import { useApi } from '../workspaceContext';
import { Wrench, Loader2, Check } from '../icons';

export function InstitutionalEnvironmentSettings() {
  const api = useApi();
  const [state,setState] = useState<InstitutionalEnvironment|null>(null);
  const [error,setError] = useState(''), [busy,setBusy] = useState(false), [reload,setReload] = useState(0);
  const panel = useRef<HTMLElement>(null);
  useEffect(()=>{
    if(new URLSearchParams(location.hash.split('?')[1]).get('section')==='library-download') {
      panel.current?.scrollIntoView({block:'start'}); panel.current?.focus({preventScroll:true});
    }
  },[]);
  useEffect(()=>{
    let alive=true, timer:ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next=await api.institutionalEnvironment();
        if(!alive)return;
        setState(next);setError('');
        if(next.status==='installing')timer=setTimeout(poll,1500);
      } catch(e) {if(alive)setError((e as Error).message);}
    }
    void poll();return()=>{alive=false;clearTimeout(timer);};
  },[api,reload]);
  async function install() {
    setBusy(true);setError('');
    try {setState(await api.installInstitutionalEnvironment());setReload(n=>n+1);}
    catch(e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  const installing=state?.status==='installing';
  return <section ref={panel} id="library-download-environment" tabIndex={-1} className="card space-y-3 scroll-mt-24" aria-labelledby="library-environment-heading">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="library-environment-heading" className="text-lg font-semibold inline-flex items-center gap-2"><Wrench size={20}/>图书馆下载环境</h2>
      <span className="chip">{state?.ready?'已就绪':installing?'安装中':state?.status==='failed'?'安装失败':state?.status==='interrupted'?'安装已中断':'未就绪'}</span>
    </div>
    <p className="text-sm text-muted">安装独立 Python、下载引擎和浏览器后，可在论文库使用图书馆渠道获取全文。所有研究空间共用这套环境。</p>
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm">
      {installing?<Loader2 size={18} className="animate-spin motion-reduce:animate-none"/>:state?.ready?<Check size={18}/>:null}
      <span>{state?.message || '正在检查下载环境…'}</span>
    </div>
    {installing&&<p className="text-xs text-muted">首次安装需要联网下载，进度会保留；离开设置后仍会继续安装。</p>}
    {(error||state?.error)&&<p role="alert" className="text-sm break-words" style={{color:'var(--danger)'}}>{error||state?.error}</p>}
    <div className="flex flex-wrap gap-2">
      {!state?.ready&&<button className="btn-primary inline-flex items-center gap-2" disabled={!state||busy||installing} onClick={()=>void install()}><Wrench size={16}/>{installing?'正在安装…':state?.status==='failed'||state?.status==='interrupted'?'重新安装下载环境':'安装下载环境'}</button>}
      <button className="btn-subtle" disabled={busy||installing} onClick={()=>setReload(n=>n+1)}>检查环境</button>
      {state?.ready&&<a className="btn-subtle" href="#library">前往论文库获取全文</a>}
    </div>
  </section>;
}
