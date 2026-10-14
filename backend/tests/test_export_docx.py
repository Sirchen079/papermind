"""P5b: 综述正文导出 Word(.docx)(kind=docx,python-docx 逐行转换)。"""
import io
import zipfile

from docx import Document
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper
from app.models.review import LibraryReview
from app.reviews import export_docx

DOCX_MEDIA = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
DISPOSITION = ('attachment; filename="review.docx"; '
               "filename*=UTF-8''%E4%B8%93%E9%A2%98%E7%BB%BC%E8%BF%B0.docx")
GBT_ONE = '[1] 张三. Paper Five[J]. 中文期刊, 2019. DOI: 10.5678/def.'
GBT_TWO = '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.'


def seed_review(client):
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                      year=2019, venue='中文期刊', doi='10.5678/def'),
                Paper(source='manual', title='Paper Two', authors_json='["Albert Einstein"]',
                      year=2020, venue='Venue', volume='12', issue='3', pages='45-52',
                      doi='10.1234/abc')]
        s.add_all(rows);s.commit();ids = [r.id for r in rows]
        content = (f'# 检索方法综述\n\n## 背景与结论\n\n正文先引 [P{ids[0]}] **再引** [P{ids[1]}]。\n\n'
                   '- 要点一\n- 要点二\n\n'
                   f'> 引用一句 [P{ids[0]}]。\n\n### 细分\n\n细分正文。\n\n'
                   '# 总结\n\n全文总结。\n\n---\n\n'
                   '## 引用文献\n\n'
                   f'- [P{ids[0]}] Paper Five\n- [P{ids[1]}] Paper Two\n\n'
                   '## 材料范围\n\n本次范围 2 篇。\n')
        s.add(LibraryReview(id='docx-export', question='检索方法综述', status='ready',
                            content=content, version=1))
        s.commit()
    return ids, content


def fetch_docx(client, review_id='docx-export', **params):
    resp = client.get(f'/api/reviews/{review_id}/export', params={'kind': 'docx', **params})
    assert resp.status_code == 200, resp.text
    assert resp.headers['content-type'] == DOCX_MEDIA
    assert resp.headers['content-disposition'] == DISPOSITION
    body = resp.content
    assert body[:4] == b'PK\x03\x04'
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert 'word/document.xml' in zf.namelist()
        xml = zf.read('word/document.xml').decode('utf-8')
    return resp, xml


def paragraphs(body):
    return Document(io.BytesIO(body)).paragraphs


def test_export_docx_endpoint_zip_headers_and_content(client):
    seed_review(client)
    resp, xml = fetch_docx(client)
    assert resp.headers['content-disposition'] == DISPOSITION
    assert '检索方法综述' in xml
    assert '[1]' in xml and '[2]' in xml
    assert '引用文献' in xml
    # 著录里的 venue 与年份进入正文 Word
    assert GBT_ONE in xml and GBT_TWO in xml


def test_export_docx_markdown_structure_roundtrip(client):
    seed_review(client)
    resp, _ = fetch_docx(client)
    paras = paragraphs(resp.content)
    assert paras[0].style.name == 'Title' and paras[0].text == '检索方法综述'
    by_text = {p.text: p for p in paras}
    assert by_text['背景与结论'].style.name == 'Heading 2'
    assert by_text['细分'].style.name == 'Heading 3'
    assert by_text['总结'].style.name == 'Heading 1'  # 其后的 # 是 level 1
    assert by_text['引用文献'].style.name == 'Heading 2'
    assert by_text['材料范围'].style.name == 'Heading 2'
    bullets = [p.text for p in paras if p.style.name == 'List Bullet']
    assert '要点一' in bullets and '要点二' in bullets
    quote = by_text['引用一句 [1]。']
    assert quote.style.name == 'Normal' and not quote.text.startswith('>')
    bold = by_text['正文先引 [1] 再引 [2]。']
    assert [(r.text, bool(r.bold)) for r in bold.runs] == [
        ('正文先引 [1] ', False), ('再引', True), (' [2]。', False)]
    assert not any(p.text == '---' for p in paras)
    assert by_text[GBT_ONE].style.name == 'Normal'
    assert by_text[GBT_TWO].style.name == 'Normal'


