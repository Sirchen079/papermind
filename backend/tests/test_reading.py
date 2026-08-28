import json
from datetime import datetime, timezone
from unittest.mock import patch

from sqlmodel import Session, SQLModel, select

from app.db.engine import get_engine, make_engine
from app.models import Model, Paper, Provider, ReviewMatrixEntry, Summary
from app.providers.client import CompletionResult


def test_reading_models_roundtrip(tmp_path):
    from app.models import PaperExcerpt, PaperNote, PaperReadingState, ReviewMatrixEntry

    eng = make_engine(tmp_path / "m.sqlite")
    SQLModel.metadata.create_all(eng)

    with Session(eng) as session:
        paper = Paper(source="manual", title="Reading Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        session.add(PaperReadingState(paper_id=paper.id, status="reading", priority="high", rating=4, relevance=5))
        session.add(PaperNote(paper_id=paper.id, kind="note", content="Important note", tags_json='["core"]'))
        session.add(PaperExcerpt(paper_id=paper.id, quote="Key evidence", page=3, tags_json='["evidence"]'))
        session.add(ReviewMatrixEntry(paper_id=paper.id, problem="Problem", method="Method"))
        session.commit()

        state = session.exec(select(PaperReadingState)).one()
        note = session.exec(select(PaperNote)).one()
        excerpt = session.exec(select(PaperExcerpt)).one()
        matrix = session.exec(select(ReviewMatrixEntry)).one()

    assert state.status == "reading"
    assert state.priority == "high"
    assert note.content == "Important note"
    assert excerpt.page == 3
    assert matrix.problem == "Problem"
    assert isinstance(state.updated_at, datetime)


def _paper(session: Session, title: str = "Reading Paper") -> Paper:
    paper = Paper(source="manual", title=title, authors_json='["Alice"]', year=2024)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _seed_chat_provider() -> None:
    with Session(get_engine()) as session:
        provider = Provider(name="kimi", type="openai_compat", base_url="https://example.invalid/v1")
        session.add(provider)
        session.commit()
        session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id="moonshot-v1-8k", role_default="chat"))
        session.commit()


def test_default_workspace_for_unread_paper(client):
    from app.reading.service import get_reading_workspace

    with Session(get_engine()) as session:
        paper = _paper(session)

        workspace = get_reading_workspace(session, paper.id)

    assert workspace["state"]["status"] == "unread"
    assert workspace["state"]["priority"] == "normal"
    assert workspace["state"]["rating"] is None
    assert workspace["state"]["relevance"] is None
    assert workspace["notes"] == []
    assert workspace["excerpts"] == []
    assert workspace["matrix"] is None


def test_patch_reading_state_applies_timestamp_rules(client):
    from app.reading.service import patch_reading_state

    with Session(get_engine()) as session:
        paper = _paper(session)

        reading = patch_reading_state(session, paper.id, {"status": "reading", "priority": "high"})
        read = patch_reading_state(session, paper.id, {"status": "read", "rating": 4, "relevance": 5})

    assert reading["status"] == "reading"
    assert reading["priority"] == "high"
    assert reading["started_at"] is not None
    assert reading["last_read_at"] is not None
    assert read["status"] == "read"
    assert read["rating"] == 4
    assert read["relevance"] == 5
    assert read["started_at"] == reading["started_at"]
    assert read["finished_at"] is not None


def test_reading_state_validation(client):
    import pytest

    from app.reading.service import patch_reading_state

    with Session(get_engine()) as session:
        paper = _paper(session)

        for payload in [
            {"status": "done"},
            {"priority": "urgent"},
            {"rating": 0},
            {"rating": 6},
            {"relevance": 0},
            {"relevance": 6},
        ]:
            with pytest.raises(ValueError):
                patch_reading_state(session, paper.id, payload)


def test_notes_lifecycle(client):
    from app.reading.service import create_note, delete_note, get_reading_workspace, patch_note

    with Session(get_engine()) as session:
        paper = _paper(session)

        note = create_note(session, paper.id, {"kind": "idea", "content": "Use this in chapter 2", "tags": ["thesis"]})
        updated = patch_note(session, paper.id, note["id"], {"content": "Use this in related work"})
        workspace = get_reading_workspace(session, paper.id)
        delete_note(session, paper.id, note["id"])
        after_delete = get_reading_workspace(session, paper.id)

    assert note["kind"] == "idea"
    assert note["tags"] == ["thesis"]
    assert updated["content"] == "Use this in related work"
    assert workspace["notes"][0]["content"] == "Use this in related work"
    assert after_delete["notes"] == []


