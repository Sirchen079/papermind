// 专题综述选择列表：与 LibraryReview「最近综述」同一套 shelf-paper 行样式，
// 供精读卡片页与后续文献地图页复用。
export const statusLabels: Record<string, string> = { draft: '待开始', running: '正在生成', ready: '已生成', partial: '部分完成', paused: '已暂停', needs_input: '等待材料或模型', done: '已分析', fallback: '保留已有材料', missing: '缺少可读材料', pending: '待分析', failed: '生成失败' };

export function ReviewListPicker({ reviews, selectedId, onSelect }: { reviews: { id: string; question: string; status: string }[]; selectedId: string; onSelect: (id: string) => void }) {
  if (!reviews.length) return null;
  return <div className="review-index-list">{reviews.map(r => <button key={r.id} className="review-index-item" aria-current={selectedId === r.id ? 'true' : undefined} onClick={() => onSelect(r.id)}><span>{r.question}</span><small>{statusLabels[r.status] ?? r.status}</small></button>)}</div>;
}
