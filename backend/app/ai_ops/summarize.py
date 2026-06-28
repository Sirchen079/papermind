import json

_SUMMARY_PROMPT = """你是一名科研论文分析专家。请将下面的论文总结为一个 JSON 对象，恰好包含以下键，每个值都是简洁的简体中文字符串：
{{"problem": "...", "method": "...", "dataset": "...", "results": "...", "limitations": "..."}}
若某字段不适用，填 "不适用"。仅返回 JSON 对象本身（不要任何解释文字，不要 markdown 代码块标记）。

标题：{title}
摘要：{abstract}

全文（已截断）：
{text}"""


def summarize_paper(
    client,  # ProviderClient
    provider,  # Provider
    model_id: str,
    title: str | None,
    abstract: str | None,
    full_text: str | None,
) -> dict:
    """Ask the model for a structured summary; return a parsed dict.

    The dict is one of: the five structured keys, or ``{"freeform": ...}``
    if the model did not return parseable JSON.
    """
    prompt = _SUMMARY_PROMPT.format(
        title=title or "(unknown)",
        abstract=abstract or "(none)",
        text=(full_text or "")[:8000],
    )
    result = client.complete(
        provider,
        model_id,
        [{"role": "user", "content": prompt}],
        request_kind="ingest",
    )
    return _parse_summary(result.content)


def _parse_summary(content: str) -> dict:
    """Best-effort parse; tolerate markdown fences around the JSON."""
    if not content:
        return {"freeform": ""}
    text = content.strip()
    if text.startswith("```"):
        # strip a leading ```json or ``` and a trailing ```
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001
        pass
    return {"freeform": content}
