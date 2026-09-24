import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Paper, PaperChunk, Setting, TokenUsage
from app.providers.client import ProviderClient
from app.providers.purposes import purpose_model, rerank_mode
from app.rag.index import retrieve
from app.rag.llm_rerank import rank
from app.rag.vector import serialize


def setup(client, provider_type='openai_chat', prefix='/api'):
    provider = client.post(prefix + '/providers', json={'name': 'One model', 'type': provider_type}).json()['id']
    mid = client.post(prefix + f'/providers/{provider}/models', json={'model_id': 'multimodal', 'role_default': 'chat'}).json()['id']
    assert client.put(prefix + '/settings/rerank_mode', json={'value': 'llm'}).status_code == 200
    return provider, mid


def add_papers(session):
    a = Paper(title='Alpha', source='manual', full_text='Protein folding baseline shows low accuracy.')
    b = Paper(title='Beta', source='manual', full_text='Protein folding experiment improves accuracy and robustness.')
    c = Paper(title='Outside', source='manual', full_text='Protein folding private outside scope.')
    d = Paper(title='Deleted', source='manual', full_text='Protein folding deleted.', is_deleted=True)
    session.add_all([a, b, c, d]); session.commit()
    for p in [a, b, c, d]:
        session.refresh(p)
    return a, b, c, d


def test_one_model_can_share_all_text_purposes_and_rank_vector_candidates(client, monkeypatch):
    provider, mid = setup(client)
    client.post(f'/api/providers/{provider}/models', json={'model_id': 'vector', 'role_default': 'embedding'})
    for purpose in ['ocr', 'translation', 'rerank_llm']:
        assert client.put(f'/api/settings/{purpose}_model_config_id', json={'value': str(mid)}).status_code == 200
    assert client.get('/api/chat/models').json()[0]['id'] == mid
    choices = client.get('/api/document-models').json()
    assert mid in [m['id'] for m in choices['ocr']] and mid in [m['id'] for m in choices['rerank_llm']]
    assert mid not in [m['id'] for m in choices['rerank']]
    calls = []
    def complete(self, provider, model, messages, **kwargs):
        assert model == 'multimodal' and kwargs['request_kind'] == 'rerank_llm'
        payload = json.loads(messages[1]['content']); calls.append(payload)
        assert all('private' not in d['text'] and 'deleted' not in d['text'] for d in payload['candidates'])
        chosen = next(d['id'] for d in payload['candidates'] if 'improves' in d['text'])
        return SimpleNamespace(content=json.dumps({'ranking': [chosen]}))
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1, 0]])
    monkeypatch.setattr(ProviderClient, 'rerank', lambda *a, **kw: pytest.fail('must not call /rerank'))
    with Session(get_engine()) as session:
        a, b, _, _ = add_papers(session)
        for paper, vector in [(a, [1, 0]), (b, [.8, .2])]:
            session.add(PaperChunk(paper_id=paper.id, text=paper.full_text, embedding_model='vector', embedding=serialize(vector)))
        session.commit()
        result = retrieve(session, 'protein folding', k=1, paper_ids=[a.id, b.id])
        assert result[0][0].paper_id == b.id and len(calls) == 1
        assert len(session.exec(select(PaperChunk)).all()) == 2
        assert retrieve(session, 'protein folding', paper_ids=[]) == []
        assert retrieve(session, '  ') == []
        assert len(calls) == 1


def test_llm_reranks_vector_candidates_and_bad_output_falls_back(client, monkeypatch):
    provider, _ = setup(client)
    client.post(f'/api/providers/{provider}/models', json={'model_id': 'vector', 'role_default': 'embedding'})
    monkeypatch.setattr(ProviderClient, 'embed', lambda *a, **kw: [[1, 0]])
    with Session(get_engine()) as session:
        a, b, c, _ = add_papers(session)
        for p, vector in [(a, [1, 0]), (b, [.6, .4]), (c, [1, 0])]:
            session.add(PaperChunk(paper_id=p.id, text=p.full_text, embedding_model='vector', embedding=serialize(vector)))
        session.commit()
        def complete(self, provider, model, messages, **kwargs):
            candidates = json.loads(messages[1]['content'])['candidates']
            assert len(candidates) == 2 and 'baseline' in candidates[0]['text']
            return SimpleNamespace(content='{"ranking":[1]}')
        monkeypatch.setattr(ProviderClient, 'complete', complete)
        assert retrieve(session, 'protein', k=1, paper_ids=[a.id, b.id])[0][0].paper_id == b.id
        monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: SimpleNamespace(content='{"ranking":[99]}'))
        assert retrieve(session, 'protein', k=1, paper_ids=[a.id, b.id])[0][0].paper_id == a.id


@pytest.mark.parametrize('response', ['{"ranking":[0,0]}', '{"ranking":[0,99]}', '{"ranking":[true,1]}', '{"ranking":["0",1]}', '{"ranking":[0]}', '{"ranking":[0,1,2]}', 'Here is my ranking: [0,1]', '{"ranking":null}', '[]'])
def test_rank_rejects_invalid_or_invented_ids(response):
    caller = SimpleNamespace(complete=lambda *a, **kw: SimpleNamespace(content=response))
    with pytest.raises(ValueError):
        rank((caller, None, 'model'), 'query', ['one', 'two'], 2)


