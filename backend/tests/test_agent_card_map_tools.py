"""Agent tools reading saved review artifacts: paper cards and literature maps."""
import json
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.agent.provenance import tool_sources
from app.agent.tools import TOOLS, get_tool, tool_schemas
from app.db.engine import get_engine
from app.models import Paper
from app.models.base import utcnow
from app.models.card import PaperCard
from app.models.review import LibraryReview, ReviewPaper, ReviewMap
from app.reviews import service

FRONTEND_LABELS = (Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'pages'
                   / 'agentActivityModel.ts')

CARD = {
    'problem': {'value': '恢复稀疏观测下的波场', 'quote': 'We restore the wavefield.',
                'status': 'quote_verified', 'found_in': 'abstract', 'pages': [1],
                'missing_numbers': [], 'similarity': 1.0},
    'mechanism': {'value': '物理约束的迭代循环', 'quote': 'a physics-constrained loop',
                  'status': 'quote_verified', 'found_in': 'abstract', 'pages': [1],
                  'missing_numbers': [], 'similarity': 1.0},
    'data_setting': {'value': '合成二维数据', 'quote': 'synthetic 2D data',
                     'status': 'quote_verified', 'found_in': 'abstract', 'pages': [2],
                     'missing_numbers': [], 'similarity': 1.0},
    'contributions': [{'value': '精度提升到 52.7', 'quote': 'improves to 52.7',
                       'status': 'number_mismatch', 'found_in': 'full_text', 'pages': [3],
                       'missing_numbers': ['52.7'], 'similarity': 0.9}],
    'boundary': {'value': '仅验证了合成数据', 'quote': '',
                 'status': 'no_quote', 'found_in': None, 'pages': [],
                 'missing_numbers': [], 'similarity': None},
    'metadata': {'title': 'Sparse recovery', 'authors': ['Doe, Jane'], 'year': 2021},
    'evidence_level': 'abstract', 'verify_version': 3,
}


def _seed_paper(title='Sparse recovery', **kwargs):
    with Session(get_engine()) as s:
        paper = Paper(source='manual', title=title, **kwargs)
        s.add(paper)
        s.commit()
        s.refresh(paper)
        return paper.id


def _seed_review(review_id, question, paper_ids, updated_at=None, **kwargs):
    with Session(get_engine()) as s:
        row = LibraryReview(id=review_id, question=question, **kwargs)
        if updated_at is not None:
            row.updated_at = updated_at
        s.add(row)
        for pid in paper_ids:
            s.add(ReviewPaper(review_id=review_id, paper_id=pid, title=f'论文 {pid}'))
        s.commit()


def _seed_card(paper_id, card=CARD, status='done', warning=''):
    with Session(get_engine()) as s:
        s.add(PaperCard(paper_id=paper_id, fingerprint='fp', status=status,
                        card_json=json.dumps(card, ensure_ascii=False), model='fake',
                        warning=warning, version=2))
        s.commit()


def test_get_paper_card_returns_fields_quotes_pages_and_review(client):
    pid = _seed_paper()
    _seed_review('review-a', '稀疏恢复综述', [pid])
    _seed_card(pid)
    tool = get_tool('get_paper_card')
    with Session(get_engine()) as s:
        out = json.loads(tool.run(s, paper_id=pid))
    assert out['paper_id'] == pid and out['title'] == 'Sparse recovery'
    assert out['card_status'] == 'done'
    assert out['review'] == {'review_id': 'review-a', 'title': '稀疏恢复综述'}
    assert out['card']['problem']['quote'] == 'We restore the wavefield.'
    assert out['card']['data_setting']['pages'] == [2]
    assert out['updated_at'] and out['card_version'] == 2
    assert out['verification'] == {'quote_verified': 3, 'number_mismatch': 1, 'no_quote': 1}
    assert 'other_reviews' not in out


def test_get_paper_card_without_card_points_to_full_text(client):
    pid = _seed_paper()
    _seed_review('review-empty', '未生成卡片', [pid])
    tool = get_tool('get_paper_card')
    with Session(get_engine()) as s:
        out = json.loads(tool.run(s, paper_id=pid))
    assert out['card_status'] is None and 'card' not in out
    assert 'get_paper_full_text' in out['note']


def test_get_paper_card_missing_paper_reports_error(client):
    with Session(get_engine()) as s:
        out = json.loads(get_tool('get_paper_card').run(s, paper_id=99999))
    assert out['error'] == 'paper 99999 not found'
    _seed_paper(is_deleted=True)
    with Session(get_engine()) as s:
        deleted = s.exec(select(Paper).where(Paper.is_deleted == True)).one()  # noqa: E712
        gone = json.loads(get_tool('get_paper_card').run(s, paper_id=deleted.id))
    assert gone['error'] == f'paper {deleted.id} not found'