def test_excerpts_lifecycle_and_validation(client):
    import pytest

    from app.reading.service import create_excerpt, delete_excerpt, get_reading_workspace, patch_excerpt

    with Session(get_engine()) as session:
        paper = _paper(session)

        with pytest.raises(ValueError):
            create_excerpt(session, paper.id, {"quote": "Evidence", "page": 0})

        excerpt = create_excerpt(
            session,
            paper.id,
            {"quote": "Important evidence", "page": 2, "section": "Method", "tags": ["evidence"]},
        )
        updated = patch_excerpt(session, paper.id, excerpt["id"], {"note": "Supports my baseline choice"})
        workspace = get_reading_workspace(session, paper.id)
        delete_excerpt(session, paper.id, excerpt["id"])
        after_delete = get_reading_workspace(session, paper.id)

    assert excerpt["quote"] == "Important evidence"
    assert excerpt["page"] == 2
    assert excerpt["tags"] == ["evidence"]
    assert updated["note"] == "Supports my baseline choice"
    assert workspace["excerpts"][0]["section"] == "Method"
    assert after_delete["excerpts"] == []


def test_matrix_upsert_and_listing(client):
    from app.reading.service import list_review_matrix, patch_reading_state, upsert_review_matrix

    with Session(get_engine()) as session:
        paper = _paper(session, "Matrix Paper")
        patch_reading_state(session, paper.id, {"status": "read", "priority": "high", "relevance": 5})
        matrix = upsert_review_matrix(
            session,
            paper.id,
            {
                "problem": "Problem",
                "method": "Method",
                "results": "Strong result",
                "relation_to_thesis": "Directly useful",
            },
        )
        rows = list_review_matrix(session, status="read", min_relevance=4, high_priority=True)

    assert matrix["problem"] == "Problem"
    assert len(rows) == 1
    assert rows[0]["paper"]["title"] == "Matrix Paper"
    assert rows[0]["state"]["status"] == "read"
    assert rows[0]["matrix"]["relation_to_thesis"] == "Directly useful"


def test_matrix_suggestion_uses_chat_llm_without_saving(client):
    _seed_chat_provider()
    with Session(get_engine()) as session:
        paper = _paper(session, "LLM Matrix Paper")
        paper.abstract = "This paper studies retrieval augmented literature review workflows."
        paper.full_text = "The method builds a graph and evaluates precision and recall on graduate papers."
        session.add(paper)
        session.add(
            Summary(
                paper_id=paper.id,
                content_json=json.dumps(
                    {
                        "problem": "Existing literature tools do not connect reading notes to thesis writing.",
                        "method": "A structured review workflow with graph support.",
                    }
                ),
            )
        )
        session.commit()
        pid = paper.id

    fake = CompletionResult(
        content=json.dumps(
            {
                "problem": "现有工具难以把阅读记录转化为论文写作材料。",
                "method": "构建检索增强的文献审阅流程。",
                "dataset": "研究生论文管理样例库。",
                "metrics": "Precision、Recall 和人工可用性评价。",
                "results": "能够减少人工整理审阅矩阵的时间。",
                "limitations": "样本规模仍有限。",
                "novelty": "把图谱、矩阵和写作素材联动。",
                "relation_to_thesis": "可用于相关工作章节的文献对比。",
                "future_work": "扩展到多学科论文库。",
                "notes": "需要人工核对模型抽取结果。",
            },
            ensure_ascii=False,
        ),
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )

    with patch("app.providers.client.ProviderClient.complete", return_value=fake) as mocked:
        res = client.post(f"/api/papers/{pid}/reading/matrix/suggest")

    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["model"] == "moonshot-v1-8k"
    assert body["draft"]["problem"] == "现有工具难以把阅读记录转化为论文写作材料。"
    assert body["draft"]["relation_to_thesis"] == "可用于相关工作章节的文献对比。"
    assert mocked.call_args.args[3] == "reading_matrix_suggest"
    with Session(get_engine()) as session:
        assert session.exec(select(ReviewMatrixEntry).where(ReviewMatrixEntry.paper_id == pid)).first() is None


def test_matrix_suggestion_reports_unconfigured_without_llm(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "No LLM Matrix Paper")
        pid = paper.id

    res = client.post(f"/api/papers/{pid}/reading/matrix/suggest")

    assert res.status_code == 200
    assert res.json() == {
        "configured": False,
        "model": None,
        "draft": {},
        "error": "未配置可用的 LLM，请先在设置中配置对话模型。",
    }


def test_matrix_listing_searches_linked_concepts(client):
    from app.models import Concept, PaperConcept
    from app.reading.service import list_review_matrix, upsert_review_matrix

    with Session(get_engine()) as session:
        matching = _paper(session, "Concept Search Target")
        other = _paper(session, "Unrelated Reading")
        concept = Concept(name="Contrastive Learning", normalized_key="contrastive learning", type="method")
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(PaperConcept(paper_id=matching.id, concept_id=concept.id))
        session.commit()
        upsert_review_matrix(session, matching.id, {"method": "Representation method"})
        upsert_review_matrix(session, other.id, {"method": "No concept link"})

        rows = list_review_matrix(session, q="contrastive")

    assert [row["paper"]["title"] for row in rows] == ["Concept Search Target"]


