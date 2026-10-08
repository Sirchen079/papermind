import httpx
import pytest
import respx
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model, Provider
from app.providers.client import ProviderClient
from app.providers.local import normalize_local_url
from app.security.crypto import get_crypto


@respx.mock
def test_discover_and_connect_roles_atomically_without_duplicate_providers(client):
    cloud=client.post('/api/providers', json={'name':'existing','type':'openai_chat'}).json()['id']
    client.post(f'/api/providers/{cloud}/models',json={'model_id':'old-chat','role_default':'chat'})
    client.post(f'/api/providers/{cloud}/models',json={'model_id':'old-vector','role_default':'embedding'})
    endpoint=respx.get('http://127.0.0.1:11434/v1/models').respond(200,json={'data':[{'id':'local-text'},{'id':'local-vector'}]})
    result=client.post('/api/local-models/discover',json={'base_url':'http://127.0.0.1:11434'}).json()
    assert len(result['models'])==2
    body={'base_url':result['base_url'],'name':'Ollama','chat_model':'local-text','chat_context_window':8192}
    first=client.post('/api/local-models/connect',json=body)
    assert first.status_code==200,first.text
    again=client.post('/api/local-models/connect',json=body)
    assert again.json()['provider_id']==first.json()['provider_id']
    rows=client.get('/api/models').json()
    assert {r['role_default']:r['model_id'] for r in rows if r['role_default']}=={'chat':'local-text','embedding':'old-vector'}
    assert next(r for r in rows if r['model_id']=='local-text')['context_window']==8192
    assert endpoint.calls.last.request.headers.get('authorization') is None
    connected=client.post('/api/local-models/connect',json={**body,'embedding_model':'local-vector'})
    assert connected.status_code==200,connected.text
    rows=client.get('/api/models').json()
    assert {r['role_default']:r['model_id'] for r in rows if r['role_default']}=={'chat':'local-text','embedding':'local-vector'}
    assert len(client.get('/api/providers').json())==2
    wid=client.post('/api/workspaces',json={'name':'Another local project'}).json()['id']
    prefix=f'/api/w/{wid}'
    assert client.get(prefix+'/providers').json()==[]
    assert client.post(prefix+'/local-models/connect',json=body).status_code==200
    assert len(client.get(prefix+'/providers').json())==1
    assert len(client.get('/api/providers').json())==2


@respx.mock
def test_failed_discovery_or_stale_model_does_not_change_roles(client):
    endpoint=respx.get('http://localhost:1234/v1/models').respond(401)
    body={'base_url':'http://localhost:1234/v1','chat_model':'missing'}
    assert client.post('/api/local-models/connect',json=body).status_code==502
    endpoint.respond(200,json={'data':[{'id':'available'}]})
    assert client.post('/api/local-models/connect',json=body).status_code==409
    assert client.get('/api/providers').json()==[]


@respx.mock
def test_explicit_local_key_stays_private_and_empty_key_works(client):
    endpoint=respx.get('http://[::1]:8080/v1/models').respond(200,json={'data':[{'id':'text'}]})
    body={'base_url':'http://[::1]:8080/v1','chat_model':'text','api_key':'local-test-password'}
    response=client.post('/api/local-models/connect',json=body)
    assert response.status_code==200,response.text
    assert 'local-test-password' not in response.text
    assert endpoint.calls.last.request.headers['authorization']=='Bearer local-test-password'
    with Session(get_engine()) as session:
        provider=session.get(Provider,response.json()['provider_id'])
        api=ProviderClient(lambda:Session(get_engine()),get_crypto())
        assert api._api_key(provider)=='local-test-password'
        provider.api_key_encrypted=None
        assert api._api_key(provider)=='papermind-local'
        provider.base_url='https://models.example.org/v1'
        assert api._api_key(provider) is None


def test_local_setup_accepts_loopback_and_does_not_mislabel_remote_servers(client):
    assert normalize_local_url('http://127.0.0.1:8080/v1/chat/completions')=='http://127.0.0.1:8080/v1'
    for url in ['https://models.example.org/v1','http://localhost.example.org/v1','file:///models','http://user:pass@localhost:8080/v1']:
        assert client.post('/api/local-models/discover',json={'base_url':url}).status_code==422
    # Remote/private services continue to work through the existing provider API.
    assert client.post('/api/providers',json={'name':'LAN','type':'openai_compat','base_url':'http://192.168.1.2:8080/v1'}).status_code==200