def test_get_paper_card_multiple_reviews_prefers_latest_and_lists_others(client):
    from datetime import timedelta
    pid = _seed_paper()
    _seed_review('review-old', '旧综述', [pid], updated_at=utcnow() - timedelta(days=2))
    _seed_review('review-new', '新综述', [pid], updated_at=utcnow())
    _seed_card(pid)
    tool = get_tool('get_paper_card')
    with Session(get_engine()) as s:
        out = json.loads(tool.run(s, paper_id=pid))
    assert out['review']['review_id'] == 'review-new'
    assert out['other_reviews'] == [{'review_id': 'review-old', 'title': '旧综述'}]
    assert 'review_id' in out['note']
    with Session(get_engine()) as s:
        chosen = json.loads(tool.run(s, paper_id=pid, review_id='review-old'))
    assert chosen['review']['review_id'] == 'review-old'
    assert chosen['other_reviews'] == [{'review_id': 'review-new', 'title': '新综述'}]


def test_get_paper_card_review_id_not_a_member_is_still_usable(client):
    pid = _seed_paper()
    _seed_review('review-a', '含该论文', [pid])
    _seed_review('review-b', '不含该论文', [])
    _seed_card(pid)
    with Session(get_engine()) as s:
        out = json.loads(get_tool('get_paper_card').run(s, paper_id=pid, review_id='review-b'))
    assert out['review'] == {'review_id': 'review-b', 'title': '不含该论文'}
    assert '不在该综述' in out['note']
    with Session(get_engine()) as s:
        missing = json.loads(get_tool('get_paper_card').run(s, paper_id=pid, review_id='nope'))
    assert missing['error'] == '综述任务不存在'


def _seed_map(review_id, paper_ids, status='ready', themes=None,
              assignments=None, syntheses=None, overview=None, stage='文献地图已生成'):
    with Session(get_engine()) as s:
        row = s.exec(select(ReviewMap).where(ReviewMap.review_id == review_id)).first()
        if row is None:
            row = ReviewMap(review_id=review_id)
        row.status = status
        row.stage = stage
        row.themes_json = service.encode(themes if themes is not None else [])
        row.assignments_json = service.encode(assignments or {})
        row.syntheses_json = service.encode(syntheses or {})
        row.overview_json = service.encode(overview or {})
        s.add(row)
        s.commit()


def _theme(tid, name):
    return {'id': tid, 'name': name, 'definition': f'{name}的定义', 'include': '纳入', 'exclude': '不纳入'}


def _synthesis(paper_id):
    return {'trend': '从稀疏恢复演进到检索增强。',
            'open_questions': [{'question': '实测数据上是否成立？', 'why': 'w',
                                'cannot_claim': '不能据合成数据宣称', 'cards': [paper_id]}],
            'combination_opportunities': [{'idea': '结合物理约束', 'expected': 'e', 'risk': 'r',
                                           'cards': [paper_id]}],
            'representative': [{'paper_id': paper_id, 'why': '代表'}],
            'stats': {'count': 1}, 'fingerprint': 'abc'}


def _seed_map_review(count=4):
    ids = [_seed_paper(title=f'Paper {i}') for i in range(count)]
    review_id = 'map-review-' + uuid4().hex[:8]
    _seed_review(review_id, '地图综述', ids)
    themes = [_theme('T1', '检索增强'), _theme('T2', '稀疏恢复'), _theme('T3', '物理约束'),
              _theme('T4', '数据条件'), _theme('T5', '评价方法')]
    assignments = {str(pid): {'themes': ['T1', 'T2'] if index < 2 else (['T3'] if index == 2 else []),
                              'reason': '机制匹配'} for index, pid in enumerate(ids)}
    syntheses = {'T1': _synthesis(ids[0]), 'T2': _synthesis(ids[1]), 'T3': _synthesis(ids[2])}
    overview = {'summary': '主要路线围绕检索增强。', 'reading_route': [{'step': 1, 'goal': '入门',
                'papers': ids[:2], 'why': '开创'}], 'research_steps': ['先复现基线']}
    _seed_map(review_id, ids, status='ready', themes=themes, assignments=assignments,
              syntheses=syntheses, overview=overview)
    for pid in ids:
        _seed_card(pid)
    return review_id, ids


