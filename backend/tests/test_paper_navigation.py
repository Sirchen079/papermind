"""Reading must reach experimental details and retain the pages actually read."""
import json

from sqlmodel import Session, SQLModel

from app.agent.provenance import tool_sources
from app.agent.tools import t_get_paper_full_text
from app.db.engine import make_engine
from app.models import Paper


def seed(text):
    engine = make_engine(':memory:')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(source='manual', title='Test methods', full_text=text)
        session.add(paper)
        session.commit()
        return engine, paper.id


def test_query_exposes_late_setup_and_preserves_each_source_page():
    text = ('<!-- page:1 -->\nOur extractor processes evidence.\n' + 'Background. ' * 120 +
            '\n<!-- page:2 -->\nUnrelated details.\n' + 'Body. ' * 150 +
            '\n<!-- page:3 -->\nImplementation: the extractor is Small-A; the reader is Large-B.\n' +
            'Other details. ' * 100)
    engine, pid = seed(text)
    with Session(engine) as session:
        first = json.loads(t_get_paper_full_text(session, pid, query='extractor', max_chars=500))
        assert first['pages'] == [1] and 'Large-B' not in first['text']
        assert first['match_count'] == 2
        assert len(first['other_matches']) == 1
        preview = first['other_matches'][0]
        assert 3 in preview['pages'] and 'Large-B' in preview['text']
        assert preview['text'] == text[preview['start_char']:preview['end_char']]
        sources = tool_sources(session, 'get_paper_full_text', json.dumps(first))
        assert len(sources) == 2
        assert sources[0]['pages'] == [1]
        assert sources[1]['excerpt'] == preview['text']
        assert sources[1]['pages'] == preview['pages']
        later = json.loads(t_get_paper_full_text(session, pid, query='extractor',
                                               start_char=first['next_match_start_char'], max_chars=500))
        assert later['match_char'] > first['match_char']
        assert 'Large-B' in later['text']
        assert later['next_match_start_char'] is None


def test_pdf_page_read_is_bounded_and_can_continue_by_offset():
    text = '<!-- page:2 -->\nPrinted page 100. Method A.\n<!-- page:4 -->\nPrinted page 102. Method B.'
    engine, pid = seed(text)
    with Session(engine) as session:
        page = json.loads(t_get_paper_full_text(session, pid, page=2, start_char=9999))
        assert page['pages'] == [2]
        assert 'Method A' in page['text'] and 'Method B' not in page['text']
        rest = json.loads(t_get_paper_full_text(session, pid, start_char=page['next_start_char']))
        assert rest['pages'] == [4] and 'Method B' in rest['text']
        absent = t_get_paper_full_text(session, pid, page=100)
        assert 'text' not in json.loads(absent)
        assert tool_sources(session, 'get_paper_full_text', absent) == []
        wrong_page_query = json.loads(t_get_paper_full_text(session, pid, page=2, query='Method B'))
        assert wrong_page_query['match_found'] is False


def test_wrapped_phrase_matches_original_offsets_without_casefold_shift():
    text = '<!-- page:1 -->\nİ contains a Unicode uppercase expansion.\nTraining\n  Hardware: eight GPUs.'
    engine, pid = seed(text)
    with Session(engine) as session:
        found = json.loads(t_get_paper_full_text(session, pid, query='training hardware'))
        assert found['match_char'] == text.index('Training')
        assert found['text'] == text[found['start_char']:found['end_char']]
        assert found['pages'] == [1]


def test_many_hits_include_appendix_and_pagination_does_not_skip_hits():
    text = '\n'.join(f'<!-- page:{page} -->\nTraining details {page}. ' + 'x ' * 300
                     for page in range(1, 21))
    engine, pid = seed(text)
    with Session(engine) as session:
        first = json.loads(t_get_paper_full_text(session, pid, query='training', max_chars=500))
        assert first['match_count'] == 20
        assert len(first['other_matches']) == 8
        assert 20 in first['other_matches'][-1]['pages']
        seen = [first['match_char']]
        while first['next_match_start_char'] is not None:
            first = json.loads(t_get_paper_full_text(session, pid, query='training', max_chars=500,
                                                   start_char=first['next_match_start_char']))
            seen.append(first['match_char'])
        assert len(seen) == len(set(seen)) == 20


def test_unmarked_text_stays_readable_without_inventing_pdf_pages():
    text = 'extractor introduction. ' + 'x ' * 900 + 'extractor detailed implementation.'
    engine, pid = seed(text)
    with Session(engine) as session:
        found = json.loads(t_get_paper_full_text(session, pid, query='extractor', max_chars=500))
        assert found['pages'] == []
        assert found['other_matches'][0]['pages'] == []
        assert 'implementation' in found['other_matches'][0]['text']
        missing = json.loads(t_get_paper_full_text(session, pid, page=1))
        assert 'text' not in missing


