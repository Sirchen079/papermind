import { useEffect, useMemo, useRef, useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { createReviewRequest, putReviewThemes, type MapTheme, type PaperCardEntry, type ReviewMapDetail, type ReviewMapPaper } from '../reviewsApi';
import { addTheme, fieldLocation, filterPapers, mergeThemes, removeTheme, renameTheme, statusLabel, type CardField, type FilterablePaper } from '../pages/reviewMapModel';

const EXPORTS: [string, string][] = [['html', 'HTML'], ['xlsx', 'Excel'], ['docx', 'Word'], ['csv', 'CSV'], ['bib', 'BibTeX']];

function fieldsOf(card: PaperCardEntry['card']): CardField[] {
  if (!card) return [];
  return [card.problem, card.mechanism, card.data_setting, ...(card.contributions ?? []), card.boundary].filter(
    (field): field is CardField => Boolean(field),
  );
}

export function ReviewMap({ reviewId, onOpenPaper }: { reviewId: string; onOpenPaper: (id: number, page?: number) => void }) {
  const { base } = useWorkspace();
  const request = useMemo(() => createReviewRequest(base), [base]);
  const [map, setMap] = useState<ReviewMapDetail | null>(null);
  const [cards, setCards] = useState<PaperCardEntry[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<MapTheme[]>([]);
  const [mergePick, setMergePick] = useState<string[]>([]);
  const [mergeName, setMergeName] = useState('');
  const [newName, setNewName] = useState('');
  const [savedHint, setSavedHint] = useState('');
  const [query, setQuery] = useState('');
  const [themeFilter, setThemeFilter] = useState('');
  const [evidenceFilter, setEvidenceFilter] = useState('');
  const [onlyCheck, setOnlyCheck] = useState(false);
  const [cardPage, setCardPage] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    const g = ++generation.current;
    setMap(null); setCards([]); setError(''); setEditing(false); setSavedHint('');
    request<ReviewMapDetail>(`/${reviewId}/map`).then((next) => { if (g === generation.current) setMap(next); })
      .catch((e) => { if (g === generation.current) setError((e as Error).message); });
    return () => { ++generation.current; };
  }, [reviewId, request]);

  useEffect(() => {
    if (!map || map.status === 'running' || map.status === 'draft') return;
    const g = generation.current;
    request<PaperCardEntry[]>(`/${reviewId}/cards`).then((rows) => { if (g === generation.current) setCards(rows); })
      .catch(() => {/* 卡片列表失败不阻塞地图展示 */});
  }, [reviewId, request, map?.status, map?.version]);

  useEffect(() => {
    if (map?.status !== 'running') return;
    let alive = true, pending = false;
    const timer = setInterval(async () => {
      if (pending) return;
      pending = true;
      try { const next = await request<ReviewMapDetail>(`/${reviewId}/map`); if (alive) setMap(next); }
      catch (e) { if (alive) setError((e as Error).message); }
      finally { pending = false; }
    }, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [map?.status, reviewId, request]);

  async function call(name: string) {
    setBusy(true); setError('');
    const g = generation.current;
    try { const next = await request<ReviewMapDetail>(`/${reviewId}/map/${name}`, {}); if (g === generation.current) setMap(next); }
    catch (e) { if (g === generation.current) setError((e as Error).message); }
    finally { if (g === generation.current) setBusy(false); }
  }

  async function saveThemes() {
    if (!map) return;
    setBusy(true); setError(''); setSavedHint('');
    try {
      const next = await putReviewThemes<ReviewMapDetail>(base, reviewId, draft, map.version);
      setMap(next); setEditing(false); setMergePick([]); setMergeName(''); setNewName('');
      setSavedHint('主题已保存。点“重新生成受影响部分”更新地图。');
    } catch (e) {
      const err = e as Error & { status?: number };
      setError(err.status === 409 ? '地图已被更新，请刷新后再改' : err.message);
    } finally { setBusy(false); }
  }

  const cardById = useMemo(() => new Map(cards.map((c) => [c.paper_id, c])), [cards]);
  const papers: FilterablePaper[] = useMemo(() => (map?.papers ?? []).map((paper: ReviewMapPaper) => {
    const entry = cardById.get(paper.paper_id);
    return { ...paper, fields: fieldsOf(entry?.card ?? null) };
  }), [map?.papers, cardById]);
  const filtered = useMemo(() => filterPapers(papers, { query, theme: themeFilter, evidence: evidenceFilter, status: onlyCheck ? 'needs_check' : '' }), [papers, query, themeFilter, evidenceFilter, onlyCheck]);

  function jumpTo(pid: number) {
    const node = document.getElementById(`map-card-${pid}`) as HTMLDetailsElement | null;
    if (node) { node.open = true; node.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  }

  if (!map) return <section className="card space-y-3" aria-label="文献地图"><p role="status">正在读取文献地图…</p>{error && <p className="text-sm text-red-600" role="alert">{error}</p>}</section>;

  const running = map.status === 'running';
  const generated = map.themes.length > 0;
  const paperTitle = (pid: number) => map.papers.find((p) => p.paper_id === pid)?.title ?? `论文 ${pid}`;

  return <section className="card space-y-4" aria-label="文献地图">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg">文献地图</h2>
      <div className="flex flex-wrap gap-2">
        {EXPORTS.map(([fmt, label]) => <button key={fmt} className="btn-ghost" disabled={!generated} onClick={() => window.open(`${base}/reviews/${reviewId}/map/export?format=${fmt}`, '_blank')}>导出{label}</button>)}
      </div>
    </div>
    {!generated && !running && <div className="space-y-3">
      <p className="text-sm text-muted">基于本次综述的论文生成精读卡片、研究主题、值得研究的问题和阅读路线，不需要等正文写完。</p>
      {map.error && <p className="text-sm text-amber-700">{map.error}</p>}
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      <button className="btn-primary" disabled={busy} onClick={() => call('run')}>{busy ? '正在启动…' : '生成文献地图'}</button>
    </div>}
    {running && <div className="space-y-3">
      <p role="status">{map.stage || '正在生成'} · 论文 {map.counts.papers} 篇 · 已归类 {map.counts.assigned} 篇</p>
      <button className="btn-ghost" disabled={busy} onClick={() => call('stop')}>暂停</button>
    </div>}
    {generated && !running && <>
      {map.error && <p className="text-sm text-amber-700">{map.error}</p>}
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      {savedHint && <p className="text-sm" style={{ color: 'var(--success, #15803d)' }}>{savedHint}</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={busy} onClick={() => call('run')}>{map.status === 'failed' ? '重新生成' : '重新生成受影响部分'}</button>
        {!editing && <button className="btn-ghost" disabled={busy} onClick={() => { setDraft(map.themes); setEditing(true); setSavedHint(''); }}>编辑主题</button>}
        {editing && <>
          <button className="btn-primary" disabled={busy} onClick={saveThemes}>保存主题</button>
          <button className="btn-ghost" disabled={busy} onClick={() => { setEditing(false); setMergePick([]); setMergeName(''); setNewName(''); }}>取消</button>
        </>}
      </div>
      <p className="text-sm text-muted">论文 {map.counts.papers} 篇 · 精读卡片 {map.counts.cards_done} 篇 · 已归类 {map.counts.assigned} 篇 · 未归类 {map.counts.unassigned} 篇</p>

      {(map.overview.summary || map.overview.reading_route?.length || map.overview.research_steps?.length) && <div className="space-y-2 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
        <h3 className="font-semibold">总览与阅读路线</h3>
        {map.overview.error && <p className="text-sm text-amber-700">{map.overview.error}</p>}
        {map.overview.summary && <p className="text-sm">{map.overview.summary}</p>}
        {!!map.overview.reading_route?.length && <ol className="space-y-1 text-sm list-decimal list-inside">
          {map.overview.reading_route.map((step) => <li key={step.step}><strong>{step.goal}</strong>
            {' '}{step.papers.map((pid) => <button key={pid} className="btn-ghost text-xs" onClick={() => jumpTo(pid)}>[P{pid}] {paperTitle(pid)}</button>)}
            {step.source_missing && <span className="text-xs text-muted"> · 来源待补</span>}
            {step.why && <span className="text-xs text-muted">（{step.why}）</span>}</li>)}
        </ol>}
        {!!map.overview.research_steps?.length && <div className="text-sm"><p className="font-semibold">开展新研究的步骤</p><ol className="list-decimal list-inside space-y-1">{map.overview.research_steps.map((step, i) => <li key={i}>{step}</li>)}</ol></div>}
      </div>}

      <div className="space-y-2 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
        <h3 className="font-semibold">研究主题 · {map.themes.length} 条</h3>
        {!editing && map.themes.map((theme) => {
          const synthesis = map.syntheses[theme.id] ?? {};
          return <details key={theme.id} className="space-y-2 border rounded p-2" style={{ borderColor: 'var(--border)' }}>
            <summary className="cursor-pointer">{theme.name} <span className="text-xs text-muted">{synthesis.stats?.count ?? 0} 篇</span></summary>
            <p className="text-sm text-muted">{theme.definition}</p>
            {synthesis.error && <p className="text-sm text-amber-700">{synthesis.error}</p>}
            {synthesis.stats && <p className="text-xs text-muted">年份：{Object.entries(synthesis.stats.years ?? {}).map(([y, n]) => `${y} 年 ${n} 篇`).join('、') || '无'}；数据：{Object.entries(synthesis.stats.setting ?? {}).map(([k, n]) => `${k} ${n}`).join('、')}</p>}
            {synthesis.trend && <p className="text-sm"><strong>趋势：</strong>{synthesis.trend}</p>}
            {!!synthesis.open_questions?.length && <div className="text-sm"><p className="font-semibold">值得研究的问题</p><ul className="list-disc list-inside space-y-1">{synthesis.open_questions.map((q, i) => <li key={i}>{q.question}{q.source_missing && <span className="text-xs text-muted"> · 来源待补</span>}{q.cannot_claim && <span className="text-xs text-muted">（不能宣称：{q.cannot_claim}）</span>}</li>)}</ul></div>}
            {!!synthesis.combination_opportunities?.length && <div className="text-sm"><p className="font-semibold">方法组合机会</p><ul className="list-disc list-inside space-y-1">{synthesis.combination_opportunities.map((c, i) => <li key={i}>{c.idea}{c.source_missing && <span className="text-xs text-muted"> · 来源待补</span>}{c.risk && <span className="text-xs text-muted">（风险：{c.risk}）</span>}</li>)}</ul></div>}
            {!!synthesis.representative?.length && <p className="text-sm"><strong>代表论文：</strong>{synthesis.representative.map((r) => <button key={r.paper_id} className="btn-ghost text-xs" onClick={() => jumpTo(r.paper_id)}>[P{r.paper_id}] {paperTitle(r.paper_id)}</button>)}</p>}
          </details>;
        })}
        {editing && <div className="space-y-3">
          {draft.map((theme, index) => <div key={theme.id || `new-${index}`} className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={mergePick.includes(theme.id)} disabled={!theme.id} onChange={() => setMergePick((old) => old.includes(theme.id) ? old.filter((x) => x !== theme.id) : [...old, theme.id])}/>合并</label>
            <input className="input flex-1 min-w-40" aria-label="主题名称" value={theme.name} onChange={(e) => setDraft(renameTheme(draft, theme.id, e.target.value))}/>
            <button className="btn-ghost" disabled={!theme.id} onClick={() => setDraft(removeTheme(draft, theme.id))}>删除</button>
          </div>)}
          <div className="flex flex-wrap items-center gap-2">
            <input className="input flex-1 min-w-40" placeholder="新主题名称" aria-label="新主题名称" value={newName} onChange={(e) => setNewName(e.target.value)}/>
            <button className="btn-ghost" disabled={!newName.trim()} onClick={() => { setDraft(addTheme(draft, newName.trim())); setNewName(''); }}>新增主题</button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input className="input flex-1 min-w-40" placeholder="合并后的主题名称" aria-label="合并后的主题名称" value={mergeName} onChange={(e) => setMergeName(e.target.value)}/>
            <button className="btn-ghost" disabled={mergePick.length < 2 || !mergeName.trim()} onClick={() => { setDraft(mergeThemes(draft, mergePick, mergeName.trim())); setMergePick([]); setMergeName(''); }}>合并所选（{mergePick.length}）</button>
          </div>
          <p className="text-xs text-muted">改名、删除、合并、新增都会保留未受影响的归类与综合；保存后点“重新生成受影响部分”更新地图。</p>
        </div>}
      </div>

      <div className="space-y-2 border-t pt-3" style={{ borderColor: 'var(--border)' }}>
        <h3 className="font-semibold">精读卡片 · {filtered.length} 篇</h3>
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1 min-w-40" placeholder="搜索题名或 DOI" aria-label="搜索精读卡片" value={query} onChange={(e) => { setQuery(e.target.value); setCardPage(0); }}/>
          <select className="input" aria-label="按主题筛选" value={themeFilter} onChange={(e) => { setThemeFilter(e.target.value); setCardPage(0); }}>
            <option value="">全部主题</option>
            {map.themes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select className="input" aria-label="按证据级别筛选" value={evidenceFilter} onChange={(e) => { setEvidenceFilter(e.target.value); setCardPage(0); }}>
            <option value="">全部证据级别</option>
            <option value="full_text">全文</option>
            <option value="abstract">摘要</option>
            <option value="metadata">仅元数据</option>
          </select>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={onlyCheck} onChange={(e) => { setOnlyCheck(e.target.checked); setCardPage(0); }}/>只看需核对的</label>
        </div>
        {filtered.slice(cardPage * 20, cardPage * 20 + 20).map((paper) => {
          const entry = cardById.get(paper.paper_id);
          const card = entry?.card ?? null;
          return <details key={paper.paper_id} id={`map-card-${paper.paper_id}`} className="space-y-2 border rounded p-2" style={{ borderColor: 'var(--border)' }}>
            <summary className="cursor-pointer">[P{paper.paper_id}] {paper.year ? `${paper.year} ` : ''}{paper.title}{paper.venue ? ` · ${paper.venue}` : ''}</summary>
            <p className="text-xs text-muted">主题：{paper.themes.map((tid) => map.themes.find((t) => t.id === tid)?.name ?? tid).join('、') || '未归类'}；证据级别：{paper.evidence_level || '—'}；卡片状态：{entry?.status ?? paper.card_status}{entry?.warning ? ` · ${entry.warning}` : ''}</p>
            {paper.doi && <p className="text-xs"><a className="underline" href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer">{paper.doi}</a></p>}
            {card ? [
              ['问题', card.problem], ['机制', card.mechanism], ['数据条件', card.data_setting],
              ...(card.contributions ?? []).map((c, i) => [`主要贡献 ${i + 1}`, c] as [string, typeof card.problem]),
              ['判断边界', card.boundary],
            ].filter((pair): pair is [string, NonNullable<typeof card.problem>] => Boolean(pair[1])).map(([label, field]) => {
              const location = fieldLocation(field);
              return <p key={label} className="text-sm"><strong>{label}：</strong>{field.value}
                {' '}<span className="text-xs" style={{ color: field.status === 'number_mismatch' ? 'var(--warning, #b45309)' : 'var(--muted, #6b7280)' }}>
                  {statusLabel(field.status)}{field.missing_numbers?.length ? `：缺少 ${field.missing_numbers.join('、')}` : ''}{location.text ? `（${location.text}）` : ''}
                </span>
                {location.page !== undefined && <button className="btn-ghost text-xs" onClick={() => onOpenPaper(paper.paper_id, location.page)}>查看原文</button>}
                {field.quote && <span className="block text-xs text-muted">原文：“{field.quote}”</span>}
              </p>;
            }) : <p className="text-sm text-muted">这篇论文还没有精读卡片。</p>}
          </details>;
        })}
        <div className="flex gap-2">
          <button className="btn-ghost" disabled={!cardPage} onClick={() => setCardPage(cardPage - 1)}>上一页</button>
          <button className="btn-ghost" disabled={(cardPage + 1) * 20 >= filtered.length} onClick={() => setCardPage(cardPage + 1)}>下一页</button>
        </div>
      </div>
    </>}
  </section>;
}
