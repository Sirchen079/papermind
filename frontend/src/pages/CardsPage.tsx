import { useEffect, useMemo, useRef, useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { Shell } from '../components/layout/Shell';
import { ReviewListPicker } from '../components/ReviewListPicker';
import { createReviewRequest, type PaperCardEntry, type ReviewMapDetail, type ReviewMapPaper } from '../reviewsApi';
import { cardCheckSummary, cardFieldRows, cardRowQuoteLabel, cardRowStatusText, cardToMarkdown, filterCards } from './cardsPageModel';
import type { NavLocation } from './navigationModel';

type ReviewSummary = { id: string; question: string; status: string };

function download(text: string, name: string, type = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type: type + ';charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function CardsPage({ params, onNavigate, onOpenPaper }: { params: Record<string, string>; onNavigate: (target: NavLocation | string) => void; onOpenPaper: (id: number, page?: number) => void }) {
  const { base } = useWorkspace();
  const request = useMemo(() => createReviewRequest(base), [base]);
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [reviewsLoaded, setReviewsLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState(() => params.review ?? '');
  const [cards, setCards] = useState<PaperCardEntry[] | null>(null);
  const [metaById, setMetaById] = useState<Map<number, ReviewMapPaper>>(new Map());
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const generation = useRef(0);
  const paramReview = params.review ?? '';

  // 挂载时拉综述列表；初始选中 params.review（存在时），否则第一项。
  useEffect(() => {
    let alive = true;
    request<ReviewSummary[]>('').then(rows => {
      if (!alive) return;
      setReviews(rows); setReviewsLoaded(true);
      setSelectedId(prev => {
        if (prev && rows.some(r => r.id === prev)) return prev;
        if (paramReview && rows.some(r => r.id === paramReview)) return paramReview;
        return rows[0]?.id ?? '';
      });
    }).catch(e => { if (alive) { setError(e.message); setReviewsLoaded(true); } });
    return () => { alive = false; };
    // paramReview 只作为初始/深链选择依据，列表只在挂载与 base 变化时拉取。
  }, [request]);

  // 深链变化（前进/后退或带 review 参数跳入）时同步选中专题。
  useEffect(() => {
    if (paramReview && paramReview !== selectedId) setSelectedId(paramReview);
  }, [paramReview]);

  // 选中变化重新拉精读卡片；年份/venue/DOI 取自文献地图的论文表，缺失或失败不阻塞卡片列表。
  useEffect(() => {
    if (!selectedId) { setCards(null); setLoading(false); return; }
    const g = ++generation.current;
    setCards(null); setError(''); setLoading(true);
    request<PaperCardEntry[]>('/' + selectedId + '/cards').then(rows => {
      if (g !== generation.current) return;
      setCards(rows); setLoading(false);
    }).catch(e => {
      if (g !== generation.current) return;
      setError((e as Error).message); setLoading(false);
    });
    request<ReviewMapDetail>('/' + selectedId + '/map').then(m => {
      if (g === generation.current) setMetaById(new Map((m.papers ?? []).map(p => [p.paper_id, p])));
    }).catch(() => { /* 地图不存在时只少元信息 */ });
    return () => { ++generation.current; };
  }, [selectedId, request]);

  const filtered = filterCards(cards ?? [], query);
  return <Shell max="wide"><div className="space-y-6">
    <div className="flex flex-wrap justify-between gap-3">
      <div><h1 className="page-title">精读卡片</h1><p className="page-subtitle mt-2">按专题浏览精读卡片，查看字段与引文，可单篇导出。</p></div>
      <div className="flex gap-2">
        <button className="btn-ghost" disabled={!selectedId} onClick={() => onNavigate({ page: 'research', params: { mode: 'review', review: selectedId } })}>打开文献地图</button>
        <button className="btn-ghost" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建精读批次</button>
      </div>
    </div>
    {error && <p className="card text-red-600" role="alert">{error}</p>}
    {!reviewsLoaded && !error && <p role="status">正在读取专题列表…</p>}
    {reviewsLoaded && !error && !reviews.length && <section className="card space-y-3"><p className="text-sm text-muted">还没有专题综述。先新建一个精读批次，生成文献地图后就会得到精读卡片。</p><button className="btn-primary" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建精读批次</button></section>}
    {!!reviews.length && <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="space-y-2"><h2 className="text-lg">专题</h2><ReviewListPicker reviews={reviews} selectedId={selectedId} onSelect={setSelectedId}/></aside>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg">精读卡片 · {filtered.length} 篇</h2>
          <input className="input flex-1 min-w-40" placeholder="搜索题名或 P 编号" aria-label="搜索精读卡片" value={query} onChange={e => setQuery(e.target.value)}/>
        </div>
        {loading && <p role="status">正在读取精读卡片…</p>}
        {!loading && !error && cards && !cards.length && <p className="text-sm text-muted">该综述还没有精读卡片，先在综述页生成文献地图。</p>}
        <div className="space-y-2">
          {filtered.map(entry => {
            const meta = metaById.get(entry.paper_id);
            const rows = cardFieldRows(entry.card);
            const checkSummary = cardCheckSummary(entry.card);
            return <details key={entry.paper_id} className="space-y-2 border rounded p-2" style={{ borderColor: 'var(--border)' }}>
              <summary className="cursor-pointer">[P{entry.paper_id}] {meta?.year ? `${meta.year} ` : ''}{entry.title}{meta?.venue ? ` · ${meta.venue}` : ''}</summary>
              <p className="text-xs text-muted">卡片状态：{entry.status}{checkSummary ? ` · ${checkSummary}` : ''}{entry.warning ? ` · ${entry.warning}` : ''}</p>
              {meta?.doi && <p className="text-xs"><a className="underline" href={`https://doi.org/${meta.doi}`} target="_blank" rel="noreferrer">{meta.doi}</a></p>}
              {rows.length ? rows.map(row => {
                const status = cardRowStatusText(row);
                return <p key={row.label} className="text-sm"><strong>{row.label}：</strong>{row.value}
                  {' '}<span className="text-xs" style={{ color: row.problem ? 'var(--warning, #b45309)' : 'var(--muted, #6b7280)' }}>{status}</span>
                  {row.page !== undefined && <button className="btn-ghost text-xs" onClick={() => onOpenPaper(entry.paper_id, row.page)}>查看原文</button>}
                  {row.quote && <span className="block text-xs text-muted">{cardRowQuoteLabel(row)}：“{row.quote}”</span>}
                </p>;
              }) : <p className="text-sm text-muted">这篇论文还没有精读卡片。</p>}
              <div className="flex flex-wrap gap-2">
                <button className="btn-ghost" onClick={() => download(cardToMarkdown(entry, meta), `P${entry.paper_id}-精读卡片.md`)}>导出卡片</button>
                <button className="btn-ghost" onClick={() => onOpenPaper(entry.paper_id)}>打开论文</button>
              </div>
            </details>;
          })}
        </div>
      </section>
    </div>}
  </div></Shell>;
}
