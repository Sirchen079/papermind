import { useEffect, useMemo, useRef, useState } from 'react';
import type { Paper, RecentlyReadPaper } from '../api';
import { createReviewRequest, type PaperCardEntry, type ReviewMapDetail } from '../reviewsApi';
import { useWorkspace } from '../workspaceContext';
import { buildResearchDeskGraph } from '../pages/researchDeskModel';
import { cardFieldRows } from '../pages/cardsPageModel';
import { pickInitialReview } from '../pages/mapPageModel';
import type { NavLocation } from '../pages/navigationModel';
import { statusLabels } from './ReviewListPicker';
import { ResearchDeskGraph } from './ResearchDeskGraph';
import { BookOpen, Plus } from '../icons';

type ReviewSummary={id:string;question:string;status:string};
type Props={recentlyRead:RecentlyReadPaper[]|null;papers:Paper[];paperTotal:number|null;readingError:string;onOpenPaper:(id:number,page?:number)=>void;onNavigate?:(target:NavLocation|string)=>void;onReviewChange:(id:string)=>void};

export default function ResearchOverview({recentlyRead,papers,paperTotal,readingError,onOpenPaper,onNavigate,onReviewChange}:Props) {
  const {base}=useWorkspace();
  const request=useMemo(()=>createReviewRequest(base),[base]);
  const [reviews,setReviews]=useState<ReviewSummary[]>([]),[loaded,setLoaded]=useState(false),[reviewId,setReviewId]=useState('');
  const [reviewsError,setReviewsError]=useState(''),[attempt,setAttempt]=useState(0);
  const [detail,setDetail]=useState<{id:string;map:ReviewMapDetail}|null>(null),[cards,setCards]=useState<PaperCardEntry[]>([]);
  const [mapError,setMapError]=useState(''),[cardsError,setCardsError]=useState(''),[mapLoading,setMapLoading]=useState(false),[selectedPaperId,setSelectedPaperId]=useState<number>();
  const dashboardRef=useRef<HTMLDivElement>(null);
  const readingTitleRef=useRef<HTMLHeadingElement>(null);
  const readingBodyRef=useRef<HTMLDivElement>(null);
  function selectPaper(id:number) {
    setSelectedPaperId(id);
    if(window.matchMedia('(max-width:900px)').matches)requestAnimationFrame(()=>{
      readingTitleRef.current?.focus({preventScroll:true});
      readingTitleRef.current?.scrollIntoView({block:'start'});
    });
  }
  function returnToPapers() {
    dashboardRef.current?.querySelector<HTMLButtonElement>('.rd-graph-list button[aria-pressed="true"]')?.focus();
  }
  useEffect(()=>{
    let alive=true;setLoaded(false);setReviews([]);setReviewsError('');setReviewId('');setDetail(null);setCards([]);
    request<ReviewSummary[]>('').then(rows=>{if(alive){setReviews(rows);setReviewId(previous=>pickInitialReview(previous,'',rows));}}).catch(error=>{if(alive)setReviewsError((error as Error).message);}).finally(()=>{if(alive)setLoaded(true);});
    return()=>{alive=false;};
  },[request,attempt]);
  useEffect(()=>{onReviewChange(reviewId);},[reviewId,onReviewChange]);
  useEffect(()=>{
    if(!reviewId)return;
    let alive=true;setMapLoading(true);setMapError('');setCardsError('');setDetail(null);setCards([]);setSelectedPaperId(undefined);
    void Promise.allSettled([
      request<ReviewMapDetail>(`/${reviewId}/map`).then(map=>{if(alive)setDetail({id:reviewId,map});}).catch(error=>{if(alive)setMapError((error as Error).message);}).finally(()=>{if(alive)setMapLoading(false);}),
      request<PaperCardEntry[]>(`/${reviewId}/cards`).then(rows=>{if(alive)setCards(rows);}).catch(error=>{if(alive)setCardsError((error as Error).message);}),
    ]);
    return()=>{alive=false;};
  },[reviewId,request]);
  const review=reviews.find(row=>row.id===reviewId);
  const map=detail?.id===reviewId?detail.map:null;
  const graph=buildResearchDeskGraph(map);
  const activeId=selectedPaperId??graph.papers[0]?.paper_id;
  const mapPaper=map?.papers.find(paper=>paper.paper_id===activeId);
  const recent=mapPaper?recentlyRead?.find(paper=>paper.id===mapPaper.paper_id):recentlyRead?.[0];
  const imported=mapPaper?papers.find(paper=>paper.id===mapPaper.paper_id):papers[0];
  const paper=mapPaper?{id:mapPaper.paper_id,title:mapPaper.title,year:mapPaper.year,venue:mapPaper.venue}:recent??imported;
  useEffect(()=>{
    if(!paper?.id||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const transition=readingBodyRef.current?.animate([{opacity:.45,transform:'translateX(10px)'},{opacity:1,transform:'translateX(0)'}],{duration:320,easing:'cubic-bezier(.2,.7,.2,1)'});
    return()=>transition?.cancel();
  },[reviewId,paper?.id]);
  const lastPage=recent?.last_page;
  const checks=cards.flatMap(card=>cardFieldRows(card.card)).filter(row=>row.problem).length;
  const cardCount=cards.filter(entry=>entry.card!==null).length;
  const card=cards.find(entry=>entry.paper_id===paper?.id);
  const navReview=(page:string)=>onNavigate?.({page,params:reviewId?{review:reviewId,...(page==='research'?{mode:'review'}:{})}:{mode:'review'}});
  return <div ref={dashboardRef} className="rd-dashboard">
    <section className="rd-topic-panel" aria-labelledby="rd-topic-title">
      <div className="rd-topic-heading"><div><p className="rd-eyebrow">正在推进的专题</p><h2 id="rd-topic-title">{review?.question||(loaded?'从一个研究问题开始':'正在找回研究专题…')}</h2></div>{reviews.length>0&&<label className="rd-topic-picker"><span className="sr-only">切换研究专题</span><select aria-label="切换研究专题" value={reviewId} onChange={event=>setReviewId(event.target.value)}>{reviews.map(row=><option key={row.id} value={row.id}>{row.question}</option>)}</select></label>}</div>
      {review&&<div className="rd-topic-meta"><span>{statusLabels[review.status]||review.status}</span>{map&&<><span><b>{map.papers.length}</b> 篇论文</span><span><b>{map.themes.length}</b> 个主题</span></>}{checks>0&&<span><b>{checks}</b> 项字段需核对</span>}</div>}
      <div className="rd-map-heading"><span>主题与论文</span><button className="btn-subtle" disabled={!reviewId} onClick={()=>navReview('map')}>完整地图 ↗</button></div>
      {(!loaded||mapLoading)?<div className="rd-map-empty" role="status"><BookOpen size={30}/><h3>正在读取文献地图…</h3><p>阅读档案与研究入口仍可使用。</p></div>:map&&graph.edges.length>0?<ResearchDeskGraph map={map} question={review?.question??''} selectedPaperId={activeId} onSelectPaper={selectPaper}/>:<div className="rd-map-empty"><h3>{reviewsError?'暂时无法读取专题':mapError?'文献地图暂时无法读取':review?'专题尚无主题关系':'尚未建立研究专题'}</h3><p>{reviewsError||mapError||(review?'专题尚无主题归属关系。打开文献地图，生成或补充主题后在此查看。':'建立专题并加入论文，即可按研究主题查看材料之间的归属关系。')}</p><div>{(reviewsError||mapError)&&<button className="btn-ghost" onClick={()=>setAttempt(value=>value+1)}>重试</button>}<button className="btn-primary" onClick={()=>navReview(review?'map':'research')}>{review?'打开文献地图':'新建研究专题'} <Plus size={15}/></button><button className="btn-ghost" onClick={()=>onNavigate?.({page:'library',params:{import:'pdf'}})}>导入论文</button></div></div>}
      {map?.overview.summary&&<footer className="rd-topic-footer"><span className="rd-record-tag">专题概览</span><p>{map.overview.summary}</p>{reviewId&&<button aria-label="打开专题综述" onClick={()=>navReview('research')}>↗</button>}</footer>}
    </section>
    <aside className="rd-side">
      <section className="rd-reading"><div className="rd-reading-top"><span>{mapPaper?'论文档案':recent?'继续阅读':'最近收藏'}</span>{lastPage&&lastPage>0?<span>上次读到第 {lastPage} 页</span>:<span>阅读与笔记</span>}</div>{paper?<div ref={readingBodyRef} className="rd-reading-body"><div className="rd-paper-id"><b>P{paper.id}</b><span>{mapPaper?'来自当前专题':'来自论文库'}</span></div><h3 ref={readingTitleRef} tabIndex={-1} aria-live="polite">{paper.title||'未命名论文'}</h3><p className="rd-paper-meta">{[paper.year,paper.venue].filter(Boolean).join(' · ')||'未记录出版信息'}</p>{card&&<p className="rd-card-status">精读卡片 · {statusLabels[card.status]||card.status}</p>}<div className="rd-reading-actions">{loaded&&!mapLoading&&graph.edges.length>0&&<button className="rd-return-papers" onClick={returnToPapers}>返回论文列表</button>}<button className="rd-open-paper" onClick={()=>onOpenPaper(paper.id,lastPage&&lastPage>0?lastPage:undefined)}>打开原文 ↗</button>{mapPaper&&reviewId&&<button onClick={()=>onNavigate?.({page:'cards',params:{review:reviewId,paper:String(paper.id)}})}>精读档案</button>}</div></div>:<div className="rd-reading-empty"><BookOpen size={30}/><h3>{recentlyRead===null?'正在读取论文…':readingError?'论文暂时无法读取':'把第一篇论文放到桌上'}</h3><p>{readingError||'导入论文后，在这里继续阅读与记录。'}</p><button onClick={()=>onNavigate?.({page:'library',params:{import:'pdf'}})}>导入论文</button></div>}</section>
      <section className="rd-topic-status"><div className="rd-small-heading"><h3>{review?'专题状态':'本项目论文'}</h3><span>{review?'专题概况':'论文库'}</span></div>{review?<><p className="rd-status-value"><i/>{statusLabels[review.status]||review.status}</p><dl><div><dt>文献地图</dt><dd>{map?statusLabels[map.status]||map.status:mapError?'暂时未读取':mapLoading?'正在读取':'尚未生成'}</dd></div><div><dt>精读卡片</dt><dd>{cardsError?'暂时未读取':cardCount?`${cardCount} 篇已有内容`:'暂无记录'}</dd></div></dl>{map?.needs_update&&<p className="rd-status-note">专题材料有变化，可在地图页更新。</p>}<button className="btn-subtle" onClick={()=>navReview('research')}>查看专题与处理记录 ↗</button></>:<><p className="rd-library-total">{paperTotal??'—'} <span>篇论文已归入本项目</span></p><button className="btn-subtle" onClick={()=>onNavigate?.('library')}>打开论文库 ↗</button></>}</section>
    </aside>
  </div>;
}
