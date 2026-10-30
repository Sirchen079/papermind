import { useEffect, useId, useRef, useState } from 'react';
import { buildResearchDeskGraph } from '../pages/researchDeskModel';
import type { ReviewMapDetail } from '../reviewsApi';

function labelLines(text:string,limit:number) {
  const units=[...text].reduce((sum,char)=>sum+(char.charCodeAt(0)>255?2:1),0);
  const firstLimit=units>limit&&units<=limit*2?Math.ceil(units/2):limit;
  const lines:string[]=[];let line='',width=0;
  for(const char of text){const size=char.charCodeAt(0)>255?2:1;if(width+size>(lines.length===0?firstLimit:limit)){lines.push(line);line='';width=0;}line+=char;width+=size;}
  if(line)lines.push(line);
  return lines.slice(0,2).map((value,index)=>index===1&&lines.length>2?value.slice(0,-1)+'…':value);
}

export function ResearchDeskGraph({map,question,selectedPaperId,onSelectPaper}:{map:ReviewMapDetail;question:string;selectedPaperId?:number;onSelectPaper:(id:number)=>void}) {
  const graph=buildResearchDeskGraph(map),patternId=useId().replace(/:/g,'');
  const viewport=useRef<HTMLDivElement>(null);
  const [paused,setPaused]=useState(()=>{try{return localStorage.getItem('papermind-graph-paused')==='true';}catch{return false;}});
  const [reduced,setReduced]=useState(()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [visible,setVisible]=useState(true),[pageVisible,setPageVisible]=useState(!document.hidden);
  useEffect(()=>{
    const media=window.matchMedia('(prefers-reduced-motion: reduce)');
    const update=()=>setReduced(media.matches),visibility=()=>setPageVisible(!document.hidden);
    media.addEventListener('change',update);document.addEventListener('visibilitychange',visibility);
    const observer=new IntersectionObserver(entries=>setVisible(entries[0].isIntersecting));
    if(viewport.current)observer.observe(viewport.current);
    return()=>{media.removeEventListener('change',update);document.removeEventListener('visibilitychange',visibility);observer.disconnect();};
  },[]);
  function toggleMotion(){setPaused(value=>{try{localStorage.setItem('papermind-graph-paused',String(!value));}catch{/* optional visual preference */}return !value;});}
  const height=Math.max(300,graph.papers.length*80+24),middle=height/2;
  const paperY=(index:number)=>graph.papers.length===1?middle:50+index*((height-100)/(graph.papers.length-1));
  const themeY=(index:number)=>graph.themes.length===1?middle:54+index*((height-108)/(graph.themes.length-1));
  const selectedThemes=new Set(graph.edges.filter(edge=>edge.paperId===selectedPaperId).map(edge=>edge.themeId));
  return <div ref={viewport} className="rd-graph-viewport" data-motion={!paused&&!reduced&&visible&&pageVisible?'running':reduced?'reduced':'paused'}>
    <svg className="rd-graph" viewBox={`0 0 850 ${height}`} role="group" aria-label={`${question}：研究专题、主题与论文的归属关系`}>
      <defs><pattern id={patternId} width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".7" fill="currentColor"/></pattern><linearGradient id={`${patternId}-scan`}><stop stopColor="currentColor" stopOpacity="0"/><stop offset=".94" stopColor="currentColor" stopOpacity=".08"/><stop offset="1" stopColor="currentColor" stopOpacity=".25"/></linearGradient></defs>
      <rect width="850" height={height} fill={`url(#${patternId})`} className="rd-graph-dots"/>
      <rect x="-100" y="18" width="100" height={height-36} fill={`url(#${patternId}-scan)`} className="rd-graph-scan" aria-hidden="true"/>
      {graph.themes.map((theme,index)=>{const path=`M244 ${middle}C269 ${middle} 269 ${themeY(index)} 294 ${themeY(index)}`;return <g key={theme.id} className={selectedThemes.has(theme.id)?'rd-graph-route is-selected':'rd-graph-route'}><path d={path} className="rd-graph-link rd-graph-root-link"/><path d={path} pathLength="100" className="rd-graph-flow" style={{animationDelay:`${-index*.8}s`}} aria-hidden="true"/></g>;})}
      {graph.edges.map((edge,index)=>{const ti=graph.themes.findIndex(t=>t.id===edge.themeId),pi=graph.papers.findIndex(p=>p.paper_id===edge.paperId),path=`M514 ${themeY(ti)}C543 ${themeY(ti)} 543 ${paperY(pi)} 572 ${paperY(pi)}`;return <g key={`${edge.themeId}:${edge.paperId}`} className={`rd-graph-route ${edge.paperId===selectedPaperId?'is-selected':''}`}><path d={path} className="rd-graph-link"/><path d={path} pathLength="100" className="rd-graph-flow" style={{animationDelay:`${-1.4-index*.6}s`}} aria-hidden="true"/></g>;})}
      <g className="rd-graph-root"><title>{question}</title><path d={`M24 ${middle-56}H228L244 ${middle-40}V${middle+56}H24Z`}/><text x="42" y={middle-31} className="rd-graph-code">研究专题</text><text x="42" y={middle-6} className="rd-graph-question">{labelLines(question,22).map((line,index)=><tspan key={index} x="42" dy={index?21:0}>{line}</tspan>)}</text><text x="42" y={middle+39} className="rd-graph-root-meta">{graph.totalPaperCount} 篇论文 / {map.themes.length} 个主题</text></g>
      {graph.themes.map((theme,index)=><g key={theme.id} className={`rd-graph-theme ${selectedThemes.has(theme.id)?'is-selected':''}`}><title>{theme.name}</title><rect x="294" y={themeY(index)-39} width="220" height="78" rx="7"/><rect x="294" y={themeY(index)-24} width="3" height="48" className="rd-graph-theme-mark"/><text x="308" y={themeY(index)-20} className="rd-graph-code">主题 {String(index+1).padStart(2,'0')}</text><text x="308" y={themeY(index)+4} className="rd-graph-theme-name">{labelLines(theme.name,24).map((line,lineIndex)=><tspan key={lineIndex} x="308" dy={lineIndex?20:0}>{line}</tspan>)}</text></g>)}
      {graph.papers.map((paper,index)=><g key={paper.paper_id} className={`rd-graph-paper ${paper.paper_id===selectedPaperId?'is-selected':''}`} role="button" tabIndex={0} aria-label={`查看 P${paper.paper_id} ${paper.title} 的阅读档案`} aria-pressed={paper.paper_id===selectedPaperId} onClick={()=>onSelectPaper(paper.paper_id)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelectPaper(paper.paper_id);}}}><title>{paper.title}</title><rect x="572" y={paperY(index)-39} width="254" height="78" rx="7"/><text x="586" y={paperY(index)-20} className="rd-graph-code">P{paper.paper_id}</text><text x="586" y={paperY(index)+4} className="rd-graph-paper-name">{labelLines(paper.title||'未命名论文',30).map((line,lineIndex)=><tspan key={lineIndex} x="586" dy={lineIndex?20:0}>{line}</tspan>)}</text><circle cx="812" cy={paperY(index)-23} r="3"/></g>)}
    </svg>
    <div className="rd-graph-list">{graph.papers.map(paper=><button key={paper.paper_id} aria-pressed={paper.paper_id===selectedPaperId} onClick={()=>onSelectPaper(paper.paper_id)}><span className="rd-mobile-paper-id">P{paper.paper_id}</span><span><strong>{paper.title||'未命名论文'}</strong><small>{graph.themes.filter(theme=>graph.edges.some(edge=>edge.themeId===theme.id&&edge.paperId===paper.paper_id)).map(theme=>theme.name).join('、')}</small></span><span aria-hidden="true">↗</span></button>)}</div>
    <div className="rd-graph-legend"><span><i/>主题归属关系</span><span>显示 {graph.papers.length} / {graph.linkedPaperCount} 篇已关联论文 · 选择论文查看档案</span><button className="rd-motion-control" disabled={reduced} aria-label={reduced?'已遵循减少动态效果设置':paused?'播放图谱动效':'暂停图谱动效'} aria-pressed={paused||reduced} onClick={toggleMotion}><span aria-hidden="true">{paused||reduced?'▷':'Ⅱ'}</span>{reduced?'静态显示':paused?'播放动效':'暂停动效'}</button></div>
  </div>;
}
