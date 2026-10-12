import { useEffect, useMemo, useState } from 'react';
import { useApi, useWorkspace } from '../workspaceContext';
import { Shell } from '../components/layout/Shell';
import { ReviewListPicker } from '../components/ReviewListPicker';
import { ReviewMap } from '../components/ReviewMap';
import { createReviewRequest } from '../reviewsApi';
import { pickInitialReview } from './mapPageModel';
import type { NavLocation } from './navigationModel';

type ReviewSummary = { id: string; question: string; status: string };

// 一级「文献地图」页：选专题 → 直接看地图。地图的生成/暂停/导出/主题编辑
// 全部由 ReviewMap 组件自带，这里只负责选专题与导航。
export default function MapPage({ params, onNavigate, onOpenPaper }: { params: Record<string, string>; onNavigate: (target: NavLocation | string) => void; onOpenPaper: (id: number, page?: number) => void }) {
  const { base } = useWorkspace();
  const api = useApi();
  const request = useMemo(() => createReviewRequest(base), [base]);
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [reviewsLoaded, setReviewsLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState(() => params.review ?? '');
  const [error, setError] = useState('');
  const paramReview = params.review ?? '';

  // 挂载时拉综述列表；初始选中 params.review（存在时），否则第一项。
  useEffect(() => {
    let alive = true;
    request<ReviewSummary[]>('').then(rows => {
      if (!alive) return;
      setReviews(rows); setReviewsLoaded(true);
      setSelectedId(prev => pickInitialReview(prev, paramReview, rows));
    }).catch(e => { if (alive) { setError(e.message); setReviewsLoaded(true); } });
    return () => { alive = false; };
    // paramReview 只作为初始/深链选择依据，列表只在挂载与 base 变化时拉取。
  }, [request]);

  // 深链变化（前进/后退或带 review 参数跳入）时同步选中专题。
  useEffect(() => {
    if (paramReview && paramReview !== selectedId) setSelectedId(paramReview);
  }, [paramReview]);

  // 与 LibraryReview 的 researchFromMap 等价：地图里的“带着这个问题继续研究”
  // 有代表论文时建论文讨论，否则开空白研究对话。错误由 ReviewMap 捕获展示。
  async function researchFromMap(question: string, paperIds: number[]) {
    const conversation = paperIds.length ? await api.createPaperDiscussion(paperIds) : await api.createConversation();
    onNavigate({ page: 'chat', params: { conversation: String(conversation.id), question } });
  }

  // 与 LibraryReview 的 ideaFromMap 等价：地图条目就地存为研究想法（origin=map），
  // 代表论文以 basis 角色关联；成功提示由 ReviewMap 显示，不跳转页面。
  async function ideaFromMap(p: { title: string; content: string; paperIds: number[] }) {
    await api.createIdea({ title: p.title, content: p.content, origin: 'map', papers: p.paperIds.map(id => ({ paper_id: id, role: 'basis' })) });
  }

  return <Shell max="wide"><div className="space-y-6">
    <div className="flex flex-wrap justify-between gap-3">
      <div><h1 className="page-title">文献地图</h1><p className="page-subtitle mt-2">按专题查看研究主题、值得研究的问题、方法组合机会与阅读路线。</p></div>
      <div className="flex gap-2">
        <button className="btn-ghost" disabled={!selectedId} onClick={() => onNavigate({ page: 'research', params: { mode: 'review', review: selectedId } })}>打开综述页面</button>
        <button className="btn-ghost" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建综述</button>
      </div>
    </div>
    {error && <p className="card text-red-600" role="alert">{error}</p>}
    {!reviewsLoaded && !error && <p role="status">正在读取专题列表…</p>}
    {reviewsLoaded && !error && !reviews.length && <section className="card space-y-3"><p className="text-sm text-muted">还没有专题综述。先新建一个综述批次，生成文献地图后就能在这里查看研究主题与阅读路线。</p><button className="btn-primary" onClick={() => onNavigate({ page: 'research', params: { mode: 'review' } })}>新建综述</button></section>}
    {!!reviews.length && <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="space-y-2"><h2 className="text-lg">专题</h2><ReviewListPicker reviews={reviews} selectedId={selectedId} onSelect={setSelectedId}/></aside>
      <section className="space-y-3">
        {selectedId && <ReviewMap reviewId={selectedId} onOpenPaper={onOpenPaper} onResearch={researchFromMap} onCreateIdea={ideaFromMap}/>}
      </section>
    </div>}
  </div></Shell>;
}
