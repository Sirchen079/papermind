import { useCallback, useEffect, useRef, useState } from 'react';
import type { LiteratureCandidate, LiteratureSurveyDetail, LiteratureSurveySummary } from '../api';
import { useApi } from '../workspaceContext';
import { Shell } from '../components/layout/Shell';
import { PageHeader } from '../components/ui/PageHeader';
import {
  DEFAULT_IMPORT_BATCH_CAP, MAX_RESULTS_OPTIONS, YEARS_OPTIONS,
  authorLine, canImportCandidate, candidateSourceLabel, candidateStatusLabel, candidateStatusTone,
  clampChoice, importActive, selectionWithinCap, surveyActive, surveyQueryValid, surveyStatusLabel,
} from './literatureModel';

export default function Literature({ onOpenPaper }: { onOpenPaper: (id: number) => void }) {
  const api = useApi();
  const [surveys, setSurveys] = useState<LiteratureSurveySummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<LiteratureSurveyDetail | null>(null);
  const [query, setQuery] = useState('');
  const [years, setYears] = useState<number>(2);
  const [maxResults, setMaxResults] = useState<number>(20);
  const [screen, setScreen] = useState(true);
  const [picked, setPicked] = useState<number[]>([]);
  const [expanded, setExpanded] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const loadDetail = useCallback(async (id: number) => {
    const next = await api.literatureSurvey(id);
    if (alive.current) setDetail(next);
    return next;
  }, [api]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      let delay = 6000;
      try {
        const items = (await api.literatureSurveys()).items;
        if (stopped) return;
        setSurveys(items);
        if (items.some(s => surveyActive(s.status) || s.import_status === 'running')) delay = 1500;
        if (selected != null) {
          const next = await loadDetail(selected);
          if (stopped) return;
          if (next && (surveyActive(next.status) || importActive(next))) delay = 1500;
          setPicked(current => current.filter(id => next?.candidates.some(c => c.id === id && canImportCandidate(c.status))));
        }
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : '读取调研状态失败');
      }
      if (!stopped) timer = setTimeout(poll, delay);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [api, loadDetail, selected]);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !surveyQueryValid(query)) return;
    setBusy(true); setError('');
    try {
      const created = await api.createLiteratureSurvey({ query: query.trim(), years, max_results: maxResults, screen });
      if (alive.current) { setSelected(created.id); setDetail(null); setPicked([]); }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : '发起调研失败');
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function importPicked() {
    if (!detail || !selectionWithinCap(picked.length, detail.import_batch_cap ?? DEFAULT_IMPORT_BATCH_CAP)) return;
    setBusy(true); setError('');
    try {
      await api.importLiteratureCandidates(detail.id, picked);
      if (alive.current) setPicked([]);
      await loadDetail(detail.id);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : '添加失败');
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function remove(id: number) {
    if (busy) return;
    try {
      await api.deleteLiteratureSurvey(id);
      if (alive.current && selected === id) { setSelected(null); setDetail(null); setPicked([]); }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : '删除失败');
    }
  }

  const cap = detail?.import_batch_cap ?? DEFAULT_IMPORT_BATCH_CAP;
  const importable = detail?.candidates.filter(c => canImportCandidate(c.status)) ?? [];
  const allPicked = importable.length > 0 && importable.every(c => picked.includes(c.id));

  return <Shell className="space-y-5">
    <PageHeader title="文献调研" subtitle="描述主题，AI 检索公开文献并给出候选；你过目勾选后加入论文库。"/>
    <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="space-y-4 self-start">
        <form onSubmit={start} className="card space-y-3">
          <label className="block text-sm">要调研什么主题？
            <textarea className="input mt-1 w-full" rows={3} maxLength={500} required placeholder="例如：近两年关于 FWI 目标函数的论文"
              value={query} disabled={busy} onChange={e => setQuery(e.target.value)}/>
          </label>
          <div className="flex gap-2">
            <label className="block text-xs text-muted flex-1">时间范围
              <select className="input mt-1 w-full text-xs" aria-label="时间范围" value={years}
                onChange={e => setYears(clampChoice(Number(e.target.value), YEARS_OPTIONS, 2))}>
                {YEARS_OPTIONS.map(value => <option key={value} value={value}>近 {value} 年</option>)}
              </select>
            </label>
            <label className="block text-xs text-muted flex-1">候选数量
              <select className="input mt-1 w-full text-xs" aria-label="候选数量" value={maxResults}
                onChange={e => setMaxResults(clampChoice(Number(e.target.value), MAX_RESULTS_OPTIONS, 20))}>
                {MAX_RESULTS_OPTIONS.map(value => <option key={value} value={value}>{value} 篇</option>)}
              </select>
            </label>
          </div>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={screen} onChange={e => setScreen(e.target.checked)}/>
            用 AI 扩展检索词并筛选候选（调用已配置的文本模型）</label>
          <button className="btn-primary w-full" disabled={busy || !surveyQueryValid(query)}>{busy ? '正在提交…' : '开始调研'}</button>
          <p className="text-xs text-muted">检索使用公开的 OpenAlex 接口，不经过图书馆账号；下载仅使用公开开放获取链接，逐篇串行添加。</p>
        </form>
        <section className="card space-y-2" aria-label="历史调研">
          <h2 className="text-sm font-medium">历史调研</h2>
          {surveys.map(s => <div key={s.id} className="flex items-start gap-1">
            <button className="btn-ghost flex-1 text-left" aria-current={selected === s.id ? 'page' : undefined}
              onClick={() => { setSelected(s.id); setDetail(null); setPicked([]); }}>
              <span className="block break-words">{s.query}</span>
              <span className="text-xs text-muted">{surveyStatusLabel(s.status)}{s.import_status === 'running' ? ' · 正在添加' : ''} · 近 {s.years} 年</span>
            </button>
            <button className="btn-ghost text-xs" aria-label={`删除调研 ${s.query}`} disabled={busy}
              onClick={() => void remove(s.id)}>删除</button>
          </div>)}
          {surveys.length === 0 && <p className="text-sm text-muted">还没有调研记录。</p>}
        </section>
      </aside>

      <section className="space-y-4" aria-label="调研结果">
        {!detail && <div className="card space-y-3"><h2 className="text-xl">候选文献由你把关</h2>
          <p className="text-sm text-muted">AI 负责检索、扩展关键词和初步筛选；每篇候选是否入库由你勾选决定。没有公开全文的文献先保存题录，之后可手动补充 PDF。</p></div>}
        {detail && <>
          <div className="card space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg break-words">{detail.query}</h2>
              <span className="text-sm text-muted">{surveyStatusLabel(detail.status)}{detail.screened ? ' · AI 已筛选' : ''}</span>
            </div>
            {detail.error && <p role="alert" className="text-sm" style={{ color: 'var(--danger)' }}>{detail.error}</p>}
            {surveyActive(detail.status) && <p role="status" className="text-sm text-muted">正在检索与筛选公开文献…</p>}
            <p className="text-xs text-muted">{importable.length} 篇可添加 · 单次最多 {cap} 篇 · 逐篇串行限速</p>
          </div>
          <ul className="card divide-y divide-[var(--border)]">
            {detail.candidates.map(candidate => <CandidateRow key={candidate.id} candidate={candidate}
              checked={picked.includes(candidate.id)}
              onToggle={() => setPicked(current => current.includes(candidate.id)
                ? current.filter(id => id !== candidate.id)
                : (current.length >= cap ? current : [...current, candidate.id]))}
              expanded={expanded.includes(candidate.id)}
              onExpand={() => setExpanded(current => current.includes(candidate.id)
                ? current.filter(id => id !== candidate.id) : [...current, candidate.id])}
              onOpenPaper={onOpenPaper}/>)}
          </ul>
          <div className="card flex flex-wrap items-center gap-2">
            <button className="btn-subtle" disabled={!importable.length || allPicked || busy || importActive(detail)}
              onClick={() => setPicked(importable.slice(0, cap).map(c => c.id))}>选择可添加的前 {Math.min(cap, importable.length)} 篇</button>
            <button className="btn-subtle" disabled={!picked.length || busy} onClick={() => setPicked([])}>清空选择</button>
            <button className="btn-primary" disabled={busy || !selectionWithinCap(picked.length, cap) || importActive(detail)}
              onClick={() => void importPicked()}>
              {importActive(detail) ? '正在添加…' : `添加所选到论文库（${picked.length}/${cap}）`}
            </button>
            {picked.length > cap && <span className="text-xs" style={{ color: 'var(--danger)' }}>一次最多添加 {cap} 篇，请取消部分选择。</span>}
          </div>
        </>}
        {error && <p role="alert" className="card text-sm" style={{ color: 'var(--danger)' }}>{error} <button className="btn-ghost" onClick={() => setError('')}>关闭</button></p>}
      </section>
    </div>
  </Shell>;
}

