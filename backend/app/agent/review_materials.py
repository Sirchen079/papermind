"""Let a research conversation continue from saved review work, including drafts."""
import json
from sqlmodel import select
from sqlalchemy import func
from app.models.review import LibraryReview, ReviewPaper, ReviewSection


def read_review(session, review_id, part='overview', paper_id=None, section=None,
                start_char=0, max_chars=10000, offset=0, query=''):
    job=session.get(LibraryReview,review_id)
    if job is None:return json.dumps({'error':'研究任务不存在'})
    result={'review_id':job.id,'question':job.question,'status':job.status,
            'stage':job.stage,'version':job.version,'source_type':'research_workspace',
            'note':'分析和草稿是研究过程产物，不是论文原文；具体事实可通过 paper_id 回读原论文。'}
    sections=session.exec(select(ReviewSection).where(ReviewSection.review_id==review_id,
        ReviewSection.ordinal>=0).order_by(ReviewSection.ordinal)).all()
    if part=='overview':
        rows=session.exec(select(ReviewPaper.paper_id,ReviewPaper.title,ReviewPaper.status,
                          func.length(ReviewPaper.analysis).label('analysis_chars')).where(ReviewPaper.review_id==review_id)
                          .order_by(ReviewPaper.id)).all()
        filtered=[p for p in rows if not query or query.casefold() in p.title.casefold()
                  or query.strip().lstrip('Pp')==str(p.paper_id)]
        offset=max(0,int(offset));page=filtered[offset:offset+30]
        result.update(total_papers=len(rows),matching_papers=len(filtered),
            papers=[{'paper_id':p.paper_id,'title':p.title,'status':p.status,'has_analysis':bool(p.analysis_chars)} for p in page],
            next_offset=offset+len(page) if offset+len(page)<len(filtered) else None,
            sections=[{'section':s.ordinal,'title':s.title,'has_content':bool(s.content)} for s in sections],
            has_draft=bool(job.content),available_parts=['draft','section','paper'])
    else:
        if part=='draft':
            text=job.content or '\n\n'.join(f'## {s.title}\n\n{s.content}' for s in sections if s.content)
            result['material']='已保存正文' if job.content else '进行中的章节草稿'
        elif part=='section':
            row=next((s for s in sections if s.ordinal==section),None)
            if row is None:return json.dumps({'error':'该章节尚无保存记录；可读取 overview 查看已有材料'},ensure_ascii=False)
            text=row.content;result.update(section=row.ordinal,title=row.title,warning=row.warning)
        elif part=='paper':
            row=session.exec(select(ReviewPaper).where(ReviewPaper.review_id==review_id,
                ReviewPaper.paper_id==paper_id)).first()
            if row is None:return json.dumps({'error':'该论文不在本研究任务中'},ensure_ascii=False)
            text=row.analysis
            result.update(paper_id=row.paper_id,title=row.title,analysis_status=row.status,
                          coverage=row.coverage,warning=row.warning,material='已保存的论文分析')
        else:return json.dumps({'error':'part 可为 overview、draft、section 或 paper'},ensure_ascii=False)
        start=max(0,min(int(start_char),len(text)));end=min(len(text),start+max(500,min(int(max_chars),16000)))
        result.update(text=text[start:end],start_char=start,end_char=end,total_chars=len(text),
                      next_start_char=end if end<len(text) else None)
    return json.dumps(result,ensure_ascii=False)
