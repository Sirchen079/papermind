from types import SimpleNamespace
from uuid import uuid4
import json
import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models.review import LibraryReview, ReviewRevision, ReviewPaper
from app.reviews import editing


def seed(client):
    rid=str(uuid4());text='# 综述\n\n相同段落😀 [P7]。\n\n## 比较\n\n相同段落😀 [P7]。\n\n末段保持原样。\n'
    with Session(get_engine()) as s:
        s.add(LibraryReview(id=rid,question='检索综述',content=text,version=1,status='ready'));s.flush()
        s.add(ReviewRevision(review_id=rid,version=1,content=text))
        s.add(ReviewPaper(review_id=rid,paper_id=7,title='Evidence',evidence_json=json.dumps([{'quote':'原始实验条件。'}])))
        s.commit()
    return '/api/reviews/'+rid,text


def test_unicode_duplicate_paragraph_patch_preserves_every_other_byte_and_restores(client):
    prefix,original=seed(client);data=client.get(prefix+'/paragraphs').json()
    block=[b for b in data['blocks'] if '相同' in b['text']][1]
    replacement='仅第二处被修改🧪 [P7]。'
    response=client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':block['id'],'replacement':replacement})
    assert response.status_code==200,response.text
    expected=original[:block['start']]+replacement+original[block['end']:]
    assert response.json()['content']==expected and response.json()['version']==2
    assert '\n\n'+replacement+'\n\n' in expected
    stale=client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':block['id'],'replacement':'stale'})
    assert stale.status_code==409
    restored=client.post(prefix+'/revisions/1/restore',json={'expected_version':2})
    assert restored.status_code==200 and restored.json()['version']==3 and restored.json()['content']==original
    assert client.get(prefix+'/revisions/2').json()['content']==expected
    assert client.post(prefix+'/revisions/2/restore',json={'expected_version':2}).status_code==409


def test_markdown_code_and_equation_blanks_are_not_split():
    text='intro\n\n```python\nx=1\n\nx+=2\n```\n\n$$\na+b\n\n=c\n$$\n\nend'
    blocks=editing.blocks(text,1)
    assert len(blocks)==4
    assert '\n\nx+=2' in blocks[1]['text'] and '\n\n=c' in blocks[2]['text']
    assert all(text[b['start']:b['end']]==b['text'] for b in blocks)


def test_proposal_is_not_saved_and_has_original_evidence(client,monkeypatch):
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    calls=[]
    def complete(*args,**kwargs):calls.append(args[2]);return SimpleNamespace(content='改写后的论点 [P7]。')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),SimpleNamespace(id=999),'fixture'))
    r=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'压缩这一段'})
    assert r.status_code==200,r.text
    assert r.json()['replacement']=='改写后的论点 [P7]。'
    assert '原始实验条件。' in calls[0][-1]['content']
    assert client.get(prefix).json()['content']==original
    assert client.get(prefix).json()['version']==1
    assert r.json()['skill']['id']=='nature/nature-writing'


def test_incomplete_proposal_is_returned_with_notice_and_can_be_applied(client,monkeypatch):
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    calls=[]
    def complete(*args,**kwargs):
        calls.append(True)
        return SimpleNamespace(content='已有部分修改 [P7]，但',output_incomplete=True)
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),SimpleNamespace(id=999),'fixture'))
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'核对原文'})
    assert response.status_code==200 and len(calls)==1
    draft=response.json()
    assert draft['replacement']=='已有部分修改 [P7]，但'
    assert '未完整返回' in draft['warning']
    assert client.get(prefix).json()['content']==original
    result=client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':block['id'],'replacement':draft['replacement']})
    assert result.status_code==200 and draft['replacement'] in result.json()['content']
    assert result.json()['version']==2


def test_running_write_and_cross_project_anchors_do_not_overwrite(client):
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    rid=prefix.rsplit('/',1)[1]
    with Session(get_engine()) as s:
        row=s.get(LibraryReview,rid);row.status='running';s.add(row);s.commit()
    assert client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':block['id'],'replacement':'bad'}).status_code==409
    assert client.post(prefix+'/revisions/1/restore',json={'expected_version':1}).status_code==409
    wid=client.post('/api/workspaces',json={'name':'Other'}).json()['id']
    assert client.get(f'/api/w/{wid}/reviews/{rid}/paragraphs').status_code==404
    assert client.get(prefix).json()['content']==original


@pytest.mark.parametrize('second',['complete','timeout','empty','short_partial'])
def test_exhausted_partial_edit_retries_once_and_retains_text_on_failure(client,monkeypatch,second):
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    partial='已经完成的论点与证据 [P7]，但后续'
    budgets=[]
    def complete(*args,**kwargs):
        budgets.append(kwargs['max_tokens'])
        if len(budgets)==1:return SimpleNamespace(content=partial,output_incomplete=True,output_exhausted=True)
        if second=='timeout':raise TimeoutError('test timeout')
        if second=='empty':return SimpleNamespace(content='')
        if second=='short_partial':return SimpleNamespace(content='更短的残稿',output_incomplete=True,output_exhausted=True)
        return SimpleNamespace(content='完整修正后的论点与证据 [P7]。')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),SimpleNamespace(id=999),'fixture'))
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'核对原文'})
    assert response.status_code==200,response.text
    assert len(budgets)==2 and budgets[1]>budgets[0]
    assert client.get(prefix).json()['content']==original
    draft=response.json()
    if second=='complete':
        assert draft['replacement']=='完整修正后的论点与证据 [P7]。' and draft['warning']==''
    else:
        assert draft['replacement']==partial and '未完整返回' in draft['warning']


