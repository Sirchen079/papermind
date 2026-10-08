"""Agent writing remains usable across tools, failures, reloads and follow-ups."""
import copy
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Model, Provider, Paper
from app.providers.client import ToolCall, ToolTurn


def turn(content='', calls=()):
    return ToolTurn(content, list(calls), 3, 2, 5)


@pytest.fixture
def chat(client):
    with Session(get_engine()) as session:
        provider = Provider(name='progress-test', type='openai_chat')
        session.add(provider); session.commit(); session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id='test-model', role_default='chat'))
        session.add(Paper(id=1, source='manual', title='Study A'))
        session.commit()
    return client, client.post('/api/chat/conversations').json()['id']


def lookup():
    return ToolCall(id='lookup', name='list_concepts', arguments={})


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_visible_writing_and_saved_work_survive_reload_and_followup(chat, suffix):
    client, cid = chat
    draft = 'Comparison draft: identical retrieval conditions, different generators.'
    note = 'Detailed reading note with comparison conditions preserved.'
    first = turn(draft, [lookup()])
    first.reasoning_content = 'PRIVATE_REASONING_DO_NOT_PUBLISH'
    steps = [first, turn('', [ToolCall(id='save', name='save_paper_note',
             arguments={'paper_id': 1, 'content': note})]), turn('The material is above.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=steps):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Compare and save notes'})
    assert response.status_code == 200
    if suffix.endswith('stream'):
        assert response.text.index('event: update') < response.text.index('event: tool')
        assert 'PRIVATE_REASONING' not in response.text
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[0]['updates'] == [] and rows[0]['tools'] == []
    assert rows[-1]['updates'] == [{'content': draft}]
    assert rows[-1]['content'] == 'The material is above.'
    assert 'PRIVATE_REASONING' not in json.dumps(rows)
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Follow-up')) as model:
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Shorten that paragraph'})
    history = model.call_args.args[2]
    assistant = [m['content'] for m in history if m['role'] == 'assistant']
    assert any(draft in text for text in assistant)
    calls = [call for m in history for call in m.get('tool_calls', [])]
    assert len(calls) == 1 and json.loads(calls[0]['function']['arguments'])['content'] == note
    receipts = [m for m in history if m['role'] == 'tool']
    assert len(receipts) == 1 and receipts[0]['tool_call_id'] == calls[0]['id']
    assert '[已保存的研究成果]' not in '\n'.join(assistant)
    assert 'PRIVATE_REASONING' not in json.dumps(history)


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_failed_model_request_resumes_from_completed_tool_results(chat, suffix):
    client, cid = chat
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=[
        turn('A useful partial comparison.', [lookup()]), RuntimeError('503 unavailable')
    ]):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Compare'})
    assert response.status_code in {200, 500}
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['delivery_status'] == 'failed' and row['retryable'] and row['continuable']
    assert row['updates'] == [{'content': 'A useful partial comparison.'}]
    assert row['tools'][0]['name'] == 'list_concepts'
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Completed')) as model:
        retry = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
            'content': row['content'], 'retry_message_id': row['id']})
    assert retry.status_code == 200
    resumed = model.call_args.args[2]
    assert sum(m.get('role') == 'tool' for m in resumed) == 1
    assert any(m.get('tool_calls') for m in resumed)
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(rows) == 2 and rows[-1]['updates'] == row['updates']
    assert rows[-1]['content'] == 'Completed'


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_timeout_after_document_save_keeps_receipt_without_saving_again(chat, suffix):
    client, cid = chat
    save = ToolCall(id='save-before-timeout', name='save_document', arguments={
        'filename': 'timeout-note.md', 'content': 'Evidence collected before timeout.'})
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=[
        turn('', [save]), TimeoutError('Model connection timed out')
    ]):
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Write a note'})
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['continuable']
    receipt = json.loads(row['tools'][0]['result'])
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Your note is saved.')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={
            'content': row['content'], 'retry_message_id': row['id']})
    assert response.status_code == 200
    results = [m for m in model.call_args.args[2] if m.get('role') == 'tool']
    assert len(results) == 1 and json.loads(results[0]['content'])['filename'] == receipt['filename']
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(rows[-1]['tools']) == 1
    assert client.get(receipt['download_url']).text == 'Evidence collected before timeout.'


def test_first_request_failure_does_not_claim_tool_progress(chat):
    client, cid = chat
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=TimeoutError('No response')):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Start research'})
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['retryable'] and not row['continuable'] and row['tools'] == []


