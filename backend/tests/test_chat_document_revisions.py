import json
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlmodel import Session,select
from app.models import Conversation,Message,Paper
from app.db.engine import get_engine
from app.config import get_settings
from app.agent.research_actions import save_document
from test_chat_api import _seed_chat_provider,_turn


def seed():
    with Session(get_engine()) as s:
        c=Conversation(title='Comparison');p=Paper(source='manual',title='Study')
        s.add_all([c,p]);s.commit()
        raw=save_document(s,'comparison.md','Original incorrect draft.')
        tool={'name':'save_document','args':{'filename':'comparison.md','content':'Original incorrect draft.'},'result':raw,'ok':True}
        m=Message(conversation_id=c.id,role='assistant',content='Saved original.',agent_state_json=json.dumps({'tools':[tool]}),
            sources_json=json.dumps([{'paper_id':p.id,'title':p.title,'snippet':'source excerpt','pages':[14]}]))
        s.add(m);s.commit()
        return c.id,m.id,tool


@pytest.mark.parametrize('suffix',['messages','messages/stream'])
def test_manual_revision_keeps_original_and_is_a_user_correction_in_followup(client,monkeypatch,suffix):
    _seed_chat_provider();monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    cid,origin_id,tool=seed();corrected='RJ: samples from three datasets, then filtering.\nQR: separate annotated training set.'
    with patch('app.providers.client.ProviderClient.complete_with_tools') as model:
        r=client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'comparison.md','content':corrected})
    assert r.status_code==200 and model.call_count==0
    revision=r.json();assert revision['filename']!='comparison.md'
    root=Path(get_settings().data_dir)/'exports'
    assert (root/'comparison.md').read_text(encoding='utf-8')=='Original incorrect draft.'
    assert (root/revision['filename']).read_text(encoding='utf-8')==corrected
    assert client.get(revision['download_url']).text.replace('\r\n','\n')==corrected
    rows=client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert rows[0]['tools']==[tool]
    assert rows[-1]['role']=='user' and rows[-1]['document_revision']['content']==corrected
    assert rows[-1]['sources'][0]['carried_from_message']==origin_id
    assert not rows[-1]['retryable']
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Continued from user revision.')) as model:
        response=client.post(f'/api/chat/conversations/{cid}/{suffix}',json={'content':'Continue from my revision'})
    assert response.status_code==200
    turns=model.call_args.args[2]
    corrected_messages=[m for m in turns if corrected in m.get('content','')]
    assert len(corrected_messages)==1 and corrected_messages[0]['role']=='user'
    assert '用户修订稿为准' in corrected_messages[0]['content']


def test_retry_is_idempotent_and_revised_version_can_be_edited_again(client):
    cid,_,_=seed()
    url=f'/api/chat/conversations/{cid}/documents/revisions'
    body={'filename':'comparison.md','content':'First manual correction.'}
    a=client.post(url,json=body).json();b=client.post(url,json=body).json()
    assert a==b
    c=client.post(url,json={'filename':a['filename'],'content':'Second manual correction.'})
    assert c.status_code==200 and c.json()['filename']!=a['filename']
    rows=client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert len(rows)==3 and rows[-1]['document_revision']['parent_filename']==a['filename']


def test_unrelated_document_and_failed_save_do_not_append_a_revision(client):
    cid,_,_=seed();other=client.post('/api/chat/conversations').json()['id']
    assert client.post(f'/api/chat/conversations/{other}/documents/revisions',json={'filename':'comparison.md','content':'Oops'}).status_code==404
    assert client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'../comparison.md','content':'Oops'}).status_code==404
    assert client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'comparison.md','content':' '}).status_code==422
    with patch('app.agent.document_revisions.save_document',side_effect=OSError('disk unavailable')):
        r=client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'comparison.md','content':'Retain my draft'})
    assert r.status_code==500
    assert len(client.get(f'/api/chat/conversations/{cid}').json()['messages'])==1


@pytest.mark.parametrize('cached',[False,True])
def test_edit_does_not_remove_failed_turn_retry_and_retry_reads_the_correction(client,monkeypatch,cached):
    _seed_chat_provider();monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    cid,_,_=seed()
    with Session(get_engine()) as s:
        pending=Message(conversation_id=cid,role='user',content='Continue research',delivery_status='failed',
            request_json=json.dumps({'content':'Continue research'}),
            agent_state_json=json.dumps({'messages':[{'role':'system','content':'Research assistant'},{'role':'user','content':'Continue research'}]}) if cached else None)
        s.add(pending);s.commit();pending_id=pending.id
    correction='USER CORRECTION: different training datasets and filtering.'
    client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'comparison.md','content':correction})
    rows=client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert next(row for row in rows if row['id']==pending_id)['retryable']
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Resumed')) as model:
        r=client.post(f'/api/chat/conversations/{cid}/messages',json={'content':'Continue research','retry_message_id':pending_id})
    assert r.status_code==200
    assert sum(correction in m.get('content','') for m in model.call_args.args[2])==1


