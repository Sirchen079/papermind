import { useEffect, useRef, useState } from 'react';
import type { InstitutionalJob, InstitutionalPreferences } from '../api';
import { useApi } from '../workspaceContext';
import { downloadSelectionValid, institutionalLabel, retryPaperIds } from '../pages/institutionalModel';

export function InstitutionalDownload({ paperIds, onAttached }: {paperIds:number[]; onAttached?:()=>void|Promise<void>}) {
  const api = useApi();
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preferences, setPreferences] = useState<InstitutionalPreferences>({institution:'', aliases:'', library_url:'', ready:false});
  const [job, setJob] = useState<InstitutionalJob|null>(null), [history, setHistory] = useState<InstitutionalJob[]>([]);
  const [mode, setMode] = useState<'auto'|'manual'>('auto');
  const notify = useRef(onAttached);
  notify.current = onAttached;
  const active = job?.status === 'running';
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setBusy(true);
    Promise.all([api.institutionalConfig(), api.institutionalJobs()]).then(([prefs, jobs]) => {
      if (alive) { setPreferences(prefs); setHistory(jobs); setJob(jobs[0] ?? null); setError(''); }
    }).catch(e => { if (alive) setError(String(e.message)); }).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [open, api]);
  useEffect(() => {
    if (!open || !job || job.status !== 'running') return;
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api.institutionalJob(job.id);
        if (!alive) return;
        setJob(value);
        setHistory(current => [value, ...current.filter(row => row.id !== value.id)]);
        if (value.status !== 'running') {
          setPreferences(current => ({...current, ready:true}));
          if (value.results.some(r => r.status === 'attached')) await notify.current?.();
          return;
        }
      } catch (e) { if (alive) setError((e as Error).message); }
      if (alive) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 500);
    return () => { alive = false; clearTimeout(timer); };
  }, [open, job?.id, job?.status, api]);
  async function start(ids: number[], selectedMode = mode) {
    if (!downloadSelectionValid(ids, selectedMode)) return;
    setBusy(true); setError('');
    try {
      await api.configureInstitutional(preferences);
      const value = await api.startInstitutionalJob(ids, selectedMode);
      setJob(value);
      setHistory(current => [value, ...current.filter(row => row.id !== value.id)]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <details className="w-full" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className="btn-subtle inline-flex cursor-pointer text-xs">通过图书馆获取全文</summary>
    {open && <section className="card mt-2 space-y-3 text-sm" aria-label="机构全文下载">
      <p className="text-muted text-xs">使用本人学校或机构权限，仅获取正文 PDF。登录、验证码在打开的浏览器内完成，登录状态保存在本机。</p>
      <div className="grid gap-3 md:grid-cols-2">
        <label>学校或机构名称<input className="input mt-1 w-full" value={preferences.institution} maxLength={200} disabled={active || busy}
          onChange={e => setPreferences({...preferences, institution:e.target.value})}/></label>
        <label>英文名称或别名（多个用 ; 分隔）<input className="input mt-1 w-full" value={preferences.aliases} maxLength={500} disabled={active || busy}
          onChange={e => setPreferences({...preferences, aliases:e.target.value})}/></label>
      </div>
      <label className="block">图书馆或校外访问入口（浏览器下载模式使用）<input type="url" className="input mt-1 w-full" value={preferences.library_url} disabled={active || busy}
        onChange={e => setPreferences({...preferences, library_url:e.target.value})} placeholder="https://…"/></label>
      <div className="flex flex-wrap items-center gap-2">
        <select className="input" aria-label="机构下载方式" value={mode} disabled={active || busy} onChange={e => setMode(e.target.value as 'auto'|'manual')}>
          <option value="auto">自动获取（最多 10 篇）</option><option value="manual">在机构浏览器内下载（单篇）</option>
        </select>
        <button className="btn-primary" disabled={busy || active || !preferences.institution.trim() || !downloadSelectionValid(paperIds, mode)}
          onClick={() => void start(paperIds)}>获取所选 {paperIds.length} 篇全文</button>
        {active && <button className="btn-subtle" onClick={async () => {
          try { await api.stopInstitutionalJob(job.id); setError('已请求停止，已入库的 PDF 会保留。'); }
          catch (e) { setError((e as Error).message); }
        }}>停止当前任务</button>}
      </div>
      {!preferences.ready && <p className="text-xs text-muted">首次使用会自动准备下载引擎和浏览器，无需输入命令。</p>}
      {mode === 'manual' && <p className="text-xs text-muted">在打开的浏览器中登录、找到目标论文并点击下载。PDF 会自动接回题录；一次处理一篇。</p>}
      {!!history.length && <label className="block text-xs">最近任务<select className="input ml-2 max-w-full" disabled={active} value={job?.id ?? ''}
        onChange={e => setJob(history.find(j => j.id === e.target.value) ?? null)}>
        {!history.some(j=>j.id===job?.id) && job && <option value={job.id}>当前任务</option>}
        {history.map(j => <option key={j.id} value={j.id}>{j.results[0]?.title || '全文下载'} · {institutionalLabel(j.status)}</option>)}
      </select></label>}
      {job && <div className="space-y-2" role="status" aria-live="polite">
        <p>{institutionalLabel(active ? job.phase : job.status)}{job.error ? ` · ${job.error}` : ''}</p>
        {active && job.phase === 'waiting_verification' && <div role="alert" className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3">
          <p className="font-medium">需要你手动完成人机验证</p>
          <p className="mt-1 text-xs text-muted">请切换到已打开的 Chromium 下载浏览器完成验证。保持页面打开，验证通过后程序会自动继续，当前下载进度已保留。</p>
        </div>}
        {job.results.map(row => <div key={row.paper_id} className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-2 text-xs">
          <span className="min-w-0 flex-1 break-words">{row.title || `论文 ${row.paper_id}`}</span><span>{institutionalLabel(row.status)}</span>
          {!active && retryPaperIds([row]).length > 0 && <button className="btn-ghost" disabled={busy} onClick={() => void start([row.paper_id], 'manual')}>浏览器下载</button>}
        </div>)}
        {!active && retryPaperIds(job.results).length > 0 && <button className="btn-subtle" disabled={busy}
          onClick={() => void start(retryPaperIds(job.results), job.mode)}>继续未完成的论文</button>}
      </div>}
      {error && <p role="alert" className="text-xs" style={{color:'var(--danger)'}}>{error}</p>}
    </section>}
  </details>;
}
