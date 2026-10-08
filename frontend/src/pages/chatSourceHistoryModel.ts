interface PaperSource {
  paper_id: number; source_type?: string; excerpt?: string; snippet: string;
  pages?: number[]; locator?: string;
}

export function paperSourceHistory<T extends PaperSource>(
  messages: {id: number; sources?: T[]}[], messageId: number, paperId: number,
): {current: T[]; earlier: T[]} {
  const index=messages.findIndex(message=>message.id===messageId);
  if(index<0)return {current:[],earlier:[]};
  const seen=new Set<string>();
  function unique(sources: T[]) {
    return sources.filter(source=>{
      if(source.paper_id!==paperId)return false;
      const key=JSON.stringify([source.source_type,source.excerpt||source.snippet,source.pages??[],source.locator]);
      if(seen.has(key))return false;
      seen.add(key);return true;
    });
  }
  const current=unique(messages[index].sources??[]);
  const earlier=messages.slice(0,index).reverse().flatMap(message=>unique(message.sources??[]));
  return {current,earlier};
}