def test_edit_does_not_consume_pending_clarification_and_answer_includes_revision(client,monkeypatch):
    from app.providers.client import ToolTurn,ToolCall
    _seed_chat_provider();monkeypatch.setattr('app.rag.index.retrieve',lambda *a,**k:[])
    cid,_,_=seed()
    ask=ToolCall('ask','ask_user',{'questions':[{'question':'Which scope?'}]})
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=ToolTurn('',[ask],1,1,2)):
        client.post(f'/api/chat/conversations/{cid}/messages',json={'content':'Plan comparison'})
    question=client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    correction='Manual revision before answering the scope question.'
    client.post(f'/api/chat/conversations/{cid}/documents/revisions',json={'filename':'comparison.md','content':correction})
    with patch('app.providers.client.ProviderClient.complete_with_tools',return_value=_turn('Continued')) as model:
        r=client.post(f'/api/chat/conversations/{cid}/messages',json={'content':'Black-box only','clarification_response':{'message_id':question['id'],'free_text':'Black-box only'}})
    assert r.status_code==200
    prompt=model.call_args.args[2]
    assert any(m['role']=='tool' and 'Black-box only' in m['content'] for m in prompt)
    assert any(m['role']=='user' and correction in m['content'] for m in prompt)


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_custom_revision_notice_keeps_exact_identity_and_adoption_in_model_context(client, monkeypatch, suffix):
    """Audit notices need not repeat filenames; identity cannot depend on prose."""
    from app.agent.document_revisions import save_revision
    _seed_chat_provider()
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    cid, mid, _ = seed()
    body = 'Established: use paired seeds. Undecided: noise levels. This is a review draft.'
    notice = 'Saved an independent audit for discussion; the researcher has not adopted it.'
    with Session(get_engine()) as session:
        revision = save_revision(session, session.get(Conversation, cid), session.get(Message, mid),
            'comparison.md', body, note=notice,
            extra={'audit_author': 'Codex', 'adoption_status': 'not_user_adopted'})
        original = session.get(Message, revision['message_id']).model_dump()
    with patch('app.providers.client.ProviderClient.complete_with_tools', return_value=_turn('Discussion outline')) as model:
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Compress the saved audit'})
    assert response.status_code == 200
    turns = model.call_args.args[2]
    provided = [m['content'] for m in turns if body in str(m.get('content', ''))]
    assert len(provided) == 1
    assert f'message_id={revision["message_id"]}; filename={revision["filename"]}' in provided[0]
    assert '"parent_message_id": ' + str(mid) in provided[0]
    assert 'not_user_adopted' in provided[0] and 'Codex' in provided[0]
    assert notice in provided[0] and provided[0].endswith(body)
    assert '[本轮用户问题]' not in provided[0]
    with Session(get_engine()) as session:
        assert session.get(Message, revision['message_id']).model_dump() == original


def test_resuming_with_custom_audit_uses_same_version_context_once(client):
    from app.agent.document_revisions import public_revision, revision_context, resume_with_revisions, save_revision
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        revision = save_revision(session, session.get(Conversation, cid), session.get(Message, mid),
            'comparison.md', 'Correction and remaining questions.', note='Audit saved.',
            extra={'adoption_status': 'not_user_adopted'})
        row = session.get(Message, revision['message_id'])
        state = {'messages': [{'role': 'user', 'content': 'Continue original task'}]}
        resumed = resume_with_revisions(session, cid, mid, state)
        assert resumed['messages'][-1]['content'] == revision_context(row, public_revision(row))
        assert resume_with_revisions(session, cid, mid, resumed) == resumed


def test_revision_context_retains_distinct_branches_without_choosing_latest(client):
    from app.agent.document_revisions import public_revision, revision_context, save_revision
    cid, mid, _ = seed()
    with Session(get_engine()) as session:
        origin = session.get(Message, mid)
        for body in ('Branch A: fixed budget.', 'Branch B: adaptive budget.'):
            saved = save_revision(session, session.get(Conversation, cid), origin, 'comparison.md', body,
                note='Alternative saved for comparison.')
            row = session.get(Message, saved['message_id'])
            text = revision_context(row, public_revision(row))
            assert text.endswith(body) and f'filename={saved["filename"]}' in text
            assert json.dumps({'parent_message_id': mid})[1:-1] in text
