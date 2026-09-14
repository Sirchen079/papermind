import { useApi } from '../workspaceContext';
import { useEffect, useState } from 'react';
import { type ReadinessReport } from '../api';
import { readinessCheckLocation, type NavLocation } from '../pages/navigationModel';

export default function ReadinessPanel({onNavigate}:{onNavigate?:(target:NavLocation|string)=>void}) {
  const api = useApi();
  const [report,setReport]=useState<ReadinessReport|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{let alive=true;api.readiness().then(data=>{if(alive)setReport(data);}).catch(()=>{if(alive)setError('暂时无法检查配置，请稍后重试。');});return()=>{alive=false;};},[]);
  return <section className="card mb-4"><h2 className="font-semibold">可选功能检查</h2><p className="text-sm text-muted mt-2">这些功能按需配置即可；导入、阅读和记笔记不需要全部完成。</p>
    {error&&<p role="alert" className="text-sm text-[var(--danger)] mt-3">{error}</p>}
    {!report&&!error&&<p className="text-sm text-muted mt-3">正在检查…</p>}
    <div className="grid gap-3 md:grid-cols-2 mt-4">{report?.checks.map(check=><div className="rounded-lg border border-[var(--border)] p-3" key={check.id}><p className="text-sm font-medium">{check.label} · {check.status==='done'?'已具备':'可稍后完善'}</p><p className="text-xs text-muted mt-2">{check.detail}</p>{check.status!=='done'&&<button className="btn-ghost mt-2 text-xs" onClick={()=>onNavigate?.(readinessCheckLocation(check.id,check.route))}>{check.action}</button>}</div>)}</div>
  </section>;
}
