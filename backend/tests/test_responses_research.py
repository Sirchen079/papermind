import pytest
pytestmark=pytest.mark.usefixtures("accept_evidence_review")

from types import SimpleNamespace

import httpx
import respx
from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Provider, TokenUsage
from app.providers.client import ProviderClient, _responses_text
from app.security.crypto import Crypto


def test_responses_only_returns_final_message():
    response = {'output': [
        {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'internal reasoning'}]},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Final answer'}]},
    ]}
    assert _responses_text(response) == 'Final answer'


@pytest.mark.parametrize('reason',['max_output_tokens','content_filter',None])
@pytest.mark.parametrize('text',['','可用的部分正文'])
def test_responses_empty_budget_metadata_keeps_nonempty_drafts(monkeypatch,reason,text):
    from app.providers.client import EmptyResponseError
    client=ProviderClient(lambda:None,Crypto(Fernet.generate_key()))
    recorded=[]
    monkeypatch.setattr(client,'_record_usage',lambda *a,**k:recorded.append(True))
    monkeypatch.setattr('app.providers.client.litellm.responses',lambda **k:SimpleNamespace(
        output_text=text,status='incomplete',incomplete_details={'reason':reason},
        usage=SimpleNamespace(input_tokens=10,output_tokens=600,total_tokens=610)))
    provider=Provider(name='test',type='openai_responses')
    if text:
        result=client.complete(provider,'fixture',[{'role':'user','content':'test'}],'library_review')
        assert result.content==text
        assert result.output_incomplete is True
        assert result.output_exhausted is (reason=='max_output_tokens')
    else:
        with pytest.raises(EmptyResponseError) as error:
            client.complete(provider,'fixture',[{'role':'user','content':'test'}],'library_review')
        assert error.value.output_exhausted==(reason=='max_output_tokens')
    assert recorded==[True]


def test_responses_input_and_usage(tmp_path, monkeypatch):
    engine = make_engine(tmp_path / 'response.sqlite')
    SQLModel.metadata.create_all(engine)
    crypto = Crypto(Fernet.generate_key())
    with Session(engine) as session:
        provider = Provider(name='synthetic', type='openai_responses', base_url='https://example.org/v1')
        session.add(provider)
        session.commit()
        session.refresh(provider)
    captured = {}
    def response(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_text='answer', usage=SimpleNamespace(input_tokens=17, output_tokens=23, total_tokens=40))
    monkeypatch.setattr('app.providers.client.litellm.responses', response)
    result = ProviderClient(lambda: Session(engine), crypto).complete(provider, 'glm-5.3', [{'role':'user','content':'test'}], 'research', max_tokens=1024, reasoning_effort='low')
    assert 'messages' not in captured
    assert captured['input'][0]['content'] == 'test'
    assert 'reasoning' not in captured  # Unknown model: use provider defaults.
    assert captured['max_output_tokens'] == 1024
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (17, 23, 40)
    with Session(engine) as session:
        usage = session.exec(select(TokenUsage)).one()
        assert usage.prompt_tokens == 17 and usage.completion_tokens == 23


@pytest.mark.parametrize('finish,exhausted',[('length',True),('stop',False),(None,False)])
def test_chat_partial_metadata_does_not_discard_text(monkeypatch,finish,exhausted):
    client=ProviderClient(lambda:None,Crypto(Fernet.generate_key()))
    monkeypatch.setattr(client,'_record_usage',lambda *a,**k:None)
    monkeypatch.setattr('app.providers.client.litellm.completion',lambda **k:SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='已有正文'),finish_reason=finish)],usage=None))
    result=client.complete(Provider(name='test',type='openai_compat',base_url='https://test.invalid/v1'),'fixture',
                           [{'role':'user','content':'draft'}],'library_review')
    assert result.content=='已有正文'
    assert result.output_incomplete is exhausted and result.output_exhausted is exhausted


@pytest.mark.parametrize('content',['','   '])
def test_chat_empty_exhausted_response_reports_recoverable_budget(monkeypatch,content):
    from app.providers.client import EmptyResponseError
    client=ProviderClient(lambda:None,Crypto(Fernet.generate_key()))
    recorded=[]
    monkeypatch.setattr(client,'_record_usage',lambda *a,**k:recorded.append(True))
    response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),finish_reason='length')],usage=None)
    monkeypatch.setattr('app.providers.client.litellm.completion',lambda **k:response)
    provider=Provider(name='test',type='openai_compat',base_url='https://test.invalid/v1')
    with pytest.raises(EmptyResponseError) as caught:
        client.complete(provider,'fixture',[{'role':'user','content':'draft'}],'library_review')
    assert caught.value.output_exhausted and len(recorded)==1
    # An empty response without exhaustion keeps its prior caller-handled path.
    response.choices[0].finish_reason='stop'
    result=client.complete(provider,'fixture',[{'role':'user','content':'draft'}],'library_review')
    assert not result.content.strip() and not result.output_exhausted


@respx.mock
def test_models_catalog_slug(tmp_path):
    respx.get('https://example.org/v1/models').respond(200, json={'models':[{'slug':'glm-5.3-flash','display_name':'Flash','context_window':1048576}]})
    client = ProviderClient(lambda: Session(make_engine(tmp_path/'x.sqlite')), Crypto(Fernet.generate_key()))
    models = client.list_models(Provider(name='test',type='openai_responses',base_url='https://example.org/v1'))
    assert models[0].model_id == 'glm-5.3-flash'
    assert models[0].context_window == 1048576


def test_responses_tool_roundtrip_stays_on_responses(tmp_path,monkeypatch):
    crypto=Crypto(Fernet.generate_key())
    client=ProviderClient(lambda:None,crypto)
    monkeypatch.setattr(client,'_record_usage',lambda *args,**kwargs:None)
    captured={}
    def response(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output=[{'type':'function_call','call_id':'next-call','name':'read','arguments':'{"id":2}'}],usage=SimpleNamespace(input_tokens=9,output_tokens=4,total_tokens=13))
    monkeypatch.setattr('app.providers.client.litellm.responses',response)
    provider=Provider(name='test',type='openai_responses')
    result=client.complete_with_tools(provider,'glm-5.3',[
        {'role':'user','content':'read'},
        {'role':'assistant','content':None,'tool_calls':[{'id':'prev-call','function':{'name':'read','arguments':'{"id":1}'}}]},
        {'role':'tool','tool_call_id':'prev-call','content':'done'}
    ],'chat',tools=[{'type':'function','function':{'name':'read','parameters':{'type':'object'}}}])
    assert captured['input'][-1]=={'type':'function_call_output','call_id':'prev-call','output':'done'}
    assert captured['tools'][0]['name']=='read'
    assert 'messages' not in captured
    assert result.tool_calls[0].id=='next-call' and result.tool_calls[0].arguments=={'id':2}
