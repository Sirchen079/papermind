import { useEffect, useRef, useState } from 'react';
import type { DocumentStatus } from '../api';
import { useApi } from '../workspaceContext';
import { DocumentProcessingPanel } from './DocumentProcessingPanel';

export function PaperDocumentAccess({paperId}: {paperId: number}) {
  const api = useApi();
  const [status, setStatus] = useState<DocumentStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.documentStatus(paperId);
        if (version !== generation.current) return;
        setStatus(next);
        if (['queued','running','waiting_model'].includes(next.status) || next.index_status === 'pending') timer = setTimeout(poll, 2000);
      } catch { /* The conversion panel exposes connection errors and retry. */ }
    }
    void poll();
    return () => { generation.current++; clearTimeout(timer); };
  }, [api, paperId, attempt]);
  const progress = status && ['queued','running'].includes(status.status) ? ` · ${status.completed_pages}/${status.total_pages} 页` : '';
  const label = status?.status === 'waiting_model' ? 'PDF 已保存 · 配置 OCR 后继续' : status?.status === 'ready' ? 'Markdown 原文' : ['error','interrupted','cancelled'].includes(status?.status || '') ? 'OCR 未完成 · 继续处理' : `OCR 与 Markdown${progress}`;
  return <>
    <button className="btn-subtle px-2.5 py-1.5 text-xs" onClick={() => setOpen(true)}>{label}</button>
    {open && <DocumentProcessingPanel paperId={paperId} onClose={() => {setOpen(false); setAttempt(n => n + 1);}} onReady={() => setAttempt(n => n + 1)} />}
  </>;
}
