from datetime import date

import httpx
import pytest

from app.ingestion.sources import fetch_arxiv, parse_bibtex, parse_ris

BIBTEX = """
@article{vaswani2017attention,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam},
  journal = {NeurIPS},
  year = {2017},
  doi = {10.5555/3295222.3295349},
  abstract = {We propose a new architecture.}
}
@inproceedings{devlin2019bert,
  title = {BERT: Pre-training Transformers},
  author = {Devlin, Jacob and Chang, Ming-Wei and Lee, Kenton},
  booktitle = {NAACL},
  year = {2019},
  eprint = {1810.04805}
}
"""


def test_parse_bibtex_two_entries():
    papers = parse_bibtex(BIBTEX)
    assert len(papers) == 2
    a = papers[0]
    assert a.source == "bibtex"
    assert a.title == "Attention Is All You Need"
    assert a.authors == ["Vaswani, Ashish", "Shazeer, Noam"]
    assert a.year == 2017
    assert a.doi == "10.5555/3295222.3295349"
    b = papers[1]
    assert b.arxiv_id == "1810.04805"
    assert len(b.authors) == 3


def test_parse_ris_two_entries_from_zotero_or_endnote():
    ris = """
TY  - JOUR
TI  - Attention Is All You Need
AU  - Ashish Vaswani
AU  - Noam Shazeer
PY  - 2017
JO  - NeurIPS
DO  - 10.5555/3295222.3295349
AB  - We propose a new architecture.
UR  - https://arxiv.org/abs/1706.03762
ER  -

TY  - CONF
T1  - BERT: Pre-training Transformers
A1  - Jacob Devlin
A1  - Ming-Wei Chang
Y1  - 2019
T2  - NAACL
N1  - arXiv:1810.04805
ER  -
"""
    papers = parse_ris(ris)

    assert len(papers) == 2
    first = papers[0]
    assert first.source == "ris"
    assert first.title == "Attention Is All You Need"
    assert first.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert first.year == 2017
    assert first.venue == "NeurIPS"
    assert first.doi == "10.5555/3295222.3295349"
    assert first.abstract == "We propose a new architecture."
    assert first.arxiv_id == "1706.03762"
    second = papers[1]
    assert second.title == "BERT: Pre-training Transformers"
    assert second.authors == ["Jacob Devlin", "Ming-Wei Chang"]
    assert second.year == 2019
    assert second.venue == "NAACL"
    assert second.arxiv_id == "1810.04805"


class _FakeResult:
    def __init__(self) -> None:
        self.title = "A Paper"
        self.authors = ["Alice", "Bob"]
        self.summary = "An abstract"
        self.published = date(2024, 5, 1)
        self.pdf_url = None  # no download attempted
        self.doi = "10.0/abc"


class _FakeClient:
    def results(self, search):  # noqa: ANN001
        return iter([_FakeResult()])


def test_fetch_arxiv_with_fake_client():
    fp = fetch_arxiv("2405.00001", client=_FakeClient())
    assert fp.title == "A Paper"
    assert fp.authors == ["Alice", "Bob"]
    assert fp.year == 2024
    assert fp.arxiv_id == "2405.00001"
    assert fp.doi == "10.0/abc"
    assert fp.pdf_bytes is None


class _FakePdfResult(_FakeResult):
    def __init__(self) -> None:
        super().__init__()
        self.pdf_url = "https://arxiv.org/pdf/2405.00001"


class _FakePdfClient:
    def results(self, search):  # noqa: ANN001
        return iter([_FakePdfResult()])


def test_fetch_arxiv_raises_on_pdf_download_error(monkeypatch):
    def fake_get(url, **kwargs):  # noqa: ANN001
        return httpx.Response(
            502,
            request=httpx.Request("GET", url),
            text="bad gateway",
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_arxiv("2405.00001", client=_FakePdfClient())
