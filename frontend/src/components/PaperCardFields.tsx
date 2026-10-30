import { useMemo, useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { createReviewRequest, type PaperCardEntry } from '../reviewsApi';
import { cardFieldRows, cardRowQuoteLabel, cardRowStatusText, type CardRow } from '../pages/cardsPageModel';
import { usePaperDraft } from './usePaperDraft';

type Props = {entry: PaperCardEntry; reviewId: string; onSaved: (entry: PaperCardEntry) => void; onOpenPaper: (id: number, page?: number) => void};

function FieldEditor({entry, reviewId, row, onSaved, onLoaded, onClose}: Props & {row: CardRow; onLoaded: Props['onSaved']; onClose: () => void}) {
  const {base} = useWorkspace();
  const request = useMemo(() => createReviewRequest(base), [base]);
  const [draft, setDraft, clearDraft, storageError] = usePaperDraft(`${entry.paper_id}:${row.key}`,
    {value: row.value, quote: row.quote || '', version: entry.version}, 'card-edit');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [conflict, setConflict] = useState(false);
  const original = entry.card?.manual_fields?.[row.key]?.original;
  async function save() {
    setBusy(true); setError('');
    try {
      const next = await request<PaperCardEntry>(`/${reviewId}/cards/${entry.paper_id}`,
        {field: row.key, value: draft.value, quote: draft.quote, expected_version: draft.version});
      clearDraft(draft); onSaved(next); onClose();
    } catch (e) { setError((e as Error).message); setConflict((e as Error & {status?: number}).status === 409); }
    finally { setBusy(false); }
  }
  async function reload() {
    setBusy(true); setError('');
    try {
      const rows = await request<PaperCardEntry[]>(`/${reviewId}/cards`);
      const latest = rows.find(e => e.paper_id === entry.paper_id);
      if (!latest) throw new Error('卡片已不存在；输入仍保留在本机草稿。');
      onLoaded(latest); setDraft({...draft, version: latest.version}); setConflict(false);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="card-field-editor space-y-3">
    <label className="block text-sm">修订内容<textarea className="input w-full" aria-label={`修订${row.label}`} rows={3} maxLength={10000} disabled={busy} value={draft.value} onChange={e => setDraft({...draft, value: e.target.value})}/></label>
    <label className="block text-sm">支撑引文（可留空）<textarea className="input w-full" aria-label={`${row.label}支撑引文`} rows={2} maxLength={10000} disabled={busy} value={draft.quote} onChange={e => setDraft({...draft, quote: e.target.value})}/></label>
    <p className="text-xs text-muted">保存为人工修订，后续地图与综述更新会带入。引文匹配只核对文字和数字。</p>
    {original && <details className="text-xs text-muted"><summary>查看修订前的 AI 内容</summary><p>{original.value}</p>{original.quote && <blockquote>{original.quote}</blockquote>}</details>}
    {storageError && <p role="alert" className="text-sm">本机存储不可用，关闭应用前请先保存修订。</p>}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="btn-primary" disabled={busy || !draft.value.trim()} onClick={save}>{busy ? '正在处理…' : '保存修订'}</button>
      <button className="btn-ghost" disabled={busy} onClick={onClose}>收起（保留草稿）</button>
      {conflict && <button className="btn-ghost" disabled={busy} onClick={reload}>载入最新卡片，保留输入</button>}
    </div>
  </div>;
}

export function PaperCardFields(props: Props) {
  const {entry, onOpenPaper} = props;
  const [editing, setEditing] = useState(''), [saved, setSaved] = useState(false);
  const rows = cardFieldRows(entry.card);
  return <div className="card-fields">
    {saved && <p role="status" className="text-sm text-muted">修订已保存。更新地图或综述后会带入；当前已生成内容保留。</p>}
    {!rows.length && <p className="text-sm text-muted">这篇论文还没有精读卡片。</p>}
    {rows.map(row => <section key={row.key} className={`card-field ${row.edited?'is-edited':''}`}>
      <div className="card-field-heading"><h3>{row.label}</h3><span className="card-field-status" style={{color: row.problem ? 'var(--warning)' : 'var(--muted)'}}>{cardRowStatusText(row)}</span></div>
      <p className="card-field-value">{row.value}</p>
      {row.quote && <blockquote className="card-field-quote"><span>{cardRowQuoteLabel(row)}</span><p>{row.quote}</p></blockquote>}
      <div className="card-field-actions"><button className="btn-ghost text-xs" onClick={() => onOpenPaper(entry.paper_id, row.page)}>查看原文 <span aria-hidden="true">↗</span></button>
        <button className="btn-ghost text-xs" onClick={() => {setEditing(row.key); setSaved(false);}}>修订{row.label}</button></div>
      {editing === row.key && <FieldEditor {...props} row={row} onLoaded={props.onSaved} onSaved={next => {props.onSaved(next); setSaved(true);}} onClose={() => setEditing('')}/>}</section>)}
    {!!entry.card?.edit_history?.length && <details className="card-revisions text-xs text-muted"><summary>修订历史 · {entry.card.edit_history.length} 次</summary>
      {[...entry.card.edit_history].reverse().map(h => <div key={h.version} className="border-t py-2"><p>{rows.find(r => r.key === h.field)?.label || h.field} · v{h.version} · {new Date(h.updated_at).toLocaleString()}</p><p>修改前：{h.before.value}</p><p>修改后：{h.after.value}</p></div>)}
    </details>}
  </div>;
}
