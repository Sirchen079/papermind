import pymupdf
import pytest

from app.reading.pdf_text import native_page, text_quality


def test_text_coverage_is_measured_against_content_and_does_not_count_overlap_twice():
    text = [pymupdf.Rect(0, 0, 100, 10)]
    image = [pymupdf.Rect(0, 0, 100, 100)]
    assert text_quality('Readable text', text * 10, image)['coverage'] == pytest.approx(.1)
    assert text_quality('Short title', text, text)['reliable']
    assert not text_quality('Page 1', [pymupdf.Rect(0, 95, 10, 100)], image)['reliable']


@pytest.mark.parametrize('bad', ['\ufffd', '\ue001', '\x00', '(cid:123)'])
def test_broken_font_mappings_and_controls_require_ocr(bad):
    boxes = [pymupdf.Rect(0, 0, 100, 100)]
    quality = text_quality('Readable text ' * 10 + bad * 10, boxes, boxes)
    assert quality['garble_rate'] > .01 and not quality['reliable']


def test_scientific_unicode_and_cjk_are_not_garbled():
    boxes = [pymupdf.Rect(0, 0, 100, 100)]
    quality = text_quality('中文 αβγ ∑ ∫ √ x² ≤ 0.05 ﬁ ﬂ', boxes, boxes)
    assert quality['garble_rate'] == 0 and quality['reliable']


def test_threshold_boundaries_are_inclusive():
    content = [pymupdf.Rect(0, 0, 100, 100)]
    text = [pymupdf.Rect(0, 0, 100, 5)]
    assert text_quality('a' * 99 + '\ufffd', text, content)['reliable']
    assert not text_quality('a' * 98 + '\ufffd' * 2, text, content)['reliable']
    assert not text_quality('Readable', [pymupdf.Rect(0, 0, 100, 4.9)], content)['reliable']


def test_rotated_pages_keep_text_in_the_visible_crop():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((40, 700), 'A readable line near the bottom of a rotated page')
        page.set_rotation(90)
        text, quality = native_page(page)
        assert 'rotated page' in text and quality['reliable']


def test_native_layout_keeps_whole_columns_after_a_spanning_title():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((40, 40), 'A scientific title spanning the two columns of this paper', fontsize=20)
        # Deliberately create right-column objects first, with aligned baselines.
        for x, label in [(320, 'RIGHT'), (40, 'LEFT')]:
            page.insert_text((x, 100), f'{label} first paragraph', fontsize=11)
            page.insert_text((x, 140), f'{label} second paragraph', fontsize=11)
        text, quality = native_page(page)
        assert quality['reliable']
        assert text.index('title') < text.index('LEFT first') < text.index('LEFT second') < text.index('RIGHT first')


def test_scan_with_only_a_native_footer_is_not_accepted_as_a_text_page():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.draw_rect((30, 30, 570, 740), fill=(.5, .5, .5))
        image = page.get_pixmap().tobytes('png')
        scan = pdf.new_page(width=600, height=800)
        scan.insert_image(scan.rect, stream=image)
        scan.insert_text((280, 780), 'Page 1', fontsize=10)
        text, quality = native_page(scan)
        assert 'Page 1' in text and quality['coverage'] < .05 and not quality['reliable']


def test_readable_text_over_a_scan_is_reused_when_coverage_is_sufficient():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=500)
        image = page.get_pixmap().tobytes('png')
        page.insert_image(page.rect, stream=image)
        for y in range(40, 460, 20):
            page.insert_text((30, y), 'A readable existing text layer for a scanned article.', fontsize=10)
        text, quality = native_page(page)
        assert text and quality['coverage'] >= .05 and quality['reliable']


def test_blank_pages_are_preserved_but_vector_only_pages_need_ocr():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        text, quality = native_page(page)
        assert text == '[空白页]' and quality['reliable']
        page.draw_rect((30, 30, 300, 400))
        assert not native_page(page)[1]['reliable']


def test_ruled_table_is_not_reordered_as_independent_columns():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=500)
        for y in [60, 90, 120]:
            page.draw_line((30, y), (350, y))
        for x in [30, 190, 350]:
            page.draw_line((x, 60), (x, 120))
        for x, y, text in [(40, 80, 'Method'), (200, 80, 'Score'), (40, 110, 'Baseline'), (200, 110, '40.32')]:
            page.insert_text((x, y), text, fontsize=10)
        text, quality = native_page(page)
        assert quality['reliable'] and '|Method|Score|' in text.replace(' ', '')
        assert '|Baseline|40.32|' in text.replace(' ', '')


def test_optional_table_detection_failure_keeps_the_text_layer(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError('complex vector drawing')
    monkeypatch.setattr(pymupdf.Page, 'find_tables', unavailable)
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 80), 'Scientific text stays readable without table detection.')
        for y in range(100, 140, 10):
            page.draw_line((40, y), (100, y))
        text, quality = native_page(page)
        assert 'Scientific text' in text and quality['reliable']
        assert quality['layout_fallback'] == 'table_detection_failed'
