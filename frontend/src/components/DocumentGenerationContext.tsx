import type {DocumentGenerationRequest} from '../api';

export function DocumentGenerationContext({request,onNavigate}:{request?:DocumentGenerationRequest|null;onNavigate:()=>void}) {
  if(!request)return null;
  return <details className="rounded-lg border border-[var(--border)] p-3 text-sm">
    <summary className="cursor-pointer font-medium">生成时的用户要求</summary>
    <p className="mt-2 text-xs text-muted">原始 AI 稿件生成前的最近一轮要求；后续修订和当前要求优先。</p>
    <blockquote className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words">{request.content}</blockquote>
    <a className="btn-ghost mt-2 inline-block" onClick={onNavigate} href={`#chat?conversation=${request.conversation_id}`}>查看任务原对话</a>
  </details>;
}
