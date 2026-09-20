import copy
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from test_chat_api import _seed_chat_provider, _turn


def seed():
    with Session(get_engine()) as session:
        rows = [Paper(source='manual', title=f'Paper {i}', abstract=f'ABSTRACT_{i}', full_text=f'FULL_{i}') for i in range(3)]
        session.add_all(rows); session.commit()
        for row in rows:
            session.refresh(row)
        return [row.id for row in rows]


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_paper_set_persists_across_followups_and_clear(client, suffix):
    _seed_chat_provider()
    ids = seed()
    response = client.post('/api/chat/conversations', json={'paper_ids': [*ids[:2], ids[0]]})
    assert response.status_code == 200
    cid = response.json()['id']
    detail = client.get(f'/api/chat/conversations/{cid}').json()
    assert [p['id'] for p in detail['papers']] == ids[:2]
    assert detail['paper_id'] is None
    captured = []
    def complete(*args, **kwargs):
        captured.append(copy.deepcopy(args[2]))
        return _turn('A comparison with paper titles')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=complete):
        for question in ['Compare methods', 'What about limitations?']:
            assert client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': question}).status_code == 200
        assert client.patch(f'/api/chat/conversations/{cid}', json={'paper_id': None}).status_code == 200
        assert client.get(f'/api/chat/conversations/{cid}').json()['papers'] == []
        assert client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'New topic'}).status_code == 200
    for prompt in captured[:2]:
        assert 'ABSTRACT_0' in json.dumps(prompt) and 'ABSTRACT_1' in json.dumps(prompt)
        assert 'ABSTRACT_2' not in json.dumps(prompt)
    # Historical turns keep their grounding, but this new turn has no selected set.
    assert '[用户选择的论文讨论范围]' not in captured[2][-1]['content']


def test_invalid_set_and_removed_paper(client):
    _seed_chat_provider()
    ids = seed()
    assert client.post('/api/chat/conversations', json={'paper_ids': [99999]}).status_code == 404
    assert client.post('/api/chat/conversations', json={'paper_id': ids[0], 'paper_ids': ids[:2]}).status_code == 422
    cid = client.post('/api/chat/conversations', json={'paper_ids': ids[:2]}).json()['id']
    with Session(get_engine()) as session:
        row = session.get(Paper, ids[0]); row.is_deleted = True; session.add(row); session.commit()
    detail = client.get(f'/api/chat/conversations/{cid}').json()
    assert detail['papers'][0]['unavailable'] is True
    captured = []
    def complete(*args, **kwargs):
        captured.append(args[2]); return _turn('Discuss remaining paper')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=complete):
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Discuss', 'paper_ids': ids[:2]})
    assert response.status_code == 200
    assert '已移除' in json.dumps(captured, ensure_ascii=False)
    assert 'ABSTRACT_0' not in json.dumps(captured)


def test_retry_retains_original_paper_set(client):
    _seed_chat_provider()
    ids = seed()
    cid = client.post('/api/chat/conversations', json={'paper_ids': ids[:2]}).json()['id']
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=RuntimeError('offline')):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Compare'})
    user = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert user['retryable']
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Recovered')):
        result = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Compare', 'retry_message_id': user['id'], 'paper_ids': [ids[2]]})
    assert result.status_code == 200
    detail = client.get(f'/api/chat/conversations/{cid}').json()
    assert [p['id'] for p in detail['papers']] == ids[:2]
    assert len([m for m in detail['messages'] if m['role'] == 'user']) == 1


def test_scoped_retrieval_ranks_only_selected_papers(client, monkeypatch):
    from types import SimpleNamespace
    from app.models import PaperChunk
    from app.rag import index
    from app.rag.vector import serialize
    ids = seed()
    with Session(get_engine()) as session:
        session.add_all([PaperChunk(paper_id=pid, ordinal=0, text=str(pid), embedding=serialize(vector), embedding_model='emb')
                         for pid, vector in [(ids[0], [0., 1.]), (ids[2], [1., 0.])]])
        session.commit()
        monkeypatch.setattr(index, 'pick_llm', lambda *args: (SimpleNamespace(embed=lambda *args, **kwargs: [[1., 0.]]), object(), 'emb'))
        hits = index.retrieve(session, 'query', k=1, paper_ids=ids[:2])
        assert [row.paper_id for row, _ in hits] == ids[:1]
