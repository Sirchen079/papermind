import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.agent.document_edits import propose_document_edit
from app.agent.document_revisions import public_revision
from app.agent.research_actions import save_document
from app.config import get_settings
from app.db.engine import get_engine
from app.models import Conversation, Message, Paper
from app.providers.client import ToolCall
from test_chat_api import _seed_chat_provider, _turn

BODY='# Research note\n\n**Speed:** Always faster.\n\nKeep this paragraph and [P1] unchanged.\n'
BEFORE='**Speed:** Always faster.'
AFTER='**Speed:** Relative latency remains to be measured.'


def seed_source(content=BODY):
    with Session(get_engine()) as s:
        conv=Conversation(title='Original research');paper=Paper(source='manual',title='Original study')
        s.add_all([conv,paper]);s.commit()
        result=save_document(s,'research.md',content)
        source={'paper_id':paper.id,'title':paper.title,'source_type':'full_text','excerpt':'The experiment used a specific workload.','pages':[14]}
        message=Message(conversation_id=conv.id,role='assistant',content='Saved.',sources_json=json.dumps([source]),
            agent_state_json=json.dumps({'tools':[{'name':'save_document','ok':True,'args':{'filename':'research.md','content':content},'result':result}]}))
        s.add(message);s.commit();s.refresh(message)
        return conv.id,message.id


def save_proposal(mid,*,cid=None,before=BEFORE,after=AFTER,start_char=None):
    args={'message_id':mid,'filename':'research.md','before':before,'after':after,'reason':'Compare measured conditions.'}
    if start_char is not None:args['start_char']=start_char
    with Session(get_engine()) as s:
        if cid is None:
            conv=Conversation(title='Follow-up');s.add(conv);s.commit();cid=conv.id
        result=propose_document_edit(s,**args)
        parsed=json.loads(result);assert parsed['ok']
        extra={'source_type':'web','snapshot_id':'new-web-evidence','url':'https://example.org/method','title':'Author method','excerpt':'Measured under this workload.','retrieved_at':'2026-09-26T00:00:00Z'}
        row=Message(conversation_id=cid,role='assistant',content='Suggested edit.',sources_json=json.dumps([extra]),
            agent_state_json=json.dumps({'tools':[{'name':'propose_document_edit','ok':True,'args':args,'result':result}]}))
        s.add(row);s.commit()
        return cid,parsed['proposal_id'],args


def apply(client,cid,pid,replacement=AFTER):
    return client.post(f'/api/chat/conversations/{cid}/documents/proposals/{pid}/apply',json={'replacement':replacement})


def test_propose_only_and_apply_edited_suggestion_preserves_rest_sources_and_retry(client):
    _,mid=seed_source();root=Path(get_settings().data_dir)/'exports'
    old=(root/'research.md').read_bytes();old_files=list(root.iterdir())
    cid,pid,_=save_proposal(mid)
    assert (root/'research.md').read_bytes()==old and list(root.iterdir())==old_files
    assert apply(client,cid,pid,BEFORE).status_code==422
    assert len(client.get('/api/chat/saved-documents').json()['items'])==1
    replacement='**Speed:** Measure relative latency on our own workload.'
    first=apply(client,cid,pid,replacement);assert first.status_code==200
    data=first.json();assert data['content']==BODY.replace(BEFORE,replacement)
    assert data['revision_kind']=='accepted_suggestion' and data['parent_filename']=='research.md'
    assert data['filename']!='research.md' and (root/'research.md').read_bytes()==old
    assert (root/data['filename']).read_text(encoding='utf-8')==data['content']
    assert apply(client,cid,pid,replacement).json()==data
    history=client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(history)==2 and history[-1]['document_revision']['proposal_id']==pid
    assert history[-1]['sources'][0]['pages']==[14]
    assert history[-1]['web_sources'][0]['snapshot_id']=='new-web-evidence'
    catalog=client.get('/api/chat/saved-documents').json()['items']
    assert len(catalog)==1 and catalog[0]['filename']==data['filename'] and catalog[0]['author']=='user'


def test_repeated_text_requires_a_location_but_can_target_one_occurrence(client):
    body='Top\nRepeated claim.\nMiddle\nRepeated claim.\nBottom'
    _,mid=seed_source(body)
    with Session(get_engine()) as s:
        assert 'error' in json.loads(propose_document_edit(s,mid,'research.md','Repeated claim.','Corrected claim.'))
    position=body.rfind('Repeated claim.')
    cid,pid,_=save_proposal(mid,before='Repeated claim.',after='Corrected claim.',start_char=position)
    response=apply(client,cid,pid,'Corrected claim.')
    assert response.status_code==200
    assert response.json()['content']==body[:position]+body[position:].replace('Repeated claim.','Corrected claim.',1)


def test_separate_suggestions_accumulate_in_the_latest_adopted_version(client):
    _,mid=seed_source()
    cid,first_id,_=save_proposal(mid)
    second_before='Keep this paragraph'
    second_after='Keep this corrected paragraph'
    _,second_id,_=save_proposal(mid,cid=cid,before=second_before,after=second_after)
    first=apply(client,cid,first_id).json()
    second=apply(client,cid,second_id,second_after)
    assert second.status_code==200
    expected=BODY.replace(BEFORE,AFTER).replace(second_before,second_after)
    assert second.json()['content']==expected
    assert second.json()['root_filename']=='research.md'
    assert len(second.json()['filename'])==len(first['filename'])
    root=Path(get_settings().data_dir)/'exports'
    assert (root/'research.md').read_text(encoding='utf-8')==BODY
    assert (root/first['filename']).read_text(encoding='utf-8')==first['content']
    count=len(client.get(f'/api/chat/conversations/{cid}').json()['messages'])
    assert apply(client,cid,first_id).json()==first
    assert len(client.get(f'/api/chat/conversations/{cid}').json()['messages'])==count


