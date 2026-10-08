"""Evaluation integrity: don't leak answers or change the compared materials."""
from types import SimpleNamespace

import pytest

from scripts.compare_reading_routes import messages, needs_full_text, output_budget, render_full, validate_dataset


def test_reference_and_audit_never_enter_prompt():
    q = {'user_input': 'Question', 'reference': 'SECRET GOLD ANSWER', 'reviewer_note': 'SECRET ERROR'}
    actual = str(messages(q, 'Full source', 'Shared guidance'))
    assert 'Question' in actual and 'Full source' in actual
    assert 'SECRET' not in actual


def test_full_route_keeps_tail_and_all_candidates():
    papers = [SimpleNamespace(id=1, title='First', full_text='x'*80000+'END_A'),
              SimpleNamespace(id=2, title='Second', full_text='START_B\n'*9000+'END_B')]
    text = render_full(papers)
    assert papers[0].full_text in text and papers[1].full_text in text
    assert text.index('END_A') < text.index('START_B')


def test_missing_full_text_is_not_silently_treated_as_full():
    with pytest.raises(ValueError):
        render_full([SimpleNamespace(id=3, title='Abstract only', full_text='')])


@pytest.mark.parametrize('text,expected', [
    ('UNANSWERABLE', True), (' unanswerable。\n', True),
    ('The paper uses UNANSWERABLE as a routing signal; here is the answer.', False),
    ('', False), ('材料不足，但这里是初步结果。', False),
])
def test_route_does_not_match_a_word_inside_an_answer(text, expected):
    assert needs_full_text(text) is expected


def test_duplicate_or_unsafe_question_ids_cannot_overwrite_results():
    row = {'id': 'q1', 'user_input': 'Question', 'paper_ids': [1], 'split': 'development'}
    with pytest.raises(ValueError):
        validate_dataset({'questions': [row, row]})
    with pytest.raises(ValueError):
        validate_dataset({'questions': [{**row, 'id': '../other'}]})


def test_default_reuses_product_reasoning_budget_but_keeps_explicit_trial_cap():
    model = SimpleNamespace(context_window=1048576, reasoning_effort='high')
    assert output_budget(model) == 10240
    assert output_budget(model, 8192) == 8192
