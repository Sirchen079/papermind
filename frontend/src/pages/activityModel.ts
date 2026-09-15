export interface Activity {key:string;workspace_id:string;workspace_name:string;kind:string;title:string;status:string;stamp:string;time:string;active:boolean;url:string;}
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
