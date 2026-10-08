import copy
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select
from app.models import Conversation, Message, Paper
from app.db.engine import get_engine
from app.agent.source_memory import carry_sources, read_chat_sources
from app.agent.source_passages import paper_source
from app.agent.context import estimate_tokens
from app.agent.provenance import tool_sources
from app.providers.client import ToolCall, ToolTurn
from test_chat_api import _seed_chat_provider, _turn


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_followup_receives_saved_original_passage_and_returns_its_pages(client, monkeypatch, suffix):
    _seed_chat_provider()
    original = '<!-- page:23 -->\nFixed retriever.\nThe authors propose a possible explanation; it is not a demonstrated cause.'
    with Session(get_engine()) as s:
        p = Paper(source='manual', title='Original study', full_text=original)
        s.add(p); s.commit(); pid = p.id
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    cid = client.post('/api/chat/conversations').json()['id']
    first = [ToolTurn('', [ToolCall('read', 'get_paper_full_text', {'paper_id': pid})], 1, 1, 2), _turn('Initial draft.')]
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=first):
        client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Read the study'})
    first_answer = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    with Session(get_engine()) as s:
        p = s.get(Paper, pid); p.full_text = 'A newer paper revision.'; s.add(p); s.commit()
    captured = []
    def complete(*args, **kwargs):
        captured.append(copy.deepcopy(args[2])); return _turn('Shortened draft.')
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=complete):
        for question in ['Shorten that draft', 'Shorten it again']:
            response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': question})
            assert response.status_code == 200
    for prompt in captured:
        encoded = json.dumps(original, ensure_ascii=False)
        assert encoded in prompt[-1]['content']
        assert sum(m['content'].count(encoded) for m in prompt if isinstance(m['content'], str)) == 1
        assert 'A newer paper revision.' not in prompt[-1]['content']
    rows = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[3]['sources'][0]['carried_from_message'] == first_answer['id']
    assert rows[-1]['sources'][0]['pages'] == [23]
    assert rows[-1]['sources'][0]['excerpt'] == original


def seed_snapshots(session, text):
    a = Conversation(title='A'); b = Conversation(title='B'); p = Paper(source='manual', title='Study', full_text='current revision')
    session.add_all([a,b,p]); session.commit()
    source = paper_source(p.id,p.title,text,'full_text','get_paper_full_text',[23,24])
    old = Message(conversation_id=a.id,role='assistant',content='Earlier draft',sources_json=json.dumps([source]))
    session.add(old);session.commit()
    current = Message(conversation_id=a.id,role='user',content='Continue')
    session.add(current);session.commit()
    return a,b,p,old,current


def test_large_snapshot_stays_complete_and_addressable_in_a_small_window(client):
    text = 'BEGIN ' + 'original conditions ' * 1000 + ' IMPORTANT END'
    with Session(get_engine()) as s:
        a,b,p,old,current = seed_snapshots(s,text)
        block,carried = carry_sources(s,a.id,current.id,None,500)
        assert estimate_tokens(block) <= 500 and not carried
        assert 'read_chat_sources' in block and 'source_index' in block
        assert 'BEGIN' not in block  # No misleading half-quote is carried automatically.
        s.info['chat_conversation_id'] = a.id
        first = json.loads(read_chat_sources(s,old.id,0,0,800))
        second = json.loads(read_chat_sources(s,old.id,0,first['next_start_char'],800))
        assert first['text']+second['text'] == text[:1600]
        assert first['pages'] == [23,24]
        assert tool_sources(s,'read_chat_sources',json.dumps(first))[0]['carried_from_message'] == old.id
        assert tool_sources(s,'read_chat_sources',read_chat_sources(s,old.id,0,999999)) == []
        s.info['chat_conversation_id'] = b.id
        assert 'error' in json.loads(read_chat_sources(s,old.id,0))
        assert carry_sources(s,b.id,current.id,None,500) == ('',[])


def test_scope_removed_papers_and_no_available_space_do_not_add_material(client):
    with Session(get_engine()) as s:
        a,b,p,old,current = seed_snapshots(s,'Complete original evidence.')
        assert carry_sources(s,a.id,current.id,[],500) == ('',[])
        assert carry_sources(s,a.id,current.id,None,0) == ('',[])
        p.is_deleted=True;s.add(p);s.commit()
        assert carry_sources(s,a.id,current.id,None,500) == ('',[])


def test_recent_reading_fits_before_exploration_without_hiding_other_sources(client):
    with Session(get_engine()) as s:
        a,b,p,old,current = seed_snapshots(s,'Early exploratory material. ' * 140)
        rows=json.loads(old.sources_json)
        latest='Final comparison with its conditions and uncertainty. ' * 110
        rows.append(paper_source(p.id,p.title,latest,'full_text','get_paper_full_text',[23,24]))
        old.sources_json=json.dumps(rows);s.add(old);s.commit()
        block,carried=carry_sources(s,a.id,current.id,None,2000)
        assert estimate_tokens(block)<=2000
        assert len(carried)==1 and carried[0]['excerpt']==latest
        records=[json.loads(line) for line in block.splitlines()[2:]]
        assert {row['source_index'] for row in records}=={0,1}
        assert 'excerpt' not in next(row for row in records if row['source_index']==0)
        s.info['chat_conversation_id']=a.id
        assert json.loads(read_chat_sources(s,old.id,0))['text']==rows[0]['excerpt']


def test_retry_preserves_the_exact_source_context_even_if_the_previous_record_changes(client,monkeypatch):
    _seed_chat_provider();monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    with Session(get_engine()) as s:
        a,b,p,old,current = seed_snapshots(s,'Immutable original excerpt.')
        s.delete(current);s.commit();cid=a.id;old_id=old.id
    captured=[]
    def fail(*args,**kwargs):
        captured.append(copy.deepcopy(args[2]));raise RuntimeError('503 unavailable')
    with patch('app.providers.client.ProviderClient.complete_with_tools',side_effect=fail):
        client.post(f'/api/chat/conversations/{cid}/messages/stream',json={'content':'Shorten'})
    row=client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    with Session(get_engine()) as s:
        old=s.get(Message,old_id);old.sources_json='[]';s.add(old);s.commit()
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Finished')) as model:
        response=client.post(f'/api/chat/conversations/{cid}/messages',json={'content':row['content'],'retry_message_id':row['id']})
    assert response.status_code==200 and model.call_args.args[2]==captured[0]
    assert response.json()['sources'][0]['excerpt']=='Immutable original excerpt.'


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_optional_evidence_review_receives_the_carried_original(client,monkeypatch,suffix):
    _seed_chat_provider();monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    original='The improvement may result from joint training;\nthis is an author hypothesis.'
    with Session(get_engine()) as s:
        a,b,p,old,current=seed_snapshots(s,original)
        s.delete(current);s.commit();cid=a.id
    def review(client,provider,model,question,draft,evidence,context_window=None):
        assert original in '\n'.join(row['text'] for row in evidence)
        return draft,0,{'edits':[]}
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Short note.')), \
         patch('app.agent.loop.review_answer',side_effect=review) as checker:
        response=client.post(f'/api/chat/conversations/{cid}/{suffix}',json={'content':'Shorten','review_evidence':True})
    assert response.status_code==200 and checker.call_count==1
    assert client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]['content']=='Short note.'
