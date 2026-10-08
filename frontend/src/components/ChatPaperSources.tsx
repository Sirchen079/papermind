import type {Source} from '../api';
import {groupPaperSources} from '../pages/sourcePresentationModel';

export function ChatPaperSources({sources,onOpen}:{sources:Source[];onOpen:(id:number)=>void}) {
  const groups=groupPaperSources(sources);
  if(!groups.length)return null;
  return <div className="mt-3 space-y-2 text-xs" data-chat-paper-materials>
    {groups.map(group=>{
      const links=<div className="mt-2 flex flex-wrap gap-2">{group.papers.map(p=><button key={p.paper_id} type="button"
        className="max-w-[300px] truncate rounded-full px-2 py-1 text-left hover:opacity-80"
        style={{backgroundColor:'var(--surface-2)',color:group.key==='original_text'?'var(--accent)':'var(--muted)'}}
        title={`${group.label}：[P${p.paper_id}] ${p.title}`} onClick={()=>onOpen(p.paper_id)}>[P{p.paper_id}] {p.title}</button>)}</div>;
      return group.key==='original_text'?<section key={group.key} aria-label={group.label}>
        <p className="text-muted">{group.label} · {group.papers.length} 篇</p>{links}
      </section>:<details key={group.key} className="rounded-lg border border-[var(--border)] p-2">
        <summary className="cursor-pointer text-muted">{group.label} · {group.papers.length} 篇</summary>{links}
      </details>;
    })}
  </div>;
}