def test_rank_has_bounded_prompt_and_supports_fenced_json():
    seen = []
    def complete(*args, **kw):
        messages = args[2]; seen.append(messages)
        assert len(messages[1]['content']) < 8000
        assert 'untrusted' in messages[0]['content']
        assert kw['request_kind'] == 'rerank_llm' and kw['max_tokens'] == 2048
        return SimpleNamespace(content='```json\n{"ranking":[1,0]}\n```')
    ctx = (SimpleNamespace(complete=complete), None, 'model')
    assert [r[0] for r in rank(ctx, 'question', ['x' * 30000] * 30, 2)] == [1, 0]
    with pytest.raises(ValueError, match='context too small'):
        rank(ctx, 'question', ['x'] * 30, 2, context_window=2048)
    assert len(seen) == 1


def test_llm_mode_still_requires_embedding_and_does_not_recall_keywords(client, monkeypatch):
    setup(client)
    monkeypatch.setattr(ProviderClient, 'complete', lambda *a, **kw: pytest.fail('no candidates without embedding'))
    with Session(get_engine()) as session:
        a = Paper(title='图像识别', source='manual', full_text='本研究比较图像识别方法的准确率。')
        session.add(a); session.commit(); session.refresh(a)
        assert retrieve(session, '图像识别准确率') == []


def test_legacy_dedicated_config_and_mode_switch_preserve_choices(client):
    provider, mid = setup(client)
    client.patch(f'/api/providers/{provider}', json={'base_url': 'https://example.test/v1'})
    dedicated = client.post(f'/api/providers/{provider}/models', json={'model_id': 'ranker'}).json()['id']
    assert client.put('/api/settings/rerank_model_config_id', json={'value': str(dedicated)}).status_code == 200
    client.delete('/api/settings/rerank_mode')
    with Session(get_engine()) as session:
        assert rerank_mode(session) == 'dedicated'
    assert client.put('/api/settings/rerank_llm_model_config_id', json={'value': str(mid)}).status_code == 200
    for mode in ['llm', 'off', 'dedicated', 'llm']:
        assert client.put('/api/settings/rerank_mode', json={'value': mode}).status_code == 200
    settings = client.get('/api/settings').json()
    assert settings['rerank_model_config_id'] == str(dedicated)
    assert settings['rerank_llm_model_config_id'] == str(mid)
    assert client.put('/api/settings/rerank_mode', json={'value': 'invalid'}).status_code == 422
    assert client.get('/api/settings').json()['rerank_mode'] == 'llm'
    for invalid in [str(dedicated), '-1', '0', 'invalid', '99999']:
        assert client.put('/api/settings/rerank_llm_model_config_id', json={'value': invalid}).status_code == 422
    assert client.patch(f'/api/models/{mid}', json={'role_default': 'embedding'}).status_code == 422
    client.patch(f'/api/providers/{provider}', json={'enabled': False})
    assert client.put('/api/settings/rerank_llm_model_config_id', json={'value': str(mid)}).status_code == 422


@pytest.mark.parametrize('kind', ['openai_chat', 'openai_responses', 'anthropic'])
def test_llm_transport_timeout_and_usage_recording(client, monkeypatch, kind):
    import litellm
    setup(client, kind)
    def completion(**kwargs):
        assert kwargs['timeout'] == 45 and kwargs['num_retries'] == 0
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ranking":[0]}'), finish_reason='stop')], usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15})
    def responses(**kwargs):
        assert kwargs['timeout'] == 45 and kwargs['num_retries'] == 0 and 'input' in kwargs
        return SimpleNamespace(output_text='{"ranking":[0]}', status='completed', usage={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15})
    monkeypatch.setattr(litellm, 'completion', completion)
    monkeypatch.setattr(litellm, 'responses', responses)
    with Session(get_engine()) as session:
        ctx = purpose_model(session, 'rerank_llm')
        assert rank(ctx, 'Q', ['A'], 1) == [(0, 1.)]
    with Session(get_engine()) as session:
        usage = session.exec(select(TokenUsage)).one()
        assert usage.request_kind == 'rerank_llm' and usage.total_tokens == 15


def test_modes_persist_and_are_project_scoped(client):
    from fastapi.testclient import TestClient
    from app.main import create_app
    ids = [client.post('/api/workspaces', json={'name': name}).json()['id'] for name in ['A rank', 'B rank']]
    prefix = '/api/w/' + ids[0]
    _, mid = setup(client, prefix=prefix)
    client.put(prefix + '/settings/rerank_llm_model_config_id', json={'value': str(mid)})
    restarted = TestClient(create_app())
    assert restarted.get(prefix + '/settings').json()['rerank_mode'] == 'llm'
    other = restarted.get('/api/w/' + ids[1] + '/settings').json()
    assert 'rerank_mode' not in other and 'rerank_llm_model_config_id' not in other