function CandidateRow({ candidate, checked, onToggle, expanded, onExpand, onOpenPaper }: {
  candidate: LiteratureCandidate; checked: boolean; onToggle: () => void;
  expanded: boolean; onExpand: () => void; onOpenPaper: (id: number) => void;
}) {
  const selectable = canImportCandidate(candidate.status);
  const link = candidate.doi ? `https://doi.org/${candidate.doi}` : candidate.oa_pdf_url || '';
  return <li className="flex gap-3 p-3">
    <input type="checkbox" className="mt-1" aria-label={`选择 ${candidate.title}`} checked={checked}
      disabled={!selectable} onChange={onToggle}/>
    <div className="min-w-0 flex-1 space-y-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        {candidate.paper_id != null
          ? <button className="btn-ghost px-0 underline break-words text-left" onClick={() => onOpenPaper(candidate.paper_id as number)}>{candidate.title}</button>
          : link ? <a className="underline break-words" href={link} target="_blank" rel="noreferrer">{candidate.title}</a>
            : <span className="break-words">{candidate.title}</span>}
        <span className="text-xs text-muted">{candidate.venue || '未知期刊'}{candidate.year ? ` · ${candidate.year}` : ''} · 被引 {candidate.cited_by_count}</span>
        <span className="text-xs rounded border border-[var(--border)] px-1">{candidateSourceLabel(candidate)}</span>
      </div>
      <p className="text-xs text-muted">{authorLine(candidate.authors)}</p>
      {candidate.relevance && <p className="text-xs">AI 意见：{candidate.relevance}{candidate.keep === false ? '（建议略过）' : ''}</p>}
      {candidate.abstract && <div>
        <button className="btn-ghost px-0 text-xs" aria-expanded={expanded} onClick={onExpand}>{expanded ? '收起摘要' : '展开摘要'}</button>
        {expanded && <p className="text-sm text-muted whitespace-pre-wrap">{candidate.abstract}</p>}
      </div>}
      <p className="text-xs" style={{ color: candidateStatusTone(candidate.status) }}>
        {candidateStatusLabel(candidate.status)}{candidate.note ? ` · ${candidate.note}` : ''}
      </p>
    </div>
  </li>;
}
