"""Review writing uses the bundled skills themselves, with explicit task routing."""
from app.skills.builtin import load


def guides():
    nature=load('nature/nature-writing',axes={
        'task':'manuscript','paper_type':'review','section':['intro','related-work','discussion','conclusion'],
        'language':'zh-to-en','journal':'generic'},extra=[
        '../nature-shared/core/discussion-argument-language.md',
        '../nature-shared/core/main-text-discipline.md'])
    researcher=load('oh-my-paper/academic-researcher')
    handoff=load('oh-my-paper/research-paper-handoff')
    return nature,researcher,handoff


PLAN = '''调用已加载的 nature-writing Review 写作流程，先完成论证设计，不写正文。
用约 600–900 字的中文写作简报给出：1. 一句贯穿全文、有证据支持且范围明确的核心判断；
2. 研究范围与组织原则；3. 术语表；4. 主要论点—来源 [P编号]—支持/推断/未决映射；
5. 4–6 个章节各自回答的问题与段落任务，说明哪些内容只在一处展开；6. 真正影响结论的待核问题。
不要将任务、数据集或评价指标不同的方法包装成直接对立。不要按论文依次介绍。
核心判断解释材料共同揭示的机制或适用条件，比较关系以结果为据，不预设所有方法互补、对立或可叠加。
研究范围和研究空白分别表述：所选论文未回答的问题可以提出，但不能据此宣称整个领域从未研究。
指标差异放在必要的比较处一次交代；不要把整篇组织成反复声明无法排名的核查报告。
不复述逐篇分析，不续写材料中未完成的表格；各章任务各用一句话，术语只列确需统一的项目。
本任务是用户要求的中文综述，无需英文优先、投稿声明或逐步确认。'''

CHAPTER = '''遵循已加载 nature-writing 技能和全篇论证简报，只写当前章节的中文正文。
每段发展一个有证据的判断，解释具体机制或结果，再说明它回答了当前章节的哪个问题。
按问题综合论文；不要每介绍一个方法就重复一组“局限/展望”，也不要重复前文机制。
仅保留能改变判断的数字，注明指标与条件。不能因为文章发表顺序就声称某方法由另一方法引出。
写出跨论文综合带来的解释，例如共同瓶颈、互补关系、方法选择条件及其原因；避免逐篇摘要串联。
数据集和指标只能随对应的原文数值一起引用；对应关系不清就删去数字并定性说明，不猜测指标。
事实与推断用句意和措辞区分，正文禁止 [My summarization]、作者注、核查标签、写作步骤、提纲和重复小结。
使用流畅中文自然段，约 450–700 字；只有比较确有帮助时使用一个紧凑表格。引用保留 [P编号]。
只输出本章正文，不重复章节标题；首章迅速提出全篇问题，末章给出有解释力的综合判断与具体未决问题。'''

EDIT = '''按 nature-writing 的 paragraph-flow、claim-repetition 和 main-text discipline 完成整篇修订。
以下是同一份综述的章节草稿、写作简报和原文摘录。依据原文重新组织成稿，不局限于逐句润色草稿。
输出约 3000–4500 字的完整中文正文，使用 ## 章节标题并保留 [P编号]；可合并重复章节，原稿结构不是约束。
开篇只提出问题与主线，方法和实例留在对应章节；避免每章都重述全篇。
形成一条连续论证：提出问题→区分机制→比较证据→解释差异→给出有边界的判断。
合并重复方法介绍，删去模板式小结和旁白，把跨设置差异说清，不虚构“争论”、时间演进或优劣排名。
统一术语和语气。删除没有必要的数字，保留改变判断的条件。标题简洁，不使用冒号堆叠主题。
不要增加材料没有支持的新事实。保留重要反证与边界，但不要把内部证据不足的排查记录逐条塞入正文。
先依据原文修正方法的实际动作、已做实验和适用范围，再调整行文。简报与前稿的归纳不是独立证据；摘录未出现某项实验也不代表原论文没有做过。
可以提出新的跨论文解释，但要写出推理依据；将文献子集中的未验证关系扩展为领域空白时，应改回本次比较的具体问题。
重点保留可从材料得出的机制解释、互补关系和研究判断；删除反复出现的“不可比较”“不可判定”和自我辩护。
逐一检查保留数字的指标口径；若原文摘录没有支持其指标与数据集对应关系，改成有依据的定性描述。
保留结果中的例外条件，避免把部分数据集的改进扩展为所有数据集；未评估的应用不能写成已证明不适用。
直接交付完整综述正文，不输出审核清单、修订建议、英译或要求用户批准。不输出参考文献清单和材料范围，程序会追加。'''