def test_matrix_listing_tolerates_malformed_paper_authors(client):
    from app.reading.service import list_review_matrix, upsert_review_matrix

    with Session(get_engine()) as session:
        paper = _paper(session, "Malformed Authors Paper")
        paper.authors_json = "not-json"
        session.add(paper)
        session.commit()
        upsert_review_matrix(session, paper.id, {"problem": "Keep row visible"})

        rows = list_review_matrix(session)

    assert rows[0]["paper"]["title"] == "Malformed Authors Paper"
    assert rows[0]["paper"]["authors"] == []
    assert rows[0]["matrix"]["problem"] == "Keep row visible"


def test_reading_service_hides_soft_deleted_papers(client):
    import pytest

    from app.reading.service import get_reading_workspace

    with Session(get_engine()) as session:
        paper = _paper(session)
        paper.is_deleted = True
        session.add(paper)
        session.commit()

        with pytest.raises(LookupError):
            get_reading_workspace(session, paper.id)


def test_reading_api_workspace_state_notes_excerpts_and_matrix(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "API Reading Paper")
        pid = paper.id

    default = client.get(f"/api/papers/{pid}/reading")
    assert default.status_code == 200
    assert default.json()["state"]["status"] == "unread"

    state = client.patch(
        f"/api/papers/{pid}/reading/state",
        json={"status": "reading", "priority": "high", "rating": 4, "relevance": 5},
    )
    assert state.status_code == 200
    assert state.json()["status"] == "reading"
    assert state.json()["priority"] == "high"

    note = client.post(
        f"/api/papers/{pid}/reading/notes",
        json={"kind": "question", "content": "Can I reuse this method?", "tags": ["todo"]},
    )
    assert note.status_code == 201
    note_id = note.json()["id"]
    patched_note = client.patch(
        f"/api/papers/{pid}/reading/notes/{note_id}",
        json={"content": "Compare this method with my baseline"},
    )
    assert patched_note.status_code == 200
    assert patched_note.json()["content"] == "Compare this method with my baseline"

    excerpt = client.post(
        f"/api/papers/{pid}/reading/excerpts",
        json={"quote": "The key empirical result.", "page": 7, "section": "Experiments"},
    )
    assert excerpt.status_code == 201
    excerpt_id = excerpt.json()["id"]
    patched_excerpt = client.patch(
        f"/api/papers/{pid}/reading/excerpts/{excerpt_id}",
        json={"note": "Use in evaluation section"},
    )
    assert patched_excerpt.status_code == 200
    assert patched_excerpt.json()["note"] == "Use in evaluation section"

    matrix = client.put(
        f"/api/papers/{pid}/reading/matrix",
        json={"problem": "API problem", "method": "API method", "relation_to_thesis": "high"},
    )
    assert matrix.status_code == 200
    assert matrix.json()["problem"] == "API problem"

    workspace = client.get(f"/api/papers/{pid}/reading").json()
    assert workspace["notes"][0]["content"] == "Compare this method with my baseline"
    assert workspace["excerpts"][0]["quote"] == "The key empirical result."
    assert workspace["matrix"]["method"] == "API method"

    matrix_rows = client.get("/api/reading/matrix?status=reading&min_relevance=4&high_priority=true")
    assert matrix_rows.status_code == 200
    assert matrix_rows.json()[0]["paper"]["title"] == "API Reading Paper"

    assert client.delete(f"/api/papers/{pid}/reading/notes/{note_id}").status_code == 204
    assert client.delete(f"/api/papers/{pid}/reading/excerpts/{excerpt_id}").status_code == 204


def test_reading_api_validation_and_ownership(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "Owner A")
        other = _paper(session, "Owner B")
        pid = paper.id
        other_id = other.id

    assert client.patch(f"/api/papers/{pid}/reading/state", json={"status": "done"}).status_code == 422
    assert client.post(f"/api/papers/{pid}/reading/notes", json={"content": ""}).status_code == 422
    assert client.post(f"/api/papers/{pid}/reading/excerpts", json={"quote": "x", "page": 0}).status_code == 422

    note = client.post(f"/api/papers/{pid}/reading/notes", json={"content": "owned"}).json()
    assert client.patch(f"/api/papers/{other_id}/reading/notes/{note['id']}", json={"content": "steal"}).status_code == 404


def test_papers_list_includes_reading_summary(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "List Reading Paper")
        pid = paper.id

    client.patch(f"/api/papers/{pid}/reading/state", json={"status": "queued", "priority": "high", "relevance": 4})
    rows = client.get("/api/papers").json()
    row = next(item for item in rows if item["id"] == pid)

    assert row["reading"] == {
        "status": "queued",
        "priority": "high",
        "rating": None,
        "relevance": 4,
    }
