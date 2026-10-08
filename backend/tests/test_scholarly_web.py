import json

from app.agent import research_actions as actions
from app.agent.provenance import tool_sources


def install(monkeypatch, data, host='api.openalex.org', path='/works/W123'):
    url = 'https://' + host + path
    raw = json.dumps(data)
    monkeypatch.setattr(actions, 'fetch_page', lambda _: (url, raw.encode(), 'application/json', 'utf-8'))
    return url, raw


def test_openalex_abstract_and_source_links_precede_large_catalogue_fields(monkeypatch):
    row = {'title': 'FWI with relative amplitudes', 'doi': 'https://doi.org/10.1234/test',
           'concepts': [{'display_name': 'Unrelated metadata'}] * 500,
           'abstract_inverted_index': {'noise': [3], 'We': [0], 'relative': [5], 'preserve': [4], 'model': [1], 'correlated': [2], 'amplitudes.': [6]},
           'best_oa_location': {'pdf_url': 'https://university.example/paper.pdf'},
           'primary_location': {'landing_page_url': 'https://doi.org/10.1234/test'}}
    url, raw = install(monkeypatch, row)
    result = json.loads(actions.read_webpage(None, url))
    assert result['content_region'] == 'scholarly_metadata'
    assert 'We model correlated noise preserve relative amplitudes.' in result['text']
    assert 'Unrelated metadata' not in result['text']
    assert result['next_start_char'] is None and len(raw) > 20000
    assert result['links'][0]['url'] == 'https://university.example/paper.pdf'
    assert 'not article full text' in result['text']
    sources = tool_sources(None, 'read_webpage', json.dumps(result))
    assert sources and 'We model correlated noise' in sources[0]['excerpt']


def test_crossref_candidates_remain_separate_with_jats_abstracts(monkeypatch):
    data = {'message': {'items': [
        {'title': ['First <i>study</i>'], 'DOI': '10.1000/a', 'abstract': '<jats:p>Preserves A &amp; B.</jats:p><jats:p>Has limitations.</jats:p>',
         'published-online': {'date-parts': [[2023]]}, 'published-print': {'date-parts': [[2024]]},
         'link': [{'URL': 'https://publisher.example/a.pdf'}]},
        {'title': ['Different candidate'], 'DOI': '10.1000/b'}]}}
    url, _ = install(monkeypatch, data, 'api.crossref.org', '/works?query=study')
    result = json.loads(actions.read_webpage(None, url))
    text = result['text']
    assert 'Record 1: First study' in text and 'Record 2: Different candidate' in text
    assert 'Preserves A & B.\nHas limitations.' in text
    assert '2023' in text and '2024' in text
    assert 'Abstract: Not provided' in text
    assert [r['url'] for r in result['links']] == ['https://publisher.example/a.pdf', 'https://doi.org/10.1000/a', 'https://doi.org/10.1000/b']


def test_original_json_remains_readable_and_view_pagination_is_lossless(monkeypatch):
    url, raw = install(monkeypatch, {'title': 'Study', 'abstract_inverted_index': {'word': list(range(300))}, 'unmodeled_field': 'keep me'})
    whole = json.loads(actions.read_webpage(None, url))
    first = json.loads(actions.read_webpage(None, url, max_chars=500))
    rest = json.loads(actions.read_webpage(None, url, start_char=first['next_start_char']))
    assert first['text'] + rest['text'] == whole['text']
    original = json.loads(actions.read_webpage(None, url, raw_json=True))
    assert original['text'] == raw and original['content_region'] == 'document'


def test_other_json_and_changed_api_shapes_fall_back_to_original(monkeypatch):
    cases = [('example.org', '/works/W1', {'title': 'Not a known scholarly API'}),
             ('api.openalex.org', '/authors/A1', {'display_name': 'An author'}),
             ('api.crossref.org', '/works/10/a', {'message': 'upstream error'}),
             ('api.openalex.org', '/works/W1', {'title': 'Study', 'primary_location': 'new schema'})]
    for host, path, data in cases:
        url, raw = install(monkeypatch, data, host, path)
        result = json.loads(actions.read_webpage(None, url))
        assert result['text'] == raw and result['content_region'] == 'document'


def test_sparse_abstract_indices_and_missing_abstract_do_not_invent_text(monkeypatch):
    url, _ = install(monkeypatch, {'results': [
        {'title': 'Sparse', 'abstract_inverted_index': {'Last': [10**12], 'First': [0], 'invalid': [False, -1, '1']}},
        {'title': 'No abstract', 'abstract_inverted_index': None}]})
    result = json.loads(actions.read_webpage(None, url))
    assert 'Abstract: First Last' in result['text']
    assert 'Abstract: Not provided' in result['text']
    assert 'invalid' not in result['text']
