import json
import time
import pytest
from types import SimpleNamespace

from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper


def setup_access(client, monkeypatch, tmp_path):
    from app.ingestion import institutional as access, institutional_jobs as jobs
    monkeypatch.setenv('PAPERMIND_INSTITUTION_RUNTIME', str(tmp_path / 'engine'))
    monkeypatch.setenv('PAPERMIND_INSTITUTION_CONFIG', str(tmp_path / 'config.json'))
    access.configure('Example University', 'https://library.example.edu/')
    monkeypatch.setattr(jobs.runtime, 'prepare', lambda callback: None)
    monkeypatch.setattr(jobs.runtime, 'ready', lambda: True)
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title='Example', doi='10.1000/example')
        session.add(paper)
        session.commit()
        pid = paper.id
    from app.security.local_token import get_or_create_token
    return jobs, pid, {'X-Local-Token': get_or_create_token()}


def wait_done(client, jid, headers):
    for _ in range(100):
        value = client.get('/api/institutional/jobs/' + jid, headers=headers).json()
        if value['status'] != 'running':
            return value
        time.sleep(.02)
    raise AssertionError('job did not finish')


def test_routes_require_token_and_reject_password_fields(client, monkeypatch, tmp_path):
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    assert client.get('/api/institutional/config').status_code == 403
    assert client.post('/api/institutional/jobs', json={'paper_ids': [pid]}).status_code == 403
    assert client.put('/api/institutional/config', headers=headers,
        json={'institution': 'School', 'password': 'never-accepted'}).status_code == 422
    assert client.put('/api/institutional/config', headers=headers,
        json={'institution': 'School', 'library_url': 'javascript:alert(1)'}).status_code == 422
    assert client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid] * 11}).status_code == 422


def test_background_failure_is_readable_recoverable_and_does_not_expose_engine_errors(client, monkeypatch, tmp_path):
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise OSError('SECRET cookie and arbitrary provider URL')
    monkeypatch.setattr(jobs.subprocess, 'Popen', fail)
    value = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).json()
    result = wait_done(client, value['id'], headers)
    assert result['status'] == 'needs_attention'
    assert result['results'][0]['status'] == 'worker_failed'
    assert 'SECRET' not in json.dumps(result)
    assert client.get('/api/institutional/jobs', headers=headers).json()[0]['id'] == value['id']
    # All profile leases are released after the failed worker.
    retry = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]})
    assert retry.status_code == 200
    wait_done(client, retry.json()['id'], headers)


def test_failed_download_allows_verified_browser_upload(client, monkeypatch, tmp_path):
    import pymupdf
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise OSError('unavailable engine')
    monkeypatch.setattr(jobs.subprocess, 'Popen', fail)
    jid = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).json()['id']
    result = wait_done(client, jid, headers)
    assert result['results'][0]['status'] == 'worker_failed'
    monkeypatch.setattr('app.literature.survey._index_imported', lambda *a: '')
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30,30), 'Example DOI: 10.1000/example')
        data = pdf.tobytes()
    endpoint = f'/api/institutional/jobs/{jid}/papers/{pid}/pdf'
    assert client.post(endpoint, files={'file': ('paper.pdf',data)}).status_code == 403
    assert client.post(endpoint, headers=headers, files={'file': ('login.pdf',b'<html>Login</html>')}).status_code == 422
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30,30), 'An unrelated paper DOI: 10.1000/other')
        wrong = pdf.tobytes()
    assert client.post(endpoint, headers=headers, files={'file': ('wrong.pdf',wrong)}).status_code == 422
    response = client.post(f'/api/institutional/jobs/{jid}/papers/{pid}/pdf', headers=headers,
        files={'file': ('paper.pdf', data, 'application/pdf')})
    assert response.status_code == 200
    assert response.json()['results'][0]['status'] == 'attached'
    assert response.json()['status'] == 'completed'
    with Session(get_engine()) as session:
        receipt = jobs.Path(session.get(Paper,pid).pdf_path).with_suffix('.source.json')
        assert json.loads(receipt.read_text())['access_mode'] == 'manual_pdf_upload'


