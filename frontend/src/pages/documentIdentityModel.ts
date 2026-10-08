/** The message role stores the event; explicit document provenance takes precedence. */
export interface DocumentIdentity {
  author?: 'user'|'assistant';
  parent_filename?: string|null;
  revision_kind?: string;
  capture_message_id?: number|null;
  audit_author?: string;
  adoption_status?: string;
}

export function documentIdentityLabel(doc:DocumentIdentity):string {
  if(doc.adoption_status==='not_user_adopted')
    return `${doc.audit_author?`${doc.audit_author} 修订稿`:'修订草稿'} · 尚未采用`;
  if(doc.audit_author)return `${doc.audit_author} 修订稿`;
  if(doc.revision_kind==='saved_answer'||doc.capture_message_id)return 'AI 回答原样保存';
  if(doc.revision_kind==='accepted_suggestion')return '已采用的修订稿';
  if(doc.author==='assistant')return 'AI 保存的研究稿';
  if(doc.author==='user'||doc.parent_filename)return '人工修订稿';
  return '已保存研究稿';
}

export function chatTurnIdentity(role:string, revision?:DocumentIdentity|null):{label:string;avatar:string;own:boolean} {
  if(role==='assistant')return {label:'研究助手',avatar:'AI',own:false};
  if(role==='user'&&revision?.audit_author)
    return {label:documentIdentityLabel(revision),avatar:revision.audit_author.slice(0,1),own:false};
  if(role==='user'&&revision?.revision_kind==='saved_answer')
    return {label:'AI 回答存档',avatar:'AI',own:false};
  if(role==='user'&&revision?.adoption_status==='not_user_adopted')
    return {label:'修订草稿 · 尚未采用',avatar:'稿',own:false};
  return {label:'你',avatar:'你',own:true};
}

export function documentReferenceText(doc:DocumentIdentity&{message_id:number;filename:string}):string {
  return `关联已保存文档：${doc.filename}\nmessage_id=${doc.message_id}\nfilename=${doc.filename}\n文档记录：${documentIdentityLabel(doc)}。请使用 read_saved_document 读取此版本及需要的来源，再结合本轮问题继续研究。`;
}
