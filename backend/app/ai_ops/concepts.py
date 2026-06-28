import json

_EXTRACT_PROMPT = """You are a research-paper analyst. Extract 3-8 key concepts (methods, datasets, problems, or domains) from the paper below.
Return ONLY a JSON array of objects, each with keys "name" (short canonical name), "type" (one of: method, dataset, problem, domain), and "evidence" (a short phrase from the paper). No prose, no markdown fences.

Title: {title}
Abstract: {abstract}

Full text (truncated):
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
