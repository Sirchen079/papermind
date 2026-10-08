"""The normal chat path discovers skills and retains actual load receipts."""
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider, Skill
from app.providers.client import ProviderClient, ToolCall, ToolTurn
from app.skills import builtin


def test_resource_receipt_preserves_actual_read_range_without_body(client):
    from app.agent.presentation import public_tool_result
    result = builtin.read_builtin_skill_resource(None, 'nature/nature-writing',
        'static/fragments/paper_type/review.md', start_char=12, max_chars=900)
    full = json.loads(result)
    receipt = json.loads(public_tool_result('read_builtin_skill_resource', result))
    assert receipt['start_char'] == 12 and receipt['end_char'] == 912
    assert receipt['next_start'] == 912 and receipt['loaded_chars'] == 900
    assert receipt['text_sha256'] == full['text_sha256']
    assert receipt['excerpt_sha256'] == full['excerpt_sha256']
    assert 'text' not in receipt and receipt['text_sha256'] != receipt['excerpt_sha256']


def test_directory_respects_enabled_state_without_loading_bodies(client):
    with Session(get_engine()) as session:
        assert builtin.discovery_prompt(session) == ''
        builtin.sync(session)
        skill = session.exec(select(Skill).where(Skill.name == 'nature-writing')).one()
        skill.description = '用户修改的写作说明'
        session.add(skill); session.commit()
        directory = builtin.discovery_prompt(session)
        assert 'nature/nature-writing' in directory and '用户修改的写作说明' in directory
        assert 'Write the argument before writing the sentences' not in directory
        skill.enabled = False
        session.add(skill); session.commit()
        assert 'nature/nature-writing' not in builtin.discovery_prompt(session)


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_chat_model_receives_catalog_and_loaded_review_resources(client, suffix):
    with Session(get_engine()) as session:
        builtin.sync(session)
        provider = Provider(name='skill-test', type='openai_chat')
        session.add(provider); session.commit(); session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id='test', role_default='chat', context_window=128000))
        session.commit()
    cid = client.post('/api/chat/conversations').json()['id']
    draft = '基于已有材料的研究判断。仍需实测数据验证具体效果。'
    calls = []

    def complete(self, provider, model, messages, kind, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            assert 'nature/nature-writing' in messages[0]['content']
            assert '尚未加载技能正文' in messages[0]['content']
            return ToolTurn('', [ToolCall(id='load', name='load_builtin_skill', arguments={
                'skill_id': 'nature/nature-writing', 'axes': {'paper_type': 'review'}})], 1, 1, 2)
        if len(calls) == 2:
            loaded = json.loads(next(m['content'] for m in messages if m['role'] == 'tool'))
            assert 'A review is **not a survey list**' in loaded['text']
            assert 'this update is not an approval gate' in loaded['text']
            assert 'continue independent passages' in loaded['text']
            assert loaded['fingerprint']
            return ToolTurn('', [ToolCall(id='save', name='save_document', arguments={
                'filename': 'skill-note.md', 'content': draft})], 1, 1, 2)
        return ToolTurn('研究笔记已保存。', [], 1, 1, 2)

    with patch.object(ProviderClient, 'complete_with_tools', complete):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
            'content': '综合现有证据写一份 FWI 研究笔记。缺失数据注明即可，继续完成。',
            'paper_ids': []})
    assert response.status_code == 200
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['role'] == 'assistant'
    assert [t['name'] for t in row['tools']] == ['load_builtin_skill', 'save_document']
    loaded = json.loads(row['tools'][0]['result'])
    assert any(r['path'] == 'static/fragments/paper_type/review.md' for r in loaded['resources'])
    assert loaded['fingerprint'] == builtin.load('nature/nature-writing', {'paper_type': 'review'})['fingerprint']
    assert loaded['loaded_chars'] > 800 and 'text' not in loaded
    saved = json.loads(row['tools'][1]['result'])
    assert client.get(saved['download_url']).text == draft
