import { useEffect, useState } from 'react';
import { localToken } from '../api';
import { workspaceRequest } from '../workspaceApi';
import { parseApiErrorMessage } from '../pages/apiErrorModel';
import { usePaperDraft } from './usePaperDraft';

interface Backup {
  filename: string; size_bytes: number; created_at: string;
  projects: { id: string; name: string }[]; error?: string | null;
}
interface Guide {
  can_restore: boolean; errors: string[]; data_dir: string;
  preflight_command: string; apply_command: string;
}

export function ApplicationBackupPanel() {
  const [rows, setRows] = useState<Backup[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [guides, setGuides] = useState<Record<string, Guide>>({});
  const [draft, setDraft, clearDraft] = usePaperDraft('application', { requestId: '' }, 'application-backup', 'application');
  async function refresh() { setRows(await workspaceRequest('/backups')); }
  useEffect(() => { let alive = true; workspaceRequest('/backups').then(value => { if (alive) setRows(value); }).catch(e => { if (alive) setError(e.message); }); return () => { alive = false; }; }, []);
  async function act(action: () => Promise<void>) {
    if (busy) return; setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function create() {
    const saved = { requestId: draft.requestId || crypto.randomUUID() };
    setDraft(saved);
    await workspaceRequest('/backups', { request_id: saved.requestId });
    clearDraft(saved); await refresh(); setNotice('全部项目的备份已保存，可以下载并查看恢复说明。');
  }
  async function download(filename: string) {
    const response = await fetch('/api/workspaces/backups/' + encodeURIComponent(filename) + '/download-ticket', {
      method: 'POST', headers: { 'X-Local-Token': localToken() },
    });
    if (!response.ok) throw new Error(parseApiErrorMessage(response.status, await response.text()));
    const { url } = await response.json();
    // Native download streams the archive without buffering the whole library in JS.
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setNotice('已请求下载，请在浏览器或桌面下载窗口中确认保存位置。');
  }
  return <section className="card space-y-3">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="font-semibold">全部研究项目备份</h3><p className="mt-1 text-sm text-muted">保存项目目录、每个项目的论文与原文、会话、专题版本，以及共享模型连接。</p></div>
      <button className="btn-primary" disabled={busy} onClick={() => act(create)}>{busy ? '处理中…' : draft.requestId ? '重试创建整体备份' : '备份全部项目'}</button>
    </div>
    <p className="text-sm text-muted">备份包含模型配置密钥，请保存到你控制的位置。整体恢复会替换目标目录中的全部研究项目，并保留恢复前的回退副本。</p>
    {error && <p role="alert" className="text-sm break-words" style={{ color: 'var(--danger)' }}>{error}</p>}
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <button className="btn-ghost text-sm" disabled={busy} onClick={() => act(refresh)}>刷新整体备份列表</button>
    {!rows.length && <p className="text-sm text-muted">尚无整体备份。下方可单独备份当前项目。</p>}
    {rows.map(row => <div key={row.filename} className="rounded-lg border p-3 space-y-2" style={{ borderColor: 'var(--border)' }}>
      <p className="text-sm">{new Date(row.created_at).toLocaleString()} · {row.projects.length} 个项目 · {(row.size_bytes / 1048576).toFixed(1)} MB</p>
      <p className="text-xs text-muted break-words">{row.projects.map(project => project.name).join('、')}</p>
      <p className="text-xs font-mono break-all text-muted">{row.filename}</p>
      {row.error ? <p className="text-sm" role="alert">{row.error}</p> : <div className="flex flex-wrap gap-2">
        <button className="btn-secondary text-sm" disabled={busy} onClick={() => act(() => download(row.filename))}>下载整体备份</button>
        <button className="btn-ghost text-sm" disabled={busy} onClick={() => act(async () => { const value = await workspaceRequest('/backups/' + encodeURIComponent(row.filename) + '/restore-guide'); setGuides(current => ({ ...current, [row.filename]: value })); })}>校验与恢复说明</button>
      </div>}
      {guides[row.filename] && <div className="space-y-2 text-sm border-t pt-3" style={{ borderColor: 'var(--border)' }}>
        {guides[row.filename].can_restore ? <>
          <p>备份校验通过。目标数据目录：<span className="break-all">{guides[row.filename].data_dir}</span></p>
          <p>在 PowerShell 中运行预检，核对将恢复的项目与目标位置：</p>
          <pre className="overflow-auto whitespace-pre-wrap break-all rounded p-2 text-xs" style={{ background: 'var(--surface-2)' }}>{guides[row.filename].preflight_command}</pre>
          <p>关闭使用该目录的 PaperMind 窗口和服务，再执行恢复：</p>
          <pre className="overflow-auto whitespace-pre-wrap break-all rounded p-2 text-xs" style={{ background: 'var(--surface-2)' }}>{guides[row.filename].apply_command}</pre>
          <p className="text-muted">换机时，将备份与同版本程序带到新电脑，按实际位置修改 Backup 和 DataDir。保留脚本输出的回退目录，直到原文、专题与模型配置检查完成。</p>
        </> : <p role="alert" style={{ color: 'var(--danger)' }}>{guides[row.filename].errors.join('；')}</p>}
      </div>}
    </div>)}
  </section>;
}
