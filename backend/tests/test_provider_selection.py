from sqlmodel import Session

from app.db.engine import get_engine
from app.providers.selection import pick_llm


def provider(client, name):
    return client.post('/api/providers', json={'name': name, 'type': 'openai_chat'}).json()['id']


def test_text_fallback_skips_connections_without_models(client):
    provider(client, 'Setup still in progress')
    ready = provider(client, 'Ready connection')
    assert client.post(f'/api/providers/{ready}/models', json={'model_id': 'text-model'}).status_code == 201
    with Session(get_engine()) as session:
        chosen = pick_llm(session, 'chat')
        assert chosen is not None
        assert chosen[1].id == ready and chosen[2] == 'text-model'


def test_text_fallback_never_uses_explicit_embedding_model(client):
    pid = provider(client, 'Vector connection')
    assert client.post(f'/api/providers/{pid}/models', json={
        'model_id': 'vector-model', 'role_default': 'embedding',
    }).status_code == 201
    with Session(get_engine()) as session:
        assert pick_llm(session, 'chat') is None
        assert pick_llm(session, 'embedding')[2] == 'vector-model'
    assert client.post(f'/api/providers/{pid}/models', json={'model_id': 'text-model'}).status_code == 201
    with Session(get_engine()) as session:
        assert pick_llm(session, 'summarize')[2] == 'text-model'


def test_explicit_chat_default_wins_over_fallback(client):
    first = provider(client, 'First')
    second = provider(client, 'Preferred')
    client.post(f'/api/providers/{first}/models', json={'model_id': 'fallback'})
    client.post(f'/api/providers/{second}/models', json={'model_id': 'preferred', 'role_default': 'chat'})
    with Session(get_engine()) as session:
        assert pick_llm(session, 'chat')[2] == 'preferred'
    client.patch(f'/api/providers/{second}', json={'enabled': False})
    with Session(get_engine()) as session:
        assert pick_llm(session, 'chat')[2] == 'fallback'
