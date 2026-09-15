from datetime import datetime, timezone
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Provider, TokenUsage


def _seed(client):
    today = datetime.now(timezone.utc).date()
    with Session(get_engine()) as s:
        p = Provider(name="oai", type="openai_chat")
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(
            TokenUsage(
                provider_id=p.id,
                model="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                request_kind="chat",
                day=today,
            )
        )
        s.add(
            TokenUsage(
                provider_id=p.id,
                model="gpt-4o",
                prompt_tokens=40,
                completion_tokens=10,
                total_tokens=50,
                request_kind="ingest",
                day=today,
            )
        )
        s.commit()


def test_usage_aggregates(client):
    _seed(client)
    res = client.get("/api/usage?days=30").json()
    assert res["total_tokens"] == 200
    assert res["by_kind"]["chat"] == 150
    assert res["by_kind"]["ingest"] == 50
    assert res["by_model"]["gpt-4o"] == 200
    assert any(d["tokens"] == 200 for d in res["by_day"])
