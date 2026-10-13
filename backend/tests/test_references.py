"""P5a: GB/T 7714 与 APA 规范引用著录（纯函数 + 导出端点 style 参数）。"""
import itertools
import re

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.models.review import LibraryReview
from app.reviews import references


def base_paper(**over):
    row = dict(title='论标题', authors=['Albert Einstein', 'Bob Other'], year=2020,
               venue='Venue', volume='12', issue='3', pages='45-52',
               doi='10.1234/abc', arxiv_id=None)
    row.update(over)
    return row


def test_format_author_two_styles_and_passthrough():
    assert references.format_author('Albert Einstein', 'gbt') == 'EINSTEIN A'
    assert references.format_author('Given Middle Family', 'gbt') == 'FAMILY G M'
    assert references.format_author('Albert Einstein', 'apa') == 'Einstein, A.'
    assert references.format_author('Given Middle Family', 'apa') == 'Family, G. M.'
    for style in ('gbt', 'apa'):
        assert references.format_author('张三', style) == '张三'
        assert references.format_author('Plato', style) == 'Plato'
    assert references.format_author('Einstein, A.', 'gbt') == 'EINSTEIN A'
    assert references.format_author('Einstein, A.', 'apa') == 'Einstein, A.'
    assert references.format_author('Family, John Michael', 'gbt') == 'FAMILY J M'
    assert references.format_author('Family, John Michael', 'apa') == 'Family, J. M.'


def test_format_authors_join_rules_per_style():
    two = ['Albert Einstein', 'Bob Other']
    assert references.format_authors(two, 'gbt') == 'EINSTEIN A, OTHER B'
    assert references.format_authors(['Albert Einstein'], 'apa') == 'Einstein, A.'
    assert references.format_authors(two, 'apa') == 'Einstein, A., & Other, B.'
    three = ['Albert Einstein', 'Bob Other', 'Cara Third']
    assert references.format_authors(three, 'apa') == 'Einstein, A., Other, B., & Third, C.'
    assert references.format_authors(three, 'gbt') == 'EINSTEIN A, OTHER B, THIRD C'
    mixed = ['张三', 'Albert Einstein', 'Grace Hopper', 'Alan Turing']
    assert references.format_authors(mixed, 'gbt') == '张三, EINSTEIN A, HOPPER G, 等'
    western = ['Albert Einstein', 'Bob Other', 'Cara Third', 'Dan Fourth']
    assert references.format_authors(western, 'gbt') == 'EINSTEIN A, OTHER B, THIRD C, et al.'
    assert references.format_authors([], 'gbt') == ''
    assert references.format_authors([], 'apa') == ''
    many = [f'Author {i} Name{i}' for i in range(21)]
    left, sep, right = references.format_authors(many, 'apa').partition(', ... ')
    assert sep and right == 'Name20, A.'
    assert left.startswith('Name0, A., Name1, A.') and left.endswith('Name18, A.')
    assert 'Name19' not in left + right
    exactly20 = references.format_authors(many[:20], 'apa')
    assert exactly20.endswith(', & Name19, A.') and '...' not in exactly20


def test_format_reference_gbt_segments():
    assert references.format_reference(base_paper(), 'gbt', index=1) == (
        '[1] EINSTEIN A, OTHER B. 论标题[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.')
    assert references.format_reference(base_paper(), 'gbt') == (
        'EINSTEIN A, OTHER B. 论标题[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.')
    assert references.format_reference(base_paper(venue=None), 'gbt', index=2) == (
        '[2] EINSTEIN A, OTHER B. 论标题[J]. 2020, 12(3): 45-52. DOI: 10.1234/abc.')
    assert references.format_reference(base_paper(volume=None, issue=None, pages=None), 'gbt') == (
        'EINSTEIN A, OTHER B. 论标题[J]. Venue, 2020. DOI: 10.1234/abc.')
    assert references.format_reference(
        base_paper(doi=None, arxiv_id='2001.01234'), 'gbt', index=3) == (
        '[3] EINSTEIN A, OTHER B. 论标题[J]. Venue, 2020, 12(3): 45-52. arXiv: 2001.01234.')
    assert references.format_reference(
        base_paper(venue=None, volume=None, issue=None, pages=None, doi=None,
                   arxiv_id='2001.01234'), 'gbt') == (
        'EINSTEIN A, OTHER B. 论标题[J]. 2020. arXiv: 2001.01234.')


