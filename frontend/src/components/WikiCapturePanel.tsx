import { useEffect, useState } from 'react';
import { useWorkspace } from '../workspaceContext';
import { usePaperDraft } from './usePaperDraft';
import type { ResearchArtifact } from '../researchApi';
import type { WikiSummary } from '../wikiApi';

export function WikiCapturePanel({artifact,question,disabled}:{artifact:ResearchArtifact;question:string;disabled:boolean}){
  const {wikiApi,workspace}=useWorkspace();
  const [pages,setPages]=useState<WikiSummary[]>([]);
  const [matches,setMatches]=useState<WikiSummary[]>([]);
  const [draft,setDraft,clearDraft]=usePaperDraft(artifact.id,{target:'',title:question,key:'',mode:''},'wiki-capture');
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [result,setResult]=useState('');
  useEffect(()=>{let alive=true;Promise.all([wikiApi.list(),wikiApi.list(question)]).then(([rows,similar])=>{if(alive){setPages(rows);setMatches(similar.slice(0,3));}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[wikiApi,question]);
  function change(value:Partial<typeof draft>){setDraft({...draft,...value,key:crypto.randomUUID()});setResult('');setError('');}
  async function capture(synthesize:boolean){
    if(busy)return;const mode=synthesize?'model':'manual';const submitted={...draft,mode,key:draft.mode===mode&&draft.key?draft.key:crypto.randomUUID()};setDraft(submitted);setBusy(true);setError('');
    try{
      const page=submitted.target?await wikiApi.get(submitted.target):await wikiApi.create(submitted.key,submitted.title);
      if(synthesize){
        if(!page.updates.some(job=>job.id===submitted.key))await wikiApi.update(page.id,{request_id:submitted.key,expected_version:page.version,artifact_ids:[artifact.id]});
      }else if(!page.history.some(rev=>rev.request_id===submitted.key)){
        const content=page.latest?`${page.latest.content}\n\n## 新纳入的研究判断\n\n${artifact.content}`:artifact.content;
        await wikiApi.save(page.id,{request_id:submitted.key,expected_version:page.version,content,references:page.latest?.references||[],artifact_ids:[artifact.id],cite_added:true,change_note:`纳入研究成果 v${artifact.version}：${question}`});
      }
      clearDraft(submitted);setResult(page.id);setPages(await wikiApi.list());
    }catch(e:any){setError(e.message);}finally{setBusy(false);}
  }
  return <section className="card space-y-3">
    <h2 className="font-semibold">纳入专题知识</h2><p className="text-sm text-muted">将当前已保存的研究判断与证据快照带入专题，继续积累。纳入后保留为候选，由你选择采用版本。</p>
    {!!matches.length&&<div className="text-sm"><p className="text-muted">按问题关键词找到的相近专题：</p><div className="flex flex-wrap gap-2 mt-2">{matches.map(p=><button key={p.id} className="btn-ghost text-sm" disabled={busy||disabled} onClick={()=>change({target:p.id})}>{p.title}</button>)}</div></div>}
    <label className="block text-sm">目标专题<select className="input block w-full mt-1" value={draft.target} disabled={busy||disabled} onChange={e=>change({target:e.target.value})}><option value="">新建一个专题</option>{pages.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
    {!draft.target&&<label className="block text-sm">专题问题<input className="input block w-full mt-1" maxLength={300} value={draft.title} disabled={busy||disabled} onChange={e=>change({title:e.target.value})}/></label>}
    <div className="flex flex-wrap gap-2"><button className="btn-secondary" disabled={busy||disabled||(!draft.target&&!draft.title.trim())} onClick={()=>capture(false)}>纳入为候选</button><button className="btn-ghost" disabled={busy||disabled||(!draft.target&&!draft.title.trim())} onClick={()=>capture(true)}>让模型合入专题</button></div>
    {disabled&&<p className="text-xs text-muted">先保存当前研究判断，再纳入专题。</p>}{error&&<p role="alert" className="text-sm break-words">{error}</p>}{result&&<p role="status" className="text-sm">已提交到专题。<a className="underline ml-2" href={`?workspace=${encodeURIComponent(workspace.id)}#wiki?page=${encodeURIComponent(result)}`}>打开专题检查</a></p>}
  </section>;
}
