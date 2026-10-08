import json

from app.agent import research_actions as actions


def page(monkeypatch, html):
    monkeypatch.setattr(actions, 'fetch_page', lambda url: ('https://example.org/project/', html.encode(), 'text/html', 'utf-8'))


def test_article_links_are_not_displaced_by_site_navigation(monkeypatch):
    navigation = ''.join(f'<a href="/nav/{i}">Navigation {i}</a>' for i in range(60))
    page(monkeypatch, f'<html><nav>{navigation}</nav><main><a href="/tabs">Tab</a>'
         '<article><h1>Our method</h1><p>Published weights.</p>'
         '<a href="https://models.example.org/released">Model</a>'
         '<a href="./inference.py">Inference</a><script>hidden()</script>'
         '</article></main></html>')
    result = json.loads(actions.read_webpage(None, 'https://example.org/project/'))
    assert result['content_region'] == 'article'
    assert result['text'] == 'Our method\nPublished weights.\nModelInference'
    assert result['links'][:2] == [
        {'title': 'Model', 'url': 'https://models.example.org/released'},
        {'title': 'Inference', 'url': 'https://example.org/project/inference.py'},
    ]
    assert result['total_links'] == 63
    assert result['next_link_offset'] == 40
    assert 'hidden' not in result['text']


def test_main_or_whole_page_fallback_preserves_sources(monkeypatch):
    for region, body in [('main', '<main><p>Method details</p><a href="/model">Weights</a></main>'),
                         ('page', '<p>Method details</p><a href="/model">Weights</a>')]:
        page(monkeypatch, '<html><article><script>no readable content</script></article>' + body + '</html>')
        result = json.loads(actions.read_webpage(None, 'https://example.org'))
        assert result['content_region'] == region
        assert 'Method details' in result['text']
        assert result['links'][0]['url'] == 'https://example.org/model'


def test_all_content_links_remain_reachable_without_duplicate_slots(monkeypatch):
    body = ''.join(f'<a href="/model/{i}">Weights {i}</a>' for i in range(45))
    page(monkeypatch, '<html><article>' + body + '<a href="/model/0">Duplicate</a>'
         '<a href="javascript:alert(1)">Unsupported</a></article></html>')
    first = json.loads(actions.read_webpage(None, 'https://example.org'))
    rest = json.loads(actions.read_webpage(None, 'https://example.org', link_offset=first['next_link_offset']))
    assert first['total_links'] == 45 and len(first['links']) == 40
    assert len(rest['links']) == 5 and rest['next_link_offset'] is None
    assert len({item['url'] for item in first['links'] + rest['links']}) == 45


def test_small_related_article_does_not_replace_model_card(monkeypatch):
    page(monkeypatch, '<html><main><h1>Released compressor</h1>'
         '<p>The model uses BF16 weights. Run inference with the published checkpoint. '
         'Training a new model is optional. Hardware depends on the selected context length.</p>'
         '<a href="/files">Model files</a><article><a href="/related">Related paper</a></article>'
         '</main></html>')
    result = json.loads(actions.read_webpage(None, 'https://example.org'))
    assert result['content_region'] == 'main'
    assert 'BF16' in result['text']
    assert result['links'][0]['url'] == 'https://example.org/files'


def test_whole_page_links_remain_available_to_search_parser(monkeypatch):
    parser = actions.PageText()
    parser.feed('<html><nav><a href="/outside">Outside</a></nav>'
                '<main><article><a href="/inside">Inside</a></article></main></html>')
    assert [item['url'] for item in parser.links] == ['/outside', '/inside']
    assert [item['url'] for item in parser.readable()[1]] == ['/inside']


def test_table_values_keep_separators_and_plain_text_still_paginates(monkeypatch):
    page(monkeypatch, '<html><main><table><tr><th>Model</th><th>Memory</th></tr>'
         '<tr><td>A</td><td>12 GB</td></tr></table></main></html>')
    result = json.loads(actions.read_webpage(None, 'https://example.org'))
    assert 'Model Memory' in result['text'] and 'A 12 GB' in result['text']
    original = '# Inference\n' + 'public documentation ' * 100
    monkeypatch.setattr(actions, 'fetch_page', lambda url: (url, original.encode(), 'text/plain', 'utf-8'))
    first = json.loads(actions.read_webpage(None, 'https://example.org/README.md', max_chars=500))
    rest = json.loads(actions.read_webpage(None, 'https://example.org/README.md', start_char=first['next_start_char']))
    assert first['text'] + rest['text'] == original
    assert first['links'] == [] and first['content_region'] == 'document'
