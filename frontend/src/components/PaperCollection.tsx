import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Paper } from '../api';
import { BookOpen, Trash2, X } from '../icons';
import '../paper-collection.css';

const readingLabels:Record<string,string>={unread:'未读',queued:'待读',reading:'阅读中',read:'已读',skipped:'跳过'};
const priorityLabels:Record<string,string>={high:'高优先级',normal:'普通',medium:'中优先级',low:'低'};

export function PaperCollection({papers,selectedIds,onToggle,onOpen,onRemove}:{papers:Paper[];selectedIds:Set<number>;onToggle:(id:number)=>void;onOpen:(paper:Paper)=>void;onRemove:(paper:Paper)=>void}) {
  const [layout,setLayout]=useState<'shelf'|'list'>('shelf');
  const [focusedId,setFocusedId]=useState<number|null>(null);
  const [previewOpen,setPreviewOpen]=useState(false);
  const previewDialog=useRef<HTMLDialogElement>(null);
  const previewTrigger=useRef<HTMLButtonElement|null>(null);
  const afterPreviewAction=useRef<(()=>void)|null>(null);
  const focused=papers.find(p=>p.id===focusedId)||papers[0];
  useEffect(()=>{
    const dialog=previewDialog.current;
    if(previewOpen&&dialog&&!dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLButtonElement>('[data-preview-close]')?.focus();
    } else if(!previewOpen&&dialog?.open)dialog.close();
  },[previewOpen]);
  function closePreview() { previewDialog.current?.close(); setPreviewOpen(false); }
  function afterPreviewClosed() {
    setPreviewOpen(false); previewTrigger.current?.focus({preventScroll:true});
    const action=afterPreviewAction.current; afterPreviewAction.current=null;
    if(action)requestAnimationFrame(action);
  }
  function afterPreview(action:()=>void) {
    if(previewDialog.current?.open) { afterPreviewAction.current=action; closePreview(); }
    else action();
  }
  if(!papers.length)return null;
  const inspector=focused&&<aside className="paper-inspector" aria-label="论文档案预览" aria-live="polite">
    <div className="inspector-heading"><span><BookOpen size={16}/> 文献档案</span><b>P{String(focused.id).padStart(3,'0')}</b></div>
    <h2>{focused.title||'未命名论文'}</h2><p className="inspector-authors">{focused.authors.join('，')||'作者待补'}</p>
    <dl><div><dt>发表</dt><dd>{[focused.year,focused.venue].filter(Boolean).join(' / ')||'待补充'}</dd></div><div><dt>阅读</dt><dd>{readingLabels[focused.reading?.status||'unread']||'未读'}{focused.reading?.priority?' / '+(priorityLabels[focused.reading.priority]||'未设置'):''}</dd></div>{focused.reading?.relevance&&<div><dt>相关度</dt><dd>{focused.reading.relevance}</dd></div>}</dl>
    <div className="inspector-tags">{[...(focused.tags||[]),...(focused.collections||[])].map((tag,i)=><span key={i}>{tag.name}</span>)}</div>
    <section className="inspector-abstract"><h3>摘要</h3><p>{focused.abstract||'这篇论文还没有摘要。可以打开档案补充资料，或上传 PDF 提取内容。'}</p></section>
    {focused.doi&&<a className="inspector-doi" href={'https://doi.org/'+focused.doi} target="_blank" rel="noreferrer">DOI / {focused.doi} ↗</a>}
    <div className="inspector-actions"><button className="btn-primary" onClick={()=>afterPreview(()=>onOpen(focused))}><BookOpen size={16}/> 打开论文与笔记</button><button className="btn-subtle inspector-remove" aria-label={'从库中移除'+(focused.title||'该论文')} onClick={()=>afterPreview(()=>onRemove(focused))}><Trash2 size={15}/> 从库中移除</button></div>
  </aside>;
  function preview(paper:Paper,trigger:HTMLButtonElement) { setFocusedId(paper.id); if(window.matchMedia('(max-width:1000px)').matches){previewTrigger.current=trigger;setPreviewOpen(true);} }
  return <section className={'paper-collection'+(previewOpen?' is-preview-open':'')} aria-label="论文收藏">
    <div className="collection-toolbar"><p><span className="collection-register" aria-hidden="true">馆藏索引</span>当前显示 <b>{papers.length}</b> 篇</p><div className="collection-toolbar-actions"><button className="collection-preview-toggle" aria-haspopup="dialog" onClick={event=>{previewTrigger.current=event.currentTarget;setPreviewOpen(true);}}>预览档案</button><div className="collection-view" aria-label="论文显示方式"><button aria-pressed={layout==='shelf'} onClick={()=>setLayout('shelf')}><span aria-hidden="true">▦</span> 书架</button><button aria-pressed={layout==='list'} onClick={()=>setLayout('list')}><span aria-hidden="true">☷</span> 清单</button></div></div></div>
    <div className="collection-split">
      <div className={'paper-tiles is-'+layout}>
        {papers.map(p=><article key={p.id} className={'paper-tile '+(focused?.id===p.id?'is-focused ':'')+(selectedIds.has(p.id)?'is-selected':'')}>
          <div className="paper-tile-top"><label><input type="checkbox" checked={selectedIds.has(p.id)} onChange={()=>onToggle(p.id)} aria-label={'选择论文：'+(p.title||'无标题')}/><span>P{String(p.id).padStart(3,'0')}</span></label><span>{p.has_pdf?'PDF':'文献记录'}</span></div>
          <button className="paper-tile-graphic" aria-label={'打开论文：'+(p.title||'无标题')} onClick={()=>onOpen(p)}><span className="paper-sheet" aria-hidden="true"><i/><i/><i/><i/></span><svg viewBox="0 0 164 48" aria-hidden="true"><path d="M10 34h34l24-22h39l31 24h17M44 34h57l37-22"/><circle cx="44" cy="34" r="4"/><circle cx="68" cy="12" r="4"/><circle cx="107" cy="12" r="4"/><circle cx="138" cy="36" r="4"/></svg><span className="paper-graphic-label" aria-hidden="true">文献档案</span></button>
          <button className="paper-tile-body" aria-label={'打开论文：'+(p.title||'无标题')} onClick={()=>onOpen(p)}>
            <span className="paper-tile-year">{p.year||'年份待补'}<span>{p.venue||'期刊待补'}</span></span>
            <strong>{p.title||'未命名论文'}</strong><span className="paper-tile-authors">{p.authors.slice(0,3).join('，')||'作者待补'}</span>
            <span className="paper-tile-abstract">{p.abstract||'暂无摘要，打开文献档案补充资料。'}</span>
          </button>
          <div className="paper-tile-footer"><span>{readingLabels[p.reading?.status||'unread']||'未读'}{p.has_summary?' · 已总结':''}</span><button className="btn-subtle" onClick={event=>preview(p,event.currentTarget)} aria-label={'预览档案：'+(p.title||'无标题')}>预览档案</button><button className="btn-ghost" onClick={()=>onRemove(p)} aria-label={'删除论文：'+(p.title||'无标题')}><Trash2 size={14}/> 删除</button></div>
        </article>)}
      </div>
      {inspector}
    </div>
    {createPortal(<dialog ref={previewDialog} className="collection-preview-dialog" aria-labelledby="collection-preview-title" onClose={afterPreviewClosed} onClick={event=>{if(event.target===event.currentTarget)closePreview();}}><div className="collection-dialog-content"><header className="collection-dialog-heading"><h2 id="collection-preview-title">文献档案预览</h2><button data-preview-close className="btn-ghost" aria-label="关闭档案预览" onClick={closePreview}><X size={18}/></button></header><div className="paper-collection collection-preview-drawer">{inspector}<button className="btn-ghost collection-return" onClick={closePreview}>返回论文库</button></div></div></dialog>,document.body)}
  </section>;
}
