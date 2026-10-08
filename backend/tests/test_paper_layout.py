"""Table comparisons need physical rows, old indexes and source pages retained."""
import json

import pymupdf
from sqlmodel import Session, SQLModel

from app.agent.provenance import tool_sources
from app.agent.tools import t_get_paper_full_text
from app.db.engine import make_engine
from app.models import Paper


def seeded(env, *, blank=False, full_text='<!-- page:1 -->\nLegacy extraction unchanged.'):
    path = env / 'data' / 'pdfs' / 'table.pdf'
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        page = doc.new_page()
        if not blank:
            # PDF object order differs from displayed rows: each column was
            # written at once, as happens in scientific result tables.
            for x, cells in [(60, ['Method', 'Baseline', 'New method']),
                             (240, ['Score', '39.2', '42.1'])]:
                for y, cell in zip([60, 90, 120], cells):
                    page.insert_text((x, y), cell)
            for i in range(24):
                page.insert_text((60, 170 + i * 20), f'Condition {i}: measured under the same setup.')
        doc.new_page().insert_text((60, 60), 'Page two separate evidence.')
        doc.save(path)
    engine = make_engine(':memory:')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(source='manual', title='Table comparison', pdf_path='table.pdf', full_text=full_text)
        session.add(paper)
        session.commit()
        return engine, paper.id, path


def test_layout_reads_actual_rows_without_rewriting_legacy_text_and_retains_source(env):
    engine, pid, _ = seeded(env)
    with Session(engine) as session:
        raw = t_get_paper_full_text(session, pid, page=1, layout=True)
        row = json.loads(raw)
        lines = row['text'].splitlines()
        assert any('Baseline' in line and '39.2' in line and '42.1' not in line for line in lines)
        assert any('New method' in line and '42.1' in line and '39.2' not in line for line in lines)
        assert 'Page two' not in row['text']
        source = tool_sources(session, 'get_paper_full_text', raw)[0]
        assert source['pages'] == [1] and source['excerpt'] == row['text']
        assert source['material_kind'] == 'original_text' and '版面文本' in source['locator']
        assert session.get(Paper, pid).full_text == '<!-- page:1 -->\nLegacy extraction unchanged.'
        assert json.loads(t_get_paper_full_text(session, pid, page=1))['text'].endswith('Legacy extraction unchanged.')


def test_page_local_pagination_never_repeats_first_page_prefix(env):
    engine, pid, _ = seeded(env)
    with Session(engine) as session:
        whole = json.loads(t_get_paper_full_text(session, pid, page=1, layout=True))['text']
        parts, offset = [], 0
        while True:
            row = json.loads(t_get_paper_full_text(session, pid, page=1, layout=True,
                                                 start_char=offset, max_chars=500))
            parts.append(row['text'])
            if row['next_start_char'] is None:
                break
            assert row['next_start_char'] > offset
            offset = row['next_start_char']
        assert len(parts) > 1 and ''.join(parts) == whole
        end = t_get_paper_full_text(session, pid, page=1, layout=True, start_char=999999)
        assert json.loads(end)['text'] == '' and tool_sources(session, 'get_paper_full_text', end) == []


def test_layout_can_read_pdf_when_index_text_is_absent(env):
    engine, pid, _ = seeded(env, full_text=None)
    with Session(engine) as session:
        row = json.loads(t_get_paper_full_text(session, pid, page=2, layout=True))
        assert row['pages'] == [2] and 'Page two' in row['text']


def test_missing_scan_invalid_page_and_conflicting_modes_do_not_become_evidence(env):
    engine, pid, path = seeded(env, blank=True)
    with Session(engine) as session:
        for kwargs in [dict(page=1), dict(page=3), dict(page=0), dict(page=True),
                       dict(), dict(page=1, section='Methods'), dict(page=1, query='value'),
                       dict(page=1, outline_only=True)]:
            raw = t_get_paper_full_text(session, pid, layout=True, **kwargs)
            assert 'text' not in json.loads(raw)
            assert tool_sources(session, 'get_paper_full_text', raw) == []
        path.unlink()
        raw = t_get_paper_full_text(session, pid, page=2, layout=True)
        assert 'text' not in json.loads(raw) and tool_sources(session, 'get_paper_full_text', raw) == []
        assert 'Legacy extraction' in t_get_paper_full_text(session, pid)


def test_deleted_paper_and_outside_library_file_are_not_read(env):
    engine, pid, path = seeded(env)
    with Session(engine) as session:
        paper = session.get(Paper, pid)
        paper.is_deleted = True
        assert 'error' in json.loads(t_get_paper_full_text(session, pid, page=1, layout=True))
        paper.is_deleted = False
        outside = env / 'other.pdf'
        outside.write_bytes(path.read_bytes())
        paper.pdf_path = str(outside)
        raw = t_get_paper_full_text(session, pid, page=1, layout=True)
        assert 'text' not in json.loads(raw) and tool_sources(session, 'get_paper_full_text', raw) == []
