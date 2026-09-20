import { useEffect, useState } from 'react';
import { useApi } from '../workspaceContext';
import type { PaperChatContext } from '../pages/chatContextModel';

export function DiscussionPapers({papers, onOpenPaper}: {
  papers: NonNullable<PaperChatContext['papers']>; onOpenPaper: (id: number) => void;
}) {
  const api = useApi();
  const [states, setStates] = useState<Record<number, {status: string; message: string}>>({});
  const [attempt, setAttempt] = useState(0);
  const signature = papers.map(p => `${p.id}:${!!p.unavailable}`).join(',');
  useEffect(() => {
    let alive = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    setStates({});
    async function prepare(id: number, retry = false) {
      try {
        const result = await api.prepareReading(id, retry);
        if (!alive) return;
        setStates(previous => ({...previous, [id]: result}));
        if (result.status === 'loading') timers.push(setTimeout(() => void prepare(id), 1500));
      } catch (e: any) { if (alive) setStates(previous => ({...previous, [id]: {status: 'error', message: e.message}})); }
    }
    papers.filter(p => !p.unavailable).forEach(p => void prepare(p.id, attempt > 0));
    return () => { alive = false; timers.forEach(clearTimeout); };
  }, [api, signature, attempt]);
  const ready = papers.filter(p => !p.unavailable && states[p.id]?.status === 'ready').length;
  const errors = papers.some(p => p.unavailable || states[p.id]?.status === 'error');
  const pending = papers.some(p => !p.unavailable && (!states[p.id] || states[p.id].status === 'loading'));
  return <details className="w-full" open>
    <summary className="cursor-pointer" aria-live="polite">所选论文 · {ready}/{papers.length} 篇全文已就绪{pending ? ' · 论文加载中…' : ''}</summary>
    <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto">
      {papers.map(p => <li key={p.id} className="flex flex-wrap items-baseline gap-x-2">
        <button className="btn-ghost max-w-full truncate py-0.5 text-left text-xs" disabled={p.unavailable} onClick={() => onOpenPaper(p.id)}>{p.title ?? `论文 #${p.id}`}</button>
        <span className={p.unavailable || states[p.id]?.status === 'error' ? 'text-[var(--danger)]' : 'text-muted'}>{p.unavailable ? '已移除，当前不可读取' : states[p.id]?.message ?? '论文加载中…'}</span>
      </li>)}
    </ul>
    {errors && <p className="mt-1 text-muted">部分论文暂时无法提供全文，仍可先讨论已有材料。<button className="btn-ghost py-0.5 text-xs" onClick={() => setAttempt(n => n + 1)}>重试加载</button></p>}
  </details>;
}
