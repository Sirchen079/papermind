// Presentation only. The attachment sent to the agent remains unchanged.
export type ArtifactReference =
  | {kind:'document';message_id:number;filename:string}
  | {kind:'research';task_id:string;version:number}
  | {kind:'review';review_id:string};
type Attachment = {kind:string;name:string;text:string;saved_document?:{message_id:number;filename:string}|null;research_task?:{task_id:string;version:number}|null};

export function artifactReference(a:Attachment):ArtifactReference|null {
  if(a.kind!=='text')return null;
  if(a.saved_document)return {kind:'document',...a.saved_document};
  if(a.research_task)return {kind:'research',...a.research_task};
  // Legacy review handoffs store a link, not a structured version reference.
  const match=a.name==='专题研究链接'&&a.text.match(/^关联专题研究：#research\?mode=review&review=([^\s]+)\n/);
  if(match){try{const id=decodeURIComponent(match[1]);if(id)return {kind:'review',review_id:id};}catch{/* ordinary text remains readable */}}
  return null;
}

export function attachmentPassage(a:Attachment):string {
  if(!a.saved_document||a.kind!=='text')return '';
  const start='\n\n[待核查的研究稿选文]\n',end='\n[选文结束]\n';
  const from=a.text.indexOf(start),to=a.text.lastIndexOf(end);
  return from>=0&&to>from?a.text.slice(from+start.length,to):'';
}

export function exactResearchArtifact<T extends {version:number}>(task:{artifact:T|null;history:T[]},version:number):T {
  const artifact=task.artifact?.version===version?task.artifact:task.history.find(a=>a.version===version);
  if(!artifact)throw new Error(`找不到所关联的 v${version}，请在论文研究中检查历史版本。`);
  return artifact;
}
