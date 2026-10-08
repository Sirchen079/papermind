import json
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper
from app.models.card import PaperCard
from app.reviews.cards import build_card, card_fingerprint, card_inputs, parse_card, save_card

BACKEND = Path(__file__).resolve().parent.parent

GOOD = {
    'problem': {'value': '恢复稀疏观测下的波场', 'quote': 'We restore the wavefield from sparse observations.'},
    'mechanism': {'value': '物理约束的迭代循环', 'quote': 'a physics-constrained loop'},
    'data_setting': {'value': '合成二维数据', 'quote': 'synthetic 2D data'},
    'contributions': [{'value': '精度提升到 52.7', 'quote': 'improves to 52.7'}],
    'boundary': {'value': '仅验证了合成数据', 'quote': ''},
}
ABSTRACT = ('We restore the wavefield from sparse observations. '
            'a physics-constrained loop; synthetic 2D data improves to 52.7.')


def _add_paper(**kwargs):
    with Session(get_engine()) as s:
        paper = Paper(source='manual', title='Sparse recovery', **kwargs)
        s.add(paper)
        s.commit()
        s.refresh(paper)
        pid = paper.id
    return pid


def _get_paper(pid):
    with Session(get_engine()) as s:
        return s.get(Paper, pid)


def _returning(payload):
    def complete(system, user):
        return payload

    return complete


def test_normal_json_builds_verified_card(client):
    pid = _add_paper(authors_json='["Doe, Jane", "Roe, Max"]', year=2021, venue='Geophysics',
                     doi='10.1000/x', abstract=ABSTRACT)
    result = build_card(_session(), _get_paper(pid), _returning(json.dumps(GOOD)))
    assert result['status'] == 'done' and result['warning'] == ''
    card = result['card']
    assert card['metadata']['title'] == 'Sparse recovery'
    assert card['metadata']['authors'] == ['Doe, Jane', 'Roe, Max']
    assert card['metadata']['year'] == 2021 and card['metadata']['venue'] == 'Geophysics'
    assert card['metadata']['links'] == ['https://doi.org/10.1000/x']
    assert card['evidence_level'] == 'abstract'
    assert card['problem']['status'] == 'quote_verified' and card['problem']['found_in'] == 'abstract'
    assert card['contributions'][0]['status'] == 'quote_verified'
    assert card['boundary']['status'] == 'no_quote'


def _session():
    return Session(get_engine())


def test_number_mismatch_marks_field(client):
    payload = json.dumps({**GOOD, 'contributions': [{'value': '精度提升到 52.7', 'quote': 'a physics-constrained loop'}]})
    pid = _add_paper(abstract=ABSTRACT)
    result = build_card(_session(), _get_paper(pid), _returning(payload))
    item = result['card']['contributions'][0]
    assert item['status'] == 'number_mismatch' and item['missing_numbers'] == ['52.7']


def test_parse_card_strips_fences_and_surrounding_prose():
    fenced = '```json\n' + json.dumps(GOOD) + '\n```'
    assert parse_card(fenced)['problem']['value'] == GOOD['problem']['value']
    prose = 'Here is the card you asked for:\n' + json.dumps(GOOD) + '\nHope this helps.'
    assert parse_card(prose)['data_setting']['value'] == '合成二维数据'


def test_bad_json_retried_once_then_succeeds(client):
    pid = _add_paper(abstract=ABSTRACT)
    calls = []

    def complete(system, user):
        calls.append(user)
        return 'not json at all' if len(calls) == 1 else json.dumps(GOOD)

    result = build_card(_session(), _get_paper(pid), complete)
    assert result['status'] == 'done'
    assert len(calls) == 2 and '上次输出不是合法 JSON' in calls[1]


def test_persistent_bad_json_falls_back_without_raising(client):
    pid = _add_paper(abstract=ABSTRACT)
    result = build_card(_session(), _get_paper(pid), _returning('still not json'))
    assert result['status'] == 'fallback'
    assert result['card'].keys() >= {'metadata', 'evidence_level'}
    assert result['warning'] == '卡片格式解析失败，保留元数据'


def test_complete_exception_falls_back_with_type_name(client):
    def complete(system, user):
        raise ValueError('provider down')

    pid = _add_paper(abstract=ABSTRACT)
    result = build_card(_session(), _get_paper(pid), complete)
    assert result['status'] == 'fallback' and result['warning'] == 'ValueError'


def test_abstract_only_skips_hybrid(client, monkeypatch):
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('no snippets expected')))
    pid = _add_paper(abstract=ABSTRACT)
    inputs = card_inputs(_session(), _get_paper(pid))
    assert inputs['snippets'] == '' and inputs['evidence_level'] == 'abstract'


