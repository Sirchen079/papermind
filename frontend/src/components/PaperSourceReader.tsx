import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useApi } from '../workspaceContext';
import type { Paper, ReadingWorkspace } from '../api';
import PdfReader from './PdfReader';
import { Drawer } from './ui/Drawer';
import { useToast } from './ui/Toast';

/** Open a source above the current task so its selection, scroll and drafts stay mounted. */
export default function PaperSourceReader({paperId, page, returnLabel, onClose, onOpenPaper}: {
  paperId: number; page?: number; returnLabel: string; onClose: () => void;
  onOpenPaper: (id: number, page?: number) => void;
}) {
  const api = useApi(), toast = useToast();
  const [paper, setPaper] = useState<Paper | null>(null);
  const [reading, setReading] = useState<ReadingWorkspace | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const pendingPage = useRef<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const alive = useRef(true);
  const host = useRef<HTMLDivElement>(null);
  const closeLabel = `返回${returnLabel}`;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false; clearTimeout(timer.current); void flushProgress();
    };
  }, []);
  useEffect(() => {
    let active = true; setError('');
    Promise.all([api.getPaper(paperId), api.getReadingWorkspace(paperId)]).then(([p, r]) => {
      if (active) { setPaper(p); setReading(r); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [api, paperId, attempt]);
  useEffect(() => { host.current?.querySelector<HTMLElement>('button:not(:disabled)')?.focus(); }, [paper, error]);
  async function refreshNotes() {
    const next = await api.getReadingWorkspace(paperId);
    if (alive.current) setReading(next);
  }
  async function save(action: () => Promise<unknown>) {
    try { await action(); }
    catch (e) { toast.error((e as Error).message); return false; }
    try { await refreshNotes(); }
    catch { toast.error('已保存，但列表刷新失败。重新打开论文可查看。'); }
    return true;
  }
  async function flushProgress() {
    const next = pendingPage.current; pendingPage.current = null;
    if (next !== null) {
      try { await api.patchReadingState(paperId, {last_page: next}); }
      catch { /* Reading and the underlying task remain available. */ }
    }
  }
  function progress(next: number) {
    pendingPage.current = next;
    if (timer.current) return;
    timer.current = setTimeout(() => { timer.current = undefined; void flushProgress(); }, 2000);
  }
  return createPortal(<div ref={host} className="fixed inset-0 z-[60]">
    {paper?.has_pdf && reading ? <PdfReader
      paperId={paperId} title={paper.title} initialPage={page ?? reading.state.last_page ?? null}
      notes={reading.notes} excerpts={reading.excerpts} closeLabel={closeLabel}
      onSaveExcerpt={(quote, sourcePage) => save(() => api.createExcerpt(paperId, {quote, page: sourcePage}))}
      onSaveExcerptNote={(id, note) => save(() => api.patchExcerpt(paperId, id, {note}))}
      onCreateNote={payload => save(() => api.createNote(paperId, payload))}
      onRefreshNotes={() => refreshNotes().catch(e => toast.error((e as Error).message))} onProgress={progress} onClose={onClose} onOpenPaper={onOpenPaper}
    /> : <Drawer open title={paper?.title || '查看论文来源'} onClose={onClose} width="max-w-2xl">
      {error ? <p role="alert">{error} <button className="btn-ghost" onClick={() => setAttempt(n => n + 1)}>重试</button></p>
        : paper ? <><p className="text-sm text-muted mb-3">这篇论文暂未附 PDF，以下是已保存的摘要。</p><p className="whitespace-pre-wrap">{paper.abstract || '暂无摘要。'}</p></>
        : <p role="status">正在打开论文…</p>}
      <button className="btn-primary mt-4" onClick={onClose}>{closeLabel}</button>
    </Drawer>}
  </div>, document.body);
}