def stage_guide(guide, stage, tokens):
    """Route original resource passages; keep full bundles untouched and audit excerpts."""
    import hashlib
    import re
    from app.skills.builtin import resource_path
    from app.agent.context import estimate_tokens
    sid=guide['id']
    if sid=='nature/nature-writing':
        paths=['static/fragments/paper_type/review.md','static/core/stance.md']
        if stage=='plan':
            paths+=['static/core/workflow.md','../nature-shared/core/terminology-ledger.md','../nature-shared/core/reader-workflow.md']
        elif stage in {'edit','update'}:
            paths+=['references/paragraph-flow.md','../nature-shared/core/main-text-discipline.md','../nature-shared/core/terminology-ledger.md']
            if stage=='update':paths+=['static/core/workflow.md']
        else:
            section=stage if stage in {'intro','discussion','conclusion'} else 'related-work'
            paths+=['static/fragments/section/'+section+'.md','static/core/workflow.md']
            if section=='discussion':paths+=['../nature-shared/core/discussion-argument-language.md']
    else:paths=['SKILL.md']
    sources=[]
    for path in paths:
        raw=resource_path(sid,path).read_text(encoding='utf-8-sig')
        text=raw
        if path=='SKILL.md':
            text=re.sub(r'\A---\n.*?\n---\n','',text,flags=re.S)
            if '## Upstream Instructions' in text:text=text.split('## Upstream Instructions',1)[1]
        if path=='static/core/workflow.md':
            selected=('1.','1b.','2.','3.') if stage=='plan' else ('9.',) if stage=='update' else ('4.','5.','6.','7.')
            text='\n\n'.join(b for b in re.split(r'(?m)(?=^## )',text) if any(b.startswith('## '+s) for s in selected))
        if path.endswith('main-text-discipline.md'):
            # Compression needs its evidence contract before deletion advice.
            # Keep the upstream wording; this route serves both chat revisions
            # and batch reviews, independent of the research topic.
            text='\n\n'.join(b for b in re.split(r'(?m)(?=^## )',text)
                if b.startswith(('## 1.','## 3.','## 7.','## 9.','## Non-negotiable exceptions')))
        sources.append((path,raw,text.strip()))
    # Short requests retain the task-specific Review rule before broad style advice.
    adapter=('按用户要求用中文完成当前综述阶段；依据提供证据，缺项局部标注并继续。保留 [P编号]。'
        '不增加确认步骤，不自动翻译为英文或强制投稿格式；只输出当前要求的内容。')
    headers=''.join('['+p+']\n' for p,_,_ in sources)
    room=max(0,tokens-estimate_tokens(adapter+headers)-32)
    costs=[estimate_tokens(t) for _,_,t in sources]
    caps=[min(c,room//max(1,len(costs))) for c in costs]
    extra=room-sum(caps)
    for i,cost in enumerate(costs):
        added=min(extra,cost-caps[i]);caps[i]+=added;extra-=added
    blocks=[];used=[]
    for (path,raw,text),cap in zip(sources,caps):
        if estimate_tokens(text)<=cap:excerpt=text
        else:
            units=re.split(r'\n\n+|\n(?=- |\d+\.)',text)
            if path.endswith('paper_type/review.md'):
                units.sort(key=lambda p: 'not a survey list' not in p)
            selected=[];remaining=cap
            for unit in units:
                cost=estimate_tokens(unit+'\n\n')
                if unit.strip() and cost<=remaining:
                    selected.append(unit);remaining-=cost
            excerpt='\n\n'.join(selected)
        if not excerpt:continue
        blocks.append('['+path+']\n'+excerpt)
        used.append({'path':path,'sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'mode':'full' if excerpt==raw.strip() else 'excerpt',
            'excerpt_sha256':hashlib.sha256(excerpt.encode()).hexdigest(),'excerpt_chars':len(excerpt)})
    text='\n\n'.join(blocks)+'\n\n'+adapter
    return {'id':sid,'version':guide['version'],'stage':stage,'text':text,'resources':used,
        'estimated_tokens':estimate_tokens(text),'fingerprint':hashlib.sha256(text.encode()).hexdigest()}
