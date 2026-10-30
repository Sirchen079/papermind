import time
from threading import Event


def test_environment_installation_has_progress_failure_retry_and_no_browser_launch(client, monkeypatch, tmp_path):
    from app.ingestion import institutional_runtime as runtime
    from app.security.local_token import get_or_create_token
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME',str(tmp_path/'runtime'))
    monkeypatch.setattr(runtime,'ready',lambda: ready[0])
    from app.ingestion import institutional_setup as setup
    ready=[False]
    headers={'X-Local-Token':get_or_create_token()}
    route='/api/institutional/environment'
    assert client.post(route).status_code == 403
    assert client.get(route,headers=headers).json()['status'] == 'not_installed'
    begun, release = Event(), Event()
    def fail(progress):
        progress('正在安装机构下载引擎…');begun.set();release.wait(3)
        raise runtime.PreparationError('下载环境 TLS 连接失败')
    monkeypatch.setattr(runtime,'prepare',fail)
    assert client.post(route,headers=headers).status_code == 202
    assert begun.wait(2)
    assert client.get(route,headers=headers).json()['status'] == 'installing'
    assert '下载引擎' in client.get(route,headers=headers).json()['message']
    assert client.post(route,headers=headers).status_code == 409
    release.set()
    def finished():
        for _ in range(100):
            state=client.get(route,headers=headers).json()
            if state['status'] != 'installing':return state
            time.sleep(.02)
        raise AssertionError('installation did not finish')
    state=finished()
    assert state['status']=='failed' and 'TLS' in state['error'] and not state['ready']
    def succeed(progress):
        progress('正在准备浏览器…');ready[0]=True
    monkeypatch.setattr(runtime,'prepare',succeed)
    assert client.post(route,headers=headers).status_code == 202
    assert finished()['ready']
    assert setup.status()['status']=='ready'


def test_abandoned_installation_is_visible_as_interrupted(monkeypatch,tmp_path):
    from app.ingestion import institutional_setup as setup
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME',str(tmp_path))
    monkeypatch.setattr(setup.runtime,'ready',lambda:False)
    setup.access.write_json(tmp_path/'installation.json',dict(status='installing',message='正在安装',error=''))
    state=setup.status()
    assert state['status']=='interrupted' and not state['ready'] and '重新安装' in state['error']
