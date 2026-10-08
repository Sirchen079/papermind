import base64
import copy
import hashlib
import io
import json

import pymupdf
import pytest
from PIL import Image
from sqlmodel import Session, select

from app.agent.attachments import Attachment, attach_content, responses_content
from app.config import get_settings
from app.db.engine import get_engine
from app.models import Message, Model, Paper, Provider
from app.providers.client import ToolTurn


def seed_pdf(*, scan=False):
    root = get_settings().data_dir / 'pdfs'
    root.mkdir(exist_ok=True)
    path = root / 'two-pages.pdf'
    with pymupdf.open() as doc:
        for number, color in enumerate([(1, 0, 0), (0, 0, 1)], 1):
            page = doc.new_page(width=612, height=792)
            page.draw_rect(page.rect, color=color, fill=color)
            if not scan:
                page.insert_text((30, 50), f'Physical page {number}', color=(1, 1, 1))
        doc.save(path)
    with Session(get_engine()) as session:
        paper = Paper(source='pdf', title='Original page test', pdf_path=str(path), full_text='unchanged OCR text')
        session.add(paper); session.commit(); session.refresh(paper)
        return paper.id, path


@pytest.mark.parametrize('scan', [False, True])
def test_original_page_image_is_read_only_and_uses_the_requested_physical_page(client, monkeypatch, scan):
    pid, path = seed_pdf(scan=scan)
    pdf_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    def no_model(*args, **kwargs):
        raise AssertionError('Page rendering must not call any model')
    monkeypatch.setattr('app.providers.client.ProviderClient.complete', no_model)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', no_model)
    monkeypatch.setattr('app.providers.client.ProviderClient.embed', no_model)
    result = client.get(f'/api/papers/{pid}/page-attachment?page=2')
    assert result.status_code == 200, result.text
    assert result.headers['cache-control'] == 'no-store'
    item = Attachment.model_validate(result.json())
    raw = base64.b64decode(item.data_url.split(',', 1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        assert max(image.size) <= 2048
        assert image.getpixel((100, 100)) == (0, 0, 255)
    assert item.paper_page.paper_id == pid and item.paper_page.page == 2
    assert item.paper_page.pdf_sha256 == pdf_hash
    assert item.paper_page.image_sha256 == hashlib.sha256(raw).hexdigest()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pdf_hash
    assert list(path.parent.iterdir()) == [path]
    with Session(get_engine()) as session:
        assert session.get(Paper, pid).full_text == 'unchanged OCR text'
        assert session.exec(select(Message)).all() == []
        assert session.connection().exec_driver_sql('SELECT COUNT(*) FROM tokenusage').scalar() == 0
    blocks = attach_content('Compare the labelled conditions', [item.model_dump()])
    assert f'paper_id={pid}; PDF第2页（物理页码）' in blocks[-2]['text']
    assert pdf_hash in blocks[-2]['text']
    assert blocks[-1]['image_url']['url'] == item.data_url
    assert responses_content(blocks)[-1]['type'] == 'input_image'


@pytest.mark.parametrize('query', ['0', '-1', '3', '1.5', 'true'])
def test_unavailable_page_does_not_create_a_snapshot(client, query):
    pid, path = seed_pdf()
    before = path.read_bytes()
    result = client.get(f'/api/papers/{pid}/page-attachment?page={query}')
    assert result.status_code == 422
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('kind', ['absent', 'deleted', 'outside', 'not-pdf', 'encrypted'])
def test_file_guards_reuse_the_local_pdf_boundary(client, tmp_path, kind):
    pid, path = seed_pdf()
    with Session(get_engine()) as session:
        paper = session.get(Paper, pid)
        if kind == 'absent': paper.pdf_path = None
        elif kind == 'deleted': paper.is_deleted = True
        elif kind == 'outside':
            other = tmp_path / 'private.pdf'; other.write_bytes(path.read_bytes()); paper.pdf_path = str(other)
        elif kind == 'not-pdf': path.write_text('not a PDF', encoding='utf-8')
        else:
            target = path.parent / 'locked.pdf'
            with pymupdf.open(path) as doc:
                doc.save(target, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='password')
            paper.pdf_path = str(target)
        session.add(paper); session.commit()
    expected = 404 if kind in ('absent', 'deleted', 'outside') else 422
    assert client.get(f'/api/papers/{pid}/page-attachment?page=1').status_code == expected


def test_page_snapshot_survives_failed_send_retry_and_a_changed_current_pdf(client, monkeypatch, accept_evidence_review):
    pid, path = seed_pdf()
    item = client.get(f'/api/papers/{pid}/page-attachment?page=2').json()
    with Session(get_engine()) as session:
        provider = Provider(name='test', type='openai_compat'); session.add(provider); session.commit(); session.refresh(provider)
        model = Model(provider_id=provider.id, model_id='vision', supports_images=True)
        session.add(model); session.commit(); session.refresh(model); mid = model.id
    cid = client.post('/api/chat/conversations', json={'paper_id': pid}).json()['id']
    requests = []
    def generate(self, provider, model, messages, *args, **kwargs):
        requests.append(copy.deepcopy(messages))
        if len(requests) == 1: raise TimeoutError('synthetic failed send')
        return ToolTurn('snapshot received', [], 1, 1, 2)
    monkeypatch.setattr('app.providers.client.ProviderClient.complete_with_tools', generate)
    result = client.post(f'/api/chat/conversations/{cid}/messages', json={'content':'Read this original page', 'attachments':[item], 'model_config_id':mid})
    assert result.status_code == 500  # The synchronous chat API's failed-turn response.
    history = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert history[0]['attachments'] == [item] and history[0]['retryable']
    # The saved image is the sent source; retry must not re-render the new PDF.
    with pymupdf.open() as changed:
        changed.new_page(); changed.save(path)
    result = client.post(f'/api/chat/conversations/{cid}/messages', json={'content':history[0]['content'], 'retry_message_id':history[0]['id']})
    assert result.status_code == 200, result.text
    assert requests[0] == requests[1]
    assert client.get(f'/api/chat/conversations/{cid}').json()['messages'][0]['attachments'] == [item]


def test_snapshot_metadata_cannot_be_attached_to_other_image_bytes_or_text(client):
    pid, _ = seed_pdf()
    item = client.get(f'/api/papers/{pid}/page-attachment?page=2').json()
    corrupt = copy.deepcopy(item); corrupt['paper_page']['image_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='快照信息不一致'): Attachment.model_validate(corrupt)
    for field, value in [('page', True), ('paper_id', 0), ('pdf_sha256', 'bad')]:
        corrupt = copy.deepcopy(item); corrupt['paper_page'][field] = value
        with pytest.raises(ValueError): Attachment.model_validate(corrupt)
    corrupt = dict(item, kind='text', text='wrong source', data_url='')
    with pytest.raises(ValueError): Attachment.model_validate(corrupt)