def test_read_literature_map_overview_with_overview_themes_and_counts(client):
    review_id, ids = _seed_map_review()
    with Session(get_engine()) as s:
        out = json.loads(get_tool('read_literature_map').run(s, review_id=review_id))
    assert out['status'] == 'ready' and out['stage'] == '文献地图已生成'
    assert out['question'] == '地图综述'
    assert out['overview']['summary'] == '主要路线围绕检索增强。'
    assert out['counts']['papers'] == 4 and out['counts']['themes'] == 5
    assert out['counts']['unassigned'] == 1  # 第四篇没有主题分配
    assert out['themes_total'] == 5 and out['next_offset'] == 3
    first = out['themes'][0]
    assert first['id'] == 'T1' and first['name'] == '检索增强'
    assert first['synthesis']['trend'] == '从稀疏恢复演进到检索增强。'
    assert first['synthesis']['open_questions'][0]['cannot_claim'] == '不能据合成数据宣称'
    assert first['papers'] == [{'paper_id': ids[0], 'title': 'Paper 0'},
                               {'paper_id': ids[1], 'title': 'Paper 1'}]
    assert first['papers_total'] == 2
    with Session(get_engine()) as s:
        page2 = json.loads(get_tool('read_literature_map').run(s, review_id=review_id, offset=3))
    assert [t['id'] for t in page2['themes']] == ['T4', 'T5']
    assert page2['next_offset'] is None


def test_read_literature_map_theme_by_name_or_id_with_card_values(client):
    review_id, ids = _seed_map_review()
    tool = get_tool('read_literature_map')
    with Session(get_engine()) as s:
        by_name = json.loads(tool.run(s, review_id=review_id, theme='检索增强'))
        by_id = json.loads(tool.run(s, review_id=review_id, theme='t1'))
    assert by_name['theme']['id'] == 'T1' and by_id['theme']['id'] == 'T1'
    assert by_name['synthesis'] == by_id['synthesis']
    assert 'fingerprint' not in by_name['synthesis']
    assert by_name['papers_total'] == 2 and by_name['next_offset'] is None
    card = by_name['papers'][0]['card']
    assert card['problem']['value'] == '恢复稀疏观测下的波场'
    assert card['problem']['pages'] == [1] and card['problem']['status'] == 'quote_verified'
    assert card['contributions'] == [{'value': '精度提升到 52.7', 'pages': [3],
                                      'status': 'number_mismatch'}]
    assert by_name['papers'][0]['card_status'] == 'done'


def test_read_literature_map_theme_pages_many_papers(client):
    pid = _seed_paper(title='Long theme')
    review_id = 'many-' + uuid4().hex[:8]
    ids = [pid] + [_seed_paper(title=f'Extra {i}') for i in range(12)]
    _seed_review(review_id, '多论文主题', ids)
    themes = [_theme('T1', '大主题')]
    assignments = {str(x): {'themes': ['T1'], 'reason': 'r'} for x in ids}
    _seed_map(review_id, ids, status='ready', themes=themes, assignments=assignments,
              syntheses={'T1': _synthesis(pid)}, overview={'summary': 's'})
    with Session(get_engine()) as s:
        first = json.loads(get_tool('read_literature_map').run(
            s, review_id=review_id, theme='T1'))
        second = json.loads(get_tool('read_literature_map').run(
            s, review_id=review_id, theme='T1', offset=first['next_offset']))
    assert len(first['papers']) == 10 and first['papers_total'] == 13
    assert len(second['papers']) == 3 and second['next_offset'] is None
    assert [p['paper_id'] for p in first['papers'] + second['papers']] == ids


def test_read_literature_map_overview_caps_member_papers_with_a_note(client):
    review_id = 'wide-' + uuid4().hex[:8]
    ids = [_seed_paper(title=f'Wide {i}') for i in range(24)]
    _seed_review(review_id, '宽主题', ids)
    themes = [_theme('T1', '大主题'), _theme('T2', '小主题')]
    assignments = {str(pid): {'themes': ['T1'], 'reason': 'r'} for pid in ids[:23]}
    assignments[str(ids[23])] = {'themes': ['T2'], 'reason': 'r'}
    _seed_map(review_id, ids, status='ready', themes=themes, assignments=assignments,
              syntheses={'T1': _synthesis(ids[0]), 'T2': _synthesis(ids[23])},
              overview={'summary': 's'})
    with Session(get_engine()) as s:
        out = json.loads(get_tool('read_literature_map').run(s, review_id=review_id))
    wide = next(t for t in out['themes'] if t['id'] == 'T1')
    assert wide['papers_total'] == 23 and len(wide['papers']) == 20
    assert '只列出前 20 篇' in out['note']
    with Session(get_engine()) as s:
        full = json.loads(get_tool('read_literature_map').run(s, review_id=review_id, theme='T1'))
    assert full['papers_total'] == 23 and len(full['papers']) == 10  # 主题页每页 10 篇
    assert full['next_offset'] == 10


