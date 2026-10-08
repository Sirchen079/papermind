import type {Source} from '../api';
import {groupPaperSources,materialLabel} from '../pages/sourcePresentationModel';

export function SavedPaperSources({sources,onOpenPaper,expanded=false}:{sources:Source[];expanded?:boolean;onOpenPaper:(id:number,page?:number)=>void}) {
  if(!sources.length)return null;
  const groups=groupPaperSources(sources);
  return <details open={expanded} className="rounded-lg border border-[var(--border)] p-3 space-y-3" data-saved-paper-sources>
    <summary className="cursor-pointer text-sm font-medium">已保存的论文材料（{groups.reduce((n,g)=>n+g.papers.length,0)} 篇）</summary>
    <p className="text-xs text-muted">保留当时的原文、摘要或研究记录，可分别回查。</p>
    {groups.map(group=><section className="space-y-2" key={group.key} aria-label={group.label}>
      <p className="text-xs font-medium text-muted">{group.label} · {group.papers.length} 篇</p>
      {group.papers.map(p=><details open={expanded} className="space-y-2 border-t border-[var(--border)] pt-3" key={p.paper_id}>
      <summary className="cursor-pointer break-words text-sm">[P{p.paper_id}] {p.title}</summary>
      <button className="btn-ghost text-xs" onClick={()=>onOpenPaper(p.paper_id)}>打开论文</button>
      {p.sources.map((s,i)=><section key={i} className="space-y-2">
        <p className="text-xs text-muted">{materialLabel(s)}{s.locator?` · ${s.locator}`:''}</p>
        <div className="flex flex-wrap gap-2">{[...new Set(s.pages??[])].filter(p=>Number.isInteger(p)&&p>0).map(page=><button key={page} className="btn-ghost text-xs" onClick={()=>onOpenPaper(p.paper_id,page)}>查看 PDF 第 {page} 页</button>)}</div>
        <blockquote className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-[var(--border)] pl-3 text-sm">{(s.excerpt||s.snippet||'此记录只有书目信息。').replace(/<!-- page:(\d+) -->/g,'\n[PDF 第 $1 页]\n')}</blockquote>
        {s.excerpt_truncated&&<p className="text-xs text-muted">此处保留摘录前部，可打开论文继续阅读。</p>}
      </section>)}
    </details>)}</section>)}
  </details>;
}
