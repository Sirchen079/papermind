import {parseApiErrorMessage} from './pages/apiErrorModel';

export type ReviewEntry={paper_id:number;title:string;status:string;coverage:string;analysis:string;warning:string;reused:boolean};
export type ReviewSection={id:number;ordinal:number;title:string;content:string;warning:string};
export type LibraryReviewDetail={id:string;question:string;status:string;stage:string;error:string;content:string;version:number;counts:Record<string,number>;papers:ReviewEntry[];sections:ReviewSection[];revisions:{version:number;created_at:string}[];writing_notes?:string;writing_skills?:{id:string;version:string;stage?:string;resources:{path:string;mode?:string}[]}[]};
export type ReviewSource=ReviewEntry&{context_note?:string;evidence:{paper_id?:number;paper_title?:string;quote:string;locator:string;scope?:string;page?:number;segments?:{page?:number;quote:string}[]}[]};
export type ReviewChanges={version:number;base_version:number;current_version:number;snapshot:boolean;changes:{id:string;before:string;after:string;reason:string;paper_ids:number[];current_block_id:string|null}[];evidence:ReviewSource['evidence']};
export type MapTheme={id:string;name:string;definition:string;include?:string;exclude?:string};
export type PaperCardField={value:string;quote:string;status:string;found_in?:string|null;pages?:number[];missing_numbers?:string[]};
export type PaperCardData={metadata?:Record<string,unknown>;evidence_level?:string;problem?:PaperCardField;mechanism?:PaperCardField;data_setting?:PaperCardField;boundary?:PaperCardField;contributions?:PaperCardField[]};
export type ReviewMapSynthesis={trend?:string;error?:string;stats?:{count?:number;years?:Record<string,number>;setting?:Record<string,number>;evidence?:Record<string,number>};open_questions?:{question:string;why?:string;cannot_claim?:string;cards:number[];source_missing?:boolean}[];combination_opportunities?:{idea:string;expected?:string;risk?:string;cards:number[];source_missing?:boolean}[];representative?:{paper_id:number;why?:string}[]};
export type ReviewMapOverview={summary?:string;error?:string;reading_route?:{step:number;goal:string;papers:number[];why?:string;source_missing?:boolean}[];research_steps?:string[]};
export type ReviewMapPaper={paper_id:number;title:string;year?:number|string|null;venue?:string;doi?:string;themes:string[];evidence_level:string;card_status:string};
export type ReviewMapDetail={status:string;stage:string;error:string;version:number;themes:MapTheme[];assignments:Record<string,{themes:string[];reason:string}>;syntheses:Record<string,ReviewMapSynthesis>;overview:ReviewMapOverview;papers:ReviewMapPaper[];counts:{papers:number;cards_done:number;assigned:number;unassigned:number}};
export type PaperCardEntry={paper_id:number;title:string;status:string;card:PaperCardData|null;warning:string;updated_at:string|null};

export async function putReviewThemes<T>(base:string,id:string,themes:MapTheme[],expectedVersion:number):Promise<T>{
  const response=await fetch(`${base}/reviews/${id}/map/themes`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({themes,expected_version:expectedVersion})});
  if(!response.ok){const error=new Error(parseApiErrorMessage(response.status,await response.text()));(error as Error&{status?:number}).status=response.status;throw error;}
  return response.json();
}

export function createReviewRequest(base:string) {
  return async<T,>(path:string,body?:unknown):Promise<T>=>{
    const response=await fetch(base+'/reviews'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok)throw new Error(parseApiErrorMessage(response.status,await response.text()));
    return response.json();
  };
}
