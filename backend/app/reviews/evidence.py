"""Sample a paper's argument and mechanism as well as its empirical results."""
import re
from app.research.materials import terms


ROLES={
    'background':r'abstract|introduction|background|overview|摘要|引言|研究背景',
    'method':r'method(?:s|ology)?|materials and methods|model(?:s)?|approach|architecture|framework|mechanism|algorithm|procedure|protocol|design|方法|模型|材料与方法|研究设计',
    'results':r'(?:additional |main )?(?:experiments?|results?|evaluation|performance)|实验|结果|评估',
    'discussion':r'discussion|conclusions?|limitations?|讨论|结论|局限',
    'references':r'references|bibliography|参考文献',
    'appendix':r'appendix|appendices|supplement(?:ary)?|附录|补充材料',
    'related':r'related work|prior work|literature review|相关工作|相关研究',
}
VOCAB={
    'background':{'problem','propose','present','objective','question','contribution'},
    'method':{'method','architecture','mechanism','encoder','encoding','algorithm','equation','representation','interaction','procedure','protocol','intervention','participants','training','model'},
    'results':{'result','results','evaluate','evaluation','experiment','experiments','compared','accuracy','effect','performance'},
    'discussion':{'limitation','limitations','conclusion','conclusions','discussion','future','however'},
}
LABELS={'background':'研究问题与概览','method':'方法与机制','results':'结果与评价条件','discussion':'结论与边界','counter':'例外与反向结果','topic':'主题相关补充'}
COUNTER=re.compile(r'\b(?:with the exception|except for|except on|underperform\w*|worse than|lower performance|fails? to|does not improve|did not improve|no significant|not significant)\b|不优于|未能改善|未显著|效果下降|例外',re.I)
EXPERIMENT_HEADING=re.compile(r'^\s*(?:\d+(?:\.\d+)*[.)]?\s+)?experiments?(?:\s|:)',re.I)


