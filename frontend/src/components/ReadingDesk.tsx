import { useEffect, useRef, useState } from 'react';
import type { Paper } from '../api';

export function JournalMasthead() {
  const today=new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'long'}).format(new Date());
  return <div className="journal-masthead"><div className="journal-dateline"><span>独立思考 · 日常积累</span><time dateTime={new Date().toLocaleDateString('sv-SE')}>{today}</time></div><div className="journal-wordmark">PaperMind<span>研究手记</span></div><div className="journal-imprint"><span>A PERSONAL RESEARCH JOURNAL</span><span>阅读 / 摘录 / 思考</span></div></div>;
}

/** Real library entries, with a quiet page turn. Rotation stops while reading. */
export function ReadingDesk({papers=[],onOpenPaper}:{papers?:Paper[];onOpenPaper?:(id:number)=>void}) {
  const [index,setIndex]=useState(0);
  const [paused,setPaused]=useState(()=>{try{return localStorage.getItem('papermind-desk-paused')==='true';}catch{return false;}});
  const [reduced,setReduced]=useState(()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [engaged,setEngaged]=useState(false);
  const [visible,setVisible]=useState(true);
  const [pageVisible,setPageVisible]=useState(!document.hidden);
  const element=useRef<HTMLDivElement>(null);
  const available=papers.slice(0,3),paper=available[index%Math.max(available.length,1)];
  const motionEnabled=!paused&&!reduced&&!engaged&&visible&&pageVisible;
  const running=motionEnabled&&available.length>1;

  useEffect(()=>{
    const media=window.matchMedia('(prefers-reduced-motion: reduce)');
    const update=()=>setReduced(media.matches), visibility=()=>setPageVisible(!document.hidden);
    media.addEventListener('change',update);document.addEventListener('visibilitychange',visibility);
    const observer=new IntersectionObserver(entries=>setVisible(entries[0].isIntersecting),{threshold:.25});
    if(element.current)observer.observe(element.current);
    return()=>{media.removeEventListener('change',update);document.removeEventListener('visibilitychange',visibility);observer.disconnect();};
  },[]);
  useEffect(()=>{
    if(!running)return;
    const timer=window.setTimeout(()=>setIndex(i=>(i+1)%available.length),7000);
    return()=>window.clearTimeout(timer);
  },[running,index,available.length]);
  function toggle(){setPaused(value=>{try{localStorage.setItem('papermind-desk-paused',String(!value));}catch{/* optional visual preference */}return !value;});}

  return <div ref={element} className="reading-desk" data-motion={motionEnabled?'running':reduced?'reduced':'paused'} onPointerEnter={()=>setEngaged(true)} onPointerLeave={event=>{if(!event.currentTarget.contains(document.activeElement))setEngaged(false);}} onFocusCapture={()=>setEngaged(true)} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node)&&!event.currentTarget.matches(':hover'))setEngaged(false);}}>
    <div className="desk-heading"><span className="desk-lab-label"><i/> RESEARCH DESK</span><span>{paper?'最近收进书架':'留给下一篇好论文'}</span></div>
    <div className="desk-sheets">
      <div className="desk-calibration" aria-hidden="true"><span>+</span><span>+</span><span>+</span><span>+</span><i className="desk-scan"/></div>
      <div className="desk-sheet-back" aria-hidden="true"/><div className="desk-sheet-middle" aria-hidden="true"/>
      <article key={paper?.id??'empty'} className="desk-paper">
        <div className="desk-paper-kicker"><span>{paper?'READING NOTE':'A BEGINNING'}</span><span>{paper?.year??'PAPER / MIND'}</span></div>
        <div className="desk-paper-rule"/>
        <h2>{paper?.title??<>留一页空白，<br/>给下一个发现。</>}</h2>
        <p className="desk-paper-byline">{paper?(paper.authors?.slice(0,2).join(' · ')||'你的论文收藏'):'从阅读开始，把理解慢慢写下来。'}</p>
        <div className="desk-paper-excerpt">{paper?.abstract?<p>{paper.abstract}</p>:<p>{paper?'打开论文，读一读原文，记下值得继续追问的地方。':'收下一篇值得读的论文，留下一段自己的理解。研究可以从这样的小事开始。'}</p>}</div>
        <div className="desk-paper-bottom"><span>{paper?String(index%available.length+1).padStart(2,'0'):'01'}</span>{paper&&onOpenPaper?<button onClick={()=>onOpenPaper(paper.id)}>打开这篇论文 <span aria-hidden="true">↗</span></button>:<span>阅读，然后思考。</span>}</div>
      </article>
    </div>
    {available.length>1&&<div className="desk-controls"><div className="desk-pagination">{available.map((item,i)=><button key={item.id} aria-label={`查看第 ${i+1} 篇收藏`} aria-current={index%available.length===i?'true':undefined} onClick={()=>setIndex(i)}>{String(i+1).padStart(2,'0')}</button>)}</div><button disabled={reduced} className="desk-motion-control" aria-label={reduced?'已遵循减少动态效果设置':paused?'继续书页轮播':'暂停书页轮播'} aria-pressed={paused||reduced} onClick={toggle}>{reduced?'静态阅读':paused?'继续轮播':'暂停轮播'} <span aria-hidden="true">{paused||reduced?'▷':'Ⅱ'}</span></button></div>}
    {available.length>1&&<div className="desk-progress" aria-hidden="true"><span key={`${index}-${running}`} className={running?'is-running':''}/></div>}
    <div className="desk-research-trace"><div className="desk-trace-caption"><span>研究路径 · 示意</span>{available.length<=1?<button onClick={toggle} disabled={reduced} aria-label={reduced?'已遵循减少动态效果设置':paused?'播放背景动效':'暂停背景动效'}>{reduced?'静态':paused?'播放动效':'暂停动效'}</button>:<span>QUESTION → EVIDENCE → INSIGHT</span>}</div><svg viewBox="0 0 400 82" fill="none" aria-hidden="true" focusable="false"><path d="M20 53H380M28 10V59M200 10V59M372 10V59" className="trace-grid"/><path d="M28 35C80 4 145 4 200 35S313 66 372 35" className="trace-line"/><path d="M28 35C80 4 145 4 200 35S313 66 372 35" className="trace-flow"/>{[28,200,372].map((x,i)=><g key={x}><circle cx={x} cy="35" r="8" className="trace-halo"/><circle cx={x} cy="35" r="3" className={i===1?'trace-node trace-node-evidence':'trace-node'}/><text x={x} y="77" textAnchor="middle">{['提出问题','核对证据','形成判断'][i]}</text></g>)}</svg></div>
  </div>;
}
