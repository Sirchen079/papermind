import { useEffect, useRef, useState } from 'react';
import type { PaperCardEntry, ReviewMapPaper } from '../reviewsApi';
import { cardCheckSummary, cardFieldRows } from '../pages/cardsPageModel';
import { PaperCardFields } from './PaperCardFields';
import { statusLabels } from './ReviewListPicker';

type Props = {
  entries: PaperCardEntry[];
  total: number;
  reviewId: string;
  metaById: Map<number, ReviewMapPaper>;
  query: string;
  preferredPaperId?: number;
  onSelectPaper: (id: number) => void;
  onClearSearch: () => void;
  onSaved: (entry: PaperCardEntry) => void;
  onOpenPaper: (id: number, page?: number) => void;
  onExport: (entry: PaperCardEntry) => void;
};

export function CardWorkbench({ entries, total, reviewId, metaById, query, preferredPaperId, onSelectPaper, onClearSearch, onSaved, onOpenPaper, onExport }: Props) {
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(preferredPaperId ?? entries[0]?.paper_id ?? null);
  const articleRef = useRef<HTMLElement>(null);
  useEffect(() => { if (preferredPaperId) setSelectedPaperId(preferredPaperId); }, [preferredPaperId]);
  const selected = entries.find(entry => entry.paper_id === selectedPaperId) ?? entries[0];

  // 搜索移除当前论文时立即展示首条结果，并将它保留为新的阅读位置。
  useEffect(() => {
    if (!entries.some(entry => entry.paper_id === selectedPaperId)) setSelectedPaperId(entries[0]?.paper_id ?? null);
  }, [entries, selectedPaperId]);

  if (!selected) return <section className="card-workbench-empty">
    <p className="workspace-kicker">{total ? '没有匹配论文' : '等待精读材料'}</p>
    <h2>{total ? `未找到“${query.trim()}”` : '这个专题还没有精读卡片'}</h2>
    <p>{total ? '可按论文题名或 P 编号重新搜索。' : '在专题综述中生成文献地图后，论文的研究判断与引文会收录在这里。'}</p>
    {total > 0 && <button className="btn-ghost" onClick={onClearSearch}>清除搜索</button>}
  </section>;

  const meta = metaById.get(selected.paper_id);
  const rows = cardFieldRows(selected.card);
  const quoteCount = rows.filter(row => row.quote).length;
  const checkSummary = cardCheckSummary(selected.card);
  return <div className="card-workbench">
    <aside className="card-workbench-index" aria-label="专题论文索引">
      <div className="card-workbench-index-heading"><h2><span aria-hidden="true">▤</span> 论文索引</h2><span>{entries.length}{entries.length !== total ? ` / ${total}` : ''} 篇</span></div>
      <div className="card-workbench-paper-list">
        {entries.map(entry => {
          const paper = metaById.get(entry.paper_id);
          const needsCheck = cardCheckSummary(entry.card);
          return <button type="button" key={entry.paper_id} className="card-workbench-paper" aria-current={selected.paper_id === entry.paper_id ? 'true' : undefined} onClick={() => { setSelectedPaperId(entry.paper_id); onSelectPaper(entry.paper_id); articleRef.current?.scrollIntoView({block:'start'}); }}>
            <span className="card-workbench-paper-top"><span className="card-workbench-id">P{entry.paper_id}</span><span>{statusLabels[entry.status] || entry.status}</span></span>
            <span className="card-workbench-paper-title">{entry.title || `论文 ${entry.paper_id}`}</span>
            <span className="card-workbench-paper-meta">{[paper?.year, paper?.venue].filter(Boolean).join(' · ') || '未记录出版信息'}</span>
            {needsCheck && <span className="card-workbench-paper-warning">{needsCheck}</span>}
          </button>;
        })}
      </div>
    </aside>
    <article ref={articleRef} className="card-workbench-file" aria-labelledby="card-workbench-title" style={{scrollMarginTop:'calc(var(--layout-header) + 16px)'}}>
      <header className="card-workbench-file-heading">
        <div className="card-workbench-file-top"><p className="workspace-kicker"><span className="card-workbench-id">P{selected.paper_id}</span> 证据档案</p><span className="card-workbench-version">v{selected.version} · {statusLabels[selected.status] || selected.status}</span></div>
        <h2 id="card-workbench-title">{selected.title || `论文 ${selected.paper_id}`}</h2>
        <p className="card-workbench-bibliography">{[meta?.year, meta?.venue].filter(Boolean).join(' · ') || '未记录出版信息'}{meta?.doi && <> · <a href={`https://doi.org/${meta.doi}`} target="_blank" rel="noreferrer">DOI {meta.doi}</a></>}</p>
        <div className="card-workbench-file-toolbar"><p><span><b>{rows.length}</b> 项研究判断</span><span><b>{quoteCount}</b> 段引文</span></p><div><button className="btn-ghost" onClick={() => onExport(selected)}>导出卡片</button><button className="btn-primary" onClick={() => onOpenPaper(selected.paper_id)}>打开论文 <span aria-hidden="true">↗</span></button></div></div>
      </header>
      {(checkSummary || selected.warning) && <div className="card-workbench-notice" role="note">{checkSummary && <p>{checkSummary}</p>}{selected.warning && <p>{selected.warning}</p>}</div>}
      <div className="card-workbench-evidence-heading"><h3><span aria-hidden="true">01</span> 研究判断与证据</h3><p>对照支撑引文，核验并修订研究判断。</p></div>
      <PaperCardFields key={`${reviewId}:${selected.paper_id}`} entry={selected} reviewId={reviewId} onSaved={onSaved} onOpenPaper={onOpenPaper}/>
    </article>
  </div>;
}
