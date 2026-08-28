import json

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import (
    Chapter,
    Concept,
    Model,
    Paper,
    PaperChunk,
    PaperConcept,
    PaperLink,
    PaperReadingState,
    Project,
    Provider,
    ReviewMatrixEntry,
    Summary,
)


def _check(body: dict, check_id: str) -> dict:
    return next(item for item in body["checks"] if item["id"] == check_id)


def test_readiness_empty_install_points_to_setup_actions(client):
    res = client.get("/api/readiness")

    assert res.status_code == 200
    body = res.json()
    assert body["level"] == "setup"
    assert body["score"] < 50
    assert body["stats"]["papers"] == 0
    assert body["capabilities"]["llm"] is False
    assert body["capabilities"]["embedding"] is False
    assert _check(body, "llm")["status"] == "action"
    assert _check(body, "library")["route"] == "library"
    assert _check(body, "embedding")["route"] == "settings"


def test_readiness_ready_workspace_reports_research_capabilities(client):
    with Session(get_engine()) as session:
        provider = Provider(name="Kimi + SiliconFlow", type="openai_compat", base_url="https://example.invalid/v1")
        session.add(provider)
        session.commit()
        session.refresh(provider)
        session.add(Model(provider_id=provider.id, model_id="moonshot-v1-8k", role_default="chat"))
        session.add(Model(provider_id=provider.id, model_id="BAAI/bge-m3", role_default="embedding"))

        paper = Paper(
            source="manual",
            title="Ready Paper",
            authors_json='["Alice"]',
            abstract="A paper for readiness.",
            full_text="Full text for indexing and reading.",
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)
        session.add(
            Summary(
                paper_id=paper.id,
                content_json=json.dumps({"problem": "P", "method": "M"}, ensure_ascii=False),
            )
        )
        concept = Concept(name="Retrieval", normalized_key="retrieval", type="method")
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(PaperConcept(paper_id=paper.id, concept_id=concept.id))
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text="chunk", embedding=b"123", embedding_model="BAAI/bge-m3"))
        session.add(PaperReadingState(paper_id=paper.id, status="reading", relevance=5))
        session.add(ReviewMatrixEntry(paper_id=paper.id, problem="P", method="M"))
        project = Project(name="硕士论文")
        session.add(project)
        session.commit()
        session.refresh(project)
        chapter = Chapter(project_id=project.id, title="相关工作")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        session.add(PaperLink(paper_id=paper.id, project_id=project.id, chapter_id=chapter.id))
        session.commit()

    res = client.get("/api/readiness")

    assert res.status_code == 200
    body = res.json()
    assert body["level"] == "ready"
    assert body["score"] >= 85
    assert body["stats"]["papers"] == 1
    assert body["stats"]["indexed_chunks"] == 1
    assert body["capabilities"] == {
        "llm": True,
        "embedding": True,
        "library": True,
        "rag": True,
        "graph": True,
        "reading": True,
        "writing": True,
    }
    assert _check(body, "rag")["status"] == "done"
    assert _check(body, "writing")["status"] == "done"
