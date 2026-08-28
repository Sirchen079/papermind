import json

from sqlmodel import Session

from app.agent.tools import t_add_paper_to_collection, t_tag_paper
from app.db.engine import get_engine


def test_master_research_workflow_http_smoke(client):
    """A master's-workflow smoke test across library, reading, thesis, and export.

    A user can start from a manually entered paper, then carry it through
    reading, thesis organization, agent-assisted organization, and export.
    """
    paper = client.post(
        "/api/papers/manual",
        json={
            "citation_key": "smith2025workflow",
            "title": "A Workflow Paper",
            "authors": ["Ada Smith"],
            "abstract": "A paper about managing a long research workflow.",
            "year": 2025,
            "venue": "PaperMind Symposium",
        },
    )
    assert paper.status_code == 201
    paper_id = paper.json()["id"]

    state = client.patch(
        f"/api/papers/{paper_id}/reading/state",
        json={"status": "read", "priority": "high", "rating": 4, "relevance": 5},
    )
    assert state.status_code == 200
    assert state.json()["status"] == "read"

    note = client.post(
        f"/api/papers/{paper_id}/reading/notes",
        json={
            "kind": "idea",
            "content": "Use this in the thesis motivation.",
            "tags": ["thesis", "motivation"],
        },
    )
    assert note.status_code == 201
    note_id = note.json()["id"]

    excerpt = client.post(
        f"/api/papers/{paper_id}/reading/excerpts",
        json={
            "quote": "A stable workflow turns reading into reusable evidence.",
            "page": 3,
            "section": "Introduction",
            "tags": ["evidence"],
        },
    )
    assert excerpt.status_code == 201

    matrix = client.put(
        f"/api/papers/{paper_id}/reading/matrix",
        json={
            "problem": "Long-running literature work loses context.",
            "method": "Connect papers to durable reading and writing assets.",
            "relation_to_thesis": "Motivates the system design chapter.",
        },
    )
    assert matrix.status_code == 200

    root = client.post("/api/thesis/projects", json={"name": "硕士论文主线", "kind": "direction"})
    assert root.status_code == 201
    root_id = root.json()["id"]
    chapter = client.post(
        f"/api/thesis/projects/{root_id}/chapters",
        json={"title": "第二章 相关工作"},
    )
    assert chapter.status_code == 201
    chapter_id = chapter.json()["id"]

    link = client.post(
        f"/api/papers/{paper_id}/thesis-links",
        json={"chapter_id": chapter_id, "role": "evidence", "note": "支撑研究动机"},
    )
    assert link.status_code == 201

    tag = client.post("/api/tags", json={"name": "核心方法", "color": "#2563eb"})
    assert tag.status_code == 201
    tag_id = tag.json()["id"]
    attached_tag = client.post(f"/api/papers/{paper_id}/tags/{tag_id}")
    assert attached_tag.status_code == 201

    collection = client.post(
        "/api/collections",
        json={"name": "毕业论文必读", "description": "论文写作阶段反复阅读"},
    )
    assert collection.status_code == 201
    collection_id = collection.json()["id"]
    collection_member = client.post(f"/api/collections/{collection_id}/papers/{paper_id}")
    assert collection_member.status_code == 201

    with Session(get_engine()) as session:
        agent_tag = json.loads(t_tag_paper(session, paper_id, "Agent 整理"))
        agent_collection = json.loads(
            t_add_paper_to_collection(session, paper_id, "导师会议讨论", "下次组会需要回顾")
        )
    assert agent_tag["ok"] is True
    assert agent_collection["ok"] is True

    workspace = client.get(f"/api/papers/{paper_id}/reading")
    assert workspace.status_code == 200
    assert workspace.json()["notes"][0]["id"] == note_id
    assert workspace.json()["matrix"]["relation_to_thesis"] == "Motivates the system design chapter."

    library_rows = client.get("/api/papers")
    assert library_rows.status_code == 200
    library_row = next(row for row in library_rows.json() if row["id"] == paper_id)
    assert library_row["reading"]["priority"] == "high"
    assert library_row["reading"]["relevance"] == 5
    assert {tag["name"] for tag in library_row["tags"]} == {"Agent 整理", "核心方法"}
    assert {collection["name"] for collection in library_row["collections"]} == {
        "导师会议讨论",
        "毕业论文必读",
    }

    thesis_workspace = client.get("/api/thesis/workspace")
    assert thesis_workspace.status_code == 200
    thesis_body = thesis_workspace.json()
    assert thesis_body["projects"][0]["chapters"][0]["title"] == "第二章 相关工作"
    linked_paper = next(row for row in thesis_body["papers"] if row["id"] == paper_id)
    assert linked_paper["links"][0]["role"] == "evidence"

    exported = json.loads(client.get("/api/archive/export/json").text)
    assert exported["papers"][0]["title"] == "A Workflow Paper"
    assert exported["reading_states"][0]["status"] == "read"
    assert exported["paper_notes"][0]["content"] == "Use this in the thesis motivation."
    assert exported["paper_excerpts"][0]["quote"] == "A stable workflow turns reading into reusable evidence."
    assert exported["review_matrix_entries"][0]["problem"] == "Long-running literature work loses context."
    assert exported["projects"][0]["name"] == "硕士论文主线"
    assert exported["chapters"][0]["title"] == "第二章 相关工作"
    assert exported["paper_links"][0]["chapter_id"] == chapter_id
    assert {tag["name"] for tag in exported["tags"]} == {"Agent 整理", "核心方法"}
    assert {link["paper_id"] for link in exported["paper_tags"]} == {paper_id}
    assert {collection["name"] for collection in exported["collections"]} == {
        "导师会议讨论",
        "毕业论文必读",
    }
    assert {link["paper_id"] for link in exported["collection_papers"]} == {paper_id}
