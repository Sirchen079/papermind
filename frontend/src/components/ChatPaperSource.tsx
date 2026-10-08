import { createPortal } from 'react-dom';
import type { Source } from '../api';
import { Drawer } from './ui/Drawer';
import {materialLabel} from '../pages/sourcePresentationModel';

export function ChatPaperSource({sources, earlierSources=[], onClose, onOpenPaper}: {
  sources: Source[] | null; earlierSources?: Source[]; onClose: () => void; onOpenPaper: (id: number, page?: number) => void;
}) {
  const current=sources??[];
  const first = current[0]??earlierSources[0];
  if (!first) return null;
  function open(page?: number) { onClose(); onOpenPaper(first.paper_id, page); }
  const passages=(rows:Source[],earlier=false)=>rows.map((source, index) => <section key={index} className="space-y-2 border-t pt-3" style={{borderColor:'var(--border)'}}>
        <p className="text-xs text-muted">{materialLabel(source)}{source.locator ? ` · ${source.locator}` : ''}</p>
        {!earlier && source.carried_from_message && <p className="text-xs text-muted">沿用此前保存的材料</p>}
        <div className="flex flex-wrap gap-2">
          {[...new Set((source.pages ?? []).filter(p => Number.isInteger(p) && p > 0))].map(page =>
            <button key={page} className="btn-ghost text-xs" onClick={() => open(page)}>查看 PDF 第 {page} 页</button>)}
        </div>
        <blockquote className="whitespace-pre-wrap break-words border-l-2 pl-3 text-sm leading-relaxed" style={{borderColor:'var(--border)'}}>
          {(source.excerpt || source.snippet || '此记录只返回了书目信息，没有正文片段。').replace(/<!-- page:(\d+) -->/g, '\n[PDF 第 $1 页]\n')}
        </blockquote>
        {source.excerpt_truncated && <p className="text-xs text-muted">较长摘录仅展示前部，可打开论文继续阅读。</p>}
      </section>);
  return createPortal(<Drawer open onClose={onClose} title="论文来源" width="max-w-xl">
    <div className="space-y-4" data-chat-paper-source>
      <h4 className="break-words font-semibold">[P{first.paper_id}] {first.title}</h4>
      <p className="text-xs text-muted">按类型保留返回给 AI 的材料。原文片段可按页回查，片段记录不表示整篇已读完或结论已核实。</p>
      <button className="btn-ghost text-xs" onClick={() => open()}>打开论文</button>
      {earlierSources.length>0 && <details className="space-y-3" open={current.length===0}>
        <summary className="cursor-pointer text-sm font-medium">此前保存的材料（{earlierSources.length}）</summary>
        <p className="text-xs text-muted">来自这条消息之前的对话记录，未作为本轮新增读取。</p>
        <div className="space-y-3" aria-label="此前来源">{passages(earlierSources,true)}</div>
      </details>}
      {current.length>0 && <div className="space-y-3" aria-label="本轮来源">
        <p className="text-sm font-medium">本轮提供的材料</p>
        {passages(current)}
      </div>}
    </div>
  </Drawer>, document.body);
}
