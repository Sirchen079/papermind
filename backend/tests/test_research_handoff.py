import json
from unittest.mock import patch

from sqlmodel import Session, select

from app.agent.provenance import tool_sources
from app.agent.tools import get_tool
from app.db.engine import get_engine
from app.models import Conversation, Paper, ResearchArtifact, ResearchTask
from app.providers.client import ToolCall, ToolTurn
from app.workspaces.context import bind_workspace
from tests.test_chat_api import _seed_chat_provider, _turn


def seed(session, task_id='research-fixture', content='人工更正：不同预处理条件不能直接比较。'):
    paper = Paper(source='manual', title='Source paper', full_text='Newer source content')
    session.add(paper); session.flush()
    session.add(ResearchTask(id=task_id, question='比较噪声与振幅适应性', status='running',
                            run_token='keep-running', paper_ids_json=json.dumps([paper.id])))
    session.flush()
    source = {'ref': 'E1', 'paper_id': paper.id, 'title': paper.title,
              'quote': 'Original experimental conditions.', 'locator': 'PDF 第 7 页',
              'page': 7, 'scope': 'full_text', 'source_hash': 'saved-hash'}
    session.add(ResearchArtifact(task_id=task_id, version=1, content='Earlier AI inference', claim_kind='ai_inference'))
    session.add(ResearchArtifact(task_id=task_id, version=2, content=content, claim_kind='researcher_judgment',
                                evidence_refs_json='["E1"]', evidence_snapshot_json=json.dumps([source])))
    session.commit()
    return paper.id


def test_handoff_keeps_exact_version_and_original_evidence_after_updates(client):
    with Session(get_engine()) as session:
        pid = seed(session)
        session.add(ResearchArtifact(task_id='research-fixture', version=3, content='Separate later judgment'))
        session.commit()
        tool = get_tool('read_research_task')
        document = tool.run(session, task_id='research-fixture', version=2)
        result = json.loads(document)
        assert result['text'] == '人工更正：不同预处理条件不能直接比较。'
        assert result['latest_version'] == 3 and result['material_kind'] == 'researcher_judgment'
        assert tool_sources(session, 'read_research_task', document) == []
        excerpt = tool.run(session, task_id='research-fixture', version=2, part='source')
        assert json.loads(excerpt)['text'] == 'Original experimental conditions.'
        sources = tool_sources(session, 'read_research_task', excerpt)
        assert sources[0]['paper_id'] == pid and sources[0]['pages'] == [7]
        assert sources[0]['research_task']['version'] == 2
        task = session.get(ResearchTask, 'research-fixture')
        assert task.status == 'running' and task.run_token == 'keep-running'


def test_handoff_creates_scoped_conversation_without_rerun_even_with_removed_paper(client):
    with Session(get_engine()) as session:
        pid = seed(session)
        paper = session.get(Paper, pid); paper.is_deleted = True; session.add(paper); session.commit()
    response = client.post('/api/research/tasks/research-fixture/conversation', json={'expected_version': 2})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['paper_ids'] == [pid] and result['research_task'] == {'task_id': 'research-fixture', 'version': 2}
    conversation = client.get(f'/api/chat/conversations/{result["id"]}').json()
    assert conversation['papers'][0]['id'] == pid and conversation['papers'][0]['unavailable']
    assert conversation['messages'] == []
    with Session(get_engine()) as session:
        result = json.loads(get_tool('read_research_task').run(session, task_id='research-fixture', version=2, part='source'))
        assert result['text'] == 'Original experimental conditions.' and not result['original_available']
    assert client.post('/api/research/tasks/research-fixture/conversation', json={'expected_version': 99}).status_code == 404
    assert len(client.get('/api/chat/conversations').json()) == 1


def test_handoff_is_project_scoped_even_when_task_ids_collide(client):
    workspaces = [client.post('/api/workspaces', json={'name': name}).json()['id'] for name in ('First', 'Second')]
    for wid in workspaces:
        with bind_workspace(client.app.state.workspaces.context(wid)), Session(get_engine()) as session:
            seed(session, content='Project '+wid)
    for wid in workspaces:
        response = client.post(f'/api/w/{wid}/research/tasks/research-fixture/conversation', json={'expected_version': 2})
        assert response.status_code == 201
        with bind_workspace(client.app.state.workspaces.context(wid)), Session(get_engine()) as session:
            result = json.loads(get_tool('read_research_task').run(session, task_id='research-fixture', version=2))
            assert result['text'] == 'Project '+wid
            assert len(session.exec(select(Conversation)).all()) == 1
    assert client.post('/api/research/tasks/research-fixture/conversation', json={'expected_version': 2}).status_code == 404


def test_agent_reads_carried_version_and_source_with_durable_attachment(client, monkeypatch):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        pid = seed(session)
    cid = client.post('/api/research/tasks/research-fixture/conversation', json={'expected_version': 2}).json()['id']
    attachment = {'name': '论文研究 v2', 'kind': 'text', 'text': '请从已保存成果继续。',
                  'research_task': {'task_id': 'research-fixture', 'version': 2}}
    monkeypatch.setattr('app.api.chat_api._retrieve_hits', lambda *a, **k: (_ for _ in ()).throw(AssertionError('generic handoff must not retrieve unrelated material')))
    turns = [ToolTurn('', [ToolCall('document', 'read_research_task', {'task_id': 'research-fixture', 'version': 2})], 1, 1, 2),
             ToolTurn('', [ToolCall('source', 'read_research_task', {'task_id': 'research-fixture', 'version': 2, 'part': 'source'})], 1, 1, 2),
             _turn('沿用人工更正，先对齐预处理条件。')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=turns) as model:
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': '继续比较', 'attachments': [attachment]})
    assert response.status_code == 200, response.text
    assert 'version=2' in str(model.call_args_list[0].args[2])
    assert '人工更正' in str(model.call_args.args[2])
    history = client.get(f'/api/chat/conversations/{cid}').json()
    assert history['messages'][0]['attachments'][0]['research_task'] == attachment['research_task']
    assert history['messages'][-1]['sources'][0]['pages'] == [7]
    assert history['papers'][0]['id'] == pid


def test_long_saved_result_can_be_read_in_full_and_missing_version_is_explicit(client):
    with Session(get_engine()) as session:
        content = '保留人工修改与条件。' * 1400
        seed(session, content=content)
        tool = get_tool('read_research_task'); offset = 0; parts = []
        while offset is not None:
            result = json.loads(tool.run(session, task_id='research-fixture', version=2, start_char=offset, max_chars=800))
            parts.append(result['text']); offset = result['next_start_char']
        assert ''.join(parts) == content
        assert 'error' in json.loads(tool.run(session, task_id='research-fixture', version=9))
        assert 'error' in json.loads(tool.run(session, task_id='research-fixture', version=2, part='source', source_index=-1))