def test_export_docx_apa_citations_differ_from_gbt(client):
    seed_review(client)
    _, gbt_xml = fetch_docx(client)
    resp, apa_xml = fetch_docx(client, style='apa')
    assert resp.headers['content-type'] == DOCX_MEDIA
    # apa 著录含 (年份). 且与 gbt 的 [J]/DOI: 形式不同
    assert '(2019).' in apa_xml and '(2020).' in apa_xml
    assert 'https://doi.org/10.1234/abc' in apa_xml
    assert '[J]' not in apa_xml and 'DOI:' not in apa_xml
    assert '[J]' in gbt_xml and 'DOI: 10.1234/abc.' in gbt_xml


def test_export_docx_apa_body_cites_match_reference_paragraphs(client):
    # R04 回归：APA 导出中正文引用与参考列表必须是同一套作者—年份，不得是数字编号。
    seed_review(client)
    resp, xml = fetch_docx(client, style='apa')
    paras = paragraphs(resp.content)
    by_text = {p.text: p for p in paras}
    assert '[1]' not in xml and '[P' not in xml
    assert by_text['正文先引 (张三, 2019) 再引 (Einstein, 2020)。'].text == \
        '正文先引 (张三, 2019) 再引 (Einstein, 2020)。'
    assert [(r.text, bool(r.bold)) for r in by_text['正文先引 (张三, 2019) 再引 (Einstein, 2020)。'].runs] == [
        ('正文先引 (张三, 2019) ', False), ('再引', True), (' (Einstein, 2020)。', False)]
    assert by_text['引用一句 (张三, 2019)。'].text == '引用一句 (张三, 2019)。'
    # 列表按 APA 作者字母序；正文两个文内引用均可在列表中按「作者, 年份」唯一定位。
    assert [p.text for p in paras if p.text.startswith(('Einstein,', '张三 ('))] == [
        'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc',
        '张三 (2019). Paper Five. 中文期刊. https://doi.org/10.5678/def']


def test_export_docx_unknown_style_falls_back_to_gbt(client):
    seed_review(client)
    _, xml = fetch_docx(client, style='chicago')
    assert '[J]' in xml  # 沿用 P5a 语义:不在 STYLES 内的 style 按 gbt 处理


def test_render_review_docx_cleans_control_characters(client):
    with Session(get_engine()) as s:
        s.add(LibraryReview(id='docx-clean', question='干净', status='ready',
                            content='# 标题\x0c带控制符\x00\n\n正文。', version=1))
        s.commit()
    text = '\n'.join(p.text for p in paragraphs(export_docx.render_review_docx(
        Session(get_engine()), 'docx-clean')))
    assert '标题 带控制符' in text
    assert '\x0c' not in text and '\x00' not in text


def test_export_docx_keeps_sections_after_references_both_styles(client):
    # R05 回归：文献节之后的附录不能被当成节内旧条目替换掉；附录在
    # 材料范围之前时旧实现同样丢弃。导出不写回原稿。
    with Session(get_engine()) as s:
        row = Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                    year=2019, arxiv_id='1901.00001')
        s.add(row);s.commit();pid = row.id
        content = (f'正文先引 [P{pid}]。\n\n## 引用文献\n\n- [P{pid}] Paper Five\n\n'
                   '## Appendix\n\nKEEP THIS TEXT\n\n## 材料范围\n\n本次范围 1 篇。\n')
        s.add(LibraryReview(id='docx-appendix', question='附录保留', status='ready',
                            content=content, version=1))
        s.commit()
    for style in ('gbt', 'apa'):
        resp, xml = fetch_docx(client, review_id='docx-appendix', style=style)
        paras = paragraphs(resp.content)
        by_text = {p.text: p for p in paras}
        assert by_text['Appendix'].style.name == 'Heading 2'
        assert by_text['KEEP THIS TEXT'].text == 'KEEP THIS TEXT'
        assert by_text['材料范围'].style.name == 'Heading 2'
        # 附录仍位于参考列表之后、材料范围之前。
        order = [p.text for p in paras]
        assert order.index('Appendix') < order.index('材料范围')
    with Session(get_engine()) as s:
        assert s.get(LibraryReview, 'docx-appendix').content == content


