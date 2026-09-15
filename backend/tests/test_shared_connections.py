import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Provider, TokenUsage
from app.providers.selection import pick_llm
from app.providers import shared
from app.workspaces.context import bind_workspace
from app.security.crypto import Crypto


def workspace(client,name):
    wid=client.post('/api/workspaces',json={'name':name}).json()['id']
    return wid,'/api/w/'+wid


def connection(client,prefix='/api'):
    provider=client.post(prefix+'/providers',json={'name':'Synthetic connection','type':'openai_chat','api_key':'synthetic-original'}).json()
    client.post(prefix+f"/providers/{provider['id']}/models",json={'model_id':'synthetic-model','role_default':'chat'})
    published=client.post(prefix+f"/providers/{provider['id']}/share")
    assert published.status_code==200,published.text
    assert 'synthetic-original' not in published.text and 'api_key_encrypted' not in published.text
    return provider['id'],published.json()


def chosen(client,wid):
    with bind_workspace(client.app.state.workspaces.context(wid)),Session(get_engine()) as session:
        return pick_llm(session,'chat')


def test_reference_rotates_live_credentials_but_preserves_captured_request_and_local_override(client):
    pid,published=connection(client)
    wid,prefix=workspace(client,'Independent project')
    attached=client.post(prefix+'/providers/attach',json={'connection_id':published['id']})
    assert attached.status_code==201,attached.text
    bpid=attached.json()['id']
    old=chosen(client,wid)
    assert old[2]=='synthetic-model'
    assert old[0]._api_key(old[1])=='synthetic-original'
    changed=client.patch('/api/shared-connections/'+published['id'],json={'expected_version':1,'api_key':'synthetic-rotated','name':'Rotated'})
    assert changed.status_code==200,changed.text
    assert old[0]._api_key(old[1])=='synthetic-original'
    new=chosen(client,wid)
    assert new[0]._api_key(new[1])=='synthetic-rotated'
    assert client.get(prefix+'/providers').json()[0]['name']=='Rotated'
    # A project-specific override explicitly disconnects future global edits.
    assert client.patch(prefix+f'/providers/{bpid}',json={'api_key':'local'}).status_code==409
    assert client.post(prefix+f'/providers/{bpid}/detach').status_code==200
    assert client.patch(prefix+f'/providers/{bpid}',json={'api_key':'synthetic-project-only'}).status_code==200
    assert client.patch('/api/shared-connections/'+published['id'],json={'expected_version':2,'enabled':False}).status_code==200
    assert chosen(client,'legacy') is None
    checks=client.get('/api/readiness').json()['checks']
    assert next(row for row in checks if row['id']=='llm')['status']=='action'
    local=chosen(client,wid)
    assert local[0]._api_key(local[1])=='synthetic-project-only'


def test_usage_and_cache_session_stay_in_project_when_connection_shared(client):
    _,published=connection(client)
    wid,prefix=workspace(client,'Usage owner')
    provider=client.post(prefix+'/providers/attach',json={'connection_id':published['id']}).json()
    engine=client.app.state.workspaces.context(wid).db_path
    llm,p,model=chosen(client,wid)
    llm._record_usage(p,model,'chat','same-conversation',5,7,12)
    with closing(sqlite3.connect(engine)) as db:
        assert db.execute('SELECT provider_id,total_tokens FROM tokenusage').fetchall()==[(provider['id'],12)]
    with Session(get_engine()) as session:
        assert session.exec(select(TokenUsage)).all()==[]
    # Removing a referenced provider during an active request keeps its identity.
    assert client.delete(prefix+f"/providers/{provider['id']}").status_code==204
    llm._record_usage(p,model,'chat','same-conversation',2,3,5)
    assert client.get(prefix+'/providers').json()==[]


def test_publish_retry_and_concurrent_attach_are_idempotent(client):
    pid,published=connection(client)
    assert client.post(f'/api/providers/{pid}/share').json()['id']==published['id']
    wid,prefix=workspace(client,'Two windows')
    def attach():return client.post(prefix+'/providers/attach',json={'connection_id':published['id']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(lambda _:attach(),range(2)))
    assert a.status_code==b.status_code==201
    assert a.json()['id']==b.json()['id']
    assert len(client.get(prefix+'/providers').json())==1
    assert len([m for m in client.get(prefix+'/models').json() if m['role_default']=='chat'])==1


def test_project_backup_resolves_shared_connection_without_mutating_live_reference(client,env):
    _,published=connection(client)
    wid,prefix=workspace(client,'Portable backup')
    provider=client.post(prefix+'/providers/attach',json={'connection_id':published['id']}).json()
    client.patch('/api/shared-connections/'+published['id'],json={'expected_version':1,'api_key':'synthetic-latest'})
    response=client.post(prefix+'/archive/backup')
    assert response.status_code==200,response.text
    context=client.app.state.workspaces.context(wid)
    extracted=env/'restored-shared-backup'
    with zipfile.ZipFile(context.data_dir/'backups'/response.json()['filename']) as archive:
        archive.extractall(extracted)
    with closing(sqlite3.connect(extracted/'papermind.sqlite')) as db:
        cipher,reference=db.execute('SELECT api_key_encrypted,shared_connection_id FROM provider WHERE id=?',(provider['id'],)).fetchone()
    assert reference is None
    assert Crypto((extracted/'master.key').read_bytes()).decrypt(cipher)=='synthetic-latest'
    assert client.get(prefix+'/providers').json()[0]['shared_connection_id']==published['id']


def test_shared_edit_conflict_and_invalid_destination_are_reported(client):
    _,published=connection(client)
    path='/api/shared-connections/'+published['id']
    assert client.patch(path,json={'expected_version':1,'name':'Updated'}).status_code==200
    assert client.patch(path,json={'expected_version':1,'name':'Stale'}).status_code==409
    assert client.patch(path,json={'expected_version':2,'base_url':'file:///invalid'}).status_code==422
    assert client.post('/api/providers/attach',json={'connection_id':'0'*32}).status_code==404
    text=client.get('/api/shared-connections').text
    assert 'api_key' not in text and 'synthetic-original' not in text


def test_missing_shared_key_disables_connection_without_creating_a_new_key(client,env):
    connection(client)
    key=env/'data'/'connections.key'
    retained=key.read_bytes()
    key.unlink()
    assert client.get('/api/providers').json()[0]['shared_unavailable']
    assert chosen(client,'legacy') is None
    assert not key.exists()
    # Library backup still works, with the unavailable connection disabled.
    response=client.post('/api/archive/backup')
    assert response.status_code==200,response.text
    key.write_bytes(retained)