def test_format_reference_apa_segments():
    assert references.format_reference(base_paper(), 'apa') == (
        'Einstein, A., & Other, B. (2020). 论标题. Venue, 12(3), 45-52. https://doi.org/10.1234/abc')
    assert references.format_reference(base_paper(year=None), 'apa') == (
        'Einstein, A., & Other, B. (n.d.). 论标题. Venue, 12(3), 45-52. https://doi.org/10.1234/abc')
    assert references.format_reference(base_paper(authors=[]), 'apa') == (
        '论标题. (2020). Venue, 12(3), 45-52. https://doi.org/10.1234/abc')
    assert references.format_reference(base_paper(doi=None, arxiv_id='2001.01234'), 'apa') == (
        'Einstein, A., & Other, B. (2020). 论标题. Venue, 12(3), 45-52. arXiv: 2001.01234')
    assert references.format_reference(base_paper(venue=None), 'apa') == (
        'Einstein, A., & Other, B. (2020). 论标题. 12(3), 45-52. https://doi.org/10.1234/abc')


def test_format_reference_missing_fields_never_leave_dangling_punctuation():
    fields = {'title': [None, '论标题'], 'authors': [[], ['张三'], ['Albert Einstein', 'Bob Other']],
              'year': [None, 2020], 'venue': [None, 'Venue'], 'volume': [None, '12'],
              'issue': [None, '3'], 'pages': [None, '45-52'],
              'doi': [None, '10.1/x'], 'arxiv_id': [None, '2001.1']}
    names = list(fields)
    for style in ('gbt', 'apa'):
        for combo in itertools.product(*fields.values()):
            out = references.format_reference(dict(zip(names, combo)), style, index=1)
            assert '  ' not in out, out
            assert ' ,' not in out and ' .' not in out and ',,' not in out, out
            assert not out.endswith(' ') and not out.endswith(','), out
            assert out == out.strip(), out


def test_first_appearance_ids_keeps_order_and_dedupes():
    assert references.first_appearance_ids('a [P3] b [P1] c [P3] [P12] 再 [P1]') == [3, 1, 12]
    assert references.first_appearance_ids('正文没有引用标记。') == []


PAPERS = {
    5: dict(title='Paper Five', authors=['张三'], year=2019, venue=None, volume=None,
            issue=None, pages=None, doi=None, arxiv_id='1901.00001'),
    2: dict(title='Paper Two', authors=['Albert Einstein'], year=2020, venue='Venue',
            volume='12', issue='3', pages='45-52', doi='10.1234/abc', arxiv_id=None),
    7: dict(title='Paper Seven', authors=[], year=None, venue=None, volume=None,
            issue=None, pages=None, doi=None, arxiv_id=None),
}

CONTENT = ('# 检索方法综述\n\n正文先引 [P5] 再引 [P2]，重复 [P5]，未收录 [P999]。\n\n'
           '## 引用文献\n\n- [P5] Paper Five\n- [P2] Paper Two\n\n'
           '## 材料范围\n\n本次范围 2 篇；完成模型分析 2 篇。\n')


def test_render_gbt_renumbers_body_and_rebuilds_references():
    out = references.render_styled_markdown(CONTENT, PAPERS, 'gbt')
    body, rest = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 检索方法综述\n\n正文先引 [1] 再引 [2]，重复 [1]，未收录 [P999]。'
    entries, materials = rest.split('\n\n## 材料范围\n\n', 1)
    assert entries == ('[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n'
                       '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.')
    assert materials == '本次范围 2 篇；完成模型分析 2 篇。\n'


APA_YEAR = r'\d{4}[a-z]?|n\.d\.(?:-[a-z])?'


def _apa_marks(text: str) -> list[str]:
    """文内引用中「作者, 年份[后缀]」的年份部分，用于与列表双向对照。"""
    return re.findall(r'\([^(),]+(?: & [^(),]+| et al\.)?, (' + APA_YEAR + r')\)', text)


def _apa_list_years(text: str) -> list[str]:
    """参考列表条目中的年份标签（含括号），用于与文内引用双向对照。"""
    return re.findall(r'\((?:' + APA_YEAR + r')\)', text)


