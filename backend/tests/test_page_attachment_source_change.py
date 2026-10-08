"""A changed source cannot be returned with an older PDF fingerprint."""
from types import SimpleNamespace

import pymupdf
import pytest

from app.reading.page_attachment import page_attachment


def test_pdf_changed_during_render_does_not_publish_a_page_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'source.pdf'
    with pymupdf.open() as pdf:
        pdf.new_page(); pdf.save(path)
    original = path.read_bytes()
    fingerprints = iter(['a' * 64, 'b' * 64])
    monkeypatch.setattr('app.reading.page_attachment._digest', lambda _: next(fingerprints))
    with pytest.raises(ValueError, match='读取时发生变化'):
        page_attachment(SimpleNamespace(id=1, title='source', pdf_path=str(path)), 1, tmp_path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
