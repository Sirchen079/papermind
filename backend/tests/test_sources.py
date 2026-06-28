from datetime import date

from app.ingestion.sources import fetch_arxiv, parse_bibtex

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