def test_render_apa_body_cites_match_list_entries():
    # R04 回归：旧实现把正文 [Pn] 改成 [1]/[2]，而 APA 列表没有编号，无法对应。
    # 契约变更：原 test_render_apa_lines_carry_no_index_prefix 只断言列表条目且按
    # 正文首现排序；修复后正文为作者—年份、列表按 APA 作者字母序，此为更强契约。
    content = ('# 检索\n\n正文 [P2] 与 [P5]，重复 [P2]。\n\n'
               '## 引用文献\n\n- [P2] Paper Two\n- [P5] Paper Five\n\n')
    out = references.render_styled_markdown(content, PAPERS, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '[1]' not in out and '[2]' not in out
    assert '[P2]' not in body and '[P5]' not in body
    assert body == '# 检索\n\n正文 (Einstein, 2020) 与 (张三, 2019)，重复 (Einstein, 2020)。'
    # 列表按 APA 作者字母序（Einstein 在张三前），不按正文首现顺序；重复引用同标签。
    assert entries.splitlines() == [
        'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc',
        '张三 (2019). Paper Five. arXiv: 1901.00001']
    assert _apa_marks(body) == ['2020', '2019', '2020']
    assert _apa_list_years(entries) == ['(2020)', '(2019)']


def test_render_apa_in_text_author_counts():
    papers = {
        1: dict(title='One', authors=['Ada Smith'], year=2020, venue=None, volume=None,
                issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Two', authors=['Ada Smith', 'Lee Jones'], year=2021, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        3: dict(title='Three', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2022,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n单独 [P1]、两名 [P2]、多名 [P3]。\n\n## 引用文献\n\n'
    body = references.render_styled_markdown(content, papers, 'apa').split('\n\n## 引用文献\n\n')[0]
    assert '(Smith, 2020)' in body
    assert '(Smith & Jones, 2021)' in body
    assert '(Smith et al., 2022)' in body


def test_render_apa_same_author_year_suffixes_shared_with_body():
    papers = {
        1: dict(title='Alpha Result', authors=['Ada Smith'], year=2020, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Follow-up', authors=['Ada Smith'], year=2020, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        3: dict(title='Earlier Work', authors=['Ada Smith'], year=2019, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        4: dict(title='Undated Note', authors=['Ada Smith'], year=None, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        5: dict(title='Undated Draft', authors=['Ada Smith'], year=None, venue=None,
                volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n[P1] 与 [P2] 同作者同年，先 [P3]，未标年份 [P4] 与 [P5]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(Smith, 2020a)' in body and '(Smith, 2020b)' in body and '(Smith, 2019)' in body
    assert '(Smith, n.d.-a)' in body and '(Smith, n.d.-b)' in body
    # 列表顺序与后缀均按 APA：同作者年份升序、无年份最前；同年组内按题名分 a/b。
    assert entries.splitlines() == [
        'Smith, A. (n.d.-a). Undated Draft.',
        'Smith, A. (n.d.-b). Undated Note.',
        'Smith, A. (2019). Earlier Work.',
        'Smith, A. (2020a). Alpha Result.',
        'Smith, A. (2020b). Beta Follow-up.']
    # 后缀一致性：正文与列表的年份标签一一对应，不是只看条目字符串。
    assert _apa_marks(body) == ['2020a', '2020b', '2019', 'n.d.-b', 'n.d.-a']
    assert _apa_list_years(entries) == [
        '(n.d.-a)', '(n.d.-b)', '(2019)', '(2020a)', '(2020b)']


def test_render_apa_multi_author_same_first_author_shares_suffixes():
    papers = {
        1: dict(title='Alpha Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Ada Smith', 'Rae Lane', 'Pia Moore'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n两项 [P1] 与 [P2] 文内都缩写成 Smith et al.。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    # 文内形式相同（均为 Smith et al., 2020），按列表顺序共享 a/b 后缀才可一一对应。
    assert '(Smith et al., 2020a)' in body and '(Smith et al., 2020b)' in body
    assert entries.splitlines() == [
        'Smith, A., Jones, L., & Kerr, M. (2020a). Alpha Meta.',
        'Smith, A., Lane, R., & Moore, P. (2020b). Beta Pool.']
    assert _apa_marks(body) == ['2020a', '2020b']


def test_render_apa_missing_author_or_year_marked_not_fabricated():
    papers = {
        1: dict(title='Anonymous Report', authors=[], year=2021, venue=None, volume=None,
                issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Dated Later', authors=['Bo Chu'], year=None, venue=None, volume=None,
                issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n缺作者 [P1]，缺年份 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    # 缺项如实呈现：无作者用题名代替、无年份用 n.d.，不编造作者或年份。
    assert '缺作者 (Anonymous Report, 2021)，缺年份 (Chu, n.d.)。' in body
    assert entries.splitlines() == [
        'Anonymous Report. (2021).',
        'Chu, B. (n.d.). Dated Later.']


def test_render_apa_keeps_unknown_marks_without_entries():
    content = ('# 检索\n\n已收录 [P2]，未收录 [P999]。\n\n'
               '## 引用文献\n\n- [P2] Paper Two\n- [P999] Ghost\n\n')
    out = references.render_styled_markdown(content, PAPERS, 'apa')
    # 未知来源局部保留可见标记：不消失、不编造条目、不使整份导出失败；
    # 已收录引用正常解析，两者互不影响。
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 检索\n\n已收录 (Einstein, 2020)，未收录 [P999]。'
    assert entries.splitlines() == [
        'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc']
    only_unknown = references.render_styled_markdown(
        '# 检索\n\n只有 [P999] 一条。\n\n## 引用文献\n\n- [P999] Ghost\n\n', PAPERS, 'apa')
    assert only_unknown == '# 检索\n\n只有 [P999] 一条。\n\n## 引用文献\n\n(正文未引用论文)'


def test_render_inserts_section_before_materials_when_refs_missing():
    content = '# 检索方法综述\n\n正文引 [P2]。\n\n## 材料范围\n\n本次范围 1 篇。\n'
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert out == ('# 检索方法综述\n\n正文引 [1]。\n\n'
                   '## 引用文献\n\n'
                   '[1] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.\n\n'
                   '## 材料范围\n\n本次范围 1 篇。\n')


def test_render_without_citations_marks_empty_section():
    content = ('# 检索方法综述\n\n正文没有引用任何论文。\n\n'
               '## 引用文献\n\n- [P9] Ghost\n\n## 材料范围\n\n本次范围 1 篇。\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    body, rest = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 检索方法综述\n\n正文没有引用任何论文。'
    assert rest == '(正文未引用论文)\n\n## 材料范围\n\n本次范围 1 篇。\n'


def test_render_keeps_unknown_ids_without_entries():
    content = '# 检索\n\n只有 [P999] 一条。\n\n## 引用文献\n\n- [P999] Ghost\n\n'
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert out == '# 检索\n\n只有 [P999] 一条。\n\n## 引用文献\n\n(正文未引用论文)'


def test_papers_for_loads_formatter_dicts(client):
    # client 提供按用例隔离且已建表的库：无夹具时本用例落在首次导入 app.config
    # 时冻结的默认库上，跟在任一 client 用例之后会命中空库（P5b 发现）。
    with Session(get_engine()) as s:
        row = Paper(source='manual', title='Paper Five', authors_json='["张三", "李四"]',
                    year=2019, venue='期刊', volume='6', pages='1-9', arxiv_id='1901.00001')
        s.add(row);s.commit();pid = row.id
        loaded = references.papers_for(s, [pid, pid, 987654])
    assert loaded == {pid: dict(title='Paper Five', authors=['张三', '李四'], year=2019,
                                venue='期刊', volume='6', issue=None, pages='1-9',
                                doi=None, arxiv_id='1901.00001')}
    with Session(get_engine()) as s:
        assert references.papers_for(s, []) == {}


def seed_review(client):
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                      year=2019, arxiv_id='1901.00001'),
                Paper(source='manual', title='Paper Two', authors_json='["Albert Einstein"]',
                      year=2020, venue='Venue', volume='12', issue='3', pages='45-52',
                      doi='10.1234/abc')]
        s.add_all(rows);s.commit();ids = [r.id for r in rows]
        content = (f'# 检索方法综述\n\n正文先引 [P{ids[0]}] 再引 [P{ids[1]}]。\n\n'
                   '## 引用文献\n\n'
                   f'- [P{ids[0]}] Paper Five\n- [P{ids[1]}] Paper Two\n\n'
                   '## 材料范围\n\n本次范围 2 篇；完成模型分析 2 篇。\n')
        s.add(LibraryReview(id='ref-export', question='检索方法综述', status='ready',
                            content=content, version=1))
        s.commit()
    return ids, content


def test_export_endpoint_styles(client):
    ids, content = seed_review(client)
    plain = client.get('/api/reviews/ref-export/export')
    assert plain.status_code == 200 and plain.text == content
    assert plain.headers['content-type'].startswith('text/markdown')
    weird = client.get('/api/reviews/ref-export/export', params={'style': 'chicago'})
    assert weird.status_code == 200 and weird.text == content
    gbt = client.get('/api/reviews/ref-export/export', params={'style': 'gbt'})
    assert gbt.status_code == 200
    assert gbt.headers['content-type'] == 'text/markdown; charset=utf-8'
    assert f'[P{ids[0]}]' not in gbt.text.split('## 引用文献')[0]
    entries = gbt.text.split('\n\n## 引用文献\n\n', 1)[1].split('\n\n## 材料范围\n\n')[0].splitlines()
    assert entries[0] == '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.'
    assert entries[1] == '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.'
    apa = client.get('/api/reviews/ref-export/export', params={'style': 'apa'})
    assert apa.status_code == 200
    apa_body, apa_rest = apa.text.split('\n\n## 引用文献\n\n', 1)
    # 契约变更(R04)：APA 文内引用是作者—年份（可与列表对应），不再是数字编号；
    # 列表按 APA 作者字母序（Einstein 在张三前），旧断言按首现排序正是缺陷。
    assert f'[P{ids[0]}]' not in apa_body and '(张三, 2019)' in apa_body
    assert '(Einstein, 2020)' in apa_body
    entries = apa_rest.split('\n\n## 材料范围\n\n')[0].splitlines()
    assert entries == [
        'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc',
        '张三 (2019). Paper Five. arXiv: 1901.00001']
