import {useState} from 'react';
import {useApi} from '../workspaceContext';
import {usePaperDraft} from './usePaperDraft';
import {MarkdownContent} from './MarkdownContent';
import {documentEditProposals,type DocumentEditProposal} from '../pages/chatArtifactsModel';
import type {ChatDocumentRevision} from '../api';

function ProposalCard({proposal,conversationId,applied,disabled,onSaved,onPaperCitation}:{proposal:DocumentEditProposal;conversationId:number;applied?:ChatDocumentRevision;disabled:boolean;onSaved:()=>void;onPaperCitation:(id:number)=>void}){
  const api=useApi();
  const [draft,setDraft,clearDraft,storageError]=usePaperDraft(`${conversationId}:${proposal.id}`,{replacement:proposal.after},'document-edit-proposal');
  const [saving,setSaving]=useState(false),[error,setError]=useState(''),[preview,setPreview]=useState(false);
  const [saved,setSaved]=useState<ChatDocumentRevision|null>(null);
  const adopted=applied??saved;
  async function apply(){
    const submitted={...draft};setSaving(true);setError('');
    try{const result=await api.applyDocumentEdit(conversationId,proposal.id,submitted.replacement);setSaved(result);clearDraft(submitted);onSaved();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setSaving(false);}
  }
  return <details className="card space-y-3 mb-3" open aria-label="文档局部修改建议">
    <summary className="cursor-pointer font-semibold break-all">局部修改建议 · {proposal.filename}</summary>
    {proposal.reason&&<MarkdownContent content={proposal.reason} onPaperCitation={onPaperCitation}/>}
    {adopted?<p className="break-all text-sm">已采用并保存为新版本：{adopted.filename}</p>:<>
      <p className="text-xs text-muted">仅替换这一处，并保留该文档已有的其他修订。原稿保留，建议内容可继续编辑。</p>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm min-w-0">原段落<textarea aria-label="建议原段落" className="input mt-1 w-full font-mono text-sm" rows={7} readOnly value={proposal.before}/></label>
        <label className="text-sm min-w-0">建议段落<textarea aria-label="建议替换段落" className="input mt-1 w-full font-mono text-sm" rows={7} disabled={saving} value={draft.replacement} onChange={e=>setDraft({replacement:e.target.value})}/></label>
      </div>
      <div className="flex flex-wrap gap-2"><button type="button" className="btn-ghost text-xs" onClick={()=>setPreview(!preview)}>{preview?'收起排版预览':'预览建议排版'}</button><button type="button" className="btn-ghost text-xs" disabled={saving||draft.replacement===proposal.after} onClick={()=>setDraft({replacement:proposal.after})}>恢复 AI 建议</button></div>
      {preview&&<div className="rounded-lg border border-[var(--border)] p-3"><MarkdownContent content={draft.replacement} onPaperCitation={onPaperCitation}/></div>}
      {storageError&&<p role="alert" className="text-sm text-[var(--danger)]">修改暂时无法保存在浏览器中，请先保存新版本再离开。</p>}
      {error&&<p role="alert" className="text-sm text-[var(--danger)]">{error}</p>}
      <button type="button" className="btn-primary text-xs" disabled={disabled||saving||draft.replacement===proposal.before} onClick={()=>void apply()}>{saving?'正在保存…':'采用并保存新版本'}</button>
    </>}
  </details>;
}

export function DocumentEditProposals({tools,conversationId,revisions,disabled,onSaved,onPaperCitation}:{tools:{name:string;args:Record<string,unknown>;result:string;ok:boolean}[];conversationId:number;revisions:ChatDocumentRevision[];disabled:boolean;onSaved:()=>void;onPaperCitation:(id:number)=>void}){
  return <>{documentEditProposals(tools).map(proposal=><ProposalCard key={proposal.id} proposal={proposal} conversationId={conversationId} applied={revisions.find(r=>r.proposal_id===proposal.id)} disabled={disabled} onSaved={onSaved} onPaperCitation={onPaperCitation}/>)}</>;
}