def test_failed_model_leaves_original_and_manual_apply_available(client,monkeypatch):
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    def fail(*args,**kwargs):raise TimeoutError('fixture')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=fail),SimpleNamespace(id=999),'fixture'))
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'调整表述'})
    assert response.status_code==502
    assert client.get(prefix).json()['content']==original
    assert client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':block['id'],'replacement':'手工修改'}).status_code==200


def test_short_edit_on_large_context_does_not_request_huge_output(client,monkeypatch):
    from app.models import Provider, Model
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    with Session(get_engine()) as s:
        p=Provider(name='large-window',type='openai_responses',base_url='https://test.invalid')
        s.add(p);s.commit();s.refresh(p);pid=p.id
        s.add(Model(provider_id=pid,model_id='large',context_window=1048576));s.commit()
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs)
        assert block['text'] in args[2][-1]['content']
        assert kwargs['max_tokens']<=2000
        return SimpleNamespace(content='更清楚的表述 [P7]。')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),SimpleNamespace(id=pid),'large'))
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'压缩'})
    assert response.status_code==200 and len(calls)==1
    assert client.get(prefix).json()['content']==original


@pytest.mark.parametrize('exhausted',[True,False])
def test_high_effort_edit_recovers_only_from_reported_budget_exhaustion(client,monkeypatch,exhausted):
    from app.models import Provider, Model
    from app.providers.client import EmptyResponseError
    from app.agent.context import total_tokens
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    with Session(get_engine()) as s:
        p=Provider(name='thinking',type='openai_responses',base_url='https://test.invalid')
        s.add(p);s.commit();s.refresh(p);pid=p.id
        s.add(Model(provider_id=pid,model_id='thinking',context_window=32768,reasoning_effort='high'));s.commit()
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs['max_tokens'])
        assert total_tokens(args[2])+kwargs['max_tokens']<=32768
        assert block['text'] in args[2][-1]['content']
        assert '原始实验条件' in args[2][-1]['content']
        if len(calls)==1:raise EmptyResponseError('empty',output_exhausted=exhausted)
        return SimpleNamespace(content='恢复后的修改 [P7]。')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),SimpleNamespace(id=pid),'thinking'))
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':1,'block_id':block['id'],'instruction':'核对论断'})
    assert calls[0]>=8192+600
    assert response.status_code==(200 if exhausted else 502)
    assert len(calls)==(2 if exhausted else 1)
    if exhausted:assert calls[1]>calls[0]
    assert client.get(prefix).json()['content']==original


@pytest.mark.parametrize('failures',[1,2])
def test_paragraph_budget_survives_new_requests_without_changing_manuscript(client,monkeypatch,failures):
    from app.models import Provider,Model
    from app.providers.client import EmptyResponseError
    prefix,original=seed(client);block=client.get(prefix+'/paragraphs').json()['blocks'][1]
    with Session(get_engine()) as s:
        provider=Provider(name='writer',type='openai_responses',base_url='https://test.invalid')
        s.add(provider);s.commit();s.refresh(provider)
        config=Model(provider_id=provider.id,model_id='writer',context_window=1000000,reasoning_effort='high')
        s.add(config);s.commit();s.refresh(config);s.refresh(provider);mid=config.id
    caps=[]
    def complete(*args,**kwargs):
        caps.append(kwargs['max_tokens'])
        if len(caps)<=failures:raise EmptyResponseError('fixture',output_exhausted=True)
        return SimpleNamespace(content='完整的修改 [P7]。')
    monkeypatch.setattr(editing,'pick_llm',lambda *a:(SimpleNamespace(complete=complete),provider,'writer'))
    payload={'expected_version':1,'block_id':block['id'],'instruction':'核对原文'}
    first=client.post(prefix+'/paragraphs/propose',json=payload)
    assert first.status_code==(200 if failures==1 else 502)
    assert len(caps)==2 and caps[1]>caps[0]
    assert client.post(prefix+'/paragraphs/propose',json=payload).status_code==200
    assert len(caps)==3 and caps[2]>=caps[1]
    if failures==2:assert caps[2]>caps[1]
    assert client.get(prefix).json()['content']==original and client.get(prefix).json()['version']==1
    # The allowance belongs to this task and exact model configuration.
    other,_=seed(client);other_block=client.get(other+'/paragraphs').json()['blocks'][1]
    assert client.post(other+'/paragraphs/propose',json={**payload,'block_id':other_block['id']}).status_code==200
    assert caps[-1]==caps[0]
    with Session(get_engine()) as s:
        config=s.get(Model,mid);config.context_window=500000;s.add(config);s.commit()
    assert client.post(prefix+'/paragraphs/propose',json=payload).status_code==200
    assert caps[-1]==caps[0]