def test_full_text_gathers_snippets_with_three_queries(client, monkeypatch):
    calls = []
    first = [SimpleNamespace(id=1, ordinal=0, text='title block'),
             SimpleNamespace(id=2, ordinal=1, text='method snippet here')]
    later = [SimpleNamespace(id=3, ordinal=2, text='limitation snippet')]

    def fake_hybrid(session, query, paper_ids, k=2):
        calls.append(query)
        return first if len(calls) == 1 else later

    monkeypatch.setattr('app.rag.scalable.hybrid', fake_hybrid)
    pid = _add_paper(abstract=ABSTRACT, full_text='full text body')
    inputs = card_inputs(_session(), _get_paper(pid))
    assert len(calls) == 3
    assert 'method snippet here' in inputs['snippets'] and 'limitation snippet' in inputs['snippets']
    assert 'title block' not in inputs['snippets']
    assert inputs['evidence_level'] == 'full_text'


def test_snippets_truncated_to_3000_chars(client, monkeypatch):
    counter = iter(range(100))

    def fake_hybrid(session, query, paper_ids, k=2):
        return [SimpleNamespace(id=next(counter), ordinal=1, text='x' * 2000)]

    monkeypatch.setattr('app.rag.scalable.hybrid', fake_hybrid)
    pid = _add_paper(abstract=ABSTRACT, full_text='body')
    inputs = card_inputs(_session(), _get_paper(pid))
    assert len(inputs['snippets']) == 3000


def test_hybrid_failure_leaves_snippets_empty(client, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError('index offline')

    monkeypatch.setattr('app.rag.scalable.hybrid', boom)
    pid = _add_paper(abstract=ABSTRACT, full_text='body')
    inputs = card_inputs(_session(), _get_paper(pid))
    assert inputs['snippets'] == '' and inputs['abstract'] == ABSTRACT


def test_metadata_only_never_calls_model(client):
    def complete(system, user):
        raise AssertionError('metadata-only paper must not call the model')

    pid = _add_paper()
    result = build_card(_session(), _get_paper(pid), complete)
    assert result == {'status': 'metadata_only',
                      'card': {'metadata': result['card']['metadata'], 'evidence_level': 'metadata'},
                      'warning': ''}


def test_contributions_truncated_to_three_and_empty_fails():
    five = {**GOOD, 'contributions': [{'value': f'c{i}', 'quote': ''} for i in range(5)]}
    assert len(parse_card(json.dumps(five))['contributions']) == 3
    zero = {**GOOD, 'contributions': []}
    assert parse_card(json.dumps(zero)) is None


def test_save_card_updates_row_and_bumps_version(client):
    pid = _add_paper(abstract=ABSTRACT)
    inputs = card_inputs(_session(), _get_paper(pid))
    fingerprint = card_fingerprint(inputs, 'fixture-model')
    result = build_card(_session(), _get_paper(pid), _returning(json.dumps(GOOD)))
    save_card(_session(), pid, fingerprint, result, 'fixture-model')
    with Session(get_engine()) as s:
        rows = s.exec(select(PaperCard)).all()
        assert len(rows) == 1 and rows[0].version == 1 and rows[0].status == 'done'
        assert rows[0].model == 'fixture-model' and rows[0].fingerprint == fingerprint
        assert json.loads(rows[0].card_json)['problem']['value'] == GOOD['problem']['value']
    save_card(_session(), pid, fingerprint, result, 'fixture-model')
    with Session(get_engine()) as s:
        rows = s.exec(select(PaperCard)).all()
        assert len(rows) == 1 and rows[0].version == 2


def test_card_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / 'card-mig.sqlite'
    cfg = Config(str(BACKEND / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BACKEND / 'migrations'))
    cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db}')
    command.upgrade(cfg, 'head')
    inspector = inspect(create_engine(f'sqlite:///{db}'))
    assert 'papercard' in inspector.get_table_names()
    columns = {column['name'] for column in inspector.get_columns('papercard')}
    assert {'id', 'paper_id', 'fingerprint', 'status', 'card_json', 'model', 'warning', 'version',
            'updated_at'} <= columns
    uniques = {tuple(uq['column_names']) for uq in inspector.get_unique_constraints('papercard')}
    indexes = {tuple(ix['column_names']) for ix in inspector.get_indexes('papercard')}
    assert ('paper_id',) in uniques | indexes
    command.downgrade(cfg, 'c5f9a3b7d201')
    inspector = inspect(create_engine(f'sqlite:///{db}'))
    assert 'papercard' not in inspector.get_table_names()
    assert 'paperdocument' in inspector.get_table_names()
