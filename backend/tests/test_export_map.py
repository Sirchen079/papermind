import json
import re
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.reviews import service
from app.reviews.export_map import render_csv, render_docx, render_html, render_xlsx
from test_review_map import FakeMapModel

STATS = {'count': 2, 'years': {'2019': 1, '2020': 1},
         'setting': {'field': 1, 'synthetic': 1, 'both': 0, 'unknown': 0},
         'evidence': {'full_text': 1, 'abstract': 1, 'metadata': 0}}


def _field(value, quote='', status='quote_verified', found_in=None, pages=None, missing=None):
    return {'value': value, 'quote': quote, 'status': status, 'found_in': found_in,
            'pages': pages or [], 'missing_numbers': missing or []}


def _paper(pid, title, year, venue, doi, themes, level, card, authors=('Doe, Jane',)):
    return {'paper_id': pid, 'title': title, 'year': year, 'venue': venue, 'doi': doi,
            'themes': themes, 'evidence_level': level, 'card_status': 'done' if card else 'pending',
            'authors': list(authors), 'card': card}


PAYLOAD = {
    'question': '检索增强方法综述',
    'generated_at': '2026-10-08 12:00',
    'model': 'fake-model',
    'status': 'ready',
    'counts': {'papers': 4, 'cards_done': 3, 'assigned': 3, 'unassigned': 1},
    'themes': [
        {'id': 'T1', 'name': '稀疏恢复', 'definition': '稀疏采集下的波场恢复', 'include': '纳入', 'exclude': '不纳入'},
        {'id': 'T2', 'name': '检索增强', 'definition': '检索外部知识增强生成', 'include': '纳入', 'exclude': '不纳入'},
    ],
    'assignments': {
        '1': {'themes': ['T1'], 'reason': '机制匹配', 'fingerprint': 'x'},
        '2': {'themes': ['T2'], 'reason': '机制匹配', 'fingerprint': 'x'},
        '3': {'themes': ['T1', 'T2'], 'reason': '两者兼顾', 'fingerprint': 'x'},
        '4': {'themes': [], 'reason': '未能归类', 'fingerprint': 'x'},
    },
    'syntheses': {
        'T1': {
            'trend': '从稀疏恢复演进到物理约束迭代。',
            'stats': STATS,
            'open_questions': [
                {'question': '实测闭环是否成立', 'why': '仅有合成验证', 'cannot_claim': '不能宣称实测有效', 'cards': [1]},
                {'question': '来源缺失问题', 'why': 'w', 'cannot_claim': 'c', 'cards': [], 'source_missing': True},
            ],
            'combination_opportunities': [
                {'idea': '把物理约束与检索增强结合', 'expected': '更稳的恢复', 'risk': '检索噪声放大', 'cards': [1, 2]},
            ],
            'representative': [{'paper_id': 1, 'why': '开创性工作'}],
            'fingerprint': 'f1',
        },
        'T2': {'error': '本主题综合未完成，可重新运行', 'stats': STATS},
    },
    'overview': {
        'summary': '主要路线围绕检索增强与稀疏恢复，证据以合成数据为主。',
        'reading_route': [
            {'step': 1, 'goal': '理解基本问题', 'papers': [1, 2], 'why': '开创与代表作'},
            {'step': 2, 'goal': '进入前沿', 'papers': [], 'why': '待补充', 'source_missing': True},
        ],
        'research_steps': ['先复现经典基线', '在实测数据上验证'],
    },
    'papers': [
        _paper(1, 'Paper One', 2019, 'Geophysics', '10.1000/one', ['T1'], 'full_text', {
            'status': 'done', 'model': 'fake-model',
            'card': {
                'metadata': {'title': 'Paper One', 'year': 2019, 'venue': 'Geophysics',
                             'doi': '10.1000/one', 'links': ['https://doi.org/10.1000/one']},
                'evidence_level': 'full_text',
                'problem': _field('稀疏恢复', 'We restore the wavefield.', 'quote_verified', 'full_text', [3]),
                'mechanism': _field('物理约束'),
                'data_setting': _field('精度提升到 52.7', 'improves', 'number_mismatch', 'abstract', None, ['52.7']),
                'contributions': [_field('贡献一条', 'a physics-constrained loop', 'quote_not_found')],
                'boundary': _field('仅合成验证', '', 'unverifiable'),
            }}),
        _paper(2, 'Paper Two', 2020, 'Geophysics', '10.1000/two', ['T2'], 'abstract', {
            'status': 'done', 'model': 'fake-model',
            'card': {
                'metadata': {'title': 'Paper Two', 'year': 2020, 'venue': 'Geophysics', 'doi': '10.1000/two'},
                'evidence_level': 'abstract',
                'problem': _field('检索增强', 'Retrieval helps.', 'quote_verified', 'abstract'),
                'mechanism': _field('检索机制', 'Retrieval helps.', 'quote_verified', 'abstract'),
                'data_setting': _field('合成数据', 'Retrieval helps.', 'quote_verified', 'abstract'),
                'contributions': [_field('贡献', 'Retrieval helps.', 'quote_verified', 'abstract')],
                'boundary': _field('边界', 'Retrieval helps.', 'quote_verified', 'abstract'),
            }}),
        _paper(3, '<script>alert(1)</script>', 2020, ' Evil "Journal" ', '10.1000/evil', ['T1', 'T2'],
               'metadata', None, authors=('Eve, Adam',)),
        _paper(4, 'Paper Four', 2021, '', '', [], 'abstract', None),
    ],
}


