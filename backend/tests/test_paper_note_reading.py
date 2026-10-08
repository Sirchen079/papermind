"""Saved research findings remain readable after conversation context is gone."""
import json

from sqlmodel import Session, SQLModel

from app.agent.provenance import tool_sources
from app.agent.research_actions import save_paper_note
from app.agent.tools import get_tool, t_get_paper, t_search_research_notes
from app.db.engine import make_engine
from app.models import Paper, PaperNote
from app.reading.service import patch_note


def test_save_discover_read_all_pages_and_researcher_edit_across_sessions():
    engine = make_engine(':memory:')
    SQLModel.metadata.create_all(engine)
    content = '已有发现\n' + '实验条件与方法。\n' * 1800 + '\n边界：提示路线也有效，见正文表 2。'
    with Session(engine) as session:
        paper = Paper(source='manual', title='Reading reuse')
        session.add(paper)
        session.commit()
        pid = paper.id
        saved = json.loads(save_paper_note(session, pid, content))
        duplicate = json.loads(save_paper_note(session, pid, content))
        assert duplicate['reused'] and duplicate['id'] == saved['id']
        assert saved['read'] == {'tool': 'read_paper_notes', 'paper_id': pid, 'note_id': saved['id']}

    # A new session has no original chat history or source text to fall back on.
    with Session(engine) as session:
        catalog = json.loads(t_get_paper(session, pid))['saved_notes']
        assert catalog['total'] == 1 and catalog['items'][0]['note_id'] == saved['id']
        hit = json.loads(t_search_research_notes(session, '提示路线'))[0]
        assert '提示路线' not in hit['snippet']  # the important finding is beyond search preview
        assert hit['read'] == saved['read']
        read = get_tool('read_paper_notes').run
        index = read(session, pid)
        assert tool_sources(session, 'read_paper_notes', index) == []
        parts, start = [], 0
        while True:
            raw = read(session, pid, hit['note_id'], start_char=start, max_chars=999999)
            part = json.loads(raw)
            assert len(part['text']) <= 12000
            parts.append(part['text'])
            source = tool_sources(session, 'read_paper_notes', raw)[0]
            assert source['material_kind'] == 'research_record'
            assert source['research_note']['note_id'] == saved['id']
            assert source['research_note']['start_char'] == start
            start = part['next_start_char']
            if start is None:
                break
        assert ''.join(parts) == content
        assert len(parts) > 1
        assert tool_sources(session, 'read_paper_notes', read(session, pid, saved['id'], start_char=len(content))) == []
        patch_note(session, pid, saved['id'], {'content': '研究者补充：先核对实验设置。'})
    with Session(engine) as session:
        updated = json.loads(read(session, pid, saved['id']))
        assert updated['text'] == '研究者补充：先核对实验设置。'


def test_catalog_pagination_and_missing_deleted_or_wrong_paper():
    engine = make_engine(':memory:')
    SQLModel.metadata.create_all(engine)
    read = get_tool('read_paper_notes').run
    with Session(engine) as session:
        papers = [Paper(source='manual', title=title) for title in ('active', 'other', 'deleted')]
        session.add_all(papers)
        session.commit()
        for i in range(23):
            session.add(PaperNote(paper_id=papers[0].id, content=f'Note {i}'))
        deleted_note = PaperNote(paper_id=papers[2].id, content='private deleted note')
        session.add(deleted_note)
        papers[2].is_deleted = True
        session.add(papers[2])
        session.commit()
        first = json.loads(read(session, papers[0].id))
        second = json.loads(read(session, papers[0].id, offset=first['next_offset']))
        assert first['total'] == second['total'] == 23
        ids = [row['note_id'] for row in first['items'] + second['items']]
        assert len(ids) == len(set(ids)) == 23
        assert second['next_offset'] is None
        assert json.loads(read(session, papers[1].id))['total'] == 0
        for pid, nid in [(papers[1].id, ids[0]), (papers[2].id, deleted_note.id), (99999, ids[0]), (papers[0].id, 99999)]:
            raw = read(session, pid, nid)
            assert 'error' in json.loads(raw)
            assert tool_sources(session, 'read_paper_notes', raw) == []
