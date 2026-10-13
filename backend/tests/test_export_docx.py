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


def fetch_docx(client, **params):
    resp = client.get('/api/reviews/docx-export/export', params={'kind': 'docx', **params})
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