@pytest.mark.parametrize('reverse',[False,True])
def test_multiple_adoptions_keep_explicit_duplicate_occurrences_separate(client,reverse):
    body='Top\nRepeated claim.\nMiddle\nRepeated claim.\nBottom'
    _,mid=seed_source(body)
    cid,first_id,_=save_proposal(mid,before='Repeated claim.',after='First corrected claim is longer.',start_char=body.find('Repeated claim.'))
    _,second_id,_=save_proposal(mid,cid=cid,before='Repeated claim.',after='Second correction.',start_char=body.rfind('Repeated claim.'))
    changes=[(first_id,'First corrected claim is longer.'),(second_id,'Second correction.')]
    if reverse:changes.reverse()
    for pid,replacement in changes:
        result=apply(client,cid,pid,replacement)
        assert result.status_code==200
    assert result.json()['content']=='Top\nFirst corrected claim is longer.\nMiddle\nSecond correction.\nBottom'


def test_adoption_preserves_manual_revision_and_rebases_after_insertions(client):
    _,mid=seed_source();cid,pid,_=save_proposal(mid)
    manual='New introduction.\n\n'+BODY.replace('Keep this paragraph','Keep my own clarification')
    # A revision of a document in the original conversation can be used there.
    with Session(get_engine()) as s:
        origin=s.get(Message,mid)
        source_cid=origin.conversation_id
    _,pid,_=save_proposal(mid,cid=source_cid)
    edited=client.post(f'/api/chat/conversations/{source_cid}/documents/revisions',json={'filename':'research.md','content':manual})
    assert edited.status_code==200
    adopted=apply(client,source_cid,pid)
    assert adopted.status_code==200
    assert adopted.json()['content']==manual.replace(BEFORE,AFTER)
    assert adopted.json()['parent_filename']==edited.json()['filename']


def test_adoption_does_not_revert_an_already_changed_target(client):
    cid,mid=seed_source();_,pid,_=save_proposal(mid,cid=cid)
    manual=BODY.replace(BEFORE,'**Speed:** My revised observation.')
    edited=client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'research.md','content':manual})
    assert edited.status_code==200
    assert apply(client,cid,pid).status_code==409
    latest=client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert latest['document_revision']['content']==manual


def test_missing_or_changed_source_and_wrong_conversation_keep_original(client):
    _,mid=seed_source();cid,pid,_=save_proposal(mid)
    other=client.post('/api/chat/conversations').json()['id']
    assert apply(client,other,pid).status_code==404
    with Session(get_engine()) as s:
        source=s.get(Message,mid);state=json.loads(source.agent_state_json)
        state['tools'][0]['args']['content']=BODY+'Additional material.'
        source.agent_state_json=json.dumps(state);s.add(source);s.commit()
    assert apply(client,cid,pid).status_code==409
    assert (Path(get_settings().data_dir)/'exports/research.md').read_text(encoding='utf-8')==BODY
    with Session(get_engine()) as s:s.delete(s.get(Message,mid));s.commit()
    assert apply(client,cid,pid).status_code==409


def test_failed_save_can_retry_and_empty_replacement_can_delete_a_passage(client,monkeypatch):
    _,mid=seed_source();cid,pid,_=save_proposal(mid)
    with patch('app.agent.document_revisions.save_document',side_effect=PermissionError('synthetic disk failure')):
        assert apply(client,cid,pid,'').status_code==500
    assert len(client.get(f'/api/chat/conversations/{cid}').json()['messages'])==1
    response=apply(client,cid,pid,'');assert response.status_code==200
    assert response.json()['content']==BODY.replace(BEFORE,'')


@pytest.mark.parametrize('suffix',['messages','messages/stream'])
def test_real_tool_proposal_is_persisted_and_can_be_adopted_from_another_conversation(client,monkeypatch,suffix):
    _seed_chat_provider();_,mid=seed_source()
    monkeypatch.setattr('app.api.chat_api._retrieve_hits',lambda *a,**k:[])
    cid=client.post('/api/chat/conversations').json()['id']
    args={'message_id':mid,'filename':'research.md','before':BEFORE,'after':AFTER,'reason':'Only local changes.'}
    with patch('app.providers.client.ProviderClient.complete_with_tools',side_effect=[_turn('',[ToolCall('edit','propose_document_edit',args)]),_turn('Please review the proposed change.')]):
        assert client.post(f'/api/chat/conversations/{cid}/{suffix}',json={'content':'Suggest a local revision'}).status_code==200
    history=client.get(f'/api/chat/conversations/{cid}').json()['messages']
    tool=history[-1]['tools'][0];result=json.loads(tool['result'])
    assert len(tool['result'])<800 and result['applied'] is False
    assert apply(client,cid,result['proposal_id']).status_code==200
    # The adopted version is passed into subsequent research as user material.
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Continue from the accepted version.')) as model:
        client.post(f'/api/chat/conversations/{cid}/messages',json={'content':'Continue'})
    assert any(m['role']=='user' and AFTER in str(m['content']) for m in model.call_args.args[2])
