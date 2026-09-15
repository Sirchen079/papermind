import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Sparkles } from '../../icons';

/** Decorative document-to-idea sketch. It does not represent stored research data. */
export function ResearchMotif({icon}:{icon?:ReactNode}) {
  const element=useRef<HTMLDivElement>(null);
  const [arrived,setArrived]=useState(false);
  useEffect(()=>{
    const observer=new IntersectionObserver(entries=>{
      if(entries.some(entry=>entry.isIntersecting)){setArrived(true);observer.disconnect();}
    },{threshold:.3});
    if(element.current)observer.observe(element.current);
    return()=>observer.disconnect();
  },[]);
  return <div ref={element} className={`research-motif ${arrived?'has-arrived':''}`} aria-hidden="true">
    <svg viewBox="0 0 200 108" fill="none" focusable="false">
      <path className="motif-grid" d="M8 22H192M8 54H192M8 86H192M36 10V98M100 10V98M164 10V98"/>
      <path className="motif-connection" d="M39 54H76M123 54C140 54 143 27 164 27M123 54C142 54 143 81 164 81"/>
      <path className="motif-flow" d="M39 54H76M123 54C140 54 143 27 164 27M123 54C142 54 143 81 164 81" pathLength="100"/>
      <g className="motif-document"><rect x="15" y="32" width="30" height="40" rx="3" transform="rotate(-9 30 52)"/><rect x="21" y="30" width="30" height="40" rx="3"/><path d="M28 40H43M28 46H43M28 52H37M28 61H41"/></g>
      <circle className="motif-endpoint" cx="168" cy="27" r="8"/><circle className="motif-endpoint motif-endpoint-green" cx="168" cy="81" r="8"/>
      <path className="motif-spark" d="M168 23V31M164 27H172M165 81H171"/>
      <path className="motif-calibration" d="M5 12V6H11M189 6H195V12M5 96V102H11M189 102H195V96"/>
    </svg>
    <span className="motif-core">{icon??<Sparkles size={24}/>}</span>
  </div>;
}