def test_download_is_disabled_until_environment_is_ready(client, monkeypatch, tmp_path):
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    monkeypatch.setattr(jobs.runtime, 'ready', lambda: False)
    monkeypatch.setattr(jobs.runtime, 'prepare', lambda *a: pytest.fail('downloads must never install dependencies'))
    for mode in ('auto','manual'):
        response = client.post('/api/institutional/jobs',headers=headers,json={'paper_ids':[pid],'mode':mode})
        assert response.status_code == 409 and '设置' in response.json()['detail']


def test_completed_items_are_imported_once_and_retained(client, monkeypatch, tmp_path):
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    imports = []
    def popen(argv, **kwargs):
        assert kwargs['shell'] is False and kwargs['stdin'] == jobs.subprocess.DEVNULL
        folder = jobs.Path(argv[-1])
        (folder / f'{pid}.json').write_text('{"status":"success"}')
        return SimpleNamespace(poll=lambda: 0, wait=lambda **kw: 0)
    monkeypatch.setattr(jobs.subprocess, 'Popen', popen)
    monkeypatch.setattr(jobs.access, 'attach', lambda s, p, *a: imports.append(p) or 'attached')
    jid = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).json()['id']
    assert wait_done(client, jid, headers)['results'][0]['status'] == 'attached'
    client.get('/api/institutional/jobs/' + jid, headers=headers)
    assert imports == [pid]
    events = client.get('/api/workspaces/activity').json()['items']
    row = next(row for row in events if row['kind'] == 'institutional')
    assert row['status'] == 'ready' and not row['active']
    assert 'library' in row['url'] and 'SECRET' not in json.dumps(row)


def test_unknown_job_does_not_escape_workspace(client, monkeypatch, tmp_path):
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    assert client.get('/api/institutional/jobs/not-a-job', headers=headers).status_code == 404


def test_browser_download_completes_without_waiting_for_a_stuck_viewer(client, monkeypatch, tmp_path):
    from threading import Event
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    stopped = Event()
    def popen(argv, **kwargs):
        (jobs.Path(argv[-1]) / f'{pid}.json').write_text('{"status":"success"}')
        return SimpleNamespace(poll=lambda: 0 if stopped.is_set() else None)
    monkeypatch.setattr(jobs.subprocess, 'Popen', popen)
    monkeypatch.setattr(jobs, '_terminate', lambda process: stopped.set())
    monkeypatch.setattr(jobs.access, 'attach', lambda *args: 'attached')
    jid = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).json()['id']
    result = wait_done(client, jid, headers)
    assert result['status'] == 'completed' and stopped.is_set()
    assert result['results'][0]['status'] == 'attached'


def test_stop_retains_progress_and_profile_lease_is_released(client, monkeypatch, tmp_path):
    from threading import Event
    jobs, pid, headers = setup_access(client, monkeypatch, tmp_path)
    launched, stopped = Event(), Event()
    def popen(argv, **kwargs):
        (jobs.Path(argv[-1]) / 'progress.json').write_text(json.dumps({'paper_id': pid, 'phase': 'waiting_verification'}))
        launched.set()
        return SimpleNamespace(poll=lambda: 0 if stopped.is_set() else None)
    monkeypatch.setattr(jobs.subprocess, 'Popen', popen)
    monkeypatch.setattr(jobs, '_terminate', lambda process: stopped.set())
    jid = client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).json()['id']
    assert launched.wait(2)
    for _ in range(50):
        value = client.get('/api/institutional/jobs/' + jid, headers=headers).json()
        if value['phase'] == 'waiting_verification':
            break
        time.sleep(.02)
    assert value['phase'] == 'waiting_verification'
    activity = client.get('/api/workspaces/activity').json()['items']
    assert any(row['kind'] == 'institutional' and row['status'] == 'waiting_verification' and row['active'] for row in activity)
    assert client.post('/api/institutional/jobs', headers=headers, json={'paper_ids': [pid]}).status_code == 409
    client.post('/api/institutional/jobs/' + jid + '/stop', headers=headers)
    assert wait_done(client, jid, headers)['status'] == 'stopped'
    from app.workspaces.context import WorkspaceContext, bind_workspace
    from fastapi import HTTPException
    import pytest
    other = tmp_path / 'other'
    with bind_workspace(WorkspaceContext('other', other, other / 'db.sqlite', other / 'master.key')):
        with pytest.raises(HTTPException) as exc:
            jobs.get_job(jid)
        assert exc.value.status_code == 404
    assert jobs.access._browser_lock.acquire(blocking=False)
    jobs.access._browser_lock.release()
