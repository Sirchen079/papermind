import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { DocumentStatus } from '../api';
import { useApi, useWorkspace } from '../workspaceContext';
import { MarkdownContent } from './MarkdownContent';
import { DocumentModelSettings } from './DocumentModelSettings';

const labels: Record<string, string> = {idle: '尚未转换', queued: '等待处理', running: '正在转换', ready: '已生成 Markdown', error: '转换未完成', cancelled: '已停止', interrupted: '上次转换中断'};

export function DocumentProcessingPanel({paperId, onClose, onReady}: {paperId: number; onClose: () => void; onReady: () => void}) {
  const api = useApi();
  const {base} = useWorkspace();
  const [status, setStatus] = useState<DocumentStatus | null>(null);
  const [mode, setMode] = useState<'auto' | 'ocr'>('auto');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [configOpen, setConfigOpen] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const ready = useRef(onReady); ready.current = onReady;
  const alive = useRef(true);
  const generation = useRef(0);
  const active = status?.status === 'running' || status?.status === 'queued';
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.isComposing || event.defaultPrevented) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close.current(); }
      if (event.key === 'Tab') {
        const elements = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]') || []);
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener('keydown', key, true);
    return () => { alive.current = false; generation.current++; window.removeEventListener('keydown', key, true); previous?.focus(); };
  }, []);
  useEffect(() => {
    const version = ++generation.current;
    let timer: ReturnType<typeof setTimeout>;
    let loaded = false;
    setError('');
    async function poll() {
      try {
        const next = await api.documentStatus(paperId);
        if (version !== generation.current) return;
        setStatus(next);
        if (!loaded) { setMode(next.mode); loaded = true; }
        if (next.has_markdown) {
          const result = await api.documentMarkdown(paperId);
          if (version !== generation.current) return;
          setMarkdown(result.markdown);
        }
        if (next.status === 'ready') ready.current();
        if (['queued', 'running'].includes(next.status) || next.index_status === 'pending') timer = setTimeout(poll, 1500);
      } catch (e: unknown) { if (version === generation.current) setError(e instanceof Error ? e.message : '读取进度失败'); }
    }
    void poll();
    return () => { generation.current++; clearTimeout(timer); };
  }, [api, paperId, attempt]);
  async function run(action: 'start' | 'force' | 'cancel') {
    setBusy(true); setError(''); generation.current++;
    try {
      const next = action === 'cancel' ? await api.cancelDocument(paperId) : await api.convertDocument(paperId, mode, action === 'force');
      if (alive.current) { setStatus(next); setAttempt(n => n + 1); }
    } catch (e: unknown) { if (alive.current) setError(e instanceof Error ? e.message : '操作失败'); }
    finally { if (alive.current) setBusy(false); }
  }
  const preview = markdown.replace(/\]\(page-(\d+)\.png\)/g, `](${base}/papers/${paperId}/document/pages/$1)`);
  return createPortal(<div className="fixed inset-0 flex justify-end bg-black/25" style={{zIndex: 80}} onClick={onClose}>
    <div ref={dialog} role="dialog" aria-modal="true" aria-label="OCR 与 Markdown" tabIndex={-1}
      className="flex h-full w-full max-w-2xl flex-col bg-[var(--surface)] shadow-xl" onClick={e => e.stopPropagation()}>
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] p-4">
        <h2 className="text-lg">OCR 与 Markdown</h2><button className="btn-ghost" onClick={onClose} aria-label="关闭文档转换">关闭</button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        <p className="text-sm text-muted">转换结果落库后供 AI 阅读，并自动更新向量索引。保留原 PDF 与逐页原图；公式、表格和模糊文字请对照原页核查。关闭面板后任务继续。</p>
        <button className="btn-ghost text-xs" aria-expanded={configOpen} onClick={() => setConfigOpen(v => !v)}>配置 OCR 模型</button>
        {configOpen && <DocumentModelSettings ocrOnly />}
        <label className="block text-sm">转换方式
          <select className="input mt-1 w-full" aria-label="转换方式" value={mode} disabled={active || busy} onChange={e => setMode(e.target.value as 'auto' | 'ocr')}>
            <option value="auto">自动：提取文本，扫描页使用 OCR</option><option value="ocr">全文 OCR：所有页面交给识别模型</option>
          </select>
        </label>
        <div className="space-y-2" role="status" aria-live="polite">
          <p className="text-sm">{status ? labels[status.status] || status.status : '正在读取进度…'}{status && status.total_pages > 0 && ` · ${status.completed_pages} / ${status.total_pages} 页（OCR ${status.ocr_pages} 页）`}</p>
          {status && status.total_pages > 0 && <div role="progressbar" aria-label="转换进度" aria-valuenow={status.completed_pages} aria-valuemin={0} aria-valuemax={status.total_pages}
            className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--border)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{width: `${Math.min(100, status.completed_pages / status.total_pages * 100)}%`}} /></div>}
          {status?.model_name && <p className="text-xs text-muted">识别模型：{status.model_name}</p>}
        </div>
        {status?.error && <p role="alert" className="text-sm" style={{color: 'var(--danger)'}}>{status.error}</p>}
        {error && <p role="alert" className="text-sm" style={{color: 'var(--danger)'}}>{error} <button className="btn-ghost" onClick={() => setAttempt(n => n + 1)}>刷新状态</button></p>}
        <div className="flex flex-wrap gap-2">
          {active ? <button className="btn-subtle" disabled={busy} onClick={() => void run('cancel')}>停止转换</button> : <>
            <button className="btn-primary" disabled={busy || !status} onClick={() => void run('start')}>{busy ? '正在处理…' : status?.status === 'ready' ? '转换 / 使用已缓存结果' : status?.completed_pages ? '继续转换' : '开始转换'}</button>
            {!!status?.completed_pages && <button className="btn-subtle" disabled={busy} onClick={() => void run('force')}>重新识别全部页面</button>}
          </>}
        </div>
        {status?.has_markdown && <div className="space-y-3 border-t border-[var(--border)] pt-4">
          <p className="text-xs text-muted">{active || status.status !== 'ready' ? '下方为上次成功生成的版本。' : '已保存，可供 AI 读取。'}{status.index_status === 'pending' ? '正在更新向量索引…' : status.index_status === 'ready' ? '向量索引已更新。' : status.index_status === 'error' ? '向量索引更新失败，可在设置中重建索引。' : '尚未配置向量模型；配置后可在设置中重建索引。'}</p>
          <div className="flex flex-wrap gap-2"><a className="btn-subtle text-xs" href={`${base}/papers/${paperId}/document/download`} download>下载 Markdown</a><a className="btn-subtle text-xs" href={`${base}/papers/${paperId}/document/download?bundle=true`} download>下载 Markdown 与原图</a></div>
          <MarkdownContent content={preview} images={false} />
        </div>}
      </div>
    </div>
  </div>, document.body);
}
