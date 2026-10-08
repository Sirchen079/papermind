from app.reviews.verify import check_field, find_quote, normalize, numbers_in


def test_normalize_fullwidth_letters_digits_and_parens():
    assert normalize('ＡＢＣ（５２.７）') == 'abc(52.7)'


def test_normalize_ligatures():
    assert normalize('the ﬁle ﬂow') == 'the file flow'


def test_normalize_removes_soft_hyphen():
    assert normalize('extra\u00adordinary') == 'extraordinary'


def test_normalize_merges_hyphen_linebreak_between_lowercase():
    assert normalize('the inver-\nsion method') == 'the inversion method'


def test_normalize_keeps_hyphen_when_uppercase_around_linebreak():
    assert normalize('INVER-\nSION') == 'inver- sion'


def test_normalize_unifies_quotes_and_dashes():
    assert normalize('“x” ‘y’ – z — w') == '"x" \'y\' - z - w'


def test_normalize_strips_page_markers_and_page_headings():
    text = '<!-- page:3 -->\n## 第 3 页\n\nBody text\n'
    assert normalize(text) == 'body text'


def test_normalize_collapses_whitespace_lowercases_and_strips():
    assert normalize('  Mixed   CASE\n\ttext  ') == 'mixed case text'


def test_find_quote_exact_returns_original_positions():
    haystack = 'ABC hello world XYZ'
    start, end = find_quote(haystack, 'HELLO\nWORLD')
    assert haystack[start:end] == 'hello world'


def test_find_quote_crosses_newline():
    haystack = 'one two\nthree four'
    start, end = find_quote(haystack, 'two three')
    assert haystack[start:end] == 'two\nthree'


def test_find_quote_matches_hyphen_split_word():
    haystack = 'applies inver-\nsion everywhere'
    start, end = find_quote(haystack, 'applies inversion everywhere')
    assert 'inver-' in haystack[start:end] and 'sion' in haystack[start:end]


def test_find_quote_matches_ligature_in_haystack():
    haystack = 'the ﬁle contains data'
    start, end = find_quote(haystack, 'the file contains')
    assert haystack[start:end].startswith('the')


def test_find_quote_fullwidth_parens_and_digits():
    haystack = '得分（52.7）较高'
    start, end = find_quote(haystack, '(52.7)')
    assert '52.7' in haystack[start:end]


def test_find_quote_curly_quotes_in_haystack():
    haystack = 'he said “52.7 percent” loudly'
    start, end = find_quote(haystack, '"52.7 percent"')
    assert '52.7' in haystack[start:end]


def test_find_quote_fuzzy_one_word_changed():
    haystack = 'the quick brown fox jumps over the lazy dog near the river bank today'
    quote = 'the quick brown fox jumps over the lazy cat near the river bank today'
    found = find_quote(haystack, quote, threshold=0.9)
    assert found is not None
    start, end = found
    assert haystack[start:end].startswith('the quick')


def test_find_quote_fabricated_long_quote_not_found():
    haystack = 'a short body of entirely different scientific content here'
    quote = 'completely invented words that never appear anywhere near this text body'
    assert find_quote(haystack, quote) is None


def test_find_quote_short_quote_is_exact_match_only():
    haystack = 'score 48.1 here'
    assert find_quote(haystack, 'score 48.2') is None
    assert find_quote(haystack, 'score 48.1') is not None


def test_find_quote_empty_returns_none():
    assert find_quote('haystack', '') is None
    assert find_quote('haystack', '   ') is None


def test_numbers_in_strips_trailing_decimal_zeros():
    assert numbers_in('52.70') == ['52.7']
    assert numbers_in('3.0') == ['3']


def test_numbers_in_removes_thousands_separator():
    assert numbers_in('1,234 items') == ['1234']


def test_numbers_in_scientific_notation_forms_agree():
    assert numbers_in('1.5×10^-3') == ['1.5e-3']
    assert numbers_in('1.5E-3') == ['1.5e-3']
    assert numbers_in('1.5×10^-3') == numbers_in('1.5e-3')


