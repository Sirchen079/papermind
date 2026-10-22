import json
from pathlib import Path

import pymupdf
import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper


@pytest.fixture
def access(client, monkeypatch, tmp_path):
    from app.ingestion import institutional as mod
    monkeypatch.setenv('PAPERMIND_INSTITUTION_CONFIG', str(tmp_path / 'institution.json'))
    mod.configure('Test University', 'https://library.example.edu/')
    with Session(get_engine()) as session:
        paper = Paper(source='manual', doi='10.1000/target', title='Curated title', year=2020)
        session.add(paper)
        session.commit()
        pid = paper.id
    return mod, pid, tmp_path


def fake_engine(folder, *, status='success', doi='10.1000/target', outside=False, invalid=False, text=None):
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / 'article.pdf' if not outside else folder.parent / 'outside.pdf'
    if invalid:
        pdf.write_text('<html>Login required</html>')
    else:
        with pymupdf.open() as doc:
            doc.new_page().insert_text((50, 50), text or 'Curated title DOI: 10.1000/target')
            doc.save(pdf)
    return {'doi': doi, 'status': status, 'verified_match': status == 'success', 'pdf_path': str(pdf)}


def receive(mod, session, pid, folder, item):
    return mod.attach(session, pid, item, folder, {'doi': '10.1000/target', 'title': 'Curated title'})


def test_verified_pdf_attaches_without_rewriting_metadata(access, monkeypatch):
    mod, pid, folder = access
    item = fake_engine(folder)
    monkeypatch.setattr('app.ingestion.document_pipeline.queue_import', lambda *a, **k: False)
    with Session(get_engine()) as session:
        assert receive(mod, session, pid, folder, item) == 'attached'
        paper = session.get(Paper, pid)
        assert paper.title == 'Curated title' and paper.year == 2020
        assert Path(paper.pdf_path).is_file()
        assert receive(mod, session, pid, folder, item) == 'has_pdf'


@pytest.mark.parametrize('options', [{'status': 'unverified'}, {'doi': '10.1000/wrong'},
                                    {'outside': True}, {'invalid': True},
                                    {'text': 'Different article\nReferences\nDOI: 10.1000/target'},
                                    {'text': 'Supporting information\nDOI: 10.1000/target'}])
def test_bad_or_unverified_result_never_attaches(access, monkeypatch, options):
    mod, pid, folder = access
    item = fake_engine(folder / 'run', **options)
    with Session(get_engine()) as session:
        assert receive(mod, session, pid, folder / 'run', item) != 'attached'
        assert session.get(Paper, pid).pdf_path is None


def test_deleted_or_changed_target_does_not_receive_pdf(access, monkeypatch):
    mod, pid, folder = access
    item = fake_engine(folder)
    with Session(get_engine()) as session:
        assert receive(mod, session, 999999, folder, item) == 'not_found'
        session.get(Paper, pid).doi = '10.1000/changed'
        session.commit()
        assert receive(mod, session, pid, folder, item) == 'identity_changed'


def test_config_stores_no_credentials(access):
    mod, pid, folder = access
    assert mod.config()['institution'] == 'Test University'
    with pytest.raises(ValueError):
        mod.configure('School', 'javascript:alert(1)')
    with pytest.raises(ValueError):
        mod.configure('School', 'https://user:password@library.example.edu/')
