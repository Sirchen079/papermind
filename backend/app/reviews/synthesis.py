"""Reuse the same hierarchical material synthesis for first drafts and deltas."""
from app.reviews.context import balanced
from app.reviews.service import digest,SYNTHESIZE


def summarize(usable,budget,question,writing_signature,researcher,ask,stage,save_section,cached_section,active):
    nodes=[]
    group_size=max(2,min(20,budget//700))
    for start_at in range(0,len(usable),group_size):
        if not active():return
        stage(f'归纳研究主题 {start_at//group_size+1}/{(len(usable)+group_size-1)//group_size}')
        group=usable[start_at:start_at+group_size]
        payload='\n\n'.join(f'[P{p.paper_id}] {p.title}\n{balanced(p.analysis,max(300,budget//len(group)-100))}' for p in group)
        ordinal=-1-start_at//group_size;fp=digest([payload,writing_signature,question])
        cached=cached_section(ordinal,fp)
        if cached:summary=cached.content
        else:
            summary,warning=ask(SYNTHESIZE,payload,2200,guide=researcher)
            summary=summary or payload[:budget]
            save_section(ordinal,'材料分组',fp,summary,warning=warning)
        nodes.append(summary)
    level=0
    while len(nodes)>6:
        next_nodes=[]
        for pos in range(0,len(nodes),6):
            if not active():return
            stage(f'合并研究主题：第 {level+1} 层 {pos//6+1}/{(len(nodes)+5)//6}')
            batch=nodes[pos:pos+6];payload='\n\n'.join(balanced(n,budget//len(batch)) for n in batch)
            ordinal=-10000-level*1000-pos;fp=digest([payload,writing_signature,question])
            cached=cached_section(ordinal,fp)
            if cached:text=cached.content
            else:
                text,warning=ask('合并研究路线、保留不同意见、比较条件与来源编号，形成下一层主题梳理。',payload,1800,guide=researcher)
                text=text or payload;save_section(ordinal,'主题合并',fp,text,warning=warning)
            next_nodes.append(text)
        nodes=next_nodes;level+=1
    overview='\n\n'.join(balanced(n,budget//len(nodes)) for n in nodes)
    return overview
