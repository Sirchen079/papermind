export interface SavedArtifact {
  key: string; title: string; content: string; paperId?: number; downloadUrl?: string; filename?:string; diagnostic?:boolean;
}

export interface DocumentEditProposal {
  id:string;filename:string;sourceMessageId:number;before:string;after:string;reason:string;
}
export function documentEditProposals(tools:{name:string;args:Record<string,unknown>;result:string;ok:boolean}[]):DocumentEditProposal[]{
  const proposals=new Map<string,DocumentEditProposal>();
  for(const tool of tools){
    if(!tool.ok||tool.name!=='propose_document_edit')continue;
    let result:Record<string,unknown>;try{result=JSON.parse(tool.result);}catch{continue;}
    if(!result||result.ok!==true||result.kind!=='document_edit_proposal'||result.applied!==false||
       typeof result.proposal_id!=='string'||!/^[a-f0-9]{32}$/.test(result.proposal_id)||
       typeof result.filename!=='string'||result.filename!==tool.args.filename||
       typeof result.source_message_id!=='number'||result.source_message_id!==tool.args.message_id||
       typeof tool.args.before!=='string'||!tool.args.before||typeof tool.args.after!=='string')continue;
    proposals.set(result.proposal_id,{id:result.proposal_id,filename:result.filename,sourceMessageId:result.source_message_id,
      before:tool.args.before,after:tool.args.after,reason:typeof tool.args.reason==='string'?tool.args.reason:''});
  }
  return [...proposals.values()];
}
export function savedArtifacts(tools: {name:string;args:Record<string,unknown>;result:string;ok:boolean}[]): SavedArtifact[] {
  const artifacts=new Map<string,SavedArtifact>();
  for(const tool of tools){
    if(tool.ok&&['prepare_paper_card_sources','audit_paper_card'].includes(tool.name)){
      let run:Record<string,unknown>;try{run=JSON.parse(tool.result);}catch{continue;}
      if(!run||typeof run.run_id!=='string'||!/^[a-f0-9]{32}$/.test(run.run_id)||typeof run.summary_md!=='string')continue;
      const files=Array.isArray(run.artifacts)?run.artifacts:[];
      const report=files.find(file=>file&&file.name==='report.md');
      const url=typeof report?.download_url==='string'&&/^\/api\/(?:w\/[^/]+\/)?builtin-skills\/runs\/[a-f0-9]{32}\/files\/report\.md$/.test(report.download_url)?report.download_url:undefined;
      artifacts.set('skill:'+run.run_id,{key:'skill:'+run.run_id,
        title:run.action==='audit'?'精读卡检查结果':'论文来源整理记录',content:run.summary_md,
        paperId:typeof run.paper_id==='number'?run.paper_id:undefined,downloadUrl:url,diagnostic:true});
      continue;
    }
    if(!tool.ok||!['save_paper_note','save_research_idea','save_document'].includes(tool.name))continue;
    let result:Record<string,unknown>;try{result=JSON.parse(tool.result);}catch{continue;}
    if(!result||result.ok!==true||typeof tool.args.content!=='string'||!tool.args.content.trim())continue;
    const id=tool.name==='save_document'?result.filename:result.id;
    if(typeof id!=='number'&&typeof id!=='string')continue;
    const key=tool.name+':'+id;
    const title=tool.name==='save_paper_note'?'已保存的论文笔记':tool.name==='save_research_idea'?
      '已保存的研究想法'+(typeof result.title==='string'?' · '+result.title:''):
      '已保存的文档 · '+String(result.filename);
    const paperId=tool.name==='save_paper_note'&&typeof result.paper_id==='number'?result.paper_id:undefined;
    const url=typeof result.download_url==='string'&&/^\/api\/(?:w\/[^/]+\/)?chat\/documents\/[^/?#]+$/.test(result.download_url)?result.download_url:undefined;
    artifacts.set(key,{key,title,content:tool.args.content,paperId,downloadUrl:url,
      ...(tool.name==='save_document'&&typeof result.filename==='string'?{filename:result.filename}:{})});
  }
  return [...artifacts.values()];
}
