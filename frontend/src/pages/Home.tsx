import { useWorkspace } from '../workspaceContext';
import { useEffect, useState } from 'react';
import { type Paper, type RecentlyReadPaper } from '../api';
import { Shell } from '../components/layout/Shell';
import ReadinessPanel from '../components/ReadinessPanel';
import ResearchProgressPanel from '../components/ResearchProgressPanel';
import GroupMeetingPanel from '../components/GroupMeetingPanel';
import LibraryDiagnosticsPanel from '../components/LibraryDiagnosticsPanel';
import type { NavLocation } from './navigationModel';
import { parseHash } from './navigationModel';
import { activityLabels, workDate, workKindLabels, type RecentWork } from './activityModel';
import ResearchLaunch from '../components/ResearchLaunch';
import ResearchOverview from '../components/ResearchOverview';
import { Sparkles, Settings, Plus } from '../icons';
import '../research-desk.css';

export default function Home({onOpenPaper,onNavigate,guided=false}:{onOpenPaper:(id:number,page?:number)=>void;onNavigate?:(target:NavLocation|string)=>void;guided?:boolean}) {
  const {api,workspace}=useWorkspace();
  const [recentlyRead,setRecentlyRead]=useState<RecentlyReadPaper[]|null>(null);
  const [recentImports,setRecentImports]=useState<Paper[]>([]),[paperTotal,setPaperTotal]=useState<number|null>(null);
  const [recent,setRecent]=useState<RecentWork[]>([]),[workLoading,setWorkLoading]=useState(true);
  const [readingError,setReadingError]=useState(''),[importsError,setImportsError]=useState(''),[workError,setWorkError]=useState('');
  const [attempt,setAttempt]=useState(0),[activeReviewId,setActiveReviewId]=useState('');
  const [showProgress,setShowProgress]=useState(false),[showChecks,setShowChecks]=useState(false);
  useEffect(()=>{
    let alive=true;setRecentlyRead(null);setRecentImports([]);setPaperTotal(null);setReadingError('');setImportsError('');
    void Promise.allSettled([
      api.recentlyRead(5).then(rows=>{if(alive)setRecentlyRead(rows);}).catch(error=>{if(alive){setRecentlyRead([]);setReadingError(error.message||'最近阅读暂时无法读取');}}),
      api.listPapers(8).then(result=>{if(alive){setRecentImports(result.items);setPaperTotal(result.total);}}).catch(error=>{if(alive)setImportsError(error.message||'最近收藏暂时无法读取');}),
    ]);
    return()=>{alive=false;};
  },[api,attempt]);
  useEffect(()=>{
    let alive=true;let timer:ReturnType<typeof setTimeout>;setRecent([]);setWorkLoading(true);setWorkError('');
    async function refresh(){
      try{const result=await api.recentWork();if(alive){setRecent(result.items);setWorkError('');}}
      catch(error){if(alive)setWorkError((error as Error).message||'研究记录暂时无法刷新');}
      finally{if(alive){setWorkLoading(false);timer=setTimeout(refresh,15000);}}
    }
    void refresh();return()=>{alive=false;clearTimeout(timer);};
  },[api,attempt]);
  return <Shell max="wide" className="rd-home">
    <header className="rd-page-heading"><div><p className="rd-section-code">01 / 研究空间</p><h1>科研工作台</h1><p>继续阅读、核对证据与整理专题。</p></div><div className="rd-page-actions"><time>{new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</time><button className="btn-primary" onClick={()=>onNavigate?.({page:'research',params:{mode:'review'}})}>新建研究 <Plus size={17}/></button></div></header>
    <ResearchOverview key={workspace.id} recentlyRead={recentlyRead} papers={recentImports} paperTotal={paperTotal} readingError={readingError} onOpenPaper={onOpenPaper} onNavigate={onNavigate} onReviewChange={setActiveReviewId}/>
    {(importsError||readingError)&&<div className="rd-local-warning" role="alert"><span>{[importsError&&`论文库：${importsError}`,readingError&&`最近阅读：${readingError}`].filter(Boolean).join('；')}</span><button className="btn-subtle" onClick={()=>setAttempt(value=>value+1)}>重试</button></div>}
    <section className="rd-next-section" aria-labelledby="rd-next-title"><div className="rd-section-heading"><h2 id="rd-next-title"><span>02 /</span>最近研究</h2><button className="btn-subtle" onClick={()=>onNavigate?.('research')}>全部研究 ↗</button></div>
      {workError&&<p className="rd-local-warning" role="alert">研究记录暂时无法刷新，下面的研究入口仍可使用。<button className="btn-subtle" onClick={()=>setAttempt(value=>value+1)}>重试</button></p>}
      {workLoading?<p className="rd-record-loading" role="status">正在找回研究记录…</p>:recent.length>0?<div className="rd-next-grid">{recent.slice(0,3).map((item,index)=><button key={item.key} className={`rd-next-card ${index===0?'is-lime':''}`} onClick={()=>onNavigate?.(parseHash(item.route))}><span className="rd-task-top"><span>{workKindLabels[item.kind]||item.kind}</span><span>{String(index+1).padStart(2,'0')} / {workDate(item.time)}</span></span><strong>{item.title}</strong><span className="rd-task-footer"><span>{item.active&&<i/>}{activityLabels[item.status]||item.status}</span><b aria-hidden="true">继续 ↗</b></span></button>)}</div>:<div className="rd-next-grid"><button className="rd-next-card is-lime" onClick={()=>onNavigate?.({page:activeReviewId?'cards':'research',params:activeReviewId?{review:activeReviewId}:{mode:'review'}})}><span className="rd-task-top"><span>{activeReviewId?'精读档案':'专题研究'}</span><span>01 /</span></span><strong>{activeReviewId?'对照原文，核对研究判断':'围绕问题，整理一组论文'}</strong><span className="rd-task-footer"><span>{activeReviewId?'打开当前专题卡片':'建立专题与研究材料'}</span><b aria-hidden="true">开始 ↗</b></span></button><button className="rd-next-card" onClick={()=>onNavigate?.({page:'library',params:{status:'queued'}})}><span className="rd-task-top"><span>阅读材料</span><span>02 /</span></span><strong>继续阅读与笔记</strong><span className="rd-task-footer"><span>{paperTotal===null?'查看本项目论文':`${paperTotal} 篇论文已归入本项目`}</span><b aria-hidden="true">打开 ↗</b></span></button><button className="rd-next-card is-blue" onClick={()=>onNavigate?.({page:'research',params:{mode:'review'}})}><span className="rd-task-top"><span>研究写作</span><span>03 /</span></span><strong>把文献证据组织成综述</strong><span className="rd-task-footer"><span>从现有材料开始</span><b aria-hidden="true">进入 ↗</b></span></button></div>}
    </section>
    {!guided&&<details className="rd-launch-details"><summary><span className="rd-section-code">03 / 研究入口</span><span><strong>提出问题，带上材料继续研究</strong><small>方法比较、精读追问、研究方向</small></span><span className="rd-launch-plus" aria-hidden="true">＋</span></summary><ResearchLaunch key={workspace.id} papers={recentImports} onNavigate={onNavigate}/></details>}
    <div className="rd-utilities"><details onToggle={event=>setShowProgress(event.currentTarget.open)}><summary><Sparkles size={20}/><span><strong>组会素材与研究进度</strong><small>整理阶段成果与下一步研究动作</small></span><span aria-hidden="true">＋</span></summary>{showProgress&&<div className="rd-utility-content"><ResearchProgressPanel onNavigate={onNavigate}/><GroupMeetingPanel/></div>}</details><details onToggle={event=>setShowChecks(event.currentTarget.open)}><summary><Settings size={20}/><span><strong>模型与资料状态</strong><small>查看连接、材料和处理情况</small></span><span aria-hidden="true">＋</span></summary>{showChecks&&<div className="rd-utility-content"><ReadinessPanel onNavigate={onNavigate}/><LibraryDiagnosticsPanel onOpenPaper={onOpenPaper} onNavigate={onNavigate}/></div>}</details></div>
  </Shell>;
}
