import { useEffect, useMemo, useRef, useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { Shell } from '../components/layout/Shell';
import { statusLabels } from '../components/ReviewListPicker';
import { createReviewRequest, type PaperCardEntry, type ReviewMapDetail, type ReviewMapPaper } from '../reviewsApi';
import { cardToMarkdown, filterCards } from './cardsPageModel';
import { CardWorkbench } from '../components/CardWorkbench';
import type { NavLocation } from './navigationModel';
import '../card-workbench.css';

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
    setCards(null); setMetaById(new Map()); setError(''); setLoading(true);
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
  const requestedPaper = Number(params.paper);
  const cardsGeneration = generation.current;
  return <Shell max="wide"><div className="card-workbench-page space-y-6">
    <div className="archive-page-heading flex flex-wrap justify-between gap-3">
      <div><p className="workspace-kicker">阅读档案 / EVIDENCE</p><h1 className="page-title">精读卡片</h1><p className="page-subtitle mt-2">研究判断、支撑引文与修订记录</p></div>
      <div className="flex gap-2">
        <button className="btn-ghost" disabled={!selectedId} onClick={() => onNavigate({ page: 'map', params: { review: selectedId } })}>打开文献地图</button>
        <button className="btn-primary" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建精读批次</button>
      </div>
    </div>
    {error && <p className="card text-red-600" role="alert">{error}</p>}
    {!reviewsLoaded && !error && <p role="status">正在读取专题列表…</p>}
    {reviewsLoaded && !error && !reviews.length && <section className="card space-y-3"><p className="text-sm text-muted">还没有专题综述。先新建一个精读批次，生成文献地图后就会得到精读卡片。</p><button className="btn-primary" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建精读批次</button></section>}
    {!!reviews.length && <>
      <div className="card-workbench-controls">
        <label className="card-workbench-topic"><span>当前专题</span><select className="input" value={selectedId} onChange={e => { setSelectedId(e.target.value); setQuery(''); onNavigate({page:'cards',params:{review:e.target.value}}); }}>{reviews.map(review => <option key={review.id} value={review.id}>{review.question} · {statusLabels[review.status] || review.status}</option>)}</select></label>
        <label className="card-workbench-search"><span>查找论文</span><input className="input" type="search" placeholder="搜索题名或 P 编号" aria-label="搜索精读卡片" value={query} onChange={e => setQuery(e.target.value)}/></label>
      </div>
      {loading && <p className="card-workbench-loading" role="status">正在读取精读卡片…</p>}
      {!loading && !error && cards && <CardWorkbench key={selectedId} entries={filtered} total={cards.length} reviewId={selectedId} metaById={metaById} query={query} onClearSearch={() => setQuery('')}
        preferredPaperId={Number.isSafeInteger(requestedPaper)&&requestedPaper>0?requestedPaper:undefined} onSelectPaper={id=>onNavigate({page:'cards',params:{review:selectedId,paper:String(id)}})}
        onSaved={next => { if (cardsGeneration === generation.current) setCards(old => old?.map(card => card.paper_id === next.paper_id ? next : card) ?? null); }} onOpenPaper={onOpenPaper}
        onExport={entry => download(cardToMarkdown(entry, metaById.get(entry.paper_id)), `P${entry.paper_id}-精读卡片.md`)}/>}
    </>}
  </div></Shell>;
}
