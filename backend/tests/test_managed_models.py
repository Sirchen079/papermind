import io
import json
import os
import shutil
import subprocess
import sys

import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Provider
from app.providers import managed
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


@pytest.fixture
def runtime(env):
    value=managed.manager(env/'data')
    yield value
    value.close()


def test_import_deduplicates_and_portable_paths_survive_relocation(runtime,tmp_path):
    contents=b'GGUF'+b'fixture'*20
    one=runtime.import_stream(io.BytesIO(contents),'one.gguf','chat',8192)
    again=runtime.import_stream(io.BytesIO(contents),'again.gguf','chat',8192)
    other_profile=runtime.import_stream(io.BytesIO(contents),'short.gguf','chat',4096)
    assert again['id']==one['id'] and other_profile['id']!=one['id']
    assert len(list((runtime.root/'weights').glob('*.gguf')))==1
    newroot=tmp_path/'portable';shutil.copytree(runtime.root,newroot/'local_ai')
    portable=managed.Manager(newroot)
    assert all(row['available'] for row in portable.status()['models'])
    portable.remove(one['id'])
    assert portable.status()['models'][0]['available']
    portable.remove(other_profile['id'])
    assert not list((portable.root/'weights').glob('*.gguf'))
    assert runtime.status()['models'][0]['available']


def test_invalid_import_and_corrupt_catalog_are_not_silently_replaced(runtime):
    with pytest.raises(ValueError):runtime.import_stream(io.BytesIO(b'not a model'),'bad','chat',8192)
    assert not list(runtime.root.rglob('*.part'))
    path=runtime.root/'catalog.json';path.write_text('{broken',encoding='utf-8')
    with pytest.raises(ValueError):runtime.import_stream(io.BytesIO(b'GGUFfixture'),'good','chat',8192)
    assert path.read_text()=='{broken'
    assert not list(runtime.root.rglob('*.part'))


def test_use_is_project_specific_and_logical_endpoint_survives_restart(client,runtime,monkeypatch):
    res=client.post('/api/managed-models/import',files={'file':('model.gguf',b'GGUFfixture')},
        data={'kind':'chat','context_window':8192})
    assert res.status_code==200,res.text
    mid=res.json()['id'];calls=[]
    monkeypatch.setattr(runtime,'ready',lambda ident:(calls.append(ident) or ('http://127.0.0.1:45678/v1','runtime-only-key')))
    result=client.post(f'/api/managed-models/{mid}/use')
    assert result.status_code==200,result.text
    assert client.post(f'/api/managed-models/{mid}/use').json()==result.json()
    wid=client.post('/api/workspaces',json={'name':'Second project'}).json()['id']
    prefix=f'/api/w/{wid}'
    assert client.get(prefix+'/managed-models').json()['models'][0]['id']==mid
    assert client.get(prefix+'/providers').json()==[]
    assert client.post(prefix+f'/managed-models/{mid}/use').status_code==200
    with Session(get_engine()) as session:
        p=session.exec(select(Provider)).one()
        logical=p.base_url
        ready=ProviderClient(lambda:Session(get_engine()),get_crypto())._ready_provider(p)
        assert ready.base_url=='http://127.0.0.1:45678/v1'
        assert p.base_url==logical==managed.PREFIX+mid
        assert p.api_key_encrypted is None
    assert mid in calls


def test_start_failure_keeps_project_model_choice(client,runtime,monkeypatch):
    row=runtime.import_stream(io.BytesIO(b'GGUFfixture'),'fixture','chat',8192)
    def fail(_):raise ValueError('模型文件无法加载')
    monkeypatch.setattr(runtime,'ready',fail)
    result=client.post(f'/api/managed-models/{row["id"]}/use')
    assert result.status_code==422
    assert client.get('/api/providers').json()==[]


def test_whole_backup_restores_owned_weights_without_runtime_logs(client,runtime,env):
    from test_application_archive import backup
    from app.archive.application import verify
    from app.archive.application_restore import restore
    import zipfile
    row=runtime.import_stream(io.BytesIO(b'GGUF'+b'portable model'*20),'portable.gguf','chat',8192)
    (runtime.root/'logs').mkdir();(runtime.root/'logs/debug.log').write_text('temporary log')
    archive=backup(client)
    assert verify(archive)['ok']
    with zipfile.ZipFile(archive) as bundle:
        assert 'application/local_ai/catalog.json' in bundle.namelist()
        assert not any('/logs/' in n for n in bundle.namelist())
    result=restore(archive,env/'restored-models',apply=True)
    assert result['applied'],result
    restored=managed.Manager(env/'restored-models')
    assert restored.status()['models'][0]['id']==row['id']
    assert restored.status()['models'][0]['available']


def test_stop_during_startup_does_not_leave_child_running(runtime,monkeypatch,tmp_path):
    row=runtime.import_stream(io.BytesIO(b'GGUFfixture'),'fixture','chat',8192)
    executable=tmp_path/'fake.exe';executable.write_bytes(b'fake')
    monkeypatch.setattr(managed,'engine_path',lambda:executable)
    class Process:
        code=None
        def poll(self):return self.code
        def terminate(self):self.code=0
        def wait(self,timeout=None):return self.code
    process=Process()
    monkeypatch.setattr(managed.subprocess,'Popen',lambda *a,**kw:process)
    monkeypatch.setattr(managed,'RuntimeJob',lambda:type('Job',(),{'assign':lambda *a:None,'close':lambda *a:None})())
    monkeypatch.setattr(runtime,'_watch',lambda *args:None)
    assert runtime.start(row['id'])['state']=='starting'
    assert runtime.stop(row['id'])['state']=='stopped'
    assert process.poll()==0


@pytest.mark.skipif(os.name!='nt',reason='Windows process lifetime contract')
def test_windows_parent_crash_reaps_owned_children():
    from ctypes import WinDLL, wintypes
    kernel=WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    script="""
import subprocess,sys,os
from app.providers.runtime_job import RuntimeJob
job=RuntimeJob()
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],creationflags=subprocess.CREATE_NO_WINDOW)
job.assign(child)
print(child.pid,flush=True)
os._exit(0)
"""
    parent=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    assert parent.returncode==0,parent.stderr
    handle=kernel.OpenProcess(0x100000,False,int(parent.stdout.strip()))
    if handle:
        try:assert kernel.WaitForSingleObject(handle,10000)==0
        finally:kernel.CloseHandle(handle)