def test_clarification_preserves_writing_without_repeating_it_in_the_next_turn(chat):
    client, cid = chat
    ask = ToolCall(id='ask', name='ask_user', arguments={
        'questions': [{'question': 'Which comparison matters most?'}]})
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Initial comparison.', [ask])):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Compare'})
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[-1]['updates'] == [{'content': 'Initial comparison.'}]
    assert rows[-1]['clarification']['status'] == 'pending'
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Focused comparison.')) as model:
        client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Compare methods'})
    assert 'Initial comparison.' in json.dumps(model.call_args.args[2])
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[1]['updates'] == [{'content': 'Initial comparison.'}]
    assert rows[-1]['updates'] == []


def test_step_limit_continuation_keeps_journal_and_does_not_repeat_tools(chat):
    client, cid = chat
    with patch('app.api.chat_api._max_iters', return_value=1), patch(
        'app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Working draft.', [lookup()])
    ):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Compare'})
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['continuable'] and row['updates']
    captured = []
    def finish(*args, **kwargs):
        captured.append(copy.deepcopy(args[2])); return turn('Finished from prior lookup.')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=finish):
        response = client.post(f'/api/chat/conversations/{cid}/messages/stream', json={
            'content': row['content'], 'retry_message_id': row['id']})
    assert 'event: done' in response.text
    assert sum(m.get('role') == 'tool' for m in captured[0]) == 1
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[-1]['updates'] == row['updates'] and len(rows[-1]['tools']) == 1


def test_intermediate_writing_is_durable_before_the_next_model_request(chat):
    client, cid = chat
    calls = 0
    def complete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return turn('Already useful before completion.', [lookup()])
        row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
        assert row['delivery_status'] == 'pending'
        assert row['updates'] == [{'content': 'Already useful before completion.'}]
        assert row['tools'][0]['name'] == 'list_concepts'
        return turn('Done')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=complete):
        assert client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Compare'}).status_code == 200


def test_new_question_can_build_on_a_failed_turns_partial_work(chat):
    client, cid = chat
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=[
        turn('Partial draft worth keeping.\nSecond paragraph.', [lookup()]), RuntimeError('503 unavailable')
    ]):
        client.post(f'/api/chat/conversations/{cid}/messages/stream', json={'content': 'Compare'})
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=turn('Edited draft')) as model:
        client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Shorten what you have so far'})
    assert any('Partial draft worth keeping.\nSecond paragraph.' in m['content']
               for m in model.call_args.args[2] if m['role'] == 'assistant')


def test_followup_uses_latest_saved_document_and_excludes_failed_saves():
    from app.agent.presentation import research_messages
    tools = [dict(name='save_document', ok=True, args={'filename':'draft.md','content': body},
                  result=json.dumps({'ok': True, 'filename': 'draft.md'}))
             for body in ['Superseded old document', 'Latest visible document']]
    tools.append(dict(name='save_paper_note', ok=False, args={'content': 'Failed note'}, result='failed'))
    tools.append(dict(name='save_document', ok=True, args={'content': 'Incomplete save receipt'}, result='{"ok": true}'))
    messages = research_messages('Saved above.', {'tools': tools}, 17)
    history = json.dumps(messages)
    assert 'Latest visible document' in history
    assert 'Superseded old document' not in history and 'Failed note' not in history
    assert 'Incomplete save receipt' not in history
    assert len([m for m in messages if m['role'] == 'tool']) == 1
    assert messages == research_messages('Saved above.', {'tools': tools}, 17)


def test_prose_save_claim_never_becomes_a_tool_execution():
    from app.agent.presentation import research_messages
    prose = '[已保存的研究成果]\nNew draft\n[最终回复]\nSaved as imaginary.md'
    assert research_messages(prose, {}, 19) == [{'role':'assistant','content':prose}]


def test_recorded_save_survives_tool_unsupported_fallback():
    from app.agent.presentation import research_messages
    from app.agent.loop import run_agent
    from types import SimpleNamespace
    state = {'tools':[{'name':'save_document','ok':True,'args':{
        'filename':'existing.md','content':'Actual previously saved content'},
        'result':json.dumps({'ok':True,'filename':'existing.md'})}]}
    messages = [{'role':'system','content':'Help with research.'},
                {'role':'user','content':'Save this note.'},
                *research_messages('Saved.', state, 23),
                {'role':'user','content':'Discuss this note.'}]
    seen=[]
    def complete(provider, model, context, kind, **kwargs):
        seen.append(context)
        if kwargs['tools'] is not None:
            raise RuntimeError('tools are unsupported')
        assert all(m.get('role') != 'tool' and not m.get('tool_calls') for m in context)
        assert 'Actual previously saved content' in json.dumps(context)
        return turn('Discussion continues.')
    events = list(run_agent(SimpleNamespace(complete_with_tools=complete), None, 'plain',
                           messages, None, context_window=16000))
    assert len(seen) == 2 and events[-1][0] == 'done'
    assert not any(name == 'tool' for name, _ in events)
