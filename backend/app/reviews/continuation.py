"""Published-input checkpoint and current-manuscript update semantics.

Uses the existing task checkpoints/revisions, as output-reserve tracking does.
The checkpoint is committed with the published version, never before it.
"""
import json
import re
from sqlmodel import select
from app.models.review import ReviewSection

ORDINAL = -99994
UPDATE = ('依据已加载 Nature Writing 的局部修订工作流，更新当前版本的综述正文。'
          '当前版本是修改起点，保留其中已核对的条件、术语及不受新材料影响的段落。'
          '新生成的候选章节和写作简报只是参考，不用它们覆盖已有修订；依据原文处理必要变化，'
          '若新证据改变原判断，应在有关段落说明新的适用范围。'
          '直接输出完整中文正文和已有章节标题，保留 [P编号]，不附修改清单、投稿材料或审批要求。')


def unchanged(session,job,fingerprint):
    row=session.exec(select(ReviewSection).where(ReviewSection.review_id==job.id,
                                               ReviewSection.ordinal==ORDINAL)).first()
    if row is None or row.warning or row.fingerprint!=fingerprint or not job.content:return False
    try:version=json.loads(row.content)['published_version']
    except (ValueError,KeyError,TypeError):return False
    return type(version) is int and 0<version<=job.version


def metadata(session,job):
    row=session.exec(select(ReviewSection).where(ReviewSection.review_id==job.id,
                                               ReviewSection.ordinal==ORDINAL)).first()
    try:
        data=json.loads(row.content) if row else {}
        return data if isinstance(data,dict) else {}
    except (ValueError,TypeError):return {}


def paper_states(entries):
    from app.reviews.service import digest
    return {str(p.paper_id):digest([p.fingerprint,p.status,p.analysis,p.warning]) for p in entries}


def changed(session,job,entries):
    previous=metadata(session,job).get('papers',{})
    current=paper_states(entries)
    return [p for p in entries if previous.get(str(p.paper_id))!=current[str(p.paper_id)]]


def resume_initial(session,job):
    data=metadata(session,job)
    return bool(data.get('incomplete') and data.get('mode')=='initial' and data.get('published_version')==job.version)


def published(session,job,fingerprint,warning,entries=None,mode='initial'):
    row=session.exec(select(ReviewSection).where(ReviewSection.review_id==job.id,
                                               ReviewSection.ordinal==ORDINAL)).first()
    if row is None:row=ReviewSection(review_id=job.id,ordinal=ORDINAL,title='已发布综述的材料检查点')
    data=metadata(session,job)
    data.update(published_version=job.version,mode=mode,incomplete=bool(warning))
    # A partial update must still see its pending material after restart.
    if entries is not None and not warning:data['papers']=paper_states(entries)
    row.fingerprint=fingerprint;row.content=json.dumps(data)
    row.warning=warning;session.add(row)


def body(content):
    # Remove only the app's recognized reference/coverage block. Other user
    # sections and notes following it remain manuscript content.
    content=re.sub(r'\n\n## 引用文献\n\n(?:- \[P\d+\][^\n]*\n)*\n?\n## 材料范围\n\n'
                   r'本次范围 \d+ 篇；完成模型分析 \d+ 篇，使用摘录或已有内容 \d+ 篇，缺少可读材料 \d+ 篇。'
                   r'正文按主题选用相关文献，并非每篇都会被引用。全文分析使用选取的相关片段；这份综述基于本次材料范围。(?:\n|\Z)',
                   '',content)
    return re.sub(r'\A\s*# [^\n]+\n+','',content).strip()


def join_parts(parts):
    result=''
    for part in parts:
        if result and part and not result.endswith('\n') and not part.startswith('\n'):result+='\n\n'
        result+=part
    return result
