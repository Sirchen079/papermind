from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper, TokenUsage
from app.providers.client import ToolTurn


def create(client, name):
    result = client.post('/api/workspaces', json={'name': name, 'goal': name + ' goal'})
    assert result.status_code == 201, result.text
    return '/api/w/' + result.json()['id']


def paper(client, prefix, title):
    response = client.post(prefix + '/papers/manual', json={'title': title})
    assert response.status_code == 201, response.text
    return response.json()


def test_workspace_names_and_unknown_scope_fail_closed(client):
    assert [w['id'] for w in client.get('/api/workspaces').json()] == ['legacy']
    assert client.post('/api/workspaces', json={'name': '   '}).status_code == 422
    prefix = create(client, 'Parallel research')
    wid = prefix.rsplit('/', 1)[1]
    assert client.patch('/api/workspaces/' + wid, json={'archived': True}).json()['archived']
    assert client.patch('/api/workspaces/' + wid, json={'name': 'Renamed', 'archived': False}).json()['name'] == 'Renamed'
    assert client.get('/api/w/' + '0' * 32 + '/papers').status_code == 404
    assert client.get('/api/w/not-a-project/papers').status_code == 404
    assert client.get('/api/papers').json()['total'] == 0


def test_same_ids_keep_library_conversations_paths_and_restart_independent(client):
    a, b = create(client, 'A'), create(client, 'B')
    assert paper(client, a, 'Evidence A')['id'] == paper(client, b, 'Evidence B')['id'] == 1
    assert client.post(a + '/chat/conversations').json()['id'] == client.post(b + '/chat/conversations').json()['id'] == 1
    client.patch(a + '/chat/conversations/1', json={'title': 'Only A'})
    assert client.get(b + '/chat/conversations').json()[0]['title'] != 'Only A'
    assert [p['title'] for p in client.get(a + '/papers').json()['items']] == ['Evidence A']
    assert [p['title'] for p in client.get(b + '/papers').json()['items']] == ['Evidence B']
    assert client.get('/api/papers').json()['total'] == 0
    a_status = client.get(a + '/archive/status').json()
    b_status = client.get(b + '/archive/status').json()
    assert a_status['data_dir'] != b_status['data_dir']
    from app.main import create_app
    restarted = TestClient(create_app())
    assert restarted.get(a + '/papers/1').json()['title'] == 'Evidence A'
    assert restarted.get(b + '/papers/1').json()['title'] == 'Evidence B'


def test_parallel_same_id_chats_keep_context_locks_and_usage_in_origin(client, monkeypatch):
    a, b = create(client, 'A'), create(client, 'B')
    for prefix, title in ((a, 'Evidence A'), (b, 'Evidence B')):
        paper(client, prefix, title)
        provider = client.post(prefix + '/providers', json={'name': 'Synthetic', 'type': 'openai_chat'}).json()
        client.post(prefix + f"/providers/{provider['id']}/models", json={'model_id': 'synthetic', 'role_default': 'chat'})
        assert client.post(prefix + '/chat/conversations').json()['id'] == 1
    started, release = Event(), Event()
    def complete(self, provider, model_id, *args, **kwargs):
        with Session(get_engine()) as session:
            title = session.get(Paper, 1).title
        prompt = str(args[0])
        assert ('A goal' in prompt) == (title == 'Evidence A')
        assert ('B goal' in prompt) == (title == 'Evidence B')
        if title == 'Evidence A':
            started.set()
            assert release.wait(15), 'second project never completed'
        self._record_usage(provider, model_id, 'chat', '1', 2, 3, 5)
        return ToolTurn(title, [], 2, 3, 5)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', complete)
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(client.post, a + '/chat/conversations/1/messages/stream', json={'content': 'Question A'})
        try:
            assert started.wait(15)
            result_b = client.post(b + '/chat/conversations/1/messages', json={'content': 'Question B'})
            assert result_b.status_code == 200, result_b.text
            assert result_b.json()['content'] == 'Evidence B'
        finally:
            release.set()
        result_a = pending.result(timeout=15)
    assert 'Evidence A' in result_a.text and 'Evidence B' not in result_a.text
    for prefix in (a, b):
        context = client.app.state.workspaces.context(prefix.rsplit('/', 1)[1])
        from app.workspaces.context import bind_workspace
        with bind_workspace(context), Session(get_engine()) as session:
            assert len(session.exec(select(TokenUsage)).all()) == 1
    with Session(get_engine()) as session:
        assert session.exec(select(TokenUsage)).all() == []
