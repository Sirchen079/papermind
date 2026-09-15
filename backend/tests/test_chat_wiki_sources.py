import pytest
pytestmark=pytest.mark.usefixtures("accept_evidence_review")

"""Versioned topic provenance survives streaming, retries and project switches."""
import json
from uuid import uuid4

import pytest

from app.providers.client import ToolCall, ToolTurn


def configure(client, prefix):
    provider = client.post(prefix + '/providers', json={'name': 'Synthetic', 'type': 'openai_chat'}).json()
    assert client.post(prefix + f"/providers/{provider['id']}/models", json={
        'model_id': 'synthetic', 'role_default': 'chat',
    }).status_code == 201


def topic(client, prefix='/api', request_id=None, content='quartz original conclusion'):
    paper = client.post(prefix + '/papers/manual', json={
        'title': 'quartz source', 'abstract': 'quartz evidence captured before later edits.',
    }).json()
    page = client.post(prefix + '/wiki/pages', json={
        'request_id': request_id or str(uuid4()), 'title': 'quartz topic',
    }).json()
    response = client.post(prefix + f"/wiki/pages/{page['id']}/revisions", json={
        'request_id': str(uuid4()), 'expected_version': page['version'], 'content': content,
        'paper_ids': [paper['id']], 'cite_added': True,
        'support_status': 'partial', 'review_note': '范围仍需核对',
    })
    assert response.status_code == 200, response.text
    page = response.json()
    response = client.post(prefix + f"/wiki/pages/{page['id']}/adopt", json={
        'expected_version': page['version'], 'number': 1,
    })
    assert response.status_code == 200, response.text
    return response.json()


def newer_revision(client, page, prefix='/api'):
    response = client.post(prefix + f"/wiki/pages/{page['id']}/revisions", json={
        'request_id': str(uuid4()), 'expected_version': page['version'],
        'content': 'quartz NEW CONCLUSION',
    })
    assert response.status_code == 200, response.text
    page = response.json()
    response = client.post(prefix + f"/wiki/pages/{page['id']}/adopt", json={
        'expected_version': page['version'], 'number': 2,
    })
    assert response.status_code == 200, response.text
    return response.json()


def result(response, suffix):
    assert response.status_code == 200, response.text
    if suffix.endswith('stream'):
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')][-1]
    return response.json()


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
@pytest.mark.parametrize('query', ['quartz', 'hello'])
def test_topic_from_grounding_or_tool_retains_snapshot_after_revision_and_archive(client, monkeypatch, suffix, query):
    configure(client, '/api')
    page = topic(client)
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    turns = iter([
        ToolTurn('', [ToolCall('wiki', 'search_topic_wiki', {'query': 'quartz'})], 1, 1, 2),
        ToolTurn('结论中没有生成任何来源链接。', [], 1, 1, 2),
    ])
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', lambda *a, **k: next(turns))
    cid = client.post('/api/chat/conversations').json()['id']
    response = result(client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': query}), suffix)
    assert response['sources'] == []  # Wiki must not become a paper-id capture option.
    sources = response['topic_sources']
    assert len(sources) == 1  # Grounding and tool retrieval deduplicate by version.
    source = sources[0]
    assert source['page_id'] == page['id'] and source['revision'] == 1
    assert source['workspace_id'] == 'legacy'
    assert source['url'] == f"?workspace=legacy#wiki?page={page['id']}&revision=1"
    assert source['support_status'] == 'partial' and source['review_note'] == '范围仍需核对'
    assert 'captured before' in source['evidence'][0]['quote']
    assert source['retrieved_by'] == ('turn_context' if query == 'quartz' else 'search_topic_wiki')
    page = newer_revision(client, page)
    assert client.patch('/api/wiki/pages/' + page['id'], json={
        'expected_version': page['version'], 'archived': True,
    }).status_code == 200
    restored = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert restored['topic_sources'] == sources
    assert restored['sources'] == []


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_failed_turn_reuses_original_wiki_version_and_evidence(client, monkeypatch, suffix):
    configure(client, '/api')
    page = topic(client)
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic temporary outage')
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', fail)
    cid = client.post('/api/chat/conversations').json()['id']
    client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'quartz'})
    user = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert user['delivery_status'] == 'failed'
    newer_revision(client, page)
    def complete(self, provider, model, messages, *args, **kwargs):
        prompt = json.dumps(messages)
        assert 'quartz original conclusion' in prompt and 'NEW CONCLUSION' not in prompt
        return ToolTurn('已完成。', [], 1, 1, 2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', complete)
    response = result(client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
        'content': 'quartz', 'retry_message_id': user['id'],
    }), suffix)
    assert response['topic_sources'] == user['topic_sources']
    assert response['topic_sources'][0]['revision'] == 1


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_clarification_carries_tool_topic_sources_across_resume(client, monkeypatch, suffix):
    configure(client, '/api')
    page = topic(client)
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    turns = iter([
        ToolTurn('', [ToolCall('wiki', 'search_topic_wiki', {'query': 'quartz'})], 1, 1, 2),
        ToolTurn('', [ToolCall('ask', 'ask_user', {
            'reason': '需要确认比较范围', 'questions': [{'question': '比较哪些条件？'}],
        })], 1, 1, 2),
    ])
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', lambda *a, **k: next(turns))
    cid = client.post('/api/chat/conversations').json()['id']
    question = result(client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'hello'}), suffix)
    assert len(question['topic_sources']) == 1
    newer_revision(client, page)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools',
                        lambda *a, **k: ToolTurn('按回答继续。', [], 1, 1, 2))
    response = result(client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
        'content': '比较实验条件', 'clarification_response': {
            'message_id': question['clarification']['message_id'], 'free_text': '比较实验条件',
        },
    }), suffix)
    assert response['topic_sources'] == question['topic_sources']


def test_identical_topic_ids_in_different_projects_keep_their_own_sources(client, monkeypatch):
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools',
                        lambda *a, **k: ToolTurn('已读取。', [], 1, 1, 2))
    shared_id = str(uuid4())
    ids = []
    for name in ('Project A', 'Project B'):
        workspace = client.post('/api/workspaces', json={'name': name}).json()
        ids.append(workspace['id'])
        prefix = '/api/w/' + workspace['id']
        configure(client, prefix)
        topic(client, prefix, shared_id, f'quartz {name} private conclusion')
        cid = client.post(prefix + '/chat/conversations').json()['id']
        body = result(client.post(prefix + f'/chat/conversations/{cid}/messages', json={'content': 'quartz'}), 'messages')
        assert len(body['topic_sources']) == 1
        source = body['topic_sources'][0]
        assert source['workspace_id'] == workspace['id'] and source['workspace_name'] == name
        assert source['page_id'] == shared_id
        assert name + ' private conclusion' in source['snippet']
        assert source['url'].startswith('?workspace=' + workspace['id'] + '#wiki')
    from app.agent.provenance import merge_sources
    merged = []
    merge_sources(merged, [{'source_type': 'topic_wiki', 'workspace_id': wid,
                           'page_id': shared_id, 'revision': 1} for wid in ids])
    assert len(merged) == 2