def test_render_contains_themes_anchors_search_and_filter():
    out = render_html(PAYLOAD)
    assert '稀疏恢复' in out and '检索增强' in out
    for pid in (1, 2, 3, 4):
        assert f'id="p{pid}"' in out
    assert '<input' in out and '搜索' in out
    assert '<select' in out and '<option' in out


def test_render_is_self_contained_with_safe_hrefs():
    out = render_html(PAYLOAD)
    for banned in ('<script src', '<link', '@import', 'url(http'):
        assert banned not in out
    hrefs = re.findall(r'href="([^"]*)"', out)
    assert hrefs
    for href in hrefs:
        assert href.startswith('#p') or href.startswith('https://doi.org/'), href


def test_render_escapes_hostile_titles():
    out = render_html(PAYLOAD)
    assert '<script>alert(1)</script>' not in out
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in out


def test_render_shows_all_verification_labels():
    out = render_html(PAYLOAD)
    assert '已核对原文' in out
    assert '第 3 页' in out
    assert '（摘要）' in out
    assert '数字与原文不符' in out and '52.7' in out
    assert '未在原文找到引文' in out
    assert '模型归纳' in out
    assert '仅元数据，无法核对' in out


def test_render_marks_source_missing_and_failed_theme():
    out = render_html(PAYLOAD)
    assert '来源待补' in out
    assert '本主题综合未完成，可重新运行' in out


