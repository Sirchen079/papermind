import { useEffect, useRef, useState } from 'react';
import type { InstitutionalJob, InstitutionalPreferences } from '../api';
import { useApi } from '../workspaceContext';
import { downloadSelectionValid, institutionalLabel, retryPaperIds } from '../pages/institutionalModel';
import { BookOpen, Wrench, ChevronDown } from '../icons';

export function InstitutionalDownload({ paperIds, onAttached }: {paperIds:number[]; onAttached?:()=>void|Promise<void>}) {
  const api = useApi();
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preferences, setPreferences] = useState<InstitutionalPreferences>({institution:'', aliases:'', library_url:'', ready:false});
  const [job, setJob] = useState<InstitutionalJob|null>(null), [history, setHistory] = useState<InstitutionalJob[]>([]);
  const [mode, setMode] = useState<'auto'|'manual'>('auto');
  const [environmentLoaded,setEnvironmentLoaded] = useState(false);
  const notify = useRef(onAttached);
  notify.current = onAttached;
  const active = job?.status === 'running';
  useEffect(() => {
    let alive = true;
    setBusy(true);
    Promise.all([api.institutionalConfig(), open?api.institutionalJobs():Promise.resolve([])]).then(([prefs, jobs]) => {
      if (alive) { setPreferences(prefs); setHistory(jobs); setJob(jobs[0] ?? null); setError(''); }
    }).catch(e => { if (alive) setError(String(e.message)); }).finally(() => { if (alive) {setBusy(false);setEnvironmentLoaded(true);} });
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
          const prefs = await api.institutionalConfig();
          if (alive) setPreferences(prefs);
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
    if (!preferences.ready || !downloadSelectionValid(ids, selectedMode)) return;
    setBusy(true); setError('');
    try {
      await api.configureInstitutional(preferences);
      const value = await api.startInstitutionalJob(ids, selectedMode);
      setJob(value);
      setHistory(current => [value, ...current.filter(row => row.id !== value.id)]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function upload(paperId: number, file: File) {
    if (!job || busy) return;
    setBusy(true); setError('');
    try {
      const value = await api.attachInstitutionalPdf(job.id, paperId, file);
      setJob(value); setHistory(current => [value, ...current.filter(row => row.id !== value.id)]);
      await notify.current?.();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="w-full">
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" className="btn-subtle inline-flex min-h-11 items-center gap-2 border px-4 py-2 text-sm font-medium" style={{borderColor:'var(--border-strong)',background:'var(--surface-2)'}}
        aria-expanded={open&&preferences.ready} disabled={busy||!preferences.ready} onClick={()=>setOpen(!open)}>
        <BookOpen size={18}/>通过图书馆获取全文
        <span className="chip">{!environmentLoaded?'检查环境中':preferences.ready?'环境已就绪':'需安装环境'}</span><ChevronDown size={16}/>
      </button>
      {environmentLoaded&&!preferences.ready&&<a className="btn-subtle inline-flex min-h-11 items-center gap-2 border px-4 py-2 text-sm" href="#settings?section=library-download"><Wrench size={16}/>去设置安装</a>}
    </div>
    {open && preferences.ready && <section className="card mt-2 space-y-3 text-sm" aria-label="机构全文下载">
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
          {!active && retryPaperIds([row]).length > 0 && <div className="flex w-full flex-wrap items-center gap-3">
            {preferences.library_url && <a className="underline" href={preferences.library_url} target="_blank" rel="noreferrer">在常用浏览器打开图书馆</a>}
            {row.doi && <a className="underline" href={`https://doi.org/${row.doi}`} target="_blank" rel="noreferrer">打开论文网页</a>}
            <label className="btn-subtle cursor-pointer">上传已下载的正文 PDF<input type="file" accept="application/pdf,.pdf" className="sr-only" disabled={busy}
              onChange={e => {const file=e.target.files?.[0]; e.target.value=''; if(file)void upload(row.paper_id,file);}}/></label>
            <p className="w-full text-muted">可使用已经登录的常用浏览器下载，上传后校验并接回这条题录，无需安装下载引擎。</p>
          </div>}
        </div>)}
        {!active && retryPaperIds(job.results).length > 0 && <button className="btn-subtle" disabled={busy}
          onClick={() => void start(retryPaperIds(job.results), job.mode)}>重试未完成的论文</button>}
      </div>}
      {error && <p role="alert" className="text-xs" style={{color:'var(--danger)'}}>{error}</p>}
    </section>}
    {error&&!open&&<p role="alert" className="mt-2 text-xs" style={{color:'var(--danger)'}}>{error}</p>}
  </div>;
}
