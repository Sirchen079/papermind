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


def test_render_apa_same_full_group_same_year_keeps_suffixes():
    # F05 规则一（W03 回归）：同一完整作者组同年多篇才加年份字母 a/b，文内与
    # 列表一致（§8.19；Purdue OWL「use lower-case letters (a, b, c) with the
    # year」）。修复前该行为只被「不同作者组」的错误用例覆盖（见下）。
    papers = {
        1: dict(title='Alpha Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n同一作者组两项 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(Smith et al., 2020a)' in body and '(Smith et al., 2020b)' in body
    assert entries.splitlines() == [
        'Smith, A., Jones, L., & Kerr, M. (2020a). Alpha Meta.',
        'Smith, A., Jones, L., & Kerr, M. (2020b). Beta Pool.']
    assert _apa_marks(body) == ['2020a', '2020b']
    assert _apa_list_years(entries) == ['(2020a)', '(2020b)']


def test_render_apa_et_al_collision_expands_authors_not_year_suffixes():
    # F05 回归（W03）。替换原因：旧 test_render_apa_multi_author_same_first_author_
    # shares_suffixes 把「不同作者组碰巧缩写成同一 Smith et al.」当成同一作者组
    # 同年多篇，固化了 (Smith et al., 2020a/2020b) 的错误样式——这正是验收报告
    # F05 指出的缺陷。APA（§8.18；Purdue OWL「avoid ambiguity by writing out
    # more names」）只对同一完整作者组同年多篇加年份字母（上一用例），不同作者
    # 组须展开足够多后续姓氏消歧。新契约更强：文内展开、正文与列表全年份无 a/b、
    # 列表按作者字母序。修复前实际输出为 (Smith et al., 2020a)/(Smith et al.,
    # 2020b) 且两条列表条目带 2020a/2020b。
    # S04 校正（第三轮）：旧预期 (Smith, Jones, et al., 2020) 让 et al. 只替代
    # 剩下的一名作者，违反 Purdue OWL「et al. should always be a substitute for
    # more than one name」——展开两人后只余一人时必须列全，按规范改为
    # (Smith, Jones, & Kerr, 2020)；覆盖保留，仅按规范校正期望值。
    papers = {
        1: dict(title='Alpha Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Ada Smith', 'Rae Lane', 'Pia Moore'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n不同作者组两项 [P1] 与 [P2]，默认缩写形式相同。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(Smith, Jones, & Kerr, 2020)' in body and '(Smith, Lane, & Moore, 2020)' in body
    assert 'et al.' not in body
    assert '2020a' not in out and '2020b' not in out
    # 列表排序：姓氏序列 ('smith','jones','kerr') < ('smith','lane','moore')。
    assert entries.splitlines() == [
        'Smith, A., Jones, L., & Kerr, M. (2020). Alpha Meta.',
        'Smith, A., Lane, R., & Moore, P. (2020). Beta Pool.']


def test_render_apa_same_surname_different_persons_use_initials():
    # F05 规则三（W03 回归）：同姓不同人（John/Amy Smith 均缩写为 Smith）按
    # §8.20 用首作者名首字母区分（Purdue OWL：(E. Johnson, 2001; L. Johnson,
    # 1998)），不加年份字母；列表条目不受影响。
    papers = {
        1: dict(title='Alpha Study', authors=['John Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Study', authors=['Amy Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n同姓不同人 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(J. Smith, 2024)' in body and '(A. Smith, 2024)' in body
    assert '2024a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, J. (2024). Alpha Study.',
        'Smith, A. (2024). Beta Study.']


def test_render_apa_same_surname_same_initials_fall_back_to_given_names():
    # F05 边界（W03 回归）：名首字母也相同时（Jane/June Smith 均为 J. Smith）
    # 退到全名区分，仍是首作者限定；本实现不限定第二位及以后作者的名（Purdue
    # OWL 该节只给单作者示例，超出最小实现的部分如实记录为边界）。
    papers = {
        1: dict(title='Alpha Study', authors=['Jane Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Study', authors=['June Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n首字母相同 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(Jane Smith, 2024)' in body and '(June Smith, 2024)' in body
    assert '2024a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, J. (2024). Alpha Study.',
        'Smith, J. (2024). Beta Study.']


def test_render_apa_mixed_group_collision_keeps_letters_within_same_group():
    # F05 组合（W03 回归）：同一完整作者组两项同年（保留 a/b）与另一组同年
    # 缩写碰撞（展开消歧、无字母）同时出现，互不干扰。
    # S04 校正（第三轮）：展开后只余一名作者时须列全（et al. 至少替代两人，
    # Purdue OWL），故 Smith, Jones, et al. 改为列全三人 Smith, Jones, & Kerr。
    papers = {
        1: dict(title='Alpha Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        3: dict(title='Gamma Pool', authors=['Ada Smith', 'Rae Lane', 'Pia Moore'], year=2020,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n[P1]、[P2] 同组，[P3] 另一组。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert '(Smith, Jones, & Kerr, 2020a)' in body and '(Smith, Jones, & Kerr, 2020b)' in body
    assert '(Smith, Lane, & Moore, 2020)' in body
    assert entries.splitlines() == [
        'Smith, A., Jones, L., & Kerr, M. (2020a). Alpha Meta.',
        'Smith, A., Jones, L., & Kerr, M. (2020b). Beta Meta.',
        'Smith, A., Lane, R., & Moore, P. (2020). Gamma Pool.']


def test_render_apa_expansion_lists_all_when_et_al_would_replace_one():
    # S04 回归：et al. 至少要替代两名作者（Purdue OWL「Since et al. is plural,
    # it should always be a substitute for more than one name」）。三作者组展开
    # 两人后只余一人，必须列全三人不写 et al.；四作者组展开两人仍余两人，可以
    # 继续用 et al.。修复前输出 (Smith, Jones, et al., 2024) 等错误样式。
    papers = {
        1: dict(title='Alpha Meta', authors=['Alice Smith', 'Bob Jones', 'Carol Doe'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Alice Smith', 'David Brown', 'Emma Roe'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
        3: dict(title='Gamma Study', authors=['Alice Smith', 'Bob Jones', 'Carol Doe', 'Dan Eve'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
        4: dict(title='Delta Study', authors=['Alice Smith', 'Bob Brown', 'Carol Roe', 'Dan Fox'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n三作者 [P1] 与 [P2]，四作者 [P3] 与 [P4]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == ('# 综述\n\n三作者 (Smith, Jones, & Doe, 2024) 与 '
                    '(Smith, Brown, & Roe, 2024)，'
                    '四作者 (Smith, Jones, et al., 2024) 与 (Smith, Brown, et al., 2024)。')
    assert '2024a' not in out and '2024b' not in out
    # 列表排序：姓氏序列 ('smith','brown',...) < ('smith','jones',...)，同序列
    # 短者在前；列表条目照 APA 一贯列全作者，不受文内消歧影响。
    assert entries.splitlines() == [
        'Smith, A., Brown, D., & Roe, E. (2024). Beta Pool.',
        'Smith, A., Brown, B., Roe, C., & Fox, D. (2024). Delta Study.',
        'Smith, A., Jones, B., & Doe, C. (2024). Alpha Meta.',
        'Smith, A., Jones, B., Doe, C., & Eve, D. (2024). Gamma Study.']


def test_render_apa_same_surname_initials_across_years():
    # S04 补充回归：同姓不同人规则不受年份限制——Purdue OWL 示例 (E. Johnson,
    # 2001; L. Johnson, 1998) 本身就是不同年份。John Smith 2023 与 Amy Smith
    # 2024 同样要加名首字母；旧实现按「默认形式 + 相同年份」分组，跨年份时不
    # 消歧，错误输出 (Smith, 2023)/(Smith, 2024)。
    papers = {
        1: dict(title='Alpha Study', authors=['John Smith'], year=2023,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Study', authors=['Amy Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n跨年份同姓 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 综述\n\n跨年份同姓 (J. Smith, 2023) 与 (A. Smith, 2024)。'
    assert '2023a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, J. (2023). Alpha Study.',
        'Smith, A. (2024). Beta Study.']


def test_render_apa_same_surname_initials_with_different_default_forms():
    # S04 补充（第三轮预审）：同姓不同首作者的全局规则也不受默认显示形式限制
    # ——John Smith 单作者（Smith）与 Amy Smith+Lee Jones 双作者（Smith &
    # Jones）默认形式不同、年份不同，首作者仍是同姓不同人，都要加名首字母。
    papers = {
        1: dict(title='Alpha Study', authors=['John Smith'], year=2023,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Study', authors=['Amy Smith', 'Lee Jones'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n同姓跨形式 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 综述\n\n同姓跨形式 (J. Smith, 2023) 与 (A. Smith & Jones, 2024)。'
    assert '2023a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, J. (2023). Alpha Study.',
        'Smith, A., & Jones, L. (2024). Beta Study.']


def test_render_apa_same_first_author_different_years_keeps_et_al():
    # S04 补充（第三轮预审）：同首作者、不同作者组、不同年份——年份本身已可
    # 区分，不属于 §8.18 的同年缩写碰撞，不展开作者（展开反而造出多余的全名
    # 列表）；保持正常 et al.，也不加年份字母。
    papers = {
        1: dict(title='Alpha Meta', authors=['Ada Smith', 'Lee Jones', 'Mo Kerr'], year=2023,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Ada Smith', 'Rae Lane', 'Pia Moore'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n同首作者跨年 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 综述\n\n同首作者跨年 (Smith et al., 2023) 与 (Smith et al., 2024)。'
    assert '2023a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, A., Jones, L., & Kerr, M. (2023). Alpha Meta.',
        'Smith, A., Lane, R., & Moore, P. (2024). Beta Pool.']


def test_render_apa_subgroups_expand_alongside_same_surname_person():
    # 复审轮1回归：同年同形式碰撞组内既有同首作者的不同组、又有同姓另一人时，
    # 不能因首作者身份不一致而放弃展开——按首作者身份分子组各自展开，再与全局
    # 首字母样式组合：Alice 的两组列全区分，John 走 (J. Smith et al.)；三篇形式
    # 互异、不加年份字母。修复前前两篇都是 (A. Smith et al., 2024) 且无 a/b
    # （完整作者组不同不字母），正文引用无法对应到具体条目。
    papers = {
        1: dict(title='Alpha Meta', authors=['Alice Smith', 'Bob Jones', 'Carol Doe'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
        2: dict(title='Beta Pool', authors=['Alice Smith', 'David Brown', 'Emma Roe'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
        3: dict(title='Gamma Study', authors=['John Smith', 'Zoe West', 'Tim East'],
                year=2024, venue=None, volume=None, issue=None, pages=None,
                doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n同首作者 [P1] 与 [P2]，同姓另一人 [P3]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == ('# 综述\n\n同首作者 (A. Smith, Jones, & Doe, 2024) 与 '
                    '(A. Smith, Brown, & Roe, 2024)，同姓另一人 (J. Smith et al., 2024)。')
    assert '2024a' not in out and '2024b' not in out
    # 列表排序：姓氏序列 ('smith','brown',...) < ('smith','jones',...) < ('smith','west',...)。
    assert entries.splitlines() == [
        'Smith, A., Brown, D., & Roe, E. (2024). Beta Pool.',
        'Smith, A., Jones, B., & Doe, C. (2024). Alpha Meta.',
        'Smith, J., West, Z., & East, T. (2024). Gamma Study.']


def test_render_apa_same_surname_initials_sequences_differ():
    # 复审轮1回归：首字母序列不同即可区分——John A Smith 与 John B Smith 用
    # (J. A. Smith, 2024)/(J. B. Smith, 2024)，不必退到全名；首字母序列完全
    # 相同（Jane/June Smith）才是全名回退（见上一用例）。
    papers = {
        1: dict(title='Alpha Study', authors=['John A Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
        2: dict(title='Beta Study', authors=['John B Smith'], year=2024,
                venue=None, volume=None, issue=None, pages=None, doi=None, arxiv_id=None),
    }
    content = '# 综述\n\n中名不同 [P1] 与 [P2]。\n\n## 引用文献\n\n'
    out = references.render_styled_markdown(content, papers, 'apa')
    body, entries = out.split('\n\n## 引用文献\n\n', 1)
    assert body == '# 综述\n\n中名不同 (J. A. Smith, 2024) 与 (J. B. Smith, 2024)。'
    assert '2024a' not in out and '2024b' not in out
    assert entries.splitlines() == [
        'Smith, J. A. (2024). Alpha Study.',
        'Smith, J. B. (2024). Beta Study.']


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


def test_render_keeps_appendix_after_references_both_styles():
    # R05 回归：旧实现 partition('\n## 引用文献') 把文献节之后的全部内容当成
    # 节内旧条目一并替换，附录从导出结果里消失；只允许替换文献节自身的内容范围。
    content = ('正文 [P5]。\n\n'
               '## 引用文献\n\n- [P5] old\n\n'
               '## Appendix\n\nKEEP THIS TEXT\n')
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert gbt == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n'
                   '## Appendix\n\nKEEP THIS TEXT\n')
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert apa == ('正文 (张三, 2019)。\n\n## 引用文献\n\n'
                   '张三 (2019). Paper Five. arXiv: 1901.00001\n\n'
                   '## Appendix\n\nKEEP THIS TEXT\n')


def test_render_preserves_multiple_sections_and_materials_after_references():
    # R05 回归：文献节之后到「材料范围」之间的章节同样不能丢；材料范围
    # 只在自己的位置保留，不再充当文献节的截断点。
    content = ('正文 [P5] 与 [P2]。\n\n'
               '## 引用文献\n\n- [P5] old\n- [P2] old\n\n'
               '## 讨论\n\n讨论内容。\n\n'
               '## Appendix\n\nKEEP THIS TEXT\n\n'
               '## 材料范围\n\n本次范围 2 篇。\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    head, rest = out.split('\n\n## 引用文献\n\n', 1)
    entries, tail = rest.split('\n\n## 讨论\n\n', 1)
    assert head == '正文 [1] 与 [2]。'
    assert entries == ('[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n'
                       '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.')
    # 参考节之后的章节逐字保留（含原顺序）。
    assert tail == ('讨论内容。\n\n## Appendix\n\nKEEP THIS TEXT\n\n'
                    '## 材料范围\n\n本次范围 2 篇。\n')


def test_render_stops_at_higher_level_heading_after_references():
    # 同级或更高级标题都终止文献节：一级标题同样不能被当成节内容替换掉。
    content = '正文 [P5]。\n\n## 引用文献\n\n- [P5] old\n\n# 新章\n\n保留。\n'
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert out == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n'
                   '# 新章\n\n保留。\n')


def test_render_replaces_reference_section_with_internal_h3_headings():
    # 参考节内部的三级标题属于节内容：随节一起替换，不会把节提前切断。
    content = ('正文 [P2]。\n\n## 引用文献\n\n### 期刊\n\n- [P2] old\n\n'
               '### 更多\n\n- 无\n\n## 材料范围\n\n本次范围 1 篇。\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert out == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.\n\n'
                   '## 材料范围\n\n本次范围 1 篇。\n')


def test_render_ignores_reference_heading_inside_code_fence_and_inline():
    # R05 回归：代码围栏内的「## 引用文献」与行内同名文本不是文献节；
    # 旧实现从围栏处截断，围栏闭合符与其后的正文全部丢失。
    content = ('正文 [P5]。\n\n```markdown\n## 引用文献\n- [P999] 示例\n```\n\n'
               '行内提到 ## 引用文献 不算节。\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert '```markdown\n## 引用文献\n- [P999] 示例\n```' in out
    assert '行内提到 ## 引用文献 不算节。' in out
    # 末尾只追加一节真实文献节（围栏与行内同名文本都不构成 `\n\n## 引用文献\n\n`）。
    assert out.count('\n\n## 引用文献\n\n') == 1
    assert out.endswith('\n\n## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')


def test_render_finds_real_section_after_earlier_fence_mention():
    # 围栏里的同名标题在前时，真实文献节仍应被找到并替换。
    content = ('```text\n## 引用文献\n```\n\n正文 [P5]。\n\n'
               '## 引用文献\n\n- [P5] old\n\n## 材料范围\n\n本次范围 1 篇。\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    head, rest = out.split('\n\n## 引用文献\n\n', 1)
    entries, materials = rest.split('\n\n## 材料范围\n\n', 1)
    assert head == '```text\n## 引用文献\n```\n\n正文 [1]。'
    assert entries == '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.'
    assert materials == '本次范围 1 篇。\n'


def test_render_keeps_indented_heading_after_references_both_styles():
    # F03 反例 A（W02 回归）：≤3 空格缩进仍是合法 ATX 标题，文献节到它为止；
    # 旧扫描只认行首 `#`/`##`，把缩进附录连同内容整个吞掉。
    content = ('正文 [P5]。\n\n'
               '## 引用文献\nold\n\n'
               '  ## Appendix\nKEEP INDENTED APPENDIX\n')
    tail = '  ## Appendix\nKEEP INDENTED APPENDIX\n'
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert gbt == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n' + tail)
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert apa == ('正文 (张三, 2019)。\n\n## 引用文献\n\n'
                   '张三 (2019). Paper Five. arXiv: 1901.00001\n\n' + tail)


def test_render_keeps_four_backtick_fence_and_following_sections_both_styles():
    # F03 反例 B（W02 回归）：外层四反引号围栏内的三反引号不是闭合、其后的
    # 字面量标题不是文献节；旧实现把开围栏截成 3 个字符，代码示例被改写、
    # 末尾闭合围栏又重新开围栏吞掉 Results。
    fenced = ('Intro [P5]。\n\n'
              '````markdown\n```\n## 引用文献\nDO NOT DELETE THIS CODE EXAMPLE\n````\n\n'
              '## Results\nKEEP RESULTS\n')
    example = '````markdown\n```\n## 引用文献\nDO NOT DELETE THIS CODE EXAMPLE\n````\n\n## Results\nKEEP RESULTS'
    gbt = references.render_styled_markdown(fenced, PAPERS, 'gbt')
    assert gbt == ('Intro [1]。\n\n' + example +
                   '\n\n## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    apa = references.render_styled_markdown(fenced, PAPERS, 'apa')
    assert apa == ('Intro (张三, 2019)。\n\n' + example +
                   '\n\n## 引用文献\n\n张三 (2019). Paper Five. arXiv: 1901.00001')


def test_render_indented_reference_heading_and_indented_code_block_rules():
    # W02 边界补充：3 空格缩进的「## 引用文献」仍是合法文献节标题；4 空格
    # 缩进是缩进代码块——既不构成文献节标题，也不终止文献节（属节内容）。
    indented_ref = '正文 [P5]。\n\n   ## 引用文献\n- [P5] old\n\n## 材料范围\n\n本次范围 1 篇。\n'
    assert references.render_styled_markdown(indented_ref, PAPERS, 'gbt') == (
        '正文 [1]。\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n'
        '## 材料范围\n\n本次范围 1 篇。\n')
    code_ref = '正文 [P5]。\n\n    ## 引用文献\n- [P5] old\n'
    assert references.render_styled_markdown(code_ref, PAPERS, 'gbt') == (
        '正文 [1]。\n\n    ## 引用文献\n- [1] old\n\n'
        '## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    deep = '正文 [P5]。\n\n## 引用文献\nold\n\n    ## Appendix\nKEEP FOUR SPACES\n'
    assert references.render_styled_markdown(deep, PAPERS, 'gbt') == (
        '正文 [1]。\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')


def test_render_tilde_fence_char_length_and_close_rules():
    # W02 边界补充：~ 围栏同一规则——开围栏记录完整长度，闭合须同字符且
    # 个数不小于开启长度（更短的不闭合，更长的正常闭合）。
    tilde = ('正文 [P5]。\n\n'
             '~~~~\n~~~\n## 引用文献\nNOT A REAL SECTION\n~~~~\n\n'
             '## Results\nKEEP TILDE RESULTS\n')
    out = references.render_styled_markdown(tilde, PAPERS, 'gbt')
    assert '~~~~\n~~~\n## 引用文献\nNOT A REAL SECTION\n~~~~' in out
    assert '## Results\nKEEP TILDE RESULTS' in out
    assert out.count('\n\n## 引用文献\n\n') == 1
    longer_close = '正文 [P5]。\n\n~~~\n代码示例。\n~~~~~\n\n## 后文\nKEEP AFTER TILDE\n'
    out2 = references.render_styled_markdown(longer_close, PAPERS, 'gbt')
    assert '~~~\n代码示例。\n~~~~~' in out2 and '## 后文\nKEEP AFTER TILDE' in out2
    assert out2.count('\n\n## 引用文献\n\n') == 1
    shorter_close = '正文 [P5]。\n\n~~~~\n~~\n## 引用文献\n示例\n~~~~\n\n## 后文\nKEEP SHORT\n'
    out3 = references.render_styled_markdown(shorter_close, PAPERS, 'gbt')
    assert '~~~~\n~~\n## 引用文献\n示例\n~~~~' in out3 and 'KEEP SHORT' in out3
    assert out3.count('\n\n## 引用文献\n\n') == 1


def test_render_collects_and_rewrites_appendix_citations_after_references():
    # O01 回归（W03）：文献节之后的附录引用同样参与收集与改写——保留章节与
    # 叙述文字不等于保留内部系统占位符 [Pn]。GB/T 编号按正文首现（含附录首现）
    # 顺延，附录里重复出现的正文引用不产生第二条；文献节自身旧条目中的 [Pn]
    # 属于被替换的旧列表，不参与。修复前附录保持 [P2] 原样且 P2 不进列表。
    content = ('正文 [P5]。\n\n## 引用文献\n\n- [P5] old\n\n'
               '## Appendix\n\nExtra evidence [P2] and [P5].\n')
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert gbt == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n'
                   '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.\n\n'
                   '## Appendix\n\nExtra evidence [2] and [1].\n')
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert apa == ('正文 (张三, 2019)。\n\n## 引用文献\n\n'
                   'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc\n'
                   '张三 (2019). Paper Five. arXiv: 1901.00001\n\n'
                   '## Appendix\n\nExtra evidence (Einstein, 2020) and (张三, 2019).\n')


def test_render_never_touches_marks_inside_code_fences_or_unknown_marks():
    # O01 边界（W03 回归）：收集与改写都跳过围栏内部——代码示例中的字面 [Pn]
    # 是文本不是引用（修复前正文围栏里的 sample [P2] 会被改写成 [2]）；未知
    # [Pn] 在正文与附录中都原样保留、不产生条目。
    content = ('正文 [P5]。\n\n```text\nsample [P2] stays\n```\n\n'
               '## 引用文献\n\n- [P5] old\n\n'
               '## Appendix\n\nExtra evidence [P2].\n\n```text\nliteral [P999] stays\n```\n')
    out = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert '正文 [1]。' in out
    assert 'sample [P2] stays' in out and 'literal [P999] stays' in out
    body, entries_and_tail = out.split('\n\n## 引用文献\n\n', 1)
    entries, tail = entries_and_tail.split('\n\n## Appendix\n\n', 1)
    assert '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.' in entries
    assert '[2] EINSTEIN A. Paper Two' in entries
    assert tail == 'Extra evidence [2].\n\n```text\nliteral [P999] stays\n```\n'


def test_render_four_space_pseudo_close_keeps_code_and_results_both_styles():
    # S02 回归：四空格缩进的 ``` 不是闭合围栏（CommonMark 0.31.2：闭合围栏
    # 最多 3 空格缩进），其后整个「## 引用文献」仍是代码内容；旧实现剥掉全部
    # 缩进后误闭合，把代码示例连同 Results 当文献节整体替换掉。
    content = ('Body [P5].\n\n```text\n    ```\n## 引用文献\nKEEP CODE EXAMPLE\n'
               '```\n\n## Results\nKEEP RESULTS\n')
    kept = '```text\n    ```\n## 引用文献\nKEEP CODE EXAMPLE\n```\n\n## Results\nKEEP RESULTS'
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert gbt == ('Body [1].\n\n' + kept +
                   '\n\n## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert apa == ('Body (张三, 2019).\n\n' + kept +
                   '\n\n## 引用文献\n\n张三 (2019). Paper Five. arXiv: 1901.00001')


def test_render_fence_close_indent_rules_spaces_tabs_long_and_tilde():
    # S02 边界：0-3 空格缩进的闭合合法；4 空格或含 tab 的缩进（tab 不折算为
    # 一个空格，按制表位至少 4 列）不是闭合，更长的记号也救不了；~ 围栏同一规则。
    three = '正文 [P5]。\n\n```text\n   ```\n## 引用文献\n- [P5] old\n'
    assert references.render_styled_markdown(three, PAPERS, 'gbt') == (
        '正文 [1]。\n\n```text\n   ```\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    four = ('正文 [P5]。\n\n```text\n    ```\n    `````\n代码。\n```\n\n'
            '## 引用文献\n- [P5] old\n')
    assert references.render_styled_markdown(four, PAPERS, 'gbt') == (
        '正文 [1]。\n\n```text\n    ```\n    `````\n代码。\n```\n\n'
        '## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    tab = '正文 [P5]。\n\n```text\n\t```\n## 引用文献\nold\n```\n'
    assert references.render_styled_markdown(tab, PAPERS, 'gbt') == (
        '正文 [1]。\n\n```text\n\t```\n## 引用文献\nold\n```\n\n'
        '## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    tilde = '正文 [P5]。\n\n~~~~\n    ~~~~\n## 引用文献\nold\n~~~~\n\n## 后文\nKEEP\n'
    out = references.render_styled_markdown(tilde, PAPERS, 'gbt')
    assert '~~~~\n    ~~~~\n## 引用文献\nold\n~~~~' in out and 'KEEP' in out
    assert out.count('\n\n## 引用文献\n\n') == 1
    # 开围栏同样保留缩进含义：四空格缩进的 ``` 不是开启（是缩进代码块），
    # 其后的「## 引用文献」仍是真实文献节。
    open4 = '正文 [P5]。\n\n    ```\n## 引用文献\n- [P5] old\n'
    assert references.render_styled_markdown(open4, PAPERS, 'gbt') == (
        '正文 [1]。\n\n    ```\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')


def test_render_code_block_ids_not_collected_both_styles():
    # S03-A 回归：只在代码围栏中出现的 [P2] 不是引用——不进书目、不占编号；
    # 旧实现 _map_outside_fences(content, identity) 原样返回全文，first_
    # appearance_ids 把代码里的 [P2] 一并收集成第二条书目。
    content = 'Body [P5].\n\n```text\nExample [P2] is not a citation.\n```\n'
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert 'Example [P2] is not a citation.' in gbt
    assert 'Paper Two' not in gbt and '[2]' not in gbt
    assert gbt == ('Body [1].\n\n```text\nExample [P2] is not a citation.\n```\n\n'
                   '## 引用文献\n\n[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert 'Paper Two' not in apa and 'Einstein' not in apa
    assert apa == ('Body (张三, 2019).\n\n```text\nExample [P2] is not a citation.\n```\n\n'
                   '## 引用文献\n\n张三 (2019). Paper Five. arXiv: 1901.00001')


def test_render_code_before_body_does_not_take_first_number_both_styles():
    # S03-B 回归：代码示例先于正文时，其中的 [P2] 不占首现号——正文首引
    # [P5] 编号 [1] 而非 [2]，书目仅 P5。旧实现把代码 [P2] 当首现，正文被
    # 编成 [2] 且书目多出未被正文引用的一条。
    content = '```text\nExample [P2].\n```\n\nBody [P5].\n'
    gbt = references.render_styled_markdown(content, PAPERS, 'gbt')
    assert gbt == ('```text\nExample [P2].\n```\n\nBody [1].\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    assert 'Paper Two' not in gbt
    apa = references.render_styled_markdown(content, PAPERS, 'apa')
    assert apa == ('```text\nExample [P2].\n```\n\nBody (张三, 2019).\n\n## 引用文献\n\n'
                   '张三 (2019). Paper Five. arXiv: 1901.00001')
    assert 'Einstein' not in apa


def test_render_atx_optional_closing_hashes_and_text_after_hashes():
    # 同区域规范缺口（CommonMark 0.31.2 §4.3）：标题文本后可选的 # 闭合序列
    # （前有空白、后仅空白）——`## 引用文献 ##` 是同一标题；# 前无空白或其后
    # 还有其他文本时属于标题内容，不是文献节。
    closed = '正文 [P5]。\n\n## 引用文献 ##\n- [P5] old\n\n## 材料范围\n\n本次范围 1 篇。\n'
    assert references.render_styled_markdown(closed, PAPERS, 'gbt') == (
        '正文 [1]。\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n'
        '## 材料范围\n\n本次范围 1 篇。\n')
    glued = '正文 [P5]。\n\n## 引用文献#\n- [P5] old\n'
    assert references.render_styled_markdown(glued, PAPERS, 'gbt') == (
        '正文 [1]。\n\n## 引用文献#\n- [1] old\n\n## 引用文献\n\n'
        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    trailing = '正文 [P5]。\n\n## 引用文献 # x\nold\n'
    out = references.render_styled_markdown(trailing, PAPERS, 'gbt')
    assert out.count('\n\n## 引用文献\n\n') == 1 and '## 引用文献 # x' in out


def test_render_without_reference_section_appends_exactly_once():
    out = references.render_styled_markdown('正文 [P5]。\n', PAPERS, 'gbt')
    assert out == ('正文 [1]。\n\n## 引用文献\n\n'
                   '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.')
    assert out.count('## 引用文献') == 1


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


def test_export_endpoint_keeps_appendix_and_does_not_touch_source(client):
    # R05 回归：文献节后的附录在两种风格的 Markdown 导出中都保留，
    # 且导出不写回、不污染数据库原稿。
    with Session(get_engine()) as s:
        row = Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                    year=2019, arxiv_id='1901.00001')
        s.add(row);s.commit();pid = row.id
        content = (f'正文引 [P{pid}]。\n\n## 引用文献\n\n- [P{pid}] Paper Five\n\n'
                   '## Appendix\n\nKEEP THIS TEXT\n')
        s.add(LibraryReview(id='appendix-export', question='附录保留', status='ready',
                            content=content, version=1))
        s.commit()
    gbt = client.get('/api/reviews/appendix-export/export', params={'style': 'gbt'})
    assert gbt.status_code == 200
    assert gbt.text == (f'正文引 [1]。\n\n## 引用文献\n\n'
                        '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.\n\n'
                        '## Appendix\n\nKEEP THIS TEXT\n')
    apa = client.get('/api/reviews/appendix-export/export', params={'style': 'apa'})
    assert apa.status_code == 200
    assert apa.text == (f'正文引 (张三, 2019)。\n\n## 引用文献\n\n'
                        '张三 (2019). Paper Five. arXiv: 1901.00001\n\n'
                        '## Appendix\n\nKEEP THIS TEXT\n')
    with Session(get_engine()) as s:
        assert s.get(LibraryReview, 'appendix-export').content == content
