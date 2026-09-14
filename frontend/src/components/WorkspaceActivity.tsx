import { useEffect, useRef, useState } from 'react';
import { workspaceRequest } from '../workspaceApi';
import { libraryScope, localStore } from './usePaperDraft';
import { readDraft, writeDraft } from '../pages/draftStorageModel';
import { emptyActivity, observeActivity, type Activity } from '../pages/activityModel';

const labels:Record<string,string>={running:'正在运行',queued:'等待运行',pending:'正在回答',done:'候选已保存',ready:'研究结果已就绪',partial:'研究结果待补充',paused:'已暂停',failed:'未完成，请检查',interrupted:'运行中断',conflict:'候选待合并',complete:'回答已完成',awaiting_user:'等待你的回答'};
export function WorkspaceActivity(){
  const key='pm-activity-'+libraryScope();
  const memory=useRef(readDraft(localStore(),key,emptyActivity));
  const [items,setItems]=useState<Activity[]>([]);const [error,setError]=useState('');
  const [unavailable,setUnavailable]=useState<{id:string;name:string}[]>([]);
  const [unread,setUnread]=useState(memory.current.unread);
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    let alive=true;let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{const result=await workspaceRequest('/activity');if(!alive)return;
        memory.current=observeActivity(memory.current,result.items);writeDraft(localStore(),key,memory.current);
        setUnread(memory.current.unread);setItems(result.items);setUnavailable(result.unavailable);setError('');
      }catch(e:any){if(alive)setError(e.message);}
      if(alive)timer=setTimeout(poll,5000);
    }
    poll();return()=>{alive=false;clearTimeout(timer);};
  },[key]);
  function read(){memory.current={...memory.current,unread:[]};writeDraft(localStore(),key,memory.current);setUnread([]);}
  const active=items.filter(item=>item.active).length;
  return <div className="fixed bottom-3 right-3 z-30">
    <button className="btn-secondary shadow-sm" onClick={()=>dialog.current?.showModal()} aria-label={`项目任务，${active} 项运行中，${unread.length} 项新动态`}>项目任务{active?` · ${active} 运行中`:''}{unread.length?` · ${unread.length} 新动态`:''}</button>
    {!!unread.length&&<span className="sr-only" role="status">有 {unread.length} 项项目任务状态更新。</span>}
    <dialog ref={dialog} aria-labelledby="workspace-activity-title" className="card w-[min(640px,calc(100vw-32px))] max-h-[85vh] overflow-y-auto backdrop:bg-black/30">
      <div className="flex gap-3 items-center justify-between"><h2 id="workspace-activity-title" className="text-lg font-semibold">各项目任务</h2><button className="btn-ghost" onClick={()=>dialog.current?.close()}>关闭</button></div>
      <p className="text-sm text-muted my-3">后台任务在所属项目中继续运行，点开对应记录可查看结果。</p>
      {error&&<p role="alert" className="text-sm mb-3">暂时无法刷新任务状态：{error}</p>}
      {!!unavailable.length&&<p className="text-sm mb-3">以下项目的任务暂不可读取：{unavailable.map(w=>w.name).join('、')}</p>}
      {!!unread.length&&<button className="btn-ghost text-sm mb-2" onClick={read}>将动态标为已读</button>}
      <div className="space-y-3">{items.map(item=><a key={item.key} href={item.url} className="block rounded-lg border border-[var(--border)] p-3" onClick={()=>{dialog.current?.close();memory.current={...memory.current,unread:memory.current.unread.filter(k=>k!==item.key)};writeDraft(localStore(),key,memory.current);setUnread(memory.current.unread);}}><span className="block text-xs text-muted">{item.workspace_name} · {labels[item.status]||item.status}{unread.includes(item.key)?' · 新动态':''}</span><span className="block text-sm mt-1 break-words">{item.title}</span></a>)}{items.length===0&&<p className="text-sm">暂无后台任务记录。</p>}</div>
    </dialog>
  </div>;
}
