import json
from sqlmodel import Session
from app.db.engine import get_engine
from app.models.review import LibraryReview, ReviewPaper, ReviewSection
from app.agent.tools import get_tool
from app.agent.provenance import tool_sources


def test_agent_can_resume_from_partial_review_without_mutating_it(client):
    with Session(get_engine()) as s:
        job=LibraryReview(id='partial-research',question='研究方法的适用条件',status='running',run_token='live')
        s.add(job);s.commit()
        s.add(ReviewSection(review_id=job.id,ordinal=0,title='已有比较',content='阶段比较 [P7]'))
        s.add(ReviewSection(review_id=job.id,ordinal=-1,title='内部归纳',content='内部检查点'))
        for n in range(1,66):
            s.add(ReviewPaper(review_id=job.id,paper_id=n,title=f'论文 {n}',status='done' if n==7 else 'pending',analysis='已有分析' if n==7 else ''))
        s.commit()
        tool=get_tool('read_review')
        overview=json.loads(tool.run(s,review_id=job.id))
        assert overview['total_papers']==65 and len(overview['papers'])==30
        assert overview['next_offset']==30 and overview['sections']==[{'section':0,'title':'已有比较','has_content':True}]
        seen=[p['paper_id'] for p in overview['papers']]
        offset=overview['next_offset']
        while offset is not None:
            page=json.loads(tool.run(s,review_id=job.id,offset=offset))
            seen.extend(p['paper_id'] for p in page['papers']);offset=page['next_offset']
        assert seen==list(range(1,66))
        assert json.loads(tool.run(s,review_id=job.id,query='P7'))['papers'][0]['paper_id']==7
        draft=json.loads(tool.run(s,review_id=job.id,part='draft'))
        assert draft['text']=='## 已有比较\n\n阶段比较 [P7]'
        analysis=tool.run(s,review_id=job.id,part='paper',paper_id=7)
        assert json.loads(analysis)['text']=='已有分析'
        assert tool_sources(s,'read_review',analysis)==[]  # Generated notes cannot become primary evidence.
        assert 'error' in json.loads(tool.run(s,review_id=job.id,part='paper',paper_id=66))
        s.refresh(job)
        assert job.status=='running' and job.run_token=='live' and job.content=='' and job.version==0


def test_review_reading_preserves_saved_edits_and_all_text(client):
    with Session(get_engine()) as s:
        content='人改过的正文。'*2500
        s.add(LibraryReview(id='edited',question='Q',status='ready',content=content,version=3));s.commit()
        s.add(ReviewSection(review_id='edited',ordinal=0,title='旧章节',content='未采用的旧稿'));s.commit()
        tool=get_tool('read_review');offset=0;pieces=[]
        while offset is not None:
            result=json.loads(tool.run(s,review_id='edited',part='draft',start_char=offset,max_chars=16000))
            assert result['version']==3
            pieces.append(result['text']);offset=result['next_start_char']
        assert ''.join(pieces)==content
        assert 'error' in json.loads(tool.run(s,review_id='not-here'))
