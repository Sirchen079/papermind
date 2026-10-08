interface Material {
  material_kind?: string; source_type?: string; retrieved_by?: string; content_region?: string;
}
interface PaperMaterial extends Material {paper_id: number; title: string;}

export const materialLabels: Record<string,string> = {
  original_text:'原文片段', abstract_metadata:'摘要与书目信息', discovery:'检索线索',
  generated_analysis:'AI 生成的论文分析', research_record:'笔记与研究记录',
  webpage:'网页摘录', unknown:'已保存材料',
};

export function materialKind(source:Material):string {
  if(source.material_kind && materialLabels[source.material_kind])return source.material_kind;
  if(source.source_type==='full_text')return 'original_text';
  if(source.source_type==='metadata')return ['search_library','find_related'].includes(source.retrieved_by??'')?'discovery':'abstract_metadata';
  if(source.source_type==='summary'&&source.retrieved_by==='get_paper')return 'abstract_metadata';
  if(['summary','generated_analysis'].includes(source.source_type??''))return 'generated_analysis';
  if(['research_note','note','excerpt','matrix'].includes(source.source_type??''))return 'research_record';
  if(source.source_type==='web')return source.content_region==='scholarly_metadata'?'abstract_metadata':source.content_region==='pdf_text'?'original_text':'webpage';
  return 'unknown';
}

export function materialLabel(source:Material) {
  const specific:Record<string,string>={note:'个人笔记',excerpt:'个人摘录',matrix:'文献比较记录'};
  return specific[source.source_type??'']??materialLabels[materialKind(source)];
}

export function researchScopeKind(scope?:string):string {
  return ({abstract:'abstract_metadata',excerpt:'research_record',researcher_note:'research_record',
    full_text:'original_text',full_text_span:'original_text',retrieved_span:'original_text',
    retrieved_context:'original_text'} as Record<string,string>)[scope??'']??'unknown';
}

export const paperGroups = [
  {key:'original_text',label:'论文原文片段'},
  {key:'abstract_metadata',label:'摘要与检索线索'},
  {key:'research_record',label:'分析与研究记录'},
  {key:'unknown',label:'其他材料'},
] as const;

function groupKey(source:Material) {
  const kind=materialKind(source);
  return kind==='discovery'?'abstract_metadata':kind==='generated_analysis'?'research_record':kind;
}

/** A paper with actual original passages appears once in the primary group.
 * All its other material remains available in the detail view. No claim audit
 * or "whole paper read" status is inferred from these tool records. */
export function groupPaperSources<T extends PaperMaterial>(sources:T[]) {
  const papers=new Map<number,T[]>();
  for(const source of sources)papers.set(source.paper_id,[...(papers.get(source.paper_id)??[]),source]);
  const entries=[...papers].map(([paper_id,rows])=>{
    const index=paperGroups.findIndex(g=>rows.some(s=>groupKey(s)===g.key));
    return {paper_id,title:rows[0].title,sources:rows,group:paperGroups[index<0?paperGroups.length-1:index].key};
  });
  return paperGroups.map(g=>({...g,papers:entries.filter(p=>p.group===g.key)})).filter(g=>g.papers.length);
}

export function groupWebSources<T extends Material>(sources:T[]) {
  const isDiscovery=(s:T)=>['discovery','abstract_metadata'].includes(materialKind(s));
  return [
    {key:'content',label:'网页与 PDF 摘录',sources:sources.filter(s=>!isDiscovery(s))},
    {key:'discovery',label:'检索与书目信息',sources:sources.filter(isDiscovery)},
  ].filter(g=>g.sources.length);
}
