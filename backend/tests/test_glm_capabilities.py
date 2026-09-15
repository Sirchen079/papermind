from types import SimpleNamespace
import pytest
from app.models import Provider
from app.providers.client import ProviderClient
from app.providers.capabilities import reasoning_options,known_context_window
from app.agent.loop import _assistant_msg
from app.agent.context import total_tokens

def provider(host='open.bigmodel.cn'):
    return Provider(id=1,name='test',type='openai_chat',base_url='https://'+host+'/api/coding/paas/v4')

def test_documented_reasoning_survives_missing_sdk_catalog(monkeypatch):
    sent=[]
    monkeypatch.setattr('litellm.supports_reasoning',lambda **k:False)
    def completion(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='answer',reasoning_content='private protocol state',tool_calls=[]))],usage=None)
    monkeypatch.setattr('litellm.completion',completion)
    c=ProviderClient(None,None)
    monkeypatch.setattr(c,'_record_usage',lambda *a,**k:None)
    c.complete(provider(),'glm-5.3',[{'role':'user','content':'q'}],'research',reasoning_effort='low',max_tokens=2000)
    assert sent[0]['extra_body']['reasoning_effort']=='low'
    assert sent[0]['extra_body']['thinking']=={'type':'enabled','clear_thinking':True}
    turn=c.complete_with_tools(provider(),'glm-5.3',[{'role':'user','content':'q'}],'chat')
    message=_assistant_msg(turn)
    assert message['reasoning_content']=='private protocol state'
    c.complete_with_tools(provider(),'glm-5.3',[message,{'role':'user','content':'next'}],'chat')
    assert sent[-1]['messages'][0]['reasoning_content']=='private protocol state'
    assert total_tokens([message])>total_tokens([{'role':'assistant','content':'answer'}])

@pytest.mark.parametrize('host',['open.bigmodel.cn.evil.example','proxy.example','api.openai.com'])
def test_vendor_options_never_leak_to_other_endpoints(host):
    assert reasoning_options(provider(host),'glm-5.3','low')=={}
    assert known_context_window(provider(host),'glm-5.3') is None

def test_known_window_and_unsupported_effort():
    assert known_context_window(provider(),'glm-5.3')==1_000_000
    with pytest.raises(ValueError):reasoning_options(provider(),'glm-5.3','medium')


@pytest.mark.parametrize('kind,timeout',[('evidence_review',300),('wiki_update',180),('research',90)])
def test_background_generation_has_bounded_network_wait(monkeypatch,kind,timeout):
    sent=[]
    def completion(**kwargs):
        sent.append(kwargs)
        raise TimeoutError('synthetic provider timeout')
    monkeypatch.setattr('litellm.completion',completion)
    c=ProviderClient(None,None)
    with pytest.raises(TimeoutError):
        c.complete(provider(),'glm-5.3',[{'role':'user','content':'q'}],kind)
    assert len(sent)==1 and sent[0]['timeout']==timeout and sent[0]['num_retries']==0


def test_agent_tool_step_has_bounded_network_wait(monkeypatch):
    sent=[]
    def completion(**kwargs):
        sent.append(kwargs)
        raise TimeoutError('synthetic provider timeout')
    monkeypatch.setattr('litellm.completion',completion)
    with pytest.raises(TimeoutError):
        ProviderClient(None,None).complete_with_tools(provider(),'glm-5.3',[{'role':'user','content':'q'}],'chat')
    assert len(sent)==1 and sent[0]['timeout']==180 and sent[0]['num_retries']==0
