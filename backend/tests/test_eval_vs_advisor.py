import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from eval_vs_advisor import (accuracy_from_csv, align, card_stats, sample_sheet,
                             suggest_theme_map, theme_coverage, verified_rate_from_csv)

GOLD = {
    'themes': [
        {'name': '稀疏恢复', 'trend': 't', 'questions': [],
         'representative_dois': ['10.1000/a', '10.1000/b']},
        {'name': '检索增强', 'trend': 't', 'questions': [], 'representative_dois': ['10.1000/c']},
        {'name': '无代表', 'trend': 't', 'questions': [], 'representative_dois': []},
    ],
    'papers': [
        {'key': 'G1', 'year': 2019, 'venue': 'V', 'title': 'Sparse Recovery!', 'doi': '10.1000/A',
         'themes': ['稀疏'], 'contribution': '开创稀疏恢复', 'boundary': '仅合成', 'verification': ''},
        {'key': 'G2', 'year': 2020, 'venue': 'V', 'title': 'Another Study', 'doi': '10.1000/b',
         'themes': ['稀疏'], 'contribution': '改进', 'boundary': 'b', 'verification': ''},
        {'key': 'G3', 'year': 2021, 'venue': 'V', 'title': 'Title Match Paper', 'doi': '',
         'themes': ['检索'], 'contribution': 'c', 'boundary': 'b', 'verification': ''},
        {'key': 'G4', 'year': 2021, 'venue': 'V', 'title': 'Unmatchable', 'doi': '10.1000/zzz',
         'themes': [], 'contribution': '', 'boundary': '', 'verification': ''},
    ],
}
MAP = {
    'themes': [{'id': 'T1', 'name': '我们一'}, {'id': 'T2', 'name': '我们二'},
               {'id': 'T3', 'name': '我们三'}, {'id': 'T4', 'name': '我们四'}],
    'papers': [
        {'paper_id': 1, 'title': 'sparse recovery!', 'doi': 'https://doi.org/10.1000/a', 'themes': ['T1']},
        {'paper_id': 2, 'title': 'Another  Study', 'doi': '', 'themes': ['T1', 'T2']},
        {'paper_id': 3, 'title': 'Title Match: Paper', 'doi': '10.1000/x3', 'themes': ['T2']},
        {'paper_id': 4, 'title': 'Leftover', 'doi': '', 'themes': []},
    ],
}
CARDS = [
    {'paper_id': 1, 'status': 'done', 'card': {'evidence_level': 'full_text',
     'problem': {'value': 'v', 'status': 'quote_verified'},
     'mechanism': {'value': 'v', 'status': 'quote_verified'},
     'data_setting': {'value': 'v', 'status': 'number_mismatch'},
     'boundary': {'value': 'v', 'status': 'no_quote'},
     'contributions': [{'value': 'v', 'status': 'quote_verified'}]}},
    {'paper_id': 2, 'status': 'done', 'card': {'evidence_level': 'abstract',
     'problem': {'value': 'v', 'status': 'quote_verified'},
     'mechanism': {'value': 'v', 'status': 'quote_not_found'},
     'data_setting': {'value': 'v', 'status': 'no_quote'},
     'boundary': {'value': 'v', 'status': 'unverifiable'},
     'contributions': []}},
]


def test_align_by_doi_with_case_and_prefix_and_title_fallback():
    result = align(GOLD['papers'], MAP['papers'])
    pairs = {(a['gold_key'], a['paper_id'], a['by']) for a in result['aligned']}
    assert ('G1', 1, 'doi') in pairs  # 大小写与前缀不影响
    assert ('G2', 2, 'title') in pairs  # DOI 为空回退到规范化题名（多空格不影响）
    assert ('G3', 3, 'title') in pairs  # 标点去除后匹配
    assert result['unaligned_gold'] == ['G4']
    assert result['unaligned_map'] == [4]