def test_read_literature_map_unknown_theme_lists_available_themes(client):
    review_id, _ids = _seed_map_review()
    with Session(get_engine()) as s:
        out = json.loads(get_tool('read_literature_map').run(
            s, review_id=review_id, theme='不存在的主题'))
    assert out['theme_found'] is False
    assert [t['id'] for t in out['themes']] == ['T1', 'T2', 'T3', 'T4', 'T5']
    assert '没有匹配的主题' in out['note']


def test_read_literature_map_reports_missing_running_and_failed(client):
    pid = _seed_paper()
    tool = get_tool('read_literature_map')
    _seed_review('review-no-map', '没有地图', [pid])
    with Session(get_engine()) as s:
        none = json.loads(tool.run(s, review_id='review-no-map'))
    assert none['status'] == 'draft' and '还没有生成文献地图' in none['note']
    _seed_review('review-running', '运行中', [pid])
    _seed_map('review-running', [pid], status='running', stage='提出主题')
    with Session(get_engine()) as s:
        running = json.loads(tool.run(s, review_id='review-running'))
    assert running['status'] == 'running' and '正在生成' in running['note']
    _seed_review('review-failed', '失败', [pid])
    _seed_map('review-failed', [pid], status='failed', themes=[_theme('T1', '主题')])
    with Session(get_engine()) as s:
        failed = json.loads(tool.run(s, review_id='review-failed'))
    # themes exist from an earlier partial run: return them with a status note
    assert failed['status'] == 'failed' and '上次运行失败' in failed['note']
    with Session(get_engine()) as s:
        missing = json.loads(tool.run(s, review_id='not-here'))
    assert missing['error'] == '综述任务不存在'


def test_artifact_tools_are_read_only_sources(client):
    # Card and map reads are generated/derived material, like read_review:
    # they must not become citable original-text sources.
    review_id, ids = _seed_map_review()
    with Session(get_engine()) as s:
        card_out = get_tool('get_paper_card').run(s, paper_id=ids[0])
        map_out = get_tool('read_literature_map').run(s, review_id=review_id)
    # The empty source lists below must not pass vacuously on error stubs:
    # first check both tools returned real derived content.
    card_data = json.loads(card_out)
    assert card_data['card_status'] == 'done'
    assert card_data['card']['problem']['quote'] == 'We restore the wavefield.'
    map_data = json.loads(map_out)
    assert map_data['status'] == 'ready' and map_data['themes_total'] == 5
    with Session(get_engine()) as s:
        assert tool_sources(s, 'get_paper_card', card_out) == []
        assert tool_sources(s, 'read_literature_map', map_out) == []


def test_artifact_tools_registered_with_declared_parameters():
    names = {tool.name for tool in TOOLS}
    assert 'get_paper_card' in names and 'read_literature_map' in names
    schemas = {s['function']['name'] for s in tool_schemas()}
    assert {'get_paper_card', 'read_literature_map'} <= schemas
    card = get_tool('get_paper_card')
    assert card.parameters['required'] == ['paper_id']
    assert set(card.parameters['properties']) == {'paper_id', 'review_id'}
    read_map = get_tool('read_literature_map')
    assert read_map.parameters['required'] == ['review_id']
    assert set(read_map.parameters['properties']) == {'review_id', 'theme', 'offset'}


def test_artifact_tools_are_exposed_over_mcp_and_chat_context():
    from app.api.chat_api import CHAT_SYSTEM_PROMPT
    from app.integrations import mcp_server
    assert 'get_paper_card' in mcp_server.READ_TOOL_NAMES
    assert 'read_literature_map' in mcp_server.READ_TOOL_NAMES
    exposed = {tool.name for tool in mcp_server.exposed_tools()}
    assert {'get_paper_card', 'read_literature_map'} <= exposed
    assert 'get_paper_card' in CHAT_SYSTEM_PROMPT and 'read_literature_map' in CHAT_SYSTEM_PROMPT
    labels = FRONTEND_LABELS.read_text(encoding='utf-8')
    assert 'get_paper_card' in labels and 'read_literature_map' in labels
