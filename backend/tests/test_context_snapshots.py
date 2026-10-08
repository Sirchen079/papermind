import json
from unittest.mock import patch

from sqlmodel import Session

from app.agent.context_snapshots import coalesce_snapshots
from app.db.engine import get_engine
from app.models import Conversation, Message
from test_chat_api import _seed_chat_provider, _turn


def test_exact_material_coalesces_but_changed_conditions_and_short_headings_remain():
    common = 'Shared full paper excerpt with its original conditions. ' * 12
    old = 'Training uses 1000 samples; filtering follows. ' * 8
    new = old.replace('1000', '5000')
    snapshots = [(1, 'Title\n\n' + common + '\n\n' + old),
                 (3, 'Title\n\n' + common + '\n\n' + new),
                 (5, 'Title\n\n' + common)]
    result = coalesce_snapshots(snapshots)
    combined = '\n'.join(result.values())
    assert combined.count(common) == 1
    assert old in result[1] and new in result[3]
    assert all('Title' in text for text in result.values())
    assert '消息 #5' in result[1] and '消息 #5' in result[3]
    assert result[5].startswith('[消息 #5 的材料快照]')
    assert common in snapshots[0][1]  # originals remain unchanged
    assert coalesce_snapshots([(1, common)]) == {1: common}


def test_followup_keeps_user_revisions_questions_and_stored_snapshots(client, monkeypatch):
    _seed_chat_provider()
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    repeated = 'Original evidence with pages and uncertainty. ' * 20
    unique = 'Earlier unique observation with a different comparison condition.'
    monkeypatch.setattr('app.api.chat_api._turn_context', lambda *a, **k: repeated)
    with Session(get_engine()) as session:
        conv = Conversation(title='Continue research')
        session.add(conv); session.commit(); cid = conv.id
        first = Message(conversation_id=cid, role='user', content='Keep my research constraint',
                        model_context=repeated + '\n\n' + unique)
        revision = Message(conversation_id=cid, role='user', content='Use my corrected draft',
                           model_context=repeated, request_json=json.dumps({'document_revision': {'filename': 'user.md'}}))
        session.add_all([first, revision]); session.commit(); first_id = first.id
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Continued')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/messages', json={'content': 'Continue'})
    assert response.status_code == 200
    messages = model.call_args.args[2]
    texts = [m['content'] for m in messages]
    assert sum(repeated in text for text in texts) == 2  # current automatic context + untouched manual document
    assert any(unique in text and 'Keep my research constraint' in text for text in texts)
    assert any(repeated in text and 'Use my corrected draft' in text for text in texts)
    with Session(get_engine()) as session:
        assert session.get(Message, first_id).model_context == repeated + '\n\n' + unique