def test_suggest_theme_map_picks_top_counts_and_empty_when_no_hits():
    aligned = align(GOLD['papers'], MAP['papers'])['aligned']
    suggested = suggest_theme_map(GOLD, MAP, aligned)
    assert suggested['稀疏恢复'] == ['T1', 'T2']  # T1 命中 2 次、T2 命中 1 次
    assert suggested['检索增强'] == []  # 代表论文未对齐
    assert suggested['无代表'] == []


def test_theme_coverage_counts_and_recall():
    aligned = align(GOLD['papers'], MAP['papers'])['aligned']
    theme_map = {'稀疏恢复': ['T1'], '检索增强': [], '无代表': []}
    coverage = theme_coverage(GOLD, MAP, aligned, theme_map)
    assert coverage['covered'] == 1 and coverage['total_gold_themes'] == 3
    rows = {row['theme']: row for row in coverage['rows']}
    assert rows['稀疏恢复']['recalled'] == 2 and rows['稀疏恢复']['representatives'] == 2
    assert rows['稀疏恢复']['recall'] == 1.0
    assert rows['检索增强']['recalled'] == 0
    assert coverage['recalled_total'] == 2 and coverage['representatives_total'] == 3
    assert coverage['overall_recall'] == round(2 / 3, 4)


def test_card_stats_counts_by_status_and_evidence():
    stats = card_stats(CARDS)
    assert stats['fields_total'] == 9
    assert stats['status_total'] == {'quote_verified': 4, 'number_mismatch': 1,
                                     'quote_not_found': 1, 'no_quote': 2, 'unverifiable': 1}
    assert stats['by_evidence']['full_text']['fields'] == 5
    assert stats['by_evidence']['abstract']['statuses']['quote_not_found'] == 1
    problem = {(item['paper_id'], item['status']) for item in stats['problem_papers']}
    assert problem == {(1, 'number_mismatch'), (2, 'quote_not_found')}


def test_sample_sheet_deterministic_and_caps_at_available():
    aligned = align(GOLD['papers'], MAP['papers'])['aligned']
    first_csv, _ = sample_sheet(GOLD, CARDS, aligned, n=2, seed=7)
    second_csv, _ = sample_sheet(GOLD, CARDS, aligned, n=2, seed=7)
    assert first_csv == second_csv  # 同一种子结果相同
    assert first_csv.startswith('\ufeff')
    big_csv, _ = sample_sheet(GOLD, CARDS, aligned, n=30, seed=7)
    assert big_csv.count('\n') == 4  # n 大于可用论文数时取全部（表头 + 3 篇）
    import csv
    import io
    rows = list(csv.reader(io.StringIO(first_csv.lstrip('\ufeff'))))
    assert rows[0][0] == '导师编号' and rows[0][7] == '判定' and rows[0][8] == '备注'
    assert all(row[7] == '' and row[8] == '' for row in rows[1:])  # 判定与备注留空


def test_accuracy_and_verified_rate_from_filled_and_blank_csv():
    aligned = align(GOLD['papers'], MAP['papers'])['aligned']
    csv_text, _ = sample_sheet(GOLD, CARDS, aligned, n=3, seed=1)
    blank = accuracy_from_csv(csv_text)
    assert blank == {'filled': 0, 'correct': 0, 'accuracy': None}  # 未填写 → 待填写
    import csv
    import io
    rows = list(csv.reader(io.StringIO(csv_text.lstrip('\ufeff'))))
    rows[1][7] = '正确'
    rows[2][7] = '部分正确'
    filled = '\ufeff' + '\r\n'.join(','.join(row) for row in rows)
    result = accuracy_from_csv(filled)
    assert result['filled'] == 2 and result['correct'] == 1
    assert result['accuracy'] == 0.5
    rate = verified_rate_from_csv(filled)
    assert rate['fields'] > 0 and 0 <= rate['rate'] <= 1  # 只统计判定为“正确”的行
