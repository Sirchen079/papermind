from pathlib import Path

import fitz

from app.ingestion.pdf_identify import extract_candidates, extract_from_text, identify_pdf

ALL_NONE = {'doi': None, 'arxiv_id': None, 'title': None}


def _make_pdf(path: Path, text: str, pages: int = 1, meta: dict | None = None) -> None:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    if meta:
        doc.set_metadata(meta)
    doc.save(str(path))
    doc.close()


def test_doi_with_prefixes_and_trailing_punctuation():
    assert extract_from_text("doi:10.1038/s41586-019-1234-5")['doi'] == '10.1038/s41586-019-1234-5'
    # normalize_doi lowercases the identifier
    assert extract_from_text("DOI:10.1038/S41586-019-1234-5")['doi'] == '10.1038/s41586-019-1234-5'
    # trailing sentence punctuation is not part of the DOI
    assert extract_from_text("(doi:10.1038/s41586-019-1234-5).")['doi'] == '10.1038/s41586-019-1234-5'
    assert extract_from_text("[doi:10.1038/s41586-019-1234-5],")['doi'] == '10.1038/s41586-019-1234-5'


def test_doi_prefers_footer_over_reference_dois():
    text = (
        "We build on prior work. 10.1145/3292500.3330919.\n"
        "© 2019 The Authors. doi:10.1038/S41586-019-1234-5"
    )
    assert extract_from_text(text)['doi'] == '10.1038/s41586-019-1234-5'


def test_doi_from_resolver_urls():
    assert extract_from_text("https://doi.org/10.48550/arXiv.2405.00001.")['doi'] == '10.48550/arxiv.2405.00001'
    assert extract_from_text("https://dx.doi.org/10.1038/s41586-019-1234-5")['doi'] == '10.1038/s41586-019-1234-5'


def test_arxiv_with_version_link_and_old_style():
    assert extract_from_text("arXiv:1706.03762v7 [cs.CL]")['arxiv_id'] == '1706.03762v7'
    assert extract_from_text("https://arxiv.org/abs/2405.00001.")['arxiv_id'] == '2405.00001'
    assert extract_from_text("see arXiv:hep-th/9901001.")['arxiv_id'] == 'hep-th/9901001'


def test_identify_pdf_title_and_doi(tmp_path):
    p = tmp_path / "t.pdf"
    _make_pdf(p, "Body text. doi:10.1038/s41586-019-1234-5", meta={'title': 'Attention Is All You Need'})
    result = identify_pdf(p)
    assert result['title'] == 'Attention Is All You Need'
    assert result['doi'] == '10.1038/s41586-019-1234-5'


def test_identify_pdf_rejects_untrustworthy_metadata_titles(tmp_path):
    for index, bad in enumerate(('Untitled', 'abcde')):
        p = tmp_path / f"bad{index}.pdf"
        _make_pdf(p, "No identifiers in this text.", meta={'title': bad})
        result = identify_pdf(p)
        assert result['title'] is None
        assert result['doi'] is None


def test_identify_pdf_from_bytes(tmp_path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "arXiv:1706.03762v7")
    pdf_bytes = doc.tobytes()
    doc.close()
    assert identify_pdf(pdf_bytes)['arxiv_id'] == '1706.03762v7'


def test_identify_pdf_garbage_bytes_returns_all_none():
    assert identify_pdf(b'not a pdf') == ALL_NONE


def test_extract_from_text_without_identifiers():
    assert extract_from_text("") == ALL_NONE
    assert extract_from_text("A plain paragraph with no identifiers.") == ALL_NONE
    assert extract_from_text("no ids", {'title': 'short'}) == ALL_NONE


def test_meta_subject_and_keywords_doi_take_priority():
    text = "Refs: 10.1145/3292500.3330919. Footer: doi:10.1038/s41586-019-1234-5"
    assert extract_from_text(text, {'subject': 'doi:10.1038/xyz'})['doi'] == '10.1038/xyz'
    assert extract_from_text("no ids", {'keywords': 'kw; https://doi.org/10.1038/abc'})['doi'] == '10.1038/abc'


# --- R01: candidates carry provenance; reference-list DOIs must not win ------

def test_reference_section_doi_not_selected_over_body_doi():
    # The last DOI of the first pages can sit inside the reference list; the
    # document's own body DOI must win regardless of extraction order.
    text = (
        "Actual New Paper. See also 10.1234/actual-paper.\n"
        "\nReferences\n"
        "A. Author. 10.1234/cited-paper.\n"
        "B. Other. 10.1234/ref-two."
    )
    assert extract_from_text(text)['doi'] == '10.1234/actual-paper'


def test_reference_section_before_own_doi_still_prefers_own():
    # 参考文献可能先出现：reference-zone candidates lose to later body ones;
    # a labeled self DOI beats bare reference DOIs even inside the same zone.
    text = (
        "\nReferences\n"
        "A. Author. 10.1234/cited-paper.\n"
        "\nActual New Paper. doi:10.1234/actual-paper"
    )
    assert extract_from_text(text)['doi'] == '10.1234/actual-paper'


def test_reference_only_doi_reported_as_weak_candidate():
    text = "Body without identifiers.\n\nReferences\nA. Author. 10.1234/cited-paper."
    result = extract_candidates(text)
    assert result['doi'] == '10.1234/cited-paper'
    assert result['doi_kind'] == 'reference'
    assert result['doi_candidates'] == [
        {'doi': '10.1234/cited-paper', 'kind': 'reference', 'labeled': False},
    ]


def test_extract_candidates_reports_kinds_and_labeled_source():
    result = extract_candidates(
        "Intro. doi:10.1234/self\n\nReferences\n10.1234/cited-a.",
        {'subject': '10.1234/meta'},
    )
    assert result['doi'] == '10.1234/meta'
    assert result['doi_kind'] == 'metadata'
    assert [(c['doi'], c['kind'], c['labeled']) for c in result['doi_candidates']] == [
        ('10.1234/meta', 'metadata', False),
        ('10.1234/self', 'body', True),
        ('10.1234/cited-a', 'reference', False),
    ]


def test_arxiv_candidates_reported_with_kinds():
    text = (
        "Extending Prior Approaches\n"
        "arXiv:2601.00001v1\n"
        "\nReferences\n"
        "arXiv:1706.03762"
    )
    result = extract_candidates(text)
    assert result['arxiv_id'] == '2601.00001v1'
    assert result['arxiv_kind'] == 'body'
    assert [(c['arxiv_id'], c['kind']) for c in result['arxiv_candidates']] == [
        ('2601.00001v1', 'body'),
        ('1706.03762', 'reference'),
    ]
