import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Message, Model, Provider, Skill
from app.providers.client import ProviderClient, ToolCall, ToolTurn
from app.skills import builtin


@pytest.fixture
def writing_chat(client):
    with Session(get_engine()) as session:
        builtin.sync(session)
        provider = Provider(name='workflow-test', type='openai_chat')
        session.add(provider); session.commit(); session.refresh(provider)
        # Exercise the existing 16K default, not only a million-token model.
        session.add(Model(provider_id=provider.id, model_id='test', role_default='chat'))
        session.commit()
    return client, client.post('/api/chat/conversations').json()['id']


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
@pytest.mark.parametrize('workflow,expected', [
    ('literature-synthesis', 'not a survey list'),
    ('review-revision', 'keep unaffected passages verbatim'),
])
def test_task_loads_writing_route_before_model_and_saves(writing_chat, suffix, workflow, expected):
    client, cid = writing_chat
    seen = []

    def complete(self, provider, model, messages, kind, **kwargs):
        seen.append(messages)
        if len(seen) == 1:
            content = '\n'.join(m['content'] for m in messages)
            assert expected in content and 'nature/nature-writing' in content
            assert 'excerpt_sha256' in content
            if workflow == 'review-revision':
                assert 'Do not use compression to hide inconvenient evidence.' in content
                assert 'keep it visible in the main text' in ' '.join(content.split())
            return ToolTurn('', [ToolCall(id='save', name='save_document', arguments={
                'filename': 'review.md', 'content': '已有证据支持的研究笔记。'})], 1, 1, 2)
        return ToolTurn('已保存。', [], 1, 1, 2)

    with patch.object(ProviderClient, 'complete_with_tools', complete):
        result = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
            'content': '根据现有材料完成本轮任务。', 'workflow': workflow, 'paper_ids': []})
    assert result.status_code == 200
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[-1]['role'] == 'assistant'
    assert [t['name'] for t in rows[-1]['tools']] == ['save_document']
    with Session(get_engine()) as session:
        user = session.get(Message, rows[0]['id'])
        assert json.loads(user.request_json)['workflow'] == workflow
        assert expected in user.model_context


def test_workflow_retry_reuses_original_selection(writing_chat):
    client, cid = writing_chat
    with patch.object(ProviderClient, 'complete_with_tools', side_effect=TimeoutError('temporary')):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={
            'content': '修订这段综述。', 'workflow': 'review-revision', 'paper_ids': []})
    failed = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    with patch.object(ProviderClient, 'complete_with_tools', return_value=ToolTurn('修订结果。', [], 1, 1, 2)) as model:
        result = client.post(f'/api/chat/conversations/{cid}/messages', json={
            'content': failed['content'], 'retry_message_id': failed['id'], 'workflow': 'general'})
    assert result.status_code == 200
    content = '\n'.join(m['content'] for m in model.call_args.args[2])
    assert 'keep unaffected passages verbatim' in content


def test_disabled_guide_does_not_block_research(writing_chat):
    client, cid = writing_chat
    with Session(get_engine()) as session:
        skill = session.exec(select(Skill).where(Skill.name == 'nature-writing')).one()
        skill.enabled = False; session.add(skill); session.commit()
    with patch.object(ProviderClient, 'complete_with_tools', return_value=ToolTurn('继续完成研究。', [], 1, 1, 2)) as model:
        result = client.post(f'/api/chat/conversations/{cid}/messages', json={
            'content': '综合材料。', 'workflow': 'literature-synthesis', 'paper_ids': []})
    assert result.status_code == 200
    content = '\n'.join(m['content'] for m in model.call_args.args[2])
    assert '所选写作指导未启用' in content and 'not a survey list' not in content


def test_general_task_has_no_writing_workflow(writing_chat):
    client, cid = writing_chat
    with patch.object(ProviderClient, 'complete_with_tools', return_value=ToolTurn('你好。', [], 1, 1, 2)) as model:
        client.post(f'/api/chat/conversations/{cid}/messages', json={'content': '你好。', 'paper_ids': []})
    assert 'not a survey list' not in '\n'.join(m['content'] for m in model.call_args.args[2])
