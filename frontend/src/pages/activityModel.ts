export interface Activity {key:string;workspace_id:string;workspace_name:string;kind:string;title:string;status:string;stamp:string;time:string;active:boolean;url:string;}
export interface RecentWork {key:string;kind:string;title:string;status:string;time:string;active:boolean;route:string;}
export const activityLabels:Record<string,string>={draft:'待开始',running:'正在运行',queued:'等待运行',pending:'正在回答',done:'候选已保存',ready:'结果已生成',partial:'部分完成',needs_input:'待补材料或配置',paused:'已暂停',failed:'未完成，可接续',interrupted:'运行中断',conflict:'候选待合并',complete:'已完成',awaiting_user:'等待你的回答',saved:'已保存'};
export const workKindLabels:Record<string,string>={research:'论文研究',review:'专题综述',chat:'研究对话',wiki:'知识页'};

export function workDate(raw:string):string {
  const normalized=raw.replace(' ','T');
  const date=new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(normalized)?normalized:normalized+'Z');
  return Number.isNaN(date.getTime())?'':date.toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});
}
export interface ActivityMemory {initialized:boolean;seen:Record<string,string>;unread:string[];}
export const emptyActivity:ActivityMemory={initialized:false,seen:{},unread:[]};

export function observeActivity(before:ActivityMemory,items:Activity[]):ActivityMemory{
  const unread=new Set(before.unread);const seen:Record<string,string>={};
  for(const item of items){
    seen[item.key]=item.stamp;
    if(before.initialized&&!item.active&&before.seen[item.key]!==item.stamp)unread.add(item.key);
    if(item.active)unread.delete(item.key);
  }
  return {initialized:true,seen,unread:[...unread].filter(key=>key in seen)};
}
