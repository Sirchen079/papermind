import { parseApiErrorMessage } from './pages/apiErrorModel';

export interface WikiEvidence {ref:string;title:string;quote:string;scope:string;locator:string;paper_id?:number;captured_from?:{name:string};underlying_evidence?:WikiEvidence[];dependency?:{kind:string;id:string|number;version?:number};}
export interface WikiRevision {id:number;number:number;request_id:string;content:string;evidence:WikiEvidence[];references:string[];support_status:string;review_note:string;origin:string;change_note:string;created_at:string;}
export interface WikiUpdate {id:string;status:string;error:string|null;revision_number:number|null;result:{content:string;references:string[];change_note:string}|null;}
export interface WikiSummary {id:string;title:string;version:number;adopted_revision:number|null;archived:boolean;preview?:string;latest_number?:number|null;}
export type WikiRevisionSummary = Pick<WikiRevision,'id'|'number'|'origin'|'request_id'|'support_status'|'created_at'>;
export interface WikiPage extends WikiSummary {latest:WikiRevision|null;adopted:WikiRevision|null;history:WikiRevisionSummary[];updates:WikiUpdate[];changes:{title:string;reason:string}[];copied_from?:{source_name:string;source_title:string;source_revision:number}|null;}
export function createWikiApi(base:string){
  async function request<T>(path:string,body?:unknown,method='POST'):Promise<T>{
    const response=await fetch(base+'/wiki'+path,body===undefined?undefined:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok)throw new Error(parseApiErrorMessage(response.status,await response.text()));
    return response.json();
  }
  return {
    list:(q='',archived=false)=>request<WikiSummary[]>('/pages?q='+encodeURIComponent(q)+'&archived='+archived),
    create:(request_id:string,title:string)=>request<WikiPage>('/pages',{request_id,title}),
    get:(id:string)=>request<WikiPage>('/pages/'+encodeURIComponent(id)),
    revision:(id:string,number:number)=>request<WikiRevision>('/pages/'+encodeURIComponent(id)+'/revisions/'+number),
    save:(id:string,body:Record<string,unknown>)=>request<WikiPage>('/pages/'+encodeURIComponent(id)+'/revisions',body),
    adopt:(id:string,expected_version:number,number:number)=>request<WikiPage>('/pages/'+encodeURIComponent(id)+'/adopt',{expected_version,number}),
    patch:(id:string,body:Record<string,unknown>)=>request<WikiPage>('/pages/'+encodeURIComponent(id),body,'PATCH'),
    update:(id:string,body:Record<string,unknown>)=>request<WikiUpdate>('/pages/'+encodeURIComponent(id)+'/updates',body),
    retry:(id:string)=>request<WikiUpdate>('/updates/'+encodeURIComponent(id)+'/retry',{}),
    retain:(id:string,body:{request_id:string;expected_version:number})=>request<WikiPage>('/updates/'+encodeURIComponent(id)+'/save-candidate',body),
    copy:(id:string,body:{request_id:string;target_workspace:string;number:number})=>request<{page_id:string}>('/pages/'+encodeURIComponent(id)+'/copy-to-workspace',body),
    exportUrl:(id:string,number:number)=>base+'/wiki/pages/'+encodeURIComponent(id)+'/export?number='+number,
  };
}