def test_export_docx_keeps_indented_appendix_and_fence_example_both_styles(client):
    # F03（W02 回归，Markdown/DOCX 共享渲染路径）：缩进附录是文献节终点；
    # 四反引号围栏示例与字面量标题原样保留，其后的 Results 不被吞掉。
    with Session(get_engine()) as s:
        row = Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                    year=2019, arxiv_id='1901.00001')
        s.add(row);s.commit();pid = row.id
        content = (f'正文先引 [P{pid}]。\n\n## 引用文献\n- [P{pid}] old\n\n'
                   '  ## Appendix\nKEEP INDENTED APPENDIX\n\n'
                   f'````markdown\n```\n## 引用文献\nDO NOT DELETE {pid}\n````\n\n'
                   '## Results\nKEEP RESULTS\n')
        s.add(LibraryReview(id='docx-f03', question='内容保留', status='ready',
                            content=content, version=1))
        s.commit()
    entry = {'gbt': '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.',
             'apa': '张三 (2019). Paper Five. arXiv: 1901.00001'}
    for style in ('gbt', 'apa'):
        resp, _ = fetch_docx(client, review_id='docx-f03', style=style)
        paras = paragraphs(resp.content)
        texts = [p.text for p in paras]
        by_text = {p.text: p for p in paras}
        assert by_text['Appendix'].style.name == 'Heading 2'
        assert 'KEEP INDENTED APPENDIX' in texts
        # 围栏示例逐行保留（DOCX 有意按纯文本呈现代码块）。
        assert f'DO NOT DELETE {pid}' in texts
        assert '````markdown' in texts and texts.count('````') == 1
        # 字面量标题与真实追加的文献节各自渲染一个「引用文献」标题，Results 保留。
        assert texts.count('引用文献') == 2
        assert by_text['Results'].style.name == 'Heading 2'
        assert 'KEEP RESULTS' in texts
        assert entry[style] in texts
        if style == 'apa':
            assert '正文先引 (张三, 2019)。' in texts
    with Session(get_engine()) as s:
        assert s.get(LibraryReview, 'docx-f03').content == content


def test_export_docx_rewrites_appendix_citations_both_styles(client):
    # O01（W03 回归，Markdown/DOCX 共享渲染路径）：附录中的 [Pn] 同样参与
    # 收集与改写（GB/T 顺延编号、APA 作者—年份）并进入参考列表；附录标题与
    # 叙述文字保留；导出不写回、不污染数据库原稿。
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                      year=2019, arxiv_id='1901.00001'),
                Paper(source='manual', title='Paper Two', authors_json='["Albert Einstein"]',
                      year=2020, venue='Venue', volume='12', issue='3', pages='45-52',
                      doi='10.1234/abc')]
        s.add_all(rows);s.commit();ids = [r.id for r in rows]
        content = (f'正文先引 [P{ids[0]}]。\n\n## 引用文献\n\n- [P{ids[0]}] old\n\n'
                   f'## Appendix\n\nExtra evidence [P{ids[1]}] and [P{ids[0]}].\n')
        s.add(LibraryReview(id='docx-o01', question='附录引用', status='ready',
                            content=content, version=1))
        s.commit()
    for style in ('gbt', 'apa'):
        resp, xml = fetch_docx(client, review_id='docx-o01', style=style)
        texts = [p.text for p in paragraphs(resp.content)]
        by_text = {p.text: p for p in paragraphs(resp.content)}
        assert by_text['Appendix'].style.name == 'Heading 2'
        assert '[P' not in xml
        if style == 'gbt':
            assert '正文先引 [1]。' in texts and 'Extra evidence [2] and [1].' in texts
            assert '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.' in texts
            assert '[2] EINSTEIN A. Paper Two[J]. Venue, 2020, 12(3): 45-52. DOI: 10.1234/abc.' in texts
        else:
            assert '正文先引 (张三, 2019)。' in texts
            assert 'Extra evidence (Einstein, 2020) and (张三, 2019).' in texts
            assert 'Einstein, A. (2020). Paper Two. Venue, 12(3), 45-52. https://doi.org/10.1234/abc' in texts
    with Session(get_engine()) as s:
        assert s.get(LibraryReview, 'docx-o01').content == content


