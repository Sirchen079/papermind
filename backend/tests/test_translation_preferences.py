from types import SimpleNamespace

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper, Setting
from app.providers.client import ProviderClient


def setup_models(client):
    provider = client.post('/api/providers', json={'name': 'Translation test', 'type': 'openai_chat'}).json()['id']
    chat = client.post(f'/api/providers/{provider}/models', json={'model_id': 'chat-model', 'role_default': 'chat'}).json()['id']
    translation = client.post(f'/api/providers/{provider}/models', json={'model_id': 'translation-model'}).json()['id']
    embedding = client.post(f'/api/providers/{provider}/models', json={'model_id': 'vector-model', 'role_default': 'embedding'}).json()['id']
    with Session(get_engine()) as session:
        paper = Paper(title='Translation fixture', source='manual')
        session.add(paper); session.commit(); session.refresh(paper)
        pid = paper.id
    return provider, chat, translation, embedding, pid


def test_translation_preference_overrides_only_translation(client, monkeypatch):
    _, chat, translation, _, pid = setup_models(client)
    calls = []
    def complete(self, provider, model, messages, **kwargs):
        calls.append((model, messages, kwargs))
        return SimpleNamespace(content='Translated result')
    monkeypatch.setattr(ProviderClient, 'complete', complete)
    body = {'text': 'Source paragraph', 'target': 'English'}
    route = f'/api/papers/{pid}/translate'
    assert client.post(route, json=body).json()['model'] == 'chat-model'
    assert client.put('/api/settings/translation_model_config_id', json={'value': str(translation)}).status_code == 200
    assert client.get('/api/settings').json()['translation_model_config_id'] == str(translation)
    assert client.post(route, json=body).json()['model'] == 'translation-model'
    models = client.get('/api/chat/models').json()
    assert next(m for m in models if m['id'] == chat)['is_default'] is True
    assert client.post(route, json={**body, 'model_config_id': chat}).json()['model'] == 'chat-model'
    assert client.get('/api/settings').json()['translation_model_config_id'] == str(translation)
    client.put('/api/settings/translation_model_config_id', json={'value': ''})
    assert client.post(route, json=body).json()['model'] == 'chat-model'
    assert all(c[1][1]['content'] == body['text'] and c[2]['request_kind'] == 'reading_translation' for c in calls)


def test_translation_preference_rejects_invalid_models_and_retains_last_setting(client):
    provider, _, translation, embedding, pid = setup_models(client)
    route = '/api/settings/translation_model_config_id'
    client.put(route, json={'value': str(translation)})
    for invalid in ['abc', '-1', '0', '1.5', '9999999', str(embedding)]:
        assert client.put(route, json={'value': invalid}).status_code == 422
        assert client.get(route).json()['value'] == str(translation)
    client.patch(f'/api/providers/{provider}', json={'enabled': False})
    assert client.put(route, json={'value': str(translation)}).status_code == 422
    # A disabled dedicated model must not silently spend against a different one.
    assert client.post(f'/api/papers/{pid}/translate', json={'text': 'Test'}).status_code == 422
    assert client.put(route, json={'value': ''}).status_code == 200


def test_corrupt_saved_translation_preference_is_recoverable(client):
    _, _, _, _, pid = setup_models(client)
    with Session(get_engine()) as session:
        session.add(Setting(key='translation_model_config_id', value='corrupt'))
        session.commit()
    response = client.post(f'/api/papers/{pid}/translate', json={'text': 'Test'})
    assert response.status_code == 422
    assert '翻译模型配置无效' in response.json()['detail']
    assert client.put('/api/settings/translation_model_config_id', json={'value': ''}).status_code == 200


def test_translation_model_is_scoped_to_project_and_survives_restart(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    prefixes = []
    for name in ['A', 'B']:
        wid = client.post('/api/workspaces', json={'name': name}).json()['id']
        prefix = '/api/w/' + wid
        prefixes.append(prefix)
        provider = client.post(prefix + '/providers', json={'name': name, 'type': 'openai_chat'}).json()['id']
        client.post(prefix + f'/providers/{provider}/models', json={'model_id': name + '-chat', 'role_default': 'chat'})
        model = client.post(prefix + f'/providers/{provider}/models', json={'model_id': name + '-translator'}).json()['id']
        client.post(prefix + '/papers/manual', json={'title': 'Test'})
        if name == 'A':
            assert client.put(prefix + '/settings/translation_model_config_id', json={'value': str(model)}).status_code == 200
    monkeypatch.setattr(ProviderClient, 'complete', lambda *args, **kwargs: SimpleNamespace(content='Result'))
    restarted = TestClient(create_app())
    assert restarted.post(prefixes[0] + '/papers/1/translate', json={'text': 'Test'}).json()['model'] == 'A-translator'
    assert restarted.post(prefixes[1] + '/papers/1/translate', json={'text': 'Test'}).json()['model'] == 'B-chat'
    assert 'translation_model_config_id' not in restarted.get(prefixes[1] + '/settings').json()
