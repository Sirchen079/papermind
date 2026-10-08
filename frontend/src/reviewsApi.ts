import {parseApiErrorMessage} from './pages/apiErrorModel';

export type ReviewEntry={paper_id:number;title:string;status:string;coverage:string;analysis:string;warning:string;reused:boolean};
export type ReviewSection={id:number;ordinal:number;title:string;content:string;warning:string};
export type LibraryReviewDetail={id:string;question:string;status:string;stage:string;error:string;content:string;version:number;counts:Record<string,number>;papers:ReviewEntry[];sections:ReviewSection[];revisions:{version:number;created_at:string}[];writing_notes?:string;writing_skills?:{id:string;version:string;stage?:string;resources:{path:string;mode?:string}[]}[]};
export type ReviewSource=ReviewEntry&{context_note?:string;evidence:{paper_id?:number;paper_title?:string;quote:string;locator:string;scope?:string;page?:number;segments?:{page?:number;quote:string}[]}[]};
export type ReviewChanges={version:number;base_version:number;current_version:number;snapshot:boolean;changes:{id:string;before:string;after:string;reason:string;paper_ids:number[];current_block_id:string|null}[];evidence:ReviewSource['evidence']};

export function createReviewRequest(base:string) {
  return async<T,>(path:string,body?:unknown):Promise<T>=>{
    const response=await fetch(base+'/reviews'+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok)throw new Error(parseApiErrorMessage(response.status,await response.text()));
    return response.json();
  };
}
