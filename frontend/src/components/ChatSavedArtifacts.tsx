import {documentIdentityLabel} from '../pages/documentIdentityModel';
import { MarkdownContent } from './MarkdownContent';
import { savedArtifacts } from '../pages/chatArtifactsModel';
import type { ChatDocumentRevision } from '../api';

export function ChatSavedArtifacts({tools,onOpenPaper,onPaperCitation=onOpenPaper,onEdit,onVersions,manualDocument}:{tools:{name:string;args:Record<string,unknown>;result:string;ok:boolean}[];onOpenPaper:(id:number,page?:number)=>void;onPaperCitation?:(id:number)=>void;onEdit?:(filename:string,content:string)=>void;onVersions?:(filename:string)=>void;manualDocument?:ChatDocumentRevision|null}){
  const artifacts=savedArtifacts(tools);
  if(manualDocument)artifacts.push({key:'manual:'+manualDocument.filename,title:(documentIdentityLabel(manualDocument)+' · ')+manualDocument.filename,filename:manualDocument.filename,content:manualDocument.content,downloadUrl:manualDocument.download_url});
  if(!artifacts.length)return null;
  return <div className="space-y-3 mb-3" aria-label="本轮保存的研究成果">{artifacts.map(artifact=>
    <details key={artifact.key} className="card space-y-3" open={!artifact.diagnostic}>
      <summary className="cursor-pointer font-semibold">{artifact.title}</summary>
      <div className="max-h-[32rem] overflow-y-auto"><MarkdownContent content={artifact.content} onPaperCitation={onPaperCitation} paperId={artifact.paperId} onPdfPage={onOpenPaper}/></div>
      <div className="flex flex-wrap gap-2">{artifact.paperId!==undefined&&<button className="btn-ghost text-xs" onClick={()=>onOpenPaper(artifact.paperId!)}>打开对应论文</button>}
      {artifact.downloadUrl&&<a className="btn-ghost text-xs" href={artifact.downloadUrl} download>下载文档</a>}
      {artifact.filename&&onVersions&&<button type="button" className="btn-ghost text-xs" onClick={()=>onVersions(artifact.filename!)}>查看文档与修订</button>}</div>
      {artifact.filename&&onEdit&&<button type="button" className="btn-ghost text-xs" onClick={()=>onEdit(artifact.filename!,artifact.content)}>编辑并保存新版本</button>}
    </details>)}</div>;
}
