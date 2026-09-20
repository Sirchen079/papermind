from threading import Event
from types import SimpleNamespace

import pymupdf
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.reading import preparation


def paper(env, text="A useful scientific result."):
    root = env / 'data' / 'pdfs'
    root.mkdir(exist_ok=True)
    path = root / 'reading.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
        doc.save(path)
    with Session(get_engine()) as session:
        row = Paper(source='pdf', pdf_path=str(path), title='Reading test')
        session.add(row); session.commit(); session.refresh(row)
        return row.id


def finish(pid):
    preparation._jobs[(get_engine(), pid)][1].result(timeout=5)


def test_preparation_persists_and_reuses(client, env, monkeypatch):
    pid = paper(env)
    assert client.post(f'/api/papers/{pid}/prepare-reading').json()['status'] == 'loading'
    finish(pid)
    with Session(get_engine()) as session:
        assert 'scientific result' in session.get(Paper, pid).full_text
        from app.agent.tools import t_get_paper_full_text
        assert 'scientific result' in t_get_paper_full_text(session, pid)
    monkeypatch.setattr(preparation, 'parse_pdf', lambda _: (_ for _ in ()).throw(AssertionError('must reuse')))
    assert client.post(f'/api/papers/{pid}/prepare-reading').json()['status'] == 'ready'


def test_duplicate_and_deleted_during_parse(client, env, monkeypatch):
    pid = paper(env)
    entered, release = Event(), Event()
    calls = []
    def parse(path):
        calls.append(path); entered.set(); release.wait(5)
        return 'old content', .5
    monkeypatch.setattr(preparation, 'parse_pdf', parse)
    try:
        client.post(f'/api/papers/{pid}/prepare-reading')
        assert entered.wait(3)
        assert client.post(f'/api/papers/{pid}/prepare-reading').json()['status'] == 'loading'
        assert len(calls) == 1
        with Session(get_engine()) as session:
            row = session.get(Paper, pid); row.is_deleted = True; session.add(row); session.commit()
    finally:
        release.set()
    try:
        finish(pid)
    except ValueError:
        pass
    with Session(get_engine()) as session:
        assert not session.get(Paper, pid).full_text
    assert client.post(f'/api/papers/{pid}/prepare-reading').status_code == 404


def test_scan_failure_and_retry(client, env, monkeypatch):
    pid = paper(env, '')
    client.post(f'/api/papers/{pid}/prepare-reading')
    try:
        finish(pid)
    except ValueError:
        pass
    result = client.post(f'/api/papers/{pid}/prepare-reading').json()
    assert result['status'] == 'error' and 'OCR' in result['message']
    monkeypatch.setattr(preparation, 'parse_pdf', lambda _: ('OCR text', .8))
    assert client.post(f'/api/papers/{pid}/prepare-reading?retry=true').json()['status'] == 'loading'
    finish(pid)
    assert client.post(f'/api/papers/{pid}/prepare-reading').json()['status'] == 'ready'


def test_translation_model_and_failure(client, env, monkeypatch):
    from app.api import chat_api
    pid = paper(env)
    captured = []
    def choose(session, config):
        assert config == 19
        def complete(provider, model, messages, **kwargs):
            captured.append(messages)
            return SimpleNamespace(content='科学结果')
        return SimpleNamespace(complete=complete), object(), 'chosen-model'
    monkeypatch.setattr(chat_api, 'pick_chat_model', choose)
    body = {'text': 'Scientific result', 'target': '中文', 'model_config_id': 19}
    result = client.post(f'/api/papers/{pid}/translate', json=body)
    assert result.status_code == 200 and result.json()['text'] == '科学结果'
    assert captured[0][1]['content'] == body['text']
    assert client.post(f'/api/papers/{pid}/translate', json={**body, 'text': 'a' * 12001}).status_code == 422
    def broken(*args, **kwargs):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(chat_api, 'pick_chat_model', lambda *args: (SimpleNamespace(complete=broken), object(), 'chosen-model'))
    assert client.post(f'/api/papers/{pid}/translate', json=body).status_code == 502
    monkeypatch.setattr(chat_api, 'pick_chat_model', lambda *args: None)
    assert client.post(f'/api/papers/{pid}/translate', json=body).status_code == 422


def test_missing_file_does_not_crash(client, env):
    with Session(get_engine()) as session:
        row = Paper(source='manual', title='No PDF')
        session.add(row); session.commit(); session.refresh(row)
        pid = row.id
    assert client.post(f'/api/papers/{pid}/prepare-reading').json()['status'] == 'error'


def test_same_paper_ids_in_different_databases_do_not_share_jobs(client, env, monkeypatch):
    from sqlmodel import create_engine
    pid = paper(env)
    other_engine = create_engine(f"sqlite:///{env / 'other.sqlite'}", connect_args={'check_same_thread': False})
    Paper.__table__.create(other_engine)
    with Session(get_engine()) as source, Session(other_engine) as target:
        row = source.get(Paper, pid)
        target.add(Paper(id=pid, source='pdf', pdf_path=row.pdf_path))
        target.commit()
    entered, release = Event(), Event()
    calls = []
    def parse(path):
        calls.append(path); entered.set(); release.wait(5)
        return 'workspace text', .5
    monkeypatch.setattr(preparation, 'parse_pdf', parse)
    try:
        with Session(get_engine()) as first, Session(other_engine) as second:
            assert preparation.prepare(first, pid)['status'] == 'loading'
            assert entered.wait(3)
            assert preparation.prepare(second, pid)['status'] == 'loading'
    finally:
        release.set()
    finish(pid)
    preparation._jobs[(other_engine, pid)][1].result(timeout=5)
    assert len(calls) == 2
    with Session(other_engine) as session:
        assert session.get(Paper, pid).full_text == 'workspace text'
    other_engine.dispose()
