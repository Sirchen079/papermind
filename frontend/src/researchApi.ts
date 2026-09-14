import { parseApiErrorMessage } from './pages/apiErrorModel';

export interface Evidence { ref:string; paper_id:number; quote:string; scope:string; locator:string; source_hash:string; page?:number; }
export interface Material { paper_id:number; title:string; coverage:string; source_hash:string; evidence:Evidence[]; }
export interface Finding { answer:string; evidence_refs:string[]; unknowns:string[]; route:string; next_step?:string; }
export interface ResearchArtifact { id:number; version:number; content:string; evidence_refs:string[]; evidence_snapshot:(Evidence&{title:string})[]; support_status:string; review_note:string; claim_kind:string; adopted:boolean; }
export interface ResearchTask { id:string; question:string; depth:string; status:string; error:string|null; stop_reason:string|null; materials:Material[]; paper_ids:number[]; steps:Record<string,Finding>; artifact:ResearchArtifact|null; history:ResearchArtifact[]; reuse:{id:number;kind:string;content:string;stale:boolean;artifact_id:number}[]; cache_summary?:{local_reused_steps:number;api_calls:number;cached_input_tokens:number;cache_reported:boolean}; }
export interface TaskSummary {id:string;question:string;status:string;updated_at:string;}
async function request<T>(base:string, path:string, body?:unknown):Promise<T> {
  const response=await fetch(base+'/research/tasks'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!response.ok) throw new Error(parseApiErrorMessage(response.status,await response.text()));
  return response.json();
}
export function createResearchApi(base:string) {
const scopedRequest=<T>(path:string,body?:unknown)=>request<T>(base,path,body);
return {
  list:(q='',offset=0,limit=50)=>scopedRequest<TaskSummary[]>('?'+new URLSearchParams({q,offset:String(offset),limit:String(limit)})),
  get:(id:string)=>scopedRequest<ResearchTask>('/'+encodeURIComponent(id)),
  create:(body:{request_id:string;question:string;paper_ids:number[];depth:string})=>scopedRequest<ResearchTask>('',body),
  action:(id:string,action:string,body:unknown={})=>scopedRequest<ResearchTask>('/'+encodeURIComponent(id)+'/'+action,body),
};
}
export const supportLabels:Record<string,string>={pending:'支持关系待核对',supported:'研究者已核对支持关系',partial:'仅部分支持',unsupported:'来源不支持',unclear:'仍无法判断'};
export const statusLabels:Record<string,string>={draft:'草稿',running:'正在整理',ready:'候选已生成',partial:'部分完成',needs_input:'待补材料',paused:'已停止'};