def candidates(full, width=1600):
    """Keep source offsets exact; headings guide selection, not inferred page numbers."""
    headings=[];offset=0;previous=''
    for line in full.splitlines(keepends=True):
        raw=line.strip()
        numbered=bool(re.match(r'^\d+(?:\.\d+)*[.)]?\s+[A-Z\u4e00-\u9fff]',raw) or re.fullmatch(r'\d+(?:\.\d+)*',previous))
        text=re.sub(r'^(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)]?\s+)?','',raw)
        looks_title=(text and (text[0].isupper() or '\u4e00'<=text[0]<='\u9fff') and
            len(text)<100 and len(text.split())<=(12 if numbered else 6) and
            not re.search(r'[.!?。]$',text) and not re.search(r'\b(can|are|is|show|shows|indicate|indicates|we|our|their)\b',text,re.I))
        if looks_title:
            found=False
            for role,pattern in ROLES.items():
                if re.match(r'^(?:'+pattern+r')(?:\s|[:：\-]|$)',text,re.I):
                    headings.append((offset,role));found=True
                    break
            if numbered and not found:
                number=re.match(r'^(\d+(?:\.\d+)*)',raw)
                number=number[1] if number else previous
                role=('results' if re.search(r'ablation|trade.?o[fﬀ]|performance|sensitivity',text,re.I) else
                    'method' if re.search(r'\b(model|encoder|decoder|retriever|training|architecture|algorithm|protocol|procedure|design)\b',text,re.I) else
                    'inherit' if '.' in number else 'body')
                headings.append((offset,role))
        previous=raw
        offset+=len(line)
    boundaries=sorted({0,len(full),*(a for a,_ in headings)})
    result=[];role='background';hi=0;region='main'
    for start,end in zip(boundaries,boundaries[1:]):
        while hi<len(headings) and headings[hi][0]<=start:
            if headings[hi][1]!='inherit':role=headings[hi][1]
            # A methods subheading in the supplement must not masquerade as
            # the main methods; reference entries can resemble headings too.
            if role=='references':region='references'
            if role=='appendix':region='appendix'
            hi+=1
        pos=start
        while pos<end:
            stop=min(end,pos+width)
            if stop<end:
                newline=full.rfind('\n',pos+width//2,stop)
                if newline>pos:stop=newline+1
            quote=full[pos:stop]
            if quote.strip():result.append({'start':pos,'end':stop,'quote':quote,'role':role,'region':region,'terms':terms(quote),'heading':pos==start})
            pos=stop
    return result


def select_spans(full, question, title='', has_abstract=False):
    spans=candidates(full)
    if not spans:return []
    merged=[]
    for span in spans:
        # Join a short section opening to its body, never a preceding chunk's
        # short tail: that would swallow the next experiment's heading.
        if (merged and merged[-1]['heading'] and len(merged[-1]['quote'].strip())<180 and merged[-1]['end']==span['start']
                and merged[-1]['role']==span['role'] and merged[-1]['region']==span['region']):
            previous=merged[-1]
            previous.update(end=span['end'],quote=full[previous['start']:span['end']],terms=previous['terms']|span['terms'])
        else:merged.append(span.copy())
    spans=merged
    substantive=[s for s in spans if len(s['quote'].strip())>=180]
    if substantive:spans=substantive
    # References are not evidence about the paper's own findings. Supplementary
    # methods can still enter through an explicit methods heading or topic search.
    abstract=next((s['start'] for s in spans if re.match(r'(?i)\s*(abstract|摘要)\b',s['quote'])),0)
    body=[s for s in spans if s['region']=='main' and s['start']>=abstract]
    if not body:body=[s for s in spans if s['region']!='references']
    if not body:return []
    selected=[];used=set()
    query=terms(question)|terms(title)
    def take(role,count):
        vocabulary=VOCAB.get(role,set())
        supplements=bool(re.search(r'appendix|supplement|附录|补充',question,re.I))
        pool=body if role!='topic' or not supplements else [s for s in spans if s['region']!='references' and s['start']>=abstract]
        if role=='counter':
            windows=[]
            for s in body:
                match=COUNTER.search(s['quote'])
                if not match or s['role']=='related':continue
                start=max(body[0]['start'],s['start']+match.start()-240)
                end=min(max(b['end'] for b in body),start+1600)
                quote=full[start:end]
                windows.append(dict(s,start=start,end=end,quote=quote,terms=terms(quote)))
            if windows:pool=windows
        def score(s):
            heading=24 if s['role']==role else -8 if s['role']=='related' else 0
            lexical=len(s['terms']&vocabulary)
            relevance=min(4,len(s['terms']&query)) if role!='topic' else len(s['terms']&query)
            # Flattened PDF tables lose row/column associations. Prefer prose
            # explaining the comparison, while keeping tables available as sources.
            numbers=len(re.findall(r'(?m)^\s*[\d.±%]+\s*$',s['quote']))
            if role=='counter':
                return len(COUNTER.findall(s['quote']))*12+(3 if s['role']=='results' else 0)+relevance-min(10,numbers)
            return heading+lexical+relevance-min(20,numbers)
        ranked=sorted(pool,key=lambda s:(-score(s),s['start']))
        if role=='method':
            # Establish the mechanism before choosing keyword-rich training or
            # ablation passages. Subsequent slots still use relevance ranking.
            opening_methods=[s for s in pool if s['role']=='method'][:count]
            ranked=opening_methods+[s for s in ranked if s not in opening_methods]
        elif role=='results':
            # Separate experiment sections can test different endpoints. Do not
            # let many ablations of the first endpoint crowd out the second.
            experiments=[s for s in pool if s['role']=='results' and
                EXPERIMENT_HEADING.match(s['quote'])][:count]
            opening_results=experiments or [s for s in pool if s['role']=='results'][:1]
            ranked=opening_results+[s for s in ranked if s not in opening_results]
        for span in ranked:
            if not count:break
            if span['start'] in used:continue
            purpose=LABELS['counter'] if role=='counter' and COUNTER.search(span['quote']) else LABELS.get(span['role'],LABELS[role])
            used.add(span['start']);selected.append({k:v for k,v in span.items() if k not in {'terms','role','region','heading'}}|{'purpose':purpose})
            count-=1
    # Preserve the actual opening/abstract even when a Chinese query has little
    # lexical overlap with an English paper.
    if not has_abstract:
        opening=next((s for s in body if re.search(r'(?im)^\s*(?:abstract|摘要)\s*$',s['quote'])),body[0])
        used.add(opening['start']);selected.append({k:v for k,v in opening.items() if k not in {'terms','role','region','heading'}}|{'purpose':LABELS['background']})
    take('method',3);take('results',2);take('discussion',1);take('counter',1);take('topic',1)
    return selected


def revision_sources(papers, draft, per_paper=6):
    """Prioritize the papers actually cited, then cover mechanisms and outcomes.

    A manuscript can cite P999 without citing the first 998 library entries.
    Each cited paper gets a first source before another paper gets a second one.
    This keeps context fitting from turning revision into an abstract-only audit.
    """
    import json
    cited=list(dict.fromkeys(int(pid) for pid in re.findall(r'\[P(\d+)\]',draft)))
    by_id={p.paper_id:p for p in papers}
    ordered=[by_id[pid] for pid in cited if pid in by_id]
    if not cited:ordered=list(papers)[:12]
    queues=[]
    paragraphs=draft.split('\n\n')
    for paper in ordered:
        claims='\n'.join(p for p in paragraphs if f'[P{paper.paper_id}]' in p)
        query=terms(claims)
        sources=[];seen=set()
        for e in json.loads(paper.evidence_json):
            if e.get('scope')=='researcher_note':continue
            quote=e.get('quote','')
            key=re.sub(r'\s+',' ',quote).strip()
            if not key or key in seen:continue
            seen.add(key);sources.append(dict(e,paper_id=paper.paper_id,paper_title=getattr(paper,'title','')))
        ranked=sorted(sources,key=lambda e:len(query&terms(e['quote'])),reverse=True)
        chosen=[]
        for role in ('method','results','counter','results','discussion','method'):
            options=[e for e in ranked if e.get('purpose')==LABELS[role] and e not in chosen]
            if role=='results':
                options.sort(key=lambda e:not bool(EXPERIMENT_HEADING.match(e['quote'])))
            source=next(iter(options),None)
            if source:chosen.append(source)
        chosen.extend(e for e in ranked if e not in chosen)
        queues.append(chosen[:per_paper])
    return [queue[i] for i in range(per_paper) for queue in queues if len(queue)>i]


def source_text(evidence, tokens):
    from app.agent.context import estimate_tokens
    evidence=[e for e in evidence if e.get('scope')!='researcher_note']
    # A table's conditions often follow its numbers. Prefer complete units to
    # bare titles or rows with their caption removed. Saved evidence is untouched.
    def formatted(e):
        return (f'[P{e["paper_id"]}] '+
            (re.sub(r'\s+',' ',e['paper_title']).strip()+' · ' if e.get('paper_title') else '')+
            e.get('purpose','原文')+' · '+e.get('locator','')+'\n'+
            re.sub(r'\n\s*\n','\n',e['quote']))
    def diverse(items):
        queues={}
        for e in items:queues.setdefault(e['paper_id'],[]).append(e)
        return [queue[i] for i in range(max(map(len,queues.values()),default=0))
                for queue in queues.values() if i<len(queue)]
    focused=diverse([e for e in evidence if e.get('claim_source') and e.get('quote','').strip()])
    background=diverse([e for e in evidence if not e.get('claim_source') and e.get('quote','').strip()])
    selected=[];used=set();spent=0
    def take(items, limit):
        nonlocal spent
        for e in items:
            unit=formatted(e)
            if unit in used:continue
            cost=estimate_tokens(unit)+1
            if spent+cost>limit:continue
            selected.append(unit);used.add(unit);spent+=cost
    take(focused, tokens*2//3 if background else tokens)
    take(background,tokens)
    take(focused,tokens)
    if not selected:
        # Small windows may not fit even one full passage. Keep complete
        # sentences from its beginning and end, with an explicit omission mark,
        # instead of silently dropping all evidence or clipping a header.
        first={}
        for e in focused+background:first.setdefault(e['paper_id'],e)
        share=max(0,tokens//max(1,len(first)))
        for e in first.values():
            quote=re.sub(r'\n\s*\n','\n',e['quote'])
            sentences=re.split(r'(?<=[.!?。！？])\s+',quote.strip())
            if len(sentences)<2:continue
            start=sentences[0];end=sentences[-1]
            unit=formatted(dict(e,quote=start+'\n[… 原文中间部分省略 …]\n'+end))
            if estimate_tokens(unit)+1<=share:
                selected.append(unit)
    return '\n\n'.join(selected)


def chapter_sources(papers, recalled, title, limit=12):
    """Merge retrieval with paper snapshots, retaining different papers and roles.

    An empty or partially built index should not reduce every chapter to abstracts.
    Ranking affects selection only; evidence remains the exact original quote.
    """
    import json
    focus=('discussion' if re.search(r'讨论|局限|未来|展望|边界|discussion|limitation|future',title,re.I) else
           'results' if re.search(r'结果|实验|评估|评价|比较条件|results|evaluation|experiment',title,re.I) else
           'background' if re.search(r'背景|引言|问题|background|introduction',title,re.I) else 'method')
    query=terms(title)
    # Retrieval answers the chapter's question; section-role heuristics answer
    # what part of a paper it is. Do not rerank a semantic hit to zero merely
    # because an English passage shares no words with a Chinese chapter title.
    # Keep both channels: focused passages and broader mechanisms/conditions.
    by_id={p.paper_id:p for p in papers}
    focused=[];seen_focus=set()
    for chunk in recalled:
        if chunk.paper_id not in by_id:continue
        key=(chunk.paper_id,re.sub(r'\s+',' ',chunk.text).strip())
        if not key[1] or key in seen_focus:continue
        seen_focus.add(key)
        match=re.match(r'^\[第 (\d+) 页\]\n',getattr(chunk,'anchor_text',chunk.text))
        source=dict(paper_id=chunk.paper_id,quote=chunk.text,scope='retrieved_span',
            purpose='章节相关原文',page=int(match[1]) if match else None,
            locator=f'第 {match[1]} 页 · 检索片段 {chunk.ordinal}' if match else f'检索片段 {chunk.ordinal}')
        if getattr(chunk,'context_segments',None):
            source.update(scope='retrieved_context',segments=chunk.context_segments,
                          locator=source['locator']+'（含相邻原文）')
        focused.append(source)
    # Give each retrieved paper a place before taking another hit from it.
    first=[];extra=[];seen_papers=set()
    for e in focused:
        (extra if e['paper_id'] in seen_papers else first).append(e)
        seen_papers.add(e['paper_id'])
    focused=first+extra
    focus_slots=min(len(focused),max(1,limit//2)) if limit>0 else 0
    queues=[]
    for paper in papers:
        sources=[dict(e,paper_id=paper.paper_id) for e in json.loads(paper.evidence_json) if e.get('scope')!='researcher_note']
        sources.extend(e for e in focused if e['paper_id']==paper.paper_id)
        seen=set();unique=[]
        for e in sources:
            key=re.sub(r'\s+',' ',e['quote']).strip()
            if key and key not in seen:unique.append(e);seen.add(key)
        def score(e):
            return (12 if e.get('purpose')==LABELS[focus] else 0)+min(8,len(query&terms(e['quote'])))
        ranked=sorted(unique,key=score,reverse=True)
        # The next source contributes a different part of the paper where possible.
        if ranked:
            first=ranked[0]
            complements={'method':['results','counter','discussion','background'],
                         'results':['counter','method','discussion','background'],
                         'discussion':['counter','results','method','background'],
                         'background':['method','results','discussion','counter']}
            other=next((e for kind in complements[focus] for e in ranked[1:] if e.get('purpose')==LABELS[kind]),None)
            if other:ranked=[first,other]+[e for e in ranked[1:] if e is not other]
        queues.append(ranked)
    selected=[]
    while any(queues) and len(selected)<limit-focus_slots:
        for queue in queues:
            if queue and len(selected)<limit-focus_slots:selected.append(queue.pop(0))
    def key(e):
        return e['paper_id'],re.sub(r'\s+',' ',e['quote']).strip()
    used={key(e) for e in selected}
    for e in focused:
        if len(selected)>=limit:break
        if key(e) not in used:selected.append(e);used.add(key(e))
    # Empty/partial indexes and duplicate hits return their space to snapshots.
    while any(queues) and len(selected)<limit:
        for queue in queues:
            if queue and len(selected)<limit:
                e=queue.pop(0)
                if key(e) not in used:selected.append(e);used.add(key(e))
    return selected
