"""P10 literature radar tests: subscription CRUD (P10.1), incremental pull (P10.2),
relevance triage (P10.3)."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, select

from app.models import RadarSeen, Setting, Suggestion, Subscription
from app.models.base import utcnow


@pytest.fixture
def session(env):
    from app.main import create_app

    app = create_app()
    from app.db.engine import get_engine

    engine = get_engine()
    with Session(engine) as s:
        yield s


# ---------------------------------------------------------------- P10.1 CRUD

def test_subscription_crud_roundtrip(session):
    from app.radar.service import create_subscription, delete_subscription, list_subscriptions, patch_subscription

    row = create_subscription(
        session,
        {"name": "RAG 跟踪", "query_type": "keyword", "query_value": "retrieval augmented generation"},
    )
    assert row["id"] is not None
    assert row["max_results"] == 20
    assert row["lookback_days"] == 7
    assert row["enabled"] is True
    assert row["last_run_at"] is None

    patched = patch_subscription(session, row["id"], {"max_results": 50, "enabled": False})
    assert patched["max_results"] == 50
    assert patched["enabled"] is False

    assert len(list_subscriptions(session)) == 1
    delete_subscription(session, row["id"])
    assert list_subscriptions(session) == []


def test_subscription_validation_rejects_bad_payload(session):
    from app.radar.service import create_subscription, patch_subscription

    with pytest.raises(ValueError):
        create_subscription(session, {"name": "", "query_type": "keyword", "query_value": "x"})
    with pytest.raises(ValueError):
        create_subscription(session, {"name": "n", "query_type": "bogus", "query_value": "x"})
    with pytest.raises(ValueError):
        create_subscription(session, {"name": "n", "query_type": "keyword", "query_value": " "})
    with pytest.raises(ValueError):
        create_subscription(session, {"name": "n", "query_type": "keyword", "query_value": "x", "max_results": 0})
    with pytest.raises(ValueError):
        create_subscription(session, {"name": "n", "query_type": "keyword", "query_value": "x", "lookback_days": 400})

    row = create_subscription(session, {"name": "n", "query_type": "category", "query_value": "cs.IR"})
    with pytest.raises(ValueError):
        patch_subscription(session, row["id"], {"query_type": "nope"})


def test_subscription_api_crud(client):
    resp = client.post(
        "/api/subscriptions",
        json={"name": "作者跟踪", "query_type": "author", "query_value": "J. Smith", "max_results": 10},
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["query_type"] == "author"

    assert client.get("/api/subscriptions").json() == [row]

    resp = client.patch(f"/api/subscriptions/{row['id']}", json={"lookback_days": 14})
    assert resp.status_code == 200
    assert resp.json()["lookback_days"] == 14

    assert client.post("/api/subscriptions", json={"name": "x", "query_type": "bad", "query_value": "y"}).status_code == 422
    assert client.patch("/api/subscriptions/9999", json={"enabled": False}).status_code == 404
    assert client.patch(f"/api/subscriptions/{row['id']}", json={"max_results": -1}).status_code == 422

    assert client.delete(f"/api/subscriptions/{row['id']}").status_code == 204
    assert client.get("/api/subscriptions").json() == []


def test_subscription_is_due_24h_gate(session):
    from app.radar.service import is_due

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    assert is_due(sub) is True  # never ran

    sub.last_run_at = utcnow() - timedelta(hours=25)
    assert is_due(sub) is True

    sub.last_run_at = utcnow() - timedelta(hours=2)
    assert is_due(sub) is False

    sub.enabled = False
    assert is_due(sub) is False


def test_radarseen_unique_primary_key(session):
    from sqlalchemy.exc import IntegrityError

    session.add(RadarSeen(arxiv_id="2401.00001"))
    session.commit()
    session.add(RadarSeen(arxiv_id="2401.00001"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert len(session.exec(select(RadarSeen)).all()) == 1


# ---------------------------------------------------------------- P10.2 pull

def _entry(arxiv_id: str, title: str) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": f"摘要 of {title}",
        "authors": ["Alice A", "Bob B"],
        "published": "2026-09-01T00:00:00+00:00",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def _fake_query(entries):
    return lambda sub: entries


def test_radar_refresh_creates_suggestions_and_marks_seen(session):
    from app.radar.service import refresh_all

    sub = Subscription(name="RAG", query_type="keyword", query_value="rag")
    session.add(sub)
    session.commit()

    report = refresh_all(
        session,
        force=True,
        query_fn=_fake_query([_entry("2401.00001", "Paper One"), _entry("2401.00002", "Paper Two")]),
    )
    assert report["ran"] == 1
    assert report["created"] == 2
    assert report["results"][0]["status"] == "ok"

    suggestions = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).all()
    assert {s.dedup_key for s in suggestions} == {"radar:2401.00001", "radar:2401.00002"}
    detail = json.loads(suggestions[0].detail_json)
    assert detail["arxiv_id"] in {"2401.00001", "2401.00002"}
    assert detail["subscription"] == "RAG"
    assert detail["url"].startswith("https://arxiv.org/abs/")

    seen = session.exec(select(RadarSeen)).all()
    assert {r.arxiv_id for r in seen} == {"2401.00001", "2401.00002"}

    session.refresh(sub)
    assert sub.last_run_at is not None

    # Re-pull of the same entries: nothing new (RadarSeen idempotency).
    report2 = refresh_all(
        session,
        force=True,
        query_fn=_fake_query([_entry("2401.00001", "Paper One")]),
    )
    assert report2["created"] == 0


def test_radar_refresh_skips_entries_already_in_library(session):
    from app.models import Paper
    from app.radar.service import refresh_all

    session.add(Paper(source="arxiv", arxiv_id="2401.00001", title="In Library"))
    session.commit()

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    session.add(sub)
    session.commit()
    report = refresh_all(
        session,
        force=True,
        query_fn=_fake_query([_entry("2401.00001", "In Library (v2)"), _entry("2401.00003", "Fresh")]),
    )
    assert report["created"] == 1
    kinds = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).all()
    assert [s.title for s in kinds] == ["Fresh"]
    # The library hit is still remembered seen — never re-suggested later.
    assert session.get(RadarSeen, "2401.00001") is not None


def test_radar_refresh_isolates_subscription_failures(session):
    from app.radar import service as radar_service

    ok = radar_service.create_subscription(session, {"name": "ok", "query_type": "keyword", "query_value": "x"})
    bad = radar_service.create_subscription(session, {"name": "bad", "query_type": "keyword", "query_value": "y"})

    def flaky(sub):
        if sub.name == "bad":
            raise RuntimeError("arxiv down")
        return [_entry("2401.00004", "Survivor")]

    report = radar_service.refresh_all(session, force=True, query_fn=flaky)
    assert report["ran"] == 2
    assert report["created"] == 1
    by_name = {r["name"]: r for r in report["results"]}
    assert by_name["bad"]["status"] == "error"
    assert "arxiv down" in by_name["bad"]["error"]
    assert by_name["ok"]["status"] == "ok"

    # The failing subscription keeps its due state untouched (no last_run write
    # on error is acceptable either way; here it must simply not lose data).
    row = radar_service.patch_subscription(session, bad["id"], {"enabled": True})
    assert row["id"] == bad["id"]


def test_radar_refresh_respects_24h_gate_unless_forced(session):
    from app.radar.service import refresh_all

    sub = Subscription(
        name="n", query_type="keyword", query_value="x", last_run_at=utcnow() - timedelta(hours=2)
    )
    session.add(sub)
    session.commit()

    report = refresh_all(session, force=False, query_fn=_fake_query([_entry("2401.00001", "T")]))
    assert report["ran"] == 0  # not due yet

    report = refresh_all(session, force=True, query_fn=_fake_query([_entry("2401.00001", "T")]))
    assert report["ran"] == 1

    disabled = Subscription(name="off", query_type="keyword", query_value="x", enabled=False)
    session.add(disabled)
    session.commit()
    report = refresh_all(session, force=True, query_fn=_fake_query([]))
    assert report["ran"] == 1  # only the enabled one


def test_radar_status_and_refresh_api(client, monkeypatch):
    from app.radar import service as radar_service

    resp = client.post(
        "/api/subscriptions",
        json={"name": "kw", "query_type": "keyword", "query_value": "agent memory"},
    )
    assert resp.status_code == 201

    status = client.get("/api/radar/status").json()
    assert status["total"] == 1
    assert status["enabled"] == 1
    assert status["due"] == 1  # never ran
    assert status["last_run_at"] is None

    monkeypatch.setattr(
        radar_service, "query_arxiv", lambda sub: [_entry("2401.00009", "API Paper")]
    )
    report = client.post("/api/radar/refresh").json()
    assert report["ran"] == 1
    assert report["created"] == 1

    status = client.get("/api/radar/status").json()
    assert status["due"] == 0
    assert status["last_run_at"] is not None

    # The suggestion surfaced through the normal suggestions API.
    suggestions = client.get("/api/suggestions").json()
    assert any(s["kind"] == "radar" and s["title"] == "API Paper" for s in suggestions)


def test_clean_arxiv_id_strips_version_and_prefix():
    from app.radar.service import _clean_arxiv_id

    assert _clean_arxiv_id("http://arxiv.org/abs/2401.00001v2") == "2401.00001"
    assert _clean_arxiv_id("https://arxiv.org/abs/2401.12345") == "2401.12345"
    assert _clean_arxiv_id("2401.00001v1") == "2401.00001"


# ---------------------------------------------------------------- P10.3 triage

def _set_interests(session, text="检索增强生成、agent 记忆"):
    session.add(Setting(key="research_interests", value=text))
    session.commit()


def _grading_client(rules: dict[str, str]):
    """Fake chat client: grades an entry by matching its title in the prompt."""

    class _C:
        def complete(self, provider, model_id, messages, request_kind=None):
            prompt = messages[0]["content"]
            for needle, grade in rules.items():
                if needle in prompt:
                    return MagicMock(
                        content=json.dumps({"grade": grade, "reason": f"{needle} 判定为 {grade}"})
                    )
            return MagicMock(content=json.dumps({"grade": "medium", "reason": "默认"}))

    return _C()


def test_triage_grades_entries_and_hides_low(session, monkeypatch):
    from app.radar import service as radar_service

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    session.add(sub)
    session.commit()
    _set_interests(session)
    monkeypatch.setattr(
        "app.providers.selection.pick_llm",
        lambda s, role: (
            _grading_client({"Paper One": "high", "Paper Two": "low"}),
            object(),
            "model-x",
        ),
    )

    report = radar_service.refresh_all(
        session,
        force=True,
        query_fn=_fake_query(
            [_entry("2401.00001", "Paper One"), _entry("2401.00002", "Paper Two")]
        ),
    )
    assert report["created"] == 1  # low is not surfaced

    suggestions = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).all()
    assert [s.title for s in suggestions] == ["Paper One"]
    detail = json.loads(suggestions[0].detail_json)
    assert detail["grade"] == "high"
    assert "high" in detail["grade_reason"]

    # The low entry is still remembered seen — it never re-surfaces either.
    assert session.get(RadarSeen, "2401.00002") is not None


def test_triage_llm_failure_degrades_to_medium(session, monkeypatch):
    from app.radar import service as radar_service

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    session.add(sub)
    session.commit()
    _set_interests(session)

    class _Boom:
        def complete(self, *args, **kwargs):
            raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.providers.selection.pick_llm", lambda s, role: (_Boom(), object(), "m")
    )
    radar_service.refresh_all(
        session, force=True, query_fn=_fake_query([_entry("2401.00011", "Failing")])
    )
    suggestion = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).one()
    assert json.loads(suggestion.detail_json)["grade"] == "medium"  # never silently dropped


def test_triage_without_interests_degrades_medium_and_skips_llm(session, monkeypatch):
    from app.radar import service as radar_service

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    session.add(sub)
    session.commit()
    calls: list[int] = []
    monkeypatch.setattr(
        "app.providers.selection.pick_llm", lambda s, role: calls.append(1) or (None, None, None)
    )
    radar_service.refresh_all(
        session, force=True, query_fn=_fake_query([_entry("2401.00012", "No Interests")])
    )
    assert calls == []  # nothing to grade against — LLM never asked
    suggestion = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).one()
    assert json.loads(suggestion.detail_json)["grade"] == "medium"


def test_triage_malformed_llm_output_degrades_to_medium(session, monkeypatch):
    from app.radar import service as radar_service

    sub = Subscription(name="n", query_type="keyword", query_value="x")
    session.add(sub)
    session.commit()
    _set_interests(session)

    class _Garbage:
        def complete(self, *args, **kwargs):
            return MagicMock(content="not json at all")

    monkeypatch.setattr(
        "app.providers.selection.pick_llm", lambda s, role: (_Garbage(), object(), "m")
    )
    radar_service.refresh_all(
        session, force=True, query_fn=_fake_query([_entry("2401.00013", "Garbled")])
    )
    suggestion = session.exec(select(Suggestion).where(Suggestion.kind == "radar")).one()
    assert json.loads(suggestion.detail_json)["grade"] == "medium"


def test_radar_suggestion_one_click_ingest_flow(client, monkeypatch):
    """建议中心「一键入库」契约：复用 arXiv 入库 + 建议标记已处理，幂等。"""
    from app.db.engine import get_engine
    from app.ingestion.sources import FetchedPaper

    with Session(get_engine()) as s:
        s.add(
            Suggestion(
                kind="radar",
                title="Radar Paper",
                detail_json=json.dumps(
                    {"arxiv_id": "2401.00077", "grade": "high", "url": "https://arxiv.org/abs/2401.00077"}
                ),
                dedup_key="radar:2401.00077",
            )
        )
        s.commit()
        sid = s.exec(select(Suggestion).where(Suggestion.kind == "radar")).one().id

    def fake_fetch(arxiv_id, client=None):
        return FetchedPaper(
            source="arxiv", source_ref=arxiv_id, title="Radar Paper", arxiv_id=arxiv_id
        )

    monkeypatch.setattr("app.api.papers_api.fetch_arxiv", fake_fetch)
    resp = client.post("/api/papers/arxiv", json={"arxiv_id": "2401.00077"})
    assert resp.status_code == 200, resp.text
    paper_id = resp.json()["id"]

    assert client.patch(f"/api/suggestions/{sid}", json={"status": "accepted"}).status_code == 200

    # 幂等：同一 arxiv_id 再次入库不产生第二篇。
    resp2 = client.post("/api/papers/arxiv", json={"arxiv_id": "2401.00077"})
    assert resp2.status_code == 200
    assert resp2.json()["id"] == paper_id


# ------------------------------------------------ startup background refresh

def test_background_refresh_failure_logs_warning(monkeypatch, caplog):
    """启动后台刷新失败：必须留下带步骤名的 warning（含 traceback），
    但不把异常细节/查询词插值进消息，且线程静默退出、不影响启动。"""
    import logging
    import threading

    from app.radar import service as radar_service

    monkeypatch.delenv("PAPERMIND_DISABLE_RADAR_AUTORUN", raising=False)

    def _boom():
        raise RuntimeError("SENTINEL-engine-down")

    # `_run` 在线程里延迟 `from app.db.engine import get_engine`，因此 patch
    # 源模块属性即可命中运行时实际读取的绑定（无需真实数据库/网络）。
    monkeypatch.setattr("app.db.engine.get_engine", _boom)

    with caplog.at_level(logging.WARNING, logger="app.radar.service"):
        radar_service.start_background_refresh()
        for t in threading.enumerate():
            if t.name == "radar-startup":
                t.join(timeout=10)

    records = [r for r in caplog.records if r.name == "app.radar.service"]
    assert records, "background refresh failure must be logged, not swallowed"
    record = records[-1]
    assert record.levelno == logging.WARNING
    assert "radar_background_refresh" in record.getMessage()
    assert record.exc_info  # exc_info=True — traceback preserved for triage
    assert "SENTINEL-engine-down" not in record.getMessage()  # no interpolation
