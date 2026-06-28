import json

_EXTRACT_PROMPT = """你是一名科研论文分析专家。请从下面的论文中抽取 3-8 个关键概念（方法、数据集、问题或领域）。
仅返回一个 JSON 数组，每个对象包含键 "name"（简短的规范中文名称）、"type"（取值之一：method, dataset, problem, domain）、"evidence"（论文中能体现该概念的简短中文短语）。不要任何解释文字，不要 markdown 代码块标记。

标题：{title}
摘要：{abstract}

全文（已截断）：
{text}"""


def extract_concepts(client, provider, model_id, title, abstract, full_text) -> list[dict]:
    """Ask the model for key concepts; return a list of {name, type, evidence}."""
    prompt = _EXTRACT_PROMPT.format(
        title=title or "(unknown)",
        abstract=abstract or "(none)",
        text=(full_text or "")[:8000],
    )
    result = client.complete(
        provider, model_id, [{"role": "user", "content": prompt}], request_kind="ingest"
    )
    return _parse_concepts(result.content)


def _parse_concepts(content: str) -> list[dict]:
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if isinstance(item, dict) and item.get("name"):
            out.append(
                {
                    "name": str(item["name"]),
                    "type": item.get("type") or "domain",
                    "evidence": item.get("evidence"),
                }
            )
    return out