def test_export_endpoint_conflicts_unsupported_format_and_ok(client, monkeypatch):
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title=f'Paper {i}', year=2020,
                      abstract='Study of retrieval augmentation methods.') for i in range(4)]
        s.add_all(rows)
        s.commit()
        ids = [r.id for r in rows]
    fake = FakeMapModel()
    monkeypatch.setattr(service, 'pick_llm', lambda *_: (fake, SimpleNamespace(id=7, base_url=''), 'map-fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda *a, **k: [])
    response = client.post('/api/reviews', json={'request_id': str(uuid4()), 'question': '地图', 'paper_ids': ids})
    prefix = '/api/reviews/' + response.json()['id']
    res = client.get(prefix + '/map/export')
    assert res.status_code == 409
    assert res.json()['detail'] == '请先生成文献地图'
    assert client.post(prefix + '/map/run').status_code == 202
    res = client.get(prefix + '/map/export?format=pptx')  # 卡 16 扩展后 xlsx 已支持，换仍无效的格式
    assert res.status_code == 422
    res = client.get(prefix + '/map/export')
    assert res.status_code == 200
    assert res.headers['content-type'].startswith('text/html')
    assert 'attachment' in res.headers.get('content-disposition', '')
    assert '<!DOCTYPE html>' in res.text and '地图' in res.text


def test_render_xlsx_roundtrip():
    from io import BytesIO

    import openpyxl

    wb = openpyxl.load_workbook(BytesIO(render_xlsx(PAYLOAD)))
    assert wb.sheetnames == ['主表', '精读卡片', '主题与问题']
    main = wb['主表']
    assert main.max_row == len(PAYLOAD['papers']) + 1
    assert main.freeze_panes == 'A2'
    assert main.auto_filter.ref
    headers = [c.value for c in main[1]]
    assert headers[:3] == ['编号', '年份', '题名']
    cards = wb['精读卡片']
    assert cards.max_row == len(PAYLOAD['papers']) + 1
    assert '已核对原文' in str([c.value for c in cards[2]])
    themes_sheet = wb['主题与问题']
    assert themes_sheet.max_row == len(PAYLOAD['themes']) + 1


def test_render_docx_roundtrip():
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(render_docx(PAYLOAD)))
    text = '\n'.join(p.text for p in doc.paragraphs)
    for name in ('稀疏恢复', '检索增强'):
        assert name in text
    assert '精读卡片' in text
    assert '[P1] Paper One（2019）' in text


def test_render_csv_bom_and_quoting_roundtrip():
    import copy
    import csv
    import io

    payload = copy.deepcopy(PAYLOAD)
    payload['papers'][0]['title'] = 'Comma, and "quotes" title'
    text = render_csv(payload)
    assert text.startswith('\ufeff')
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == len(payload['papers']) + 1
    assert rows[1][2] == 'Comma, and "quotes" title'
    assert rows[1][0] == 'P1'


def test_render_bibtex_keys_and_roundtrip(client, monkeypatch):
    from app.ingestion.sources import parse_bibtex
    from app.reviews.export_map import map_payload, render_bibtex

    with Session(get_engine()) as s:
        first = Paper(source='manual', title='Same Topic', year=2020, citation_key='dupe2020same',
                      abstract='Abstract one.')
        second = Paper(source='manual', title='Same Topic Too', year=2020, citation_key='dupe2020same',
                       abstract='Abstract two.')
        s.add(first)
        s.add(second)
        s.commit()
        ids = [first.id, second.id]
    fake = FakeMapModel()
    monkeypatch.setattr(service, 'pick_llm', lambda *_: (fake, SimpleNamespace(id=7, base_url=''), 'map-fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda *a, **k: [])
    response = client.post('/api/reviews', json={'request_id': str(uuid4()), 'question': '地图',
                                                 'paper_ids': ids})
    prefix = '/api/reviews/' + response.json()['id']
    with Session(get_engine()) as s:
        payload = map_payload(s, prefix.rsplit('/', 1)[-1])
        text = render_bibtex(payload, s)
    keys = re.findall(r'@article\{([^,]+),', text)
    assert keys == ['dupe2020same', 'dupe2020same2']  # 键冲突第二个加后缀
    assert len(parse_bibtex(text)) == 2


def test_export_endpoint_all_formats(client, monkeypatch):
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title=f'Paper {i}', year=2020,
                      abstract='Study of retrieval augmentation methods.') for i in range(3)]
        s.add_all(rows)
        s.commit()
        ids = [r.id for r in rows]
    fake = FakeMapModel()
    monkeypatch.setattr(service, 'pick_llm', lambda *_: (fake, SimpleNamespace(id=7, base_url=''), 'map-fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda *a, **k: [])
    response = client.post('/api/reviews', json={'request_id': str(uuid4()), 'question': '地图', 'paper_ids': ids})
    prefix = '/api/reviews/' + response.json()['id']
    client.post(prefix + '/map/run')
    expected = {
        'html': 'text/html',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'csv': 'text/csv',
        'bib': 'application/x-bibtex',
    }
    for fmt, media in expected.items():
        res = client.get(prefix + f'/map/export?format={fmt}')
        assert res.status_code == 200, (fmt, res.status_code)
        assert res.headers['content-type'].startswith(media), (fmt, res.headers['content-type'])
        assert res.headers['content-disposition'].startswith('attachment')
        assert res.content


def test_render_marks_fuzzy_verified_fields_as_approximate():
    import copy

    payload = copy.deepcopy(PAYLOAD)
    payload['papers'][0]['card']['card']['problem']['similarity'] = 0.95
    out = render_html(payload)
    assert '近似核对原文' in out
    assert '已核对原文' in out  # similarity 为 1/未命中的字段不受影响


def test_export_neutralizes_formula_injection_in_xlsx_and_csv():
    import copy
    import csv
    import io
    from io import BytesIO

    import openpyxl

    payload = copy.deepcopy(PAYLOAD)
    payload['papers'][0]['title'] = '=HYPERLINK("http://x","y")'
    payload['themes'][0]['name'] = '+1+1'
    wb = openpyxl.load_workbook(BytesIO(render_xlsx(payload)))
    title_cell = wb['主表'].cell(row=2, column=3)
    assert title_cell.data_type != 'f'
    assert str(title_cell.value).startswith("'=")
    theme_cell = wb['主题与问题'].cell(row=2, column=1)
    assert theme_cell.data_type != 'f' and str(theme_cell.value).startswith("'+")
    text = render_csv(payload)
    title_row = next(r for r in csv.reader(io.StringIO(text)) if 'HYPERLINK' in r[2])
    assert title_row[2].startswith("'=")
    theme_col = next(r for r in csv.reader(io.StringIO(text)) if '+1+1' in r[6])
    assert theme_col[6].startswith("'+")


def test_export_survives_control_characters():
    import copy
    from io import BytesIO

    import openpyxl
    from docx import Document

    payload = copy.deepcopy(PAYLOAD)
    payload['papers'][2]['title'] = 'Bad\x0cTitle\x00Here'
    xlsx_bytes = render_xlsx(payload)  # openpyxl IllegalCharacterError 之前会在这里抛出
    docx_bytes = render_docx(payload)  # python-docx ValueError 之前会在这里抛出
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes))
    values = [str(c.value) for row in wb['主表'].iter_rows() for c in row]
    assert not any('\x0c' in v or '\x00' in v for v in values)
    text = '\n'.join(p.text for p in Document(BytesIO(docx_bytes)).paragraphs)
    assert '\x0c' not in text and '\x00' not in text


def test_export_keeps_plain_titles_and_numbers_untouched():
    from io import BytesIO

    import openpyxl

    wb = openpyxl.load_workbook(BytesIO(render_xlsx(PAYLOAD)))
    row2 = [c.value for c in wb['主表'][2]]
    assert row2[2] == 'Paper One'  # 普通题名不加引号
    assert row2[1] == 2019 and wb['主表'].cell(row=2, column=2).data_type == 'n'  # 年份数字原样
    assert wb['主表'].cell(row=2, column=3).data_type != 'f'
