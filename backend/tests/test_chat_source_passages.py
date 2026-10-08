import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper, PaperChunk, Provider, Model
from app.agent.tools import t_get_paper_full_text
from app.agent.provenance import merge_sources, tool_sources
from app.agent.source_passages import paper_source, text_pages
from app.api.chat_api import _sources_from_hits
from app.providers.client import ToolCall, ToolTurn


def test_full_text_slice_locates_mid_page_and_cross_page_evidence(client):
    text = '<!-- page:22 -->\nPrevious page.\n<!-- page:23 -->\n' + 'context ' * 200
    text += 'Fixed retriever: 0.7 PopQA and 2.0\n<!-- page:24 -->\npoints on TriviaQA, changing the generator. ' + 'more ' * 200
    text += '\n<!-- page:25 -->\nUnrelated conclusion.'
    with Session(get_engine()) as s:
        p = Paper(source='manual', title='Cross-page comparison', full_text=text)
        s.add(p); s.commit()
        row = json.loads(t_get_paper_full_text(s, p.id, query='Fixed retriever', max_chars=800))
        assert row['pages'] == [23, 24]
        assert 'TriviaQA' in row['text'] and '<!-- page:23 -->' not in row['text']
        source = tool_sources(s, 'get_paper_full_text', json.dumps(row))[0]
        assert source['excerpt'] == row['text'] and source['pages'] == [23, 24]
        assert source['locator'] == 'PDF 第 23、24 页'
        assert tool_sources(s, 'get_paper_full_text', t_get_paper_full_text(s, p.id, query='absent')) == []


def test_page_locations_do_not_guess_from_prose_or_empty_pages():
    assert text_pages('Table 23 refers to page 24.', 0, 100) == []
    text = '<!-- page:1 -->\n\n<!-- page:2 -->\nActual text.\n<!-- page:3 -->'
    assert text_pages(text, 0, len(text)) == [2]
    assert text_pages(text, len(text), len(text)) == []


def test_initial_sources_preserve_distinct_passages_and_source_categories():
    paper = Paper(id=1, source='manual', title='One study')
    prefix = 'shared opening ' * 40
    chunks = [PaperChunk(paper_id=1, ordinal=0, text='One study\nAbstract'),
              PaperChunk(paper_id=1, ordinal=2, text='[第 23 页]\n' + prefix + 'FIRST CONDITION'),
              PaperChunk(paper_id=1, ordinal=3, text='[第 24 页]\n' + prefix + 'SECOND CONDITION')]
    sources = _sources_from_hits([(c, 1.0, paper) for c in [*chunks, chunks[-1]]])
    assert len(sources) == 3
    assert sources[0]['source_type'] == 'metadata' and sources[0]['pages'] == []
    assert sources[1]['pages'] == [23] and sources[2]['pages'] == [24]
    assert 'SECOND CONDITION' in sources[2]['excerpt']
    a = paper_source(1, paper.title, prefix + 'A', 'full_text', 'reader', [23])
    b = paper_source(1, paper.title, prefix + 'B', 'full_text', 'reader', [23])
    assert a['snippet'] == b['snippet']
    combined = [a]; merge_sources(combined, [b, a])
    assert len(combined) == 2


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_full_passage_and_pages_survive_transport_and_conversation_reload(client, monkeypatch, suffix):
    original = '<!-- page:7 -->\n' + 'Long evidence before the condition. ' * 25 + 'FIXED GENERATOR CONDITION'
    with Session(get_engine()) as s:
        p = Paper(source='manual', title='Evidence', full_text=original)
        provider = Provider(name='test', type='openai_chat')
        s.add_all([p, provider]); s.commit()
        s.add(Model(provider_id=provider.id, model_id='test', role_default='chat')); s.commit()
        pid = p.id
    monkeypatch.setattr('app.rag.index.retrieve', lambda *a, **k: [])
    sequence = [ToolTurn('', [ToolCall('read', 'get_paper_full_text', {'paper_id': pid})], 1, 1, 2),
                ToolTurn(f'Compare the conditions [P{pid}].', [], 1, 1, 2)]
    cid = client.post('/api/chat/conversations').json()['id']
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=sequence):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Read the comparison conditions'})
    assert response.status_code == 200
    row = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert row['sources'][0]['excerpt'] == original
    assert row['sources'][0]['pages'] == [7]
    assert 'FIXED GENERATOR CONDITION' not in row['sources'][0]['snippet']
    if suffix.endswith('stream'):
        data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert any(item.get('sources', [{}])[0].get('excerpt') == original for item in data if item.get('sources'))
    else:
        assert response.json()['sources'] == row['sources']