def test_numbers_in_negative_and_percent():
    assert numbers_in('-0.5') == ['-0.5']
    assert numbers_in('12%') == ['12']


def test_numbers_in_skips_years_and_citation_brackets():
    assert numbers_in('in 2023 we found') == []
    assert numbers_in('as reported [12]') == []
    assert numbers_in('compare [12, 15] and 2024') == []


def test_check_field_verified_with_exact_quote():
    sources = {'abstract': 'the method reaches 52.7 accuracy on the benchmark'}
    result = check_field('52.7', 'reaches 52.7 accuracy', sources)
    assert result['status'] == 'quote_verified'
    assert result['found_in'] == 'abstract' and result['similarity'] == 1.0
    assert result['missing_numbers'] == [] and result['pages'] == []


def test_check_field_number_mismatch():
    sources = {'abstract': 'the baseline scores 48.1 overall'}
    result = check_field('52.7', 'the baseline scores 48.1 overall', sources)
    assert result['status'] == 'number_mismatch'
    assert result['missing_numbers'] == ['52.7']


def test_check_field_prefers_earlier_source():
    sources = {'abstract': 'shared quote appears here', 'full_text': 'shared quote appears here'}
    result = check_field('value', 'shared quote appears', sources)
    assert result['found_in'] == 'abstract'


def test_check_field_missing_quote():
    result = check_field('52.7', 'words that appear nowhere', {'abstract': 'other text'})
    assert result['status'] == 'quote_not_found' and result['found_in'] is None


def test_check_field_no_quote():
    result = check_field('52.7', '', {'abstract': 'text'})
    assert result['status'] == 'no_quote'


def test_check_field_full_text_pages_single_and_spanning():
    full_text = '<!-- page:3 -->\n## 第 3 页\n\nalpha 52.7 beta\n<!-- page:4 -->\n## 第 4 页\n\ngamma 7 delta'
    single = check_field('52.7', 'alpha 52.7 beta', {'full_text': full_text})
    assert single['found_in'] == 'full_text' and single['pages'] == [3]
    spanning = check_field('52.7', 'alpha 52.7 beta gamma', {'full_text': full_text})
    assert spanning['pages'] == [3, 4]


def _long_text_with_sentence():
    paragraph = 'the quick brown fox jumps over the lazy dog and nothing else happens here at all. '
    filler = paragraph * 1500  # 规范化后约 11 万字符，接近实测的慢场景
    sentence = 'we restore the wavefield from sparse observations across several marine surveys and report uncertainties'
    middle = len(filler) // 2
    return filler[:middle] + sentence + '. ' + filler[middle:], sentence


def test_find_quote_long_text_fuzzy_hit_covers_sentence():
    text, sentence = _long_text_with_sentence()
    quote = sentence.replace('observations', 'observation')  # 一处小改写
    result = find_quote(text, quote)
    assert result is not None
    start, end = result
    # 现有窗口规则按最高相似度选窗、步长为引文 1/4，返回区间与原句充分重叠即可
    s_start = text.index(sentence)
    overlap = min(end, s_start + len(sentence)) - max(start, s_start)
    assert overlap >= len(sentence) * 0.7


def test_find_quote_long_text_fabricated_quote_is_fast_none():
    import time

    text, _ = _long_text_with_sentence()
    quote = ('uncertainties surveys wavefield observations marine sparse '
             'restore report several reordered into nonsense')  # 长词都来自原句但顺序打乱
    began = time.perf_counter()
    result = find_quote(text, quote)
    elapsed = time.perf_counter() - began
    assert result is None
    assert elapsed < 0.5, elapsed


def test_find_quote_long_text_absent_long_words_return_none():
    text, _ = _long_text_with_sentence()
    quote = 'xylophone quadrilateral unrecognized abracadabra phenomenon entirely fabricated'
    assert find_quote(text, quote) is None
