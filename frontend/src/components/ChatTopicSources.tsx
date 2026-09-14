import type { TopicSource } from '../api';

const supportLabels: Record<string, string> = {
  pending: '待核对', supported: '已核对支持关系', partial: '部分支持',
  unsupported: '来源不支持', unclear: '仍不明确',
};

function excerpt(source: TopicSource): string {
  return source.snippet.replace(/\[([WAP][a-f0-9]{24})\]/g, (_match, ref) => {
    const index = source.evidence.findIndex(item => item.ref === ref);
    return index < 0 ? '[其他来源]' : `[${index + 1}]`;
  });
}

export function ChatTopicSources({ sources }: { sources: TopicSource[] }) {
  if (!sources.length) return null;
  return <details className="mt-2 rounded-lg border p-2 text-xs" style={{ borderColor: 'var(--border)' }}>
    <summary className="cursor-pointer text-muted">本轮检索到的专题（{sources.length}）</summary>
    <p className="mt-2 text-faint">以下保留检索时的版本、核对状态和证据片段。</p>
    <div className="mt-2 space-y-3">
      {sources.map(source => <div key={`${source.workspace_id}:${source.page_id}:${source.revision}`} className="min-w-0">
        <a className="break-words font-medium" style={{ color: 'var(--accent)' }} href={source.url}>
          {source.title} · v{source.revision}
        </a>
        <p className="mt-1 text-muted">{source.workspace_name || '默认项目'} · {supportLabels[source.support_status] || '待核对'}</p>
        {source.snippet && <p className="mt-1 break-words whitespace-pre-wrap">{excerpt(source)}</p>}
        {source.review_note && <p className="mt-1 break-words text-muted">核对备注：{source.review_note}</p>}
        {!!source.source_changes.length && <p className="mt-1 break-words" style={{ color: 'var(--warning)' }}>
          检索时的来源提示：{[...new Set(source.source_changes)].join('；')}
        </p>}
        {source.evidence.map((evidence, index) => <blockquote key={`${evidence.ref}:${index}`} className="mt-2 border-l-2 pl-2 text-muted" style={{ borderColor: 'var(--border)' }}>
          <p className="break-words">[{index + 1}] {evidence.title}{evidence.locator ? ` · ${evidence.locator}` : ''}</p>
          <p className="mt-1 break-words whitespace-pre-wrap">{evidence.quote}</p>
        </blockquote>)}
      </div>)}
    </div>
  </details>;
}