def test_section_read_includes_subsections_without_table_or_title_duplicates():
    text = ('<!-- page:1 -->\nAbstract\nA brief abstract.\n1\nIntroduction\nBackground.\n'
            '2\nMethods\nProcedure follows.\n2.1\nInputs\nText input.\n'
            '<!-- page:2 -->\nMethods\nGPT4\n0.7\n2.2\nDecoding\nNeeds controlled search.\n'
            '3\nExperiments\nEvaluation.\nReferences\nBibliography.\n'
            '<!-- page:3 -->\nA\nImplementation Details\nPractical requirements.')
    engine, pid = seed(text)
    with Session(engine) as session:
        outline = t_get_paper_full_text(session, pid, outline_only=True)
        data = json.loads(outline)
        assert 'text' not in data and tool_sources(session, 'get_paper_full_text', outline) == []
        assert [s['number'] for s in data['sections']] == ['', '1', '2', '2.1', '2.2', '3', '', 'A']
        read = json.loads(t_get_paper_full_text(session, pid, section='Methods'))
        assert read['text'] == text[text.index('2\nMethods'):text.index('3\nExperiments')]
        assert read['pages'] == [1, 2] and read['section_complete']
        assert read['next_start_char'] is None
        assert 'controlled search' in read['text']
        sources = tool_sources(session, 'get_paper_full_text', json.dumps(read))
        assert len(sources) == 1 and sources[0]['pages'] == [1, 2]
        appendix = json.loads(t_get_paper_full_text(session, pid, section='A'))
        assert appendix['pages'] == [3] and 'Practical requirements' in appendix['text']


def test_section_continuation_is_exact_and_bounded():
    text = ('<!-- page:1 -->\n1 Introduction\nIntro.\n2 Methods\n' + 'Long procedure. ' * 100 +
            '\n2.1 Implementation\n' + 'Details. ' * 100 + '\n3 Results\nShould not be included.')
    engine, pid = seed(text)
    with Session(engine) as session:
        parts = []
        start = 0
        while True:
            row = json.loads(t_get_paper_full_text(session, pid, section='2', max_chars=500, start_char=start))
            parts.append(row['text'])
            if row['section_complete']:
                assert row['next_start_char'] is None
                break
            assert row['next_start_char'] > start
            start = row['next_start_char']
        assert ''.join(parts) == text[text.index('2 Methods'):text.index('3 Results')]
        exhausted = json.loads(t_get_paper_full_text(session, pid, section='2', start_char=len(text)))
        assert exhausted['text'] == '' and exhausted['next_start_char'] is None


def test_missing_ambiguous_and_outside_section_keep_fallback_navigation():
    text = ('<!-- page:1 -->\n1 Introduction\nContext.\n'
            '<!-- page:2 -->\n2 Methods\n2.1 Model Setup\nSmall model.\n'
            '2.2 Evaluation Setup\nBenchmark.\n3 Results\nFindings.')
    engine, pid = seed(text)
    with Session(engine) as session:
        for kwargs in [dict(section='missing'), dict(section='Setup'), dict(section='2', page=1),
                       dict(section='2', query='Context')]:
            raw = t_get_paper_full_text(session, pid, **kwargs)
            row = json.loads(raw)
            assert 'text' not in row and row['sections']
            assert tool_sources(session, 'get_paper_full_text', raw) == []
        precise = json.loads(t_get_paper_full_text(session, pid, section='2.1 Model Setup'))
        assert 'Small model.' in precise['text'] and 'Benchmark.' not in precise['text']
        page = json.loads(t_get_paper_full_text(session, pid, page=1))
        assert 'Context.' in page['text']


def test_outline_rejects_table_counts_page_numbers_and_early_multiple_choice():
    from app.agent.paper_navigation import paper_sections
    text = ('<!-- page:1 -->\n1\nIntroduction\nA. First possible answer\nB. Second possible answer\n'
            '# Instance\n100\n# Span\n200\n'
            '2\nMethods\n2.1\nAlgorithm\n3\nGPT4\n42\nText\n'
            '3\nResults\nMeasured results.\nReferences\nSome references.\n'
            'A\nExtra Experiments\nAppendix text.')
    sections = paper_sections(text)
    assert [row['title'] for row in sections] == ['Introduction', 'Methods', 'Algorithm', 'Results',
                                                'References', 'Extra Experiments']
    for section in sections:
        assert section['end_char'] > section['heading_end_char']


def test_markdown_and_unnumbered_text_have_offsets_without_invented_pages():
    from app.agent.paper_navigation import paper_sections
    text = '# Overview\nBackground.\n## Procedure\nSteps.\n# Evaluation\nMetrics.'
    sections = paper_sections(text)
    assert [row['title'] for row in sections] == ['Overview', 'Procedure', 'Evaluation']
    assert sections[0]['end_char'] == text.index('# Evaluation')
    assert all(row['pages'] == [] for row in sections)
    raw = paper_sections('Abstract\nSummary.\nMethods\nSteps.\nResults\nFindings.')
    assert [row['title'] for row in raw] == ['Abstract', 'Methods', 'Results']


def test_standalone_pdf_heading_takes_precedence_over_preceding_numbered_list():
    from app.agent.paper_navigation import paper_sections
    text = ('<!-- page:1 -->\n1\nIntroduction\nContext.\n2\nRelated Work\nPrior work.\n'
            '3. Lack of open-source datasets for long-answer\nbenchmarking.\n'
            '3\nSystem Description\nActual procedure.\n3.1\nScorer\nScoring steps.\n'
            '4\nData\nExamples.')
    sections = paper_sections(text)
    method = next(row for row in sections if row['number'] == '3')
    assert method['title'] == 'System Description'
    assert method['start_char'] == text.index('3\nSystem Description')
    assert method['end_char'] == text.index('4\nData')
