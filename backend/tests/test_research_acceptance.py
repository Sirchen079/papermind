"""Regression cases from the graduate release acceptance (G06/G07)."""
import json
from datetime import datetime

from sqlmodel import Session

from app.archive.service import export_json
from app.db.engine import get_engine
from app.models import (Paper, ResearchTask, ResearchArtifact, ResearchReuse,
                        Claim, ClaimRelation, PaperCitation, Report, Project, Chapter, ChapterDraft)


def test_export_preserves_research_versions_evidence_and_relationships(client):
    with Session(get_engine()) as session:
        paper = Paper(title='研究原文', source='manual')
        project = Project(name='研究论文')
        session.add(paper); session.add(project); session.commit()
        chapter = Chapter(project_id=project.id, title='相关研究')
        task = ResearchTask(id='export-task', question='如何公平比较？', paper_ids_json=json.dumps([paper.id]),
                            materials_json='[{"quote":"原文依据"}]', run_token='internal-run-token')
        claim = Claim(paper_id=paper.id, text='条件不同')
        other = Claim(paper_id=paper.id, text='不能直接排名')
        deleted = Claim(paper_id=paper.id, text='删除的论断', is_deleted=True)
        session.add_all([chapter, task, claim, other, deleted]); session.commit()
        first = ResearchArtifact(task_id=task.id, version=1, content='初稿', evidence_snapshot_json='[{"quote":"原文依据"}]')
        second = ResearchArtifact(task_id=task.id, version=2, content='先统一数据划分', evidence_snapshot_json='[{"quote":"原文依据"}]', support_status='partial')
        session.add_all([first, second]); session.commit()
        session.add_all([
            ResearchReuse(task_id=task.id, artifact_id=first.id, kind='meeting', content='旧版本素材'),
            ClaimRelation(claim_a_id=claim.id, claim_b_id=other.id, type='supports'),
            ClaimRelation(claim_a_id=other.id, claim_b_id=deleted.id, type='supports'),
            PaperCitation(source_paper_id=paper.id, raw_ref='参考文献'),
            ChapterDraft(chapter_id=chapter.id, content='章节草稿'),
            Report(since=datetime(2026,9,1), until=datetime(2026,9,10), content='组会正文'),
        ]); session.commit()
        result = export_json(session)
    assert result['restore_supported'] is False
    assert 'run_token' not in result['research_tasks'][0]
    assert json.loads(result['research_tasks'][0]['materials_json'])[0]['quote'] == '原文依据'
    assert {a['version']: a['content'] for a in result['research_artifacts']} == {1:'初稿',2:'先统一数据划分'}
    assert json.loads(result['research_artifacts'][1]['evidence_snapshot_json'])[0]['quote'] == '原文依据'
    assert result['research_reuse'][0]['artifact_id'] == result['research_artifacts'][0]['id']
    assert len(result['claims']) == 2 and len(result['claim_relations']) == 1
    assert result['paper_citations'][0]['raw_ref'] == '参考文献'
    assert result['chapter_drafts'][0]['content'] == '章节草稿'
    assert result['reports'][0]['content'] == '组会正文'


def test_research_history_can_reach_and_search_older_than_fifty(client):
    with Session(get_engine()) as session:
        for n in range(61):
            session.add(ResearchTask(id=f'task-{n:03}', question=f'研究 {n}' if n else '早期 100%_研究', paper_ids_json='[]', updated_at=datetime(2026,9,1)))
        session.commit()
    first = client.get('/api/research/tasks?limit=50').json()
    second = client.get('/api/research/tasks?limit=50&offset=50').json()
    assert len(first) == 50 and len(second) == 11
    assert len({row['id'] for row in first + second}) == 61
    assert second[-1]['id'] == 'task-000'
    matching = client.get('/api/research/tasks', params={'q':'100%_'}).json()
    assert [row['id'] for row in matching] == ['task-000']
    assert client.get('/api/research/tasks?offset=-1').status_code == 422
    assert client.get('/api/research/tasks?limit=101').status_code == 422


def test_research_meeting_uses_readable_unknowns_and_stop_reason(client):
    from app.research.service import reuse_artifact
    with Session(get_engine()) as session:
        task = ResearchTask(id='readable-task', question='如何比较？', paper_ids_json='[]', status='partial',
                            stop_reason='answered_with_limits', steps_json=json.dumps({'synthesis': {'unknowns':['缺少统一划分']}}))
        session.add(task); session.commit()
        session.add(ResearchArtifact(task_id=task.id, version=1, content='有限判断')); session.commit()
        result = reuse_artifact(session, task.id, 1, 'meeting')
    text = result['reuse'][0]['content']
    assert '- 缺少统一划分' in text and '已交付有限判断' in text
    assert "['" not in text and 'answered_with_limits' not in text
