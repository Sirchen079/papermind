import { useApi, useWorkspace, workspaceDraftKey } from '../workspaceContext';
import { useEffect, useRef, useState } from 'react';
import { type Paper } from '../api';
import { statusLabels, supportLabels, type ResearchTask, type TaskSummary } from '../researchApi';
import { Shell } from '../components/layout/Shell';
import type { NavLocation } from './navigationModel';
import { EmptyState } from '../components/ui/EmptyState';
import { readResearchDraft, sameResearchEdit, syncResearchDraft } from './draftStorageModel';
import { localStore } from '../components/usePaperDraft';
import { Sparkles } from '../icons';
import { WikiCapturePanel } from '../components/WikiCapturePanel';

export default function Research({params,onNavigate,onOpenPaper}:{params:Record<string,string>;onNavigate:(target:NavLocation|string)=>void;onOpenPaper:(id:number)=>void}) {
  const api = useApi();
  const {researchApi,workspace}=useWorkspace();
  const draftKey=(id:string)=>workspaceDraftKey(workspace.id,'pm-research-draft-'+id);
  const [tasks,setTasks]=useState<TaskSummary[]>([]);
  const [historyQuery,setHistoryQuery]=useState('');
  const [historyOffset,setHistoryOffset]=useState(0);
  const [historyMore,setHistoryMore]=useState(false);
  const [historyLoading,setHistoryLoading]=useState(false);
  const [historyError,setHistoryError]=useState('');
  const listGeneration=useRef(0);
  const [task,setTask]=useState<ResearchTask|null>(null);
  const [papers,setPapers]=useState<Paper[]>([]);
  const [selected,setSelected]=useState<number[]>([]);
  const [question,setQuestion]=useState('');
  const [search,setSearch]=useState('');
  const [depth,setDepth]=useState('quick');
  const [content,setContent]=useState('');
  const [editorVersion,setEditorVersion]=useState(0);
  const [oldDraft,setOldDraft]=useState<{content:string;refs:string[]}|null>(null);
  const [refs,setRefs]=useState<string[]>([]);
  const [review,setReview]=useState('pending');
  const [note,setNote]=useState('');
  const [source,setSource]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [storageError,setStorageError]=useState(false);
  const taskId=params.task;
  const generation=useRef(0);
  const requestId=useRef(crypto.randomUUID());
  const dirty=task ? content!==(task.artifact?.content??'')||JSON.stringify(refs)!==JSON.stringify(task.artifact?.evidence_refs??[]) : false;
  const dirtyRef=useRef(false);dirtyRef.current=dirty;
  const taskIdRef=useRef(taskId);taskIdRef.current=taskId;
  const editorRef=useRef({content,refs,review,note});editorRef.current={content,refs,review,note};
  const operation=useRef(0);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++generation.current;++operation.current;};},[]);

  function adoptResponse(next:ResearchTask, syncEditor=true) {
    if(!mounted.current || next.id!==taskIdRef.current)return;
    setTask(next);
    if(syncEditor) {
      setEditorVersion(next.artifact?.version??0);
      setContent(next.artifact?.content??'');setRefs(next.artifact?.evidence_refs??[]);
      setReview(next.artifact?.support_status??'pending');setNote(next.artifact?.review_note??'');
    }
  }
  function refreshList(){
    const g=++listGeneration.current;setHistoryLoading(true);setHistoryError('');
    researchApi.list(historyQuery,historyOffset,51).then(rows=>{
      if(g!==listGeneration.current)return;
      setTasks(rows.slice(0,50));setHistoryMore(rows.length>50);
    }).catch(e=>{if(g===listGeneration.current)setHistoryError(e.message);})
      .finally(()=>{if(g===listGeneration.current)setHistoryLoading(false);});
  }
  useEffect(()=>{
    ++listGeneration.current;setHistoryLoading(true);
    const timer=setTimeout(refreshList,200);
    return()=>{clearTimeout(timer);++listGeneration.current;};
  },[historyQuery,historyOffset]);
  useEffect(()=>{
    let alive=true;
    const timer=setTimeout(()=>api.listPapers(30,0,search).then(result=>{if(alive)setPapers(result.items);}).catch(e=>{if(alive)setError(e.message);}),200);
    return()=>{alive=false;clearTimeout(timer);};
  },[search]);
  useEffect(()=>{
    const g=++generation.current;++operation.current;setBusy(false);setStorageError(false);setTask(null);setContent('');setRefs([]);setError('');setNotice('');setSource(null);setOldDraft(null);
    if(!taskId){requestId.current=crypto.randomUUID();setSelected((params.papers??'').split(',').map(Number).filter(n=>Number.isInteger(n)&&n>0).slice(0,5));setQuestion(params.question??'');return;}
    researchApi.get(taskId).then(next=>{
      if(g!==generation.current)return;
      adoptResponse(next);
      try {
        const saved=readResearchDraft(localStore(),draftKey(taskId));
        if(saved && saved.baseVersion===(next.artifact?.version??0)){setContent(saved.content);setRefs(saved.refs);setNotice('已恢复本机尚未保存的编辑。');}
        else if(saved){setOldDraft(saved);setNotice('本机有旧版本编辑，未自动覆盖服务器版本；可在下方恢复对照。');}
      }catch{/* storage unavailable */}
    }).catch(e=>{if(g===generation.current)setError(e.message);});
  },[taskId,params.papers,params.question]);
  useEffect(()=>{
    if(!taskId||!task||task.id!==taskId)return;
    setStorageError(!syncResearchDraft(localStore(), draftKey(taskId), {baseVersion:editorVersion,content,refs}, dirty));
  },[taskId,content,refs,dirty,editorVersion]);
  useEffect(()=>{
    if(!taskId||task?.status!=='running')return;
    let alive=true,pending=false;
    const timer=setInterval(async()=>{
      if(pending)return;pending=true;
      try{const next=await researchApi.get(taskId);if(alive)adoptResponse(next,!dirtyRef.current);}
      catch(e){if(alive)setError((e as Error).message);}finally{pending=false;}
    },1500);
    return()=>{alive=false;clearInterval(timer);};
  },[taskId,task?.status]);
  async function perform(action:string,body:unknown={}) {
    if(!task)return;
    const id=task.id,g=generation.current,op=++operation.current;
    const submitted={...editorRef.current};setBusy(true);setError('');setNotice('');
    try{
      const next=await researchApi.action(id,action,body);
      if(g!==generation.current||taskIdRef.current!==id)return;
      const unchanged=sameResearchEdit(submitted,editorRef.current);
      const reviewUnchanged=submitted.review===editorRef.current.review&&submitted.note===editorRef.current.note;
      adoptResponse(next,false);
      if(action==='artifacts') {
        setEditorVersion(next.artifact?.version??0);
        if(unchanged){setContent(next.artifact?.content??'');setRefs(next.artifact?.evidence_refs??[]);}
        if(reviewUnchanged){setReview('pending');setNote('');}
        setNotice(unchanged?'当前版本已保存；新修订需要重新核对。':'提交的版本已保存，随后新增的编辑仍保留在草稿中。');
      } else if(!dirtyRef.current&&unchanged) {
        setEditorVersion(next.artifact?.version??0);setContent(next.artifact?.content??'');setRefs(next.artifact?.evidence_refs??[]);
        if(reviewUnchanged){setReview(next.artifact?.support_status??'pending');setNote(next.artifact?.review_note??'');}
      }
      refreshList();
    }catch(e){if(g===generation.current&&taskIdRef.current===id)setError((e as Error).message);}finally{if(op===operation.current)setBusy(false);}
  }
  async function create() {
    const g=generation.current,op=++operation.current;setBusy(true);setError('');
    try{
      const next=await researchApi.create({request_id:requestId.current,question,paper_ids:selected,depth});
      if(g!==generation.current||!mounted.current)return;
      requestId.current=crypto.randomUUID();
      onNavigate({page:'research',params:{task:next.id}});refreshList();
      // Task creation succeeds independently of provider configuration.
      try {await researchApi.action(next.id,'run');} catch(e){if(mounted.current&&taskIdRef.current===next.id)setError((e as Error).message);}
      const loaded=await researchApi.get(next.id);if(taskIdRef.current===next.id)adoptResponse(loaded,!dirtyRef.current);
    }catch(e){if(g===generation.current&&mounted.current)setError((e as Error).message);}finally{if(op===operation.current)setBusy(false);}
  }
  function download(content:string,name:string) {
    const url=URL.createObjectURL(new Blob([content],{type:'text/markdown;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);
  }
  const evidence=task?.materials.flatMap(m=>m.evidence.map(e=>({...e,title:m.title})))??[];
  const savedEvidence=task?.artifact?.evidence_snapshot??[];
  const reviewEvidence=dirty?evidence:[...savedEvidence,...evidence.filter(e=>!savedEvidence.some(s=>s.ref===e.ref))];
  const activeSource=reviewEvidence.find(e=>e.ref===source)??reviewEvidence[0];
  const sourceChanged=activeSource&&evidence.some(e=>e.ref===activeSource.ref&&e.source_hash!==activeSource.source_hash);
  const finding=task?.steps.synthesis;
  const version=task?.artifact?.version??0;
  return <Shell max={taskId?"wide":"narrow"}><div className="research-workspace space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="page-title">论文研究</h1><p className="page-subtitle mt-2">选几篇论文，围绕一个问题总结或比较，再对照原文核对。</p></div><button className="btn-ghost" onClick={()=>onNavigate({page:'research',params:{}})}>换一个问题</button></div>
    {error&&<div role="alert" className="card text-sm text-red-600 break-words">{error}</div>}
    {notice&&<p role="status" className="text-sm text-muted">{notice}</p>}
    {storageError&&<p role="alert" className="text-sm text-amber-700">浏览器暂时无法持久保存草稿，编辑已保留在当前应用中。关闭页面前请保存判断。</p>}
    {oldDraft&&task&&<div className="card space-y-2"><p className="text-sm whitespace-pre-wrap">本机旧编辑：{oldDraft.content}</p><button className="btn-ghost" onClick={()=>{setContent(oldDraft.content);setRefs(oldDraft.refs);setEditorVersion(task.artifact?.version??0);setOldDraft(null);}}>以当前服务器版本为基础恢复这份草稿</button></div>}
    {!taskId&&<section className="research-composer space-y-5">
      <fieldset disabled={busy} className="contents">
      <p className="eyebrow">从一个好问题开始</p>

      <label className="block">这次想弄清什么<textarea aria-label="研究问题" className="input question-input mt-2 w-full" rows={3} value={question} maxLength={2000} onChange={e=>{setQuestion(e.target.value);requestId.current=crypto.randomUUID();}} placeholder="例如：这些方法在相同评测条件下能直接比较吗？"/></label>
      <div className="flex flex-wrap gap-2">{['这些论文的方法有什么不同？','总结这篇论文的主要贡献和局限。'].map(example=><button key={example} className="btn-ghost text-xs" onClick={()=>{setQuestion(example);requestId.current=crypto.randomUUID();}}>{example}</button>)}</div>
      <label className="block text-sm">选择论文（1–5 篇，无需先建课题）<input aria-label="搜索任务论文" className="input mt-2 w-full" value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索已有论文"/></label>
      <p className="text-sm text-muted">已选 {selected.length} 篇{selected.length>0&&<button className="btn-ghost ml-2" onClick={()=>setSelected([])}>清空选择</button>}</p>
      <div className="grid gap-2 md:grid-cols-2">{papers.map(p=><label key={p.id} className={`paper-option ${selected.includes(p.id)?'is-selected':''}`}><input type="checkbox" checked={selected.includes(p.id)} disabled={!selected.includes(p.id)&&selected.length>=5} onChange={()=>{setSelected(old=>old.includes(p.id)?old.filter(n=>n!==p.id):[...old,p.id]);requestId.current=crypto.randomUUID();}}/><span className="break-words min-w-0">{p.title??`论文 ${p.id}`}</span></label>)}</div>
      {!papers.length&&<EmptyState title="当前没有匹配的论文" hint="把与你的问题相关的论文放进来，就可以开始整理与比较。" action={<button className="btn-ghost" onClick={()=>onNavigate({page:'library',params:{import:'pdf'}})}>去导入一篇论文</button>}/>}
      <div className="composer-footer"><label>怎么整理 <select className="input" aria-label="处理深度" value={depth} onChange={e=>{setDepth(e.target.value);requestId.current=crypto.randomUUID();}}><option value="quick">快速了解</option><option value="evidence">逐篇比较</option></select></label><button className="btn-primary" disabled={busy||!question.trim()||!selected.length} onClick={create}>{busy?'正在创建…':'开始研究'}</button></div>
      <div className="cost-preview" aria-label="研究用量说明"><div><span className="cost-indicator" aria-hidden="true"/><strong>先复用，再调用</strong><span className="chip">输入缓存已接入</span></div><p>当前方式通常需要 <b>{depth==='quick'?1:selected.length+1}</b> 次模型调用{depth==='quick'?'，适合先抓住重点':'，包括逐篇整理和一次综合'}。相同材料、问题与模型的已完成步骤可在 7 天内直接复用。</p><p>格式修复最多再试一次／步骤；每次输出上限 2,400 tokens。材料使用摘要、摘录和相关片段。服务端缓存是否命中、如何计费，以提供商返回为准；首次写入可能收费。</p></div>
      </fieldset>
    </section>}
    {taskId&&!task&&!error&&<p role="status">正在恢复任务…</p>}
    {task&&<>
      <p className="text-sm text-muted">{task.status==='running'?'正在整理。你可以先阅读原文，也可以离开页面，稍后回来。':!task.artifact?'下一步：等待生成结果，或先写下你自己的判断。':dirty?'下一步：保存你的修改，然后重新核对原文依据。':task.artifact.support_status==='pending'?'下一步：读一读原文依据，再记录“原文能支持这句话吗？”。':'下一步：可保存组会素材、下载结果，或者先停在这里。'}</p>
      <section className="card space-y-3"><h2 className="font-semibold break-words">{task.question}</h2><p className="text-sm text-muted">{statusLabels[task.status]??task.status} · {task.depth==='quick'?'快速了解':'逐篇比较'} · {task.materials.length} 篇材料 · 无需课题即可开始</p>
        {task.cache_summary&&<div className="cache-summary" aria-label="缓存与调用记录"><span>本地复用 <b>{task.cache_summary.local_reused_steps}</b> 步</span><span>已完成步骤调用 <b>{task.cache_summary.api_calls}</b> 次</span><span>服务端缓存读取 <b>{task.cache_summary.cache_reported?task.cache_summary.cached_input_tokens.toLocaleString()+' tokens':'未报告'}</b></span><small>本地复用不发起模型请求。这里只汇总已保存步骤，失败调用的用量请在设置中查看。</small></div>}
        <div className="flex flex-wrap gap-2">{task.status!=='running'&&<button className="btn-primary" disabled={busy} onClick={()=>perform('run')}>{Object.keys(task.steps).length?'检查材料并继续':'开始整理'}</button>}<button className="btn-ghost" disabled={busy||task.status==='paused'} onClick={()=>perform('stop')}>目前足够，留在这里</button><button className="btn-ghost" onClick={()=>onNavigate('settings')}>模型设置</button></div>
        {task.status==='running'&&<p role="status" className="text-sm text-muted">已保留 {Object.keys(task.steps).filter(k=>k!=='synthesis').length} 篇抽取结果；可离开页面，任务继续。停止后不再启动下一步骤，当前已发出的调用可能仍计费。</p>}
        {task.error&&<p role="alert" className="text-sm text-amber-700 dark:text-amber-300">{task.error}</p>}
        {task.stop_reason&&<p className="text-sm text-muted">停止原因：{({user_sufficient:'目前足够',answered:'当前问题已有候选回答',answered_with_limits:'已交付有限判断',missing_material:'关键材料缺失',interrupted:'上次运行中断',budget_exhausted:'本次预算已用尽',step_failed:'当前步骤失败'} as Record<string,string>)[task.stop_reason]??task.stop_reason}。停止不代表研究已经充分。</p>}
      </section>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <section className="card research-document min-w-0 space-y-4">
          <h2 className="font-semibold">我的研究结论</h2>
          <p className="text-sm text-muted">{dirty?'修订尚未保存 · 支持关系将回到待核对':supportLabels[task.artifact?.support_status??'pending']} · {task.artifact?.adopted?'已采用':'草稿'} · {version?`v${version}`:'尚无版本'} · 无实验执行记录</p>
          <textarea className="input w-full" aria-label="当前研究判断" rows={7} maxLength={12000} value={content} onChange={e=>{setContent(e.target.value);setReview('pending');setNote('');}} placeholder="等待 AI 候选，或先写下自己的判断。"/>
          <details><summary className="cursor-pointer text-sm">引用的原文片段（{refs.length}）</summary><div className="space-y-2 mt-2">{evidence.map(e=><label key={e.ref} className="flex gap-2 text-sm"><input type="checkbox" checked={refs.includes(e.ref)} onChange={()=>setRefs(old=>old.includes(e.ref)?old.filter(r=>r!==e.ref):[...old,e.ref])}/><span className="break-words">{e.ref} · {e.title} · {e.locator}</span></label>)}</div></details>
          <div className="flex flex-wrap gap-2"><button className="btn-primary" disabled={busy||!content.trim()} onClick={()=>perform('artifacts',{expected_version:editorVersion,content,evidence_refs:refs})}>保存判断</button><button className="btn-ghost" disabled={busy||dirty||!task.artifact||task.artifact.adopted} onClick={()=>perform('adopt',{expected_version:version})}>采用这个版本</button></div>
          <p className="text-xs text-muted">保存：保留编辑。采用：标记打算使用的版本。两者都不代表内容已经核实。</p><details><summary className="cursor-pointer">原文能支持这句话吗？</summary><div className="space-y-3 mt-3"><p className="text-sm text-muted">请核对原文是否支持这句话。采用或读过原文不会自动改变此状态。</p><select className="input max-w-full" aria-label="支持关系" value={review} disabled={dirty} onChange={e=>setReview(e.target.value)}>{Object.entries(supportLabels).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select><textarea className="input w-full" aria-label="核对依据与限制" rows={3} maxLength={3000} value={note} disabled={dirty} onChange={e=>setNote(e.target.value)} placeholder="记录具体来源、支持什么，以及不支持什么"/><button className="btn-ghost" disabled={busy||dirty||!task.artifact} onClick={()=>perform('review',{expected_version:version,status:review,note})}>保存本次核对</button>{dirty&&<p className="text-sm text-muted">先保存修订，再核对新版本。</p>}</div></details>
          {finding&&<details><summary className="cursor-pointer">查看 AI 原始回答与尚不确定的内容</summary><p className="text-sm whitespace-pre-wrap mt-2">{finding.answer}</p><ul className="text-sm list-disc pl-5">{finding.unknowns.map((u,i)=><li key={i}>{u}</li>)}</ul><p className="text-sm mt-2">可选行动：{finding.next_step}</p><p className="text-sm text-muted">这些是候选建议，不会自动替换你的判断。</p></details>}
        </section>
        <aside className="card evidence-panel min-w-0 space-y-3"><h2 className="font-semibold">查看原文依据</h2><div className="flex flex-wrap gap-2">{reviewEvidence.map(e=><button key={e.ref} className="btn-ghost text-xs" aria-pressed={activeSource?.ref===e.ref} onClick={()=>setSource(e.ref)}>{e.ref}</button>)}</div>{activeSource?<><p className="text-sm break-words">{activeSource.title}</p><p className="text-xs text-muted break-words">{activeSource.locator} · {activeSource.scope==='abstract'?'仅摘要':activeSource.scope==='excerpt'?'保存的摘录':'全文局部片段'}</p>{sourceChanged&&<p className="text-sm text-amber-700 dark:text-amber-300">当前来源已有变化，这里显示保存判断时的旧材料。</p>}<blockquote className="border-l-2 border-[var(--accent)] pl-3 whitespace-pre-wrap break-words text-sm">{activeSource.quote}</blockquote><button className="btn-ghost" onClick={()=>onOpenPaper(activeSource.paper_id)}>打开论文</button><p className="text-xs text-muted">这里只检查选定片段，没有宣称完整阅读全部论文。</p></>:<p className="text-sm text-muted">没有可读取内容；可保留手工草稿，再补充材料。</p>}</aside>
      </div>
      <section className="card space-y-3"><h2 className="font-semibold">导出结果与下一步</h2><div className="flex flex-wrap gap-2"><button className="btn-ghost" disabled={busy||dirty||!task.artifact||task.status==='running'} onClick={()=>perform('reuse',{expected_version:version,kind:'meeting'})}>保存组会素材</button><button className="btn-ghost" disabled={busy||dirty||!task.artifact||task.status==='running'||task.status==='paused'} onClick={()=>perform('reuse',{expected_version:version,kind:'plan'})}>保留验证计划</button></div>{task.reuse.map(r=><details key={r.id}><summary className="cursor-pointer">{r.kind==='meeting'?'组会素材':'验证计划'} · {r.stale?'判断已更新，请重新核对后保存':'使用当前版本'}</summary><pre className="whitespace-pre-wrap break-words text-sm my-3">{r.content}</pre><button className="btn-ghost" onClick={()=>download(r.content,`research-${r.kind}.md`)}>导出 Markdown</button></details>)}</section>
      {task.artifact&&<WikiCapturePanel key={task.artifact.id} artifact={task.artifact} question={task.question} disabled={busy||dirty||task.status==='running'}/>}
      <details><summary className="cursor-pointer text-sm">历史版本与逐篇结果</summary><div className="space-y-3 mt-3">{task.history.map(a=><div className="card" key={a.id}><p className="text-xs text-muted">v{a.version} · {supportLabels[a.support_status]} · {a.adopted?'已采用':'草稿'}</p><p className="text-sm whitespace-pre-wrap">{a.content}</p></div>)}{task.materials.map(m=><div key={m.paper_id} className="card"><p>{m.title}</p><p className="text-sm text-muted">{m.coverage==='no_text'?'没有可读文本':m.coverage==='selected_full_text_spans'?'已取相关全文片段':'只有摘要或摘录'}</p><p className="text-sm whitespace-pre-wrap">{task.steps[String(m.paper_id)]?.answer??'尚未逐篇整理'}</p></div>)}</div></details>
    </>}
    <section className="recent-tasks space-y-2">
      <h2 className="font-semibold">研究历史</h2>
      <input className="input w-full" aria-label="搜索全部研究历史" placeholder="按研究问题搜索全部历史" value={historyQuery} onChange={e=>{setHistoryQuery(e.target.value);setHistoryOffset(0);}}/>
      {historyError&&<p role="alert" className="text-sm text-red-600">{historyError} <button className="btn-ghost" onClick={refreshList}>重试历史加载</button></p>}
      {historyLoading?<p role="status" className="text-sm text-muted">正在加载研究历史…</p>:!historyError&&<>
        {!tasks.length&&<EmptyState icon={<Sparkles size={24}/>} title={historyQuery?'没有匹配的研究':'把发现留在这里'} hint={historyQuery?'试试其他关键词。':'你的研究会保存在这里，随时继续。'}/>}
        {tasks.map(t=><button key={t.id} className="shelf-paper w-full text-left" onClick={()=>onNavigate({page:'research',params:{task:t.id}})}><span className="research-tool-icon" aria-hidden="true"><Sparkles size={20}/></span><span className="shelf-paper-content"><span className="text-sm break-words">{t.question}</span><span className="shelf-paper-meta">{statusLabels[t.status]??t.status}</span></span><span className="shelf-paper-arrow" aria-hidden="true">↗</span></button>)}
      </>}
      <div className="flex items-center gap-3 text-sm"><button className="btn-ghost" disabled={historyLoading||historyOffset===0} onClick={()=>setHistoryOffset(n=>Math.max(0,n-50))}>较新任务</button><span>第 {Math.floor(historyOffset/50)+1} 页</span><button className="btn-ghost" disabled={historyLoading||!!historyError||!historyMore} onClick={()=>setHistoryOffset(n=>n+50)}>更早任务</button></div>
    </section>
  </div></Shell>;
}
