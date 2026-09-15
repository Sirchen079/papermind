from unittest.mock import MagicMock

from app.ai_ops.summarize import summarize_paper


def _client_returning(content: str) -> MagicMock:
    client = MagicMock()
    client.complete.return_value = MagicMock(content=content)
    return client


def test_summarize_parses_json():
    client = _client_returning(
        '{"problem":"X","method":"Y","dataset":"n/a","results":"R","limitations":"L"}'
    )
    out = summarize_paper(client, MagicMock(), "gpt-4o", "T", "A", "full")
    assert out["problem"] == "X"
    assert out["method"] == "Y"
    client.complete.assert_called_once()


def test_summarize_strips_markdown_fence():
    client = _client_returning('```json\n{"problem":"Z"}\n```')
    out = summarize_paper(client, MagicMock(), "gpt-4o", "T", "A", None)
    assert out["problem"] == "Z"


def test_summarize_freeform_fallback():
    client = _client_returning("not json at all")
    out = summarize_paper(client, MagicMock(), "gpt-4o", "T", "A", None)
    assert out == {"freeform": "not json at all"}
