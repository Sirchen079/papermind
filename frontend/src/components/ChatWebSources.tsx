import type { WebSource } from '../api';
import {groupWebSources,materialLabel} from '../pages/sourcePresentationModel';

export function ChatWebSources({sources}: {sources: WebSource[]}) {
  if (!sources.length) return null;
  return <details className="mt-3 min-w-0 rounded-lg border p-3 text-sm" style={{borderColor:'var(--border)'}} data-web-sources>
    <summary className="cursor-pointer font-medium">已保存的网页材料（{sources.length}）</summary>
    <p className="mt-2 text-xs text-muted">保留当时返回的内容；打开原网页可查看当前版本。</p>
    <div className="mt-3 space-y-3">
      {groupWebSources(sources).map(group=><section key={group.key} className="space-y-2" aria-label={group.label}>
      <p className="text-xs font-medium text-muted">{group.label} · {group.sources.length}</p>
      {group.sources.map((source,index)=><details key={`${source.snapshot_id}:${source.start_char}:${index}`} className="min-w-0 border-t pt-3" style={{borderColor:'var(--border)'}}>
        <summary className="cursor-pointer break-all">{source.title || source.url}</summary>
        <p className="mt-2 text-xs text-muted">{materialLabel(source)} · 读取于 {new Date(source.retrieved_at).toLocaleString()}{source.carried_from_message?' · 沿用此前保存的摘录':''}</p>
        {/^(https?):\/\//i.test(source.url)&&<a className="mt-2 inline-block break-all text-xs" style={{color:'var(--accent)'}} href={source.url} target="_blank" rel="noopener noreferrer">打开原网页 · {source.url}</a>}
        <blockquote className="mt-2 max-h-80 overflow-y-auto whitespace-pre-wrap break-words border-l-2 pl-3 text-sm leading-relaxed" style={{borderColor:'var(--border)'}}>{source.excerpt || source.snippet}</blockquote>
      </details>)}</section>)}
    </div>
  </details>;
}
