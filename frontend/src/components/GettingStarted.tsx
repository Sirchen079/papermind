import { useApi, useWorkspace } from '../workspaceContext';
import { useEffect, useState } from 'react';
import {} from '../api';
import { GUIDE_KEY, LESSONS, nextLesson, parseGuide, type GuideState, type Lesson } from '../pages/onboardingModel';
import type { NavLocation } from '../pages/navigationModel';

export function useGettingStarted(onNavigate:(target:NavLocation|string)=>void,onOpenPaper:(id:number)=>void) {
  const api = useApi();
  const {researchApi}=useWorkspace();
  const [state,setState]=useState<GuideState|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [hint,setHint]=useState('');
  useEffect(()=>{
    let alive=true;
    Promise.all([api.listSettings(),api.listPapers(1)]).then(([settings,papers])=>{
      if(alive)setState(parseGuide(settings[GUIDE_KEY],papers.total));
    }).catch(()=>{if(alive)setError('入门进度暂时无法读取。可先正常使用，稍后从使用指南重试。');});
    return()=>{alive=false;};
  },[]);
  async function save(next:GuideState) {
    if(busy)return false;
    setBusy(true);setError('');setHint('');
    try {await api.putSetting(GUIDE_KEY,JSON.stringify(next));setState(next);return true;}
    catch {setError('入门进度没有保存成功，请重试；不会影响论文和研究结果。');return false;}
    finally {setBusy(false);}
  }
  async function go(lesson:Lesson) {
    if(busy)return;
    setBusy(true);setError('');setHint('');
    try {
      if(lesson.usePaper) {
        const papers=await api.listPapers(1);
        if(papers.items[0])onOpenPaper(papers.items[0].id);
        else {setHint('还没有论文。先导入一篇，再试着保存笔记。');onNavigate({page:'library',params:{import:'pdf'}});}
      } else if(lesson.useResearch) {
        const tasks=await researchApi.list();
        if(tasks[0])onNavigate({page:'research',params:{task:tasks[0].id}});
        else {setHint('还没有研究结果。先选论文、填写问题并开始研究，也可以先阅读下面的操作说明。');onNavigate(lesson.target);}
      } else onNavigate(lesson.target);
    } catch {setError('暂时无法打开材料，请稍后重试。');}
    finally {setBusy(false);}
  }
  return {state,busy,error,hint,go,
    start:(step=0)=>save({version:1,status:'active',step}),
    pause:()=>save({...state??{version:1,step:0},status:'paused'}),
    next:()=>state&&save(nextLesson(state)),
    previous:()=>state&&save({...state,step:Math.max(0,state.step-1)}),
  };
}
export type GettingStartedController=ReturnType<typeof useGettingStarted>;

export function GettingStarted({guide,page,onHelp}:{guide:GettingStartedController;page:string;onHelp:()=>void}) {
  const [compact,setCompact]=useState(false);
  const {state,busy}=guide;
  if(!state || (state.status!=='active' && !(state.status==='welcome'&&page==='home')))return null;
  const lesson=LESSONS[state.step];
  return <section aria-label="新手引导" className={`getting-started ${state.status==='welcome'?'guide-welcome':'guide-active'}`}>
    {state.status==='welcome'?<><div className="guide-welcome-copy">
      <p className="hero-eyebrow"><span/> 欢迎使用 PaperMind</p>
      <h2 className="hero-title">把问题带进来，<br/><span>带着思路往前走。</span></h2>
      <p className="hero-description">用手头的论文，得到可回看原文的回答与比较。可以跟着引导试一次，也可以直接开始。</p>
      <div className="flex flex-wrap gap-2 mt-4"><button className="btn-primary" disabled={busy} onClick={()=>guide.start()}>带我开始</button><button className="btn-ghost" disabled={busy} onClick={guide.pause}>先自己看看</button></div>
    </div><div className="guide-welcome-outcomes"><p className="eyebrow">PaperMind 帮你做什么</p><h3>整理材料、比较方法、<br/>留住可继续用的结果。</h3><p>你决定问什么、相信什么、下一步验证什么。</p><span>导入与阅读无需配置 AI</span></div></>:<>
      <div className="guide-progress" aria-hidden="true">{LESSONS.map((_,i)=><span key={i} className={i<=state.step?'is-complete':''}/>)}</div><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">入门 {state.step+1}/{LESSONS.length} · {lesson.title}</h2><button className="btn-ghost text-xs" onClick={()=>setCompact(!compact)}>{compact?'展开操作提示':'收起提示'}</button></div>
      {!compact&&<><p className="text-sm text-muted mt-2">{lesson.purpose}</p><ol className="list-decimal pl-5 text-sm space-y-1 mt-3">{lesson.instructions.map(text=><li key={text}>{text}</li>)}</ol>
        <div className="flex flex-wrap gap-2 mt-4"><button className="btn-primary" disabled={busy} onClick={()=>guide.go(lesson)}>{lesson.action}</button><button className="btn-ghost" disabled={busy} onClick={guide.next}>{state.step===LESSONS.length-1?'我学会了，结束引导':'我学会了，下一步'}</button></div>
        <div className="flex flex-wrap gap-2 mt-2 text-xs"><button className="btn-ghost text-xs" disabled={busy||state.step===0} onClick={guide.previous}>上一步</button><button className="btn-ghost text-xs" disabled={busy} onClick={guide.pause}>稍后再学</button><button className="btn-ghost text-xs" onClick={onHelp}>查看全部用法</button></div>
        <p className="text-xs text-faint mt-2">进度只记录你学到哪里；点击下一步不会代你执行操作。</p>
      </>}
    </>}
    {guide.hint&&<p role="status" className="mt-2 text-sm text-muted">{guide.hint}</p>}
    {guide.error&&<p role="alert" className="mt-2 text-sm text-[var(--danger)]">{guide.error}</p>}
  </section>;
}