def test_export_docx_four_space_pseudo_close_and_code_ids_both_styles(client):
    # S02/S03 回归（Markdown/DOCX 共享渲染路径）：四空格伪闭合不终止围栏，
    # 代码示例与 Results 保留；只在代码中出现的 [P2] 不进书目、不占首现号。
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title='Paper Five', authors_json='["张三"]',
                      year=2019, arxiv_id='1901.00001'),
                Paper(source='manual', title='Paper Two', authors_json='["Albert Einstein"]',
                      year=2020, venue='Venue', volume='12', issue='3', pages='45-52',
                      doi='10.1234/abc')]
        s.add_all(rows);s.commit();ids = [r.id for r in rows]
        content = (f'Body [P{ids[0]}].\n\n```text\n    ```\n## 引用文献\n'
                   f'Example [P{ids[1]}] is not a citation.\n```\n\n## Results\nKEEP RESULTS\n')
        s.add(LibraryReview(id='docx-s02', question='围栏保护', status='ready',
                            content=content, version=1))
        s.commit()
    entries = {'gbt': '[1] 张三. Paper Five[J]. 2019. arXiv: 1901.00001.',
               'apa': '张三 (2019). Paper Five. arXiv: 1901.00001'}
    for style in ('gbt', 'apa'):
        resp, xml = fetch_docx(client, review_id='docx-s02', style=style)
        texts = [p.text for p in paragraphs(resp.content)]
        by_text = {p.text: p for p in paragraphs(resp.content)}
        assert by_text['Results'].style.name == 'Heading 2'
        assert 'KEEP RESULTS' in texts
        # 围栏内的字面 [Pn] 不改写、不进书目（DOCX 有意按纯文本呈现代码块）。
        assert f'Example [P{ids[1]}] is not a citation.' in texts
        assert 'Paper Two' not in xml
        body_mark = 'Body [1].' if style == 'gbt' else 'Body (张三, 2019).'
        assert body_mark in texts
        # 围栏内的字面标题与追加的真实文献节各渲染一个「引用文献」。
        assert texts.count('引用文献') == 2
        assert entries[style] in texts
        # 原有内容在前，追加的文献节在后（顺序保留）。
        assert texts.index('KEEP RESULTS') < texts.index(entries[style])
    with Session(get_engine()) as s:
        assert s.get(LibraryReview, 'docx-s02').content == content


def test_export_docx_apa_et_al_collision_expands_authors_not_suffixes(client):
    # F05（W03 回归，Markdown/DOCX 共享渲染路径）：不同作者组缩写碰撞在 DOCX
    # 中同样展开后续姓氏消歧，正文与列表都不加年份字母。
    # S04 校正（第三轮）：三作者组展开两人后只余一人，et al. 至少替代两人
    # （Purdue OWL），必须列全——旧预期 (Smith, Jones, et al., 2020) 违反该条，
    # 按规范改为 (Smith, Jones, & Kerr, 2020)；覆盖保留，仅校正期望值。
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title='Alpha Meta',
                      authors_json='["Ada Smith", "Lee Jones", "Mo Kerr"]', year=2020),
                Paper(source='manual', title='Beta Pool',
                      authors_json='["Ada Smith", "Rae Lane", "Pia Moore"]', year=2020)]
        s.add_all(rows);s.commit();ids = [r.id for r in rows]
        content = f'两项 [P{ids[0]}] 与 [P{ids[1]}]。\n\n## 引用文献\n\n'
        s.add(LibraryReview(id='docx-f05', question='消歧', status='ready',
                            content=content, version=1))
        s.commit()
    resp, xml = fetch_docx(client, review_id='docx-f05', style='apa')
    assert '2020a' not in xml and '2020b' not in xml
    assert 'et al.' not in xml
    # 含 & 的正文引用与条目在 document.xml 里被转义，用段落文本断言内容。
    texts = [p.text for p in paragraphs(resp.content)]
    assert '两项 (Smith, Jones, & Kerr, 2020) 与 (Smith, Lane, & Moore, 2020)。' in texts
    assert 'Smith, A., Jones, L., & Kerr, M. (2020). Alpha Meta.' in texts
    assert 'Smith, A., Lane, R., & Moore, P. (2020). Beta Pool.' in texts
