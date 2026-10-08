import copy
import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.agent.document_revisions import capture_answer, revise_document
from app.agent.provenance import public_sources, tool_sources
from app.agent.saved_documents import read_saved_document
from app.agent.source_kinds import research_scope_kind, web_material_kind
from app.agent.source_memory import carry_sources, read_chat_sources
from app.agent.tools import t_get_paper
from app.db.engine import get_engine
from app.models import Conversation, Message, Paper, Summary
from app.providers.client import ToolCall, ToolTurn
from test_chat_api import _seed_chat_provider, _turn


def test_legacy_materials_are_described_without_rewriting_snapshots():
    assert research_scope_kind('excerpt') == 'research_record'
    assert research_scope_kind('full_text_span') == 'original_text'
    assert research_scope_kind('abstract') == 'abstract_metadata'
    assert research_scope_kind('unknown') == 'unknown'
    rows = [
        {'paper_id': 1, 'source_type': 'metadata', 'retrieved_by': 'search_library', 'excerpt': 'Candidate'},
        {'paper_id': 1, 'source_type': 'summary', 'retrieved_by': 'get_paper', 'excerpt': 'Author abstract'},
        {'paper_id': 1, 'source_type': 'full_text', 'pages': [8], 'excerpt': 'Conditions'},
        {'paper_id': 1, 'snippet': 'Old record with unknown scope'},
        {'source_type': 'web', 'url': 'https://export.arxiv.org/api/query?search_query=all:test', 'excerpt': '<feed>no results</feed>'},
        {'source_type': 'web', 'url': 'https://api.crossref.org/works/10.1234/example', 'content_region': 'scholarly_metadata', 'excerpt': 'Title and abstract'},
    ]
    frozen = copy.deepcopy(rows)
    view = public_sources(rows)
    assert [r['material_kind'] for r in view['sources']] == ['discovery', 'abstract_metadata', 'original_text', 'unknown']
    assert [r['material_kind'] for r in view['web_sources']] == ['discovery', 'abstract_metadata']
    assert rows == frozen
    assert all('verified' not in r for r in [*view['sources'], *view['web_sources']])


def test_metadata_and_generated_analysis_are_preserved_separately(client):
    with Session(get_engine()) as session:
        p = Paper(source='manual', title='Study', abstract='The authors report observations.')
        session.add(p); session.commit()
        session.add(Summary(paper_id=p.id, content_json=json.dumps({'summary': 'A model interpretation.'}))); session.commit()
        sources = tool_sources(session, 'get_paper', t_get_paper(session, p.id))
        assert [r['material_kind'] for r in sources] == ['abstract_metadata', 'generated_analysis']
        assert sources[0]['excerpt'] == p.abstract
        assert 'model interpretation' in sources[1]['excerpt']
        assert all(r['pages'] == [] for r in sources)


@pytest.mark.parametrize('url,region,expected', [
    ('https://api.openalex.org/works?search=FWI', 'scholarly_metadata', 'discovery'),
    ('https://export.arxiv.org/api/query?id_list=2401.12345', 'document', 'abstract_metadata'),
    ('https://example.org/research?search=not-a-search-endpoint', 'article', 'webpage'),
    ('https://example.org/a.pdf', 'pdf_text', 'original_text'),
    ('https://example.org/a.pdf', 'page', 'webpage'),
])
def test_web_kind_uses_record_semantics_not_word_or_extension_guessing(url, region, expected):
    assert web_material_kind(url, region) == expected


def test_discovery_kind_survives_saved_source_rereads_and_source_indices(client):
    with Session(get_engine()) as session:
        paper = Paper(source='manual', title='Study'); conv = Conversation(title='Continue')
        session.add_all([paper, conv]); session.commit()
        candidate = {'paper_id': paper.id, 'title': paper.title, 'source_type': 'metadata', 'retrieved_by': 'search_library', 'excerpt': 'A short abstract', 'snippet': 'A short abstract'}
        original = {**candidate, 'source_type': 'full_text', 'retrieved_by': 'get_paper_full_text', 'pages': [11], 'excerpt': 'No noise and known source.'}
        source_rows = [candidate, original]
        old = Message(conversation_id=conv.id, role='assistant', content='A draft.', sources_json=json.dumps(source_rows))
        session.add(old); session.commit()
        saved = capture_answer(session, conv.id, old.id)
        revision = revise_document(session, conv.id, saved['filename'], 'A revised draft.')
        read = json.loads(read_saved_document(session, revision['message_id'], revision['filename'], part='source', source_index=0))
        assert read['material_kind'] == 'discovery' and read['text'] == candidate['excerpt']
        restored = tool_sources(session, 'read_saved_document', json.dumps(read))[0]
        assert restored['material_kind'] == 'discovery'
        current = Message(conversation_id=conv.id, role='user', content='Continue')
        session.add(current); session.commit()
        block, carried = carry_sources(session, conv.id, current.id, None, 3000)
        assert carried[0]['source_type'] == 'full_text'
        records = [json.loads(line) for line in block.splitlines()[2:]]
        assert [(r['source_index'], r['material_kind']) for r in records] == [(1, 'original_text'), (0, 'discovery')]
        session.info['chat_conversation_id'] = conv.id
        read = json.loads(read_chat_sources(session, old.id, 0))
        assert tool_sources(session, 'read_chat_sources', json.dumps(read))[0]['material_kind'] == 'discovery'
        assert json.loads(session.get(Message, old.id).sources_json) == source_rows


@pytest.mark.parametrize('suffix', ['messages', 'messages/stream'])
def test_search_candidates_and_read_pages_remain_distinct_through_chat(client, suffix):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        papers = [Paper(source='manual', title='FWI primary', abstract='FWI study', full_text='<!-- page:11 -->\nNo noise and known source.'),
                  Paper(source='manual', title='FWI candidate', abstract='Another FWI study')]
        session.add_all(papers); session.commit(); ids = [p.id for p in papers]
    turns = [ToolTurn('', [ToolCall('find', 'search_library', {'query': 'FWI'})], 1, 1, 2),
             ToolTurn('', [ToolCall('read', 'get_paper_full_text', {'paper_id': ids[0], 'page': 11})], 1, 1, 2),
             _turn('The synthetic example assumes no noise; other candidates remain to be read.')]
    cid = client.post('/api/chat/conversations').json()['id']
    with patch('app.providers.client.ProviderClient.complete_with_tools', side_effect=turns):
        response = client.post(f'/api/chat/conversations/{cid}/{suffix}', json={'content': 'Find FWI and read the first paper'})
    assert response.status_code == 200
    answer = client.get(f'/api/chat/conversations/{cid}').json()['messages'][-1]
    assert [(s['paper_id'], s['material_kind']) for s in answer['sources']] == [(ids[0], 'discovery'), (ids[1], 'discovery'), (ids[0], 'original_text')]
    assert answer['sources'][-1]['pages'] == [11]
    captured = client.post(f'/api/chat/conversations/{cid}/messages/{answer["id"]}/document').json()
    doc = client.get(f'/api/chat/saved-documents/{captured["message_id"]}', params={'filename': captured['filename']}).json()
    assert [s['material_kind'] for s in doc['sources']] == ['discovery', 'discovery', 'original_text']
    if suffix.endswith('stream'):
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert any(e.get('sources') == answer['sources'] for e in events)
