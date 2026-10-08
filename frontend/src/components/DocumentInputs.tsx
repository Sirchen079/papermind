import type {DocumentInput,SavedDocumentReference} from '../api';

export function DocumentInputs({documents,onOpen}:{documents?:DocumentInput[];onOpen:(ref:SavedDocumentReference)=>void}) {
  if(!documents?.length)return null;
  return <section aria-label="关联研究文档" className="rounded-lg border border-[var(--border)] p-3 space-y-2">
    <h4 className="text-sm font-medium">关联研究文档</h4>
    <p className="text-xs text-muted">查看当时关联或读取的稿件及其来源。读取记录不表示其中所有结论均被采用。</p>
    {documents.map(doc=><div key={`${doc.message_id}:${doc.filename}`} className="space-y-1">
      <button type="button" className="btn-ghost block w-full break-all text-left" disabled={!doc.available} onClick={()=>onOpen(doc)}>
        {doc.filename}
      </button>
      <p className="text-xs text-muted">
        {doc.relations.includes('revision_parent')?'修订前版本 · ':''}
        {doc.reads.some(r=>r.part==='document')?'生成前读取过正文':doc.reads.some(r=>r.part==='source')?'生成前读取过来源片段':doc.relations.includes('read_unconfirmed')?'有读取调用，旧记录未保留完整回执':doc.relations.includes('attached')?'用户关联材料，未记录正文读取':''}
        {!doc.available?' · 原文档已不可用':''}
      </p>
    </div>)}
  </section>;
}
