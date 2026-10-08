import { useEffect, useRef, useState } from 'react';
import { localToken } from '../api';
import { useWorkspace, workspaceDraftKey } from '../workspaceContext';
import { useConfirm } from './ui/ConfirmDialog';

type Block={id:string;text:string};
type Draft={owner:string;block:Block;version:number;replacement:string;instruction:string};
export function ReviewParagraphEditor({reviewId,version,disabled,onSaved,selection}:{reviewId:string;version:number;disabled:boolean;onSaved:()=>Promise<void>;selection?:{id:string;version:number;request:number}|null}) {
  const {base,workspace}=useWorkspace();const confirm=useConfirm();
  const [blocks,setBlocks]=useState<Block[]>([]),[draft,setDraft]=useState<Draft|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[warning,setWarning]=useState('');
  const generation=useRef(0);const key=workspaceDraftKey(workspace.id,'review-paragraph-'+reviewId);
  const panel=useRef<HTMLDetailsElement>(null),handled=useRef<number|null>(null);
  async function request(path:string,body?:unknown){
    const r=await fetch(`${base}/reviews/${reviewId}/paragraphs${path}`,{method:body===undefined?'GET':'POST',
      headers:{'Content-Type':'application/json','X-Local-Token':localToken()},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'段落操作未完成');return data;
  }
  useEffect(()=>{
    const g=++generation.current;setBlocks([]);setDraft(null);setBusy(false);setError('');setWarning('');
    try{const saved=localStorage.getItem(key);if(saved){const value=JSON.parse(saved);if(value.owner===key)setDraft(value);}}catch{setError('段落草稿未能读取。');}
    request('').then(r=>{if(g===generation.current)setBlocks(r.blocks);}).catch(e=>{if(g===generation.current)setError(e.message);});
    return()=>{++generation.current;};
  },[base,reviewId,version,key]);
  useEffect(()=>{if(draft?.owner===key)try{localStorage.setItem(key,JSON.stringify(draft));}catch{setError('本机草稿无法保存，请先复制修改后的正文。');}},[draft,key]);
  async function choose(id:string){
    const block=blocks.find(b=>b.id===id);if(!block)return;const g=generation.current;
    if(draft&&draft.block.id!==id&&(draft.replacement!==draft.block.text||draft.instruction)&&
      !await confirm({title:'切换段落',message:'当前段落有未应用的草稿，切换会替换这份草稿。',confirmText:'切换段落'}))return;
    if(g!==generation.current)return;setDraft({owner:key,block,version,replacement:block.text,instruction:''});setError('');setWarning('');
  }
  useEffect(()=>{
    if(!selection||handled.current===selection.request||selection.version!==version||!blocks.some(b=>b.id===selection.id))return;
    handled.current=selection.request;
    const g=generation.current;
    void choose(selection.id).then(()=>{if(g===generation.current&&panel.current){panel.current.open=true;panel.current.scrollIntoView({block:'start',behavior:'smooth'});panel.current.focus();}});
  },[selection,blocks,version]);
  async function generate(){
    if(!draft||draft.owner!==key)return;const g=generation.current;setBusy(true);setError('');setWarning('');
    try{const result=await request('/propose',{expected_version:draft.version,block_id:draft.block.id,instruction:draft.instruction});
      if(g!==generation.current)return;setDraft({...draft,replacement:result.replacement});setWarning(result.warning);
    }catch(e){if(g===generation.current)setError((e as Error).message);}finally{if(g===generation.current)setBusy(false);}
  }
  async function apply(){
    if(!draft||draft.owner!==key)return;const g=generation.current;setBusy(true);setError('');
    try{await request('/apply',{expected_version:draft.version,block_id:draft.block.id,replacement:draft.replacement});
      if(g!==generation.current)return;try{localStorage.removeItem(key);}catch{/* Saved in the application even if browser storage is unavailable. */}setDraft(null);await onSaved();
    }catch(e){if(g===generation.current)setError((e as Error).message);}finally{if(g===generation.current)setBusy(false);}
  }
  return <details ref={panel} tabIndex={-1} className="card space-y-3"><summary>按段修改</summary>
    <p className="text-sm text-muted">选择段落直接编辑，或让 AI 按要求修改。对照原文后应用，其他正文保持原样；每次应用保存为新版本。</p>
    <select className="input w-full" aria-label="选择综述段落" value={blocks.some(b=>b.id===draft?.block.id)?draft?.block.id:''} disabled={disabled||busy} onChange={e=>void choose(e.target.value)}>
      <option value="">选择要修改的段落</option>{blocks.map((b,i)=><option key={b.id} value={b.id}>{i+1}. {b.text.replace(/\s+/g,' ').slice(0,90)}</option>)}
    </select>
    {draft?.owner===key&&<><p className="text-sm text-muted">草稿基于 v{draft.version}，当前正文 v{version}。草稿保存在本机。</p>
      <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">原段落<textarea className="input w-full mt-1" aria-label="原段落" rows={10} readOnly value={draft.block.text}/></label>
      <label className="text-sm">修改后段落<textarea className="input w-full mt-1" aria-label="修改后段落" rows={10} disabled={busy} value={draft.replacement} onChange={e=>setDraft({...draft,replacement:e.target.value})}/></label></div>
      <label className="block text-sm">修改要求<input className="input w-full mt-1" aria-label="段落修改要求" placeholder="例如：突出与前一段的区别，保留指标和引用" disabled={busy} value={draft.instruction} onChange={e=>setDraft({...draft,instruction:e.target.value})}/></label>
      <div className="flex flex-wrap gap-2"><button className="btn-ghost" disabled={disabled||busy||!draft.instruction.trim()||draft.version!==version} onClick={generate}>{busy?'正在处理…':'让 AI 修改'}</button>
      <button className="btn-primary" disabled={disabled||busy||draft.version!==version||draft.replacement===draft.block.text} onClick={apply}>应用这一段</button>
      <button className="btn-ghost" disabled={busy} onClick={()=>{localStorage.removeItem(key);setDraft(null);setWarning('');}}>舍弃段落草稿</button></div>
    </>}
    {warning&&<p className="text-sm text-amber-700">{warning}</p>}{error&&<p role="alert" className="text-sm text-red-600">{error}</p>}
  </details>;
}
