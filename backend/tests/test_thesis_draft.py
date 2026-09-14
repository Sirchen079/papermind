"""P10.5 chapter draft generation tests (mocked LLM, no network)."""
from unittest.mock import MagicMock

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper, Summary


def _client_returning(content: str):
    m = MagicMock()
    m.complete.return_value = MagicMock(content=content)
    return m


def _make_chapter_with_papers(client, paper_specs, roles=None):
    """Create project + chapter + linked papers; returns (chapter_id, paper_ids)."""
    project = client.post("/api/thesis/projects", json={"name": "论文项目"}).json()
    chapter = client.post(f"/api/thesis/projects/{project['id']}/chapters", json={"title": "相关工作"}).json()
    paper_ids = []
    with Session(get_engine()) as session:
        for i, (title, key) in enumerate(paper_specs):
            paper = Paper(
                source="manual",
                title=title,
                citation_key=key,
                abstract=f"{title} 的摘要。",
                year=2024,
            )
            session.add(paper)
            session.commit()
            session.refresh(paper)
            paper_ids.append(paper.id)
    roles = roles or ["background"] * len(paper_specs)
    for pid, role in zip(paper_ids, roles):
        resp = client.post(f"/api/papers/{pid}/thesis-links", json={"chapter_id": chapter["id"], "role": role})
        assert resp.status_code == 201
    return chapter["id"], paper_ids


def test_generate_draft_400_when_no_linked_papers(client):
    project = client.post("/api/thesis/projects", json={"name": "空项目"}).json()
    chapter = client.post(f"/api/thesis/projects/{project['id']}/chapters", json={"title": "空章节"}).json()
    resp = client.post(f"/api/thesis/chapters/{chapter['id']}/draft")
    assert resp.status_code == 400
    assert "挂载" in resp.json()["detail"]


def test_generate_draft_400_when_no_llm(client):
    chapter_id, _ = _make_chapter_with_papers(client, [("Only Paper", "only2024paper")])
    resp = client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    assert resp.status_code == 400
    assert "LLM" in resp.json()["detail"]


def test_generate_draft_success_and_version_history(client, monkeypatch):
    chapter_id, _ = _make_chapter_with_papers(
        client,
        [("Retrieval Survey", "smith2024retrieval"), ("Memory Agents", "lee2024memory")],
        roles=["background", "comparison"],
    )

    calls: list[str] = []

    def fake_pick(session, role):
        assert role == "chat"

        class _C:
            def complete(self, provider, model_id, messages, request_kind=None):
                calls.append(messages[0]["content"])
                return MagicMock(content="## 相关工作\n\n如 [@smith2024retrieval] 所述……与 [@lee2024memory] 不同。")

        return _C(), object(), "mock-model"

    monkeypatch.setattr("app.providers.selection.pick_llm", fake_pick)

    resp = client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    assert resp.status_code == 201, resp.text
    draft = resp.json()
    assert draft["chapter_id"] == chapter_id
    assert draft["model"] == "mock-model"
    assert "[@smith2024retrieval]" in draft["content"]

    # The prompt grouped papers by role and used citation keys.
    assert len(calls) == 1
    assert "[角色：背景]" in calls[0]
    assert "[角色：对比]" in calls[0]
    assert "citation_key=smith2024retrieval" in calls[0]
    assert "citation_key=lee2024memory" in calls[0]
    assert "相关工作" in calls[0]

    # Second generation appends a version; list is newest first.
    client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    versions = client.get(f"/api/thesis/chapters/{chapter_id}/drafts").json()
    assert len(versions) == 2
    assert versions[0]["id"] >= versions[1]["id"]


def test_generate_draft_includes_summary_and_matrix(client, monkeypatch):
    chapter_id, (paper_id,) = _make_chapter_with_papers(client, [("Summarized Paper", "kim2024summarized")])
    with Session(get_engine()) as session:
        session.add(
            Summary(
                paper_id=paper_id,
                content_json='{"problem": "检索延迟高", "method": "级联缓存", "results": "延迟降 40%"}',
            )
        )
        session.commit()

    prompts: list[str] = []

    def fake_pick(session, role):
        class _C:
            def complete(self, provider, model_id, messages, request_kind=None):
                prompts.append(messages[0]["content"])
                return MagicMock(content="草稿 [@kim2024summarized]。")

        return _C(), object(), "m"

    monkeypatch.setattr("app.providers.selection.pick_llm", fake_pick)
    resp = client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    assert resp.status_code == 201
    assert "问题：检索延迟高" in prompts[0]
    assert "方法：级联缓存" in prompts[0]


def test_generate_draft_502_on_llm_failure(client, monkeypatch):
    chapter_id, _ = _make_chapter_with_papers(client, [("Doomed Paper", "doom2024paper")])

    def fake_pick(session, role):
        class _Boom:
            def complete(self, *args, **kwargs):
                raise RuntimeError("upstream 500")

        return _Boom(), object(), "m"

    monkeypatch.setattr("app.providers.selection.pick_llm", fake_pick)
    resp = client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    assert resp.status_code == 502
    assert "upstream 500" in resp.json()["detail"]
    # Failure stores no draft version.
    assert client.get(f"/api/thesis/chapters/{chapter_id}/drafts").json() == []


def test_generate_draft_404_for_missing_chapter(client):
    assert client.post("/api/thesis/chapters/9999/draft").status_code == 404
    assert client.get("/api/thesis/chapters/9999/drafts").json() == []


def test_drafts_are_isolated_per_chapter(client, monkeypatch):
    ch1, _ = _make_chapter_with_papers(client, [("Paper One", "one2024paper")])
    ch2, _ = _make_chapter_with_papers(client, [("Paper Two", "two2024paper")])

    def fake_pick(session, role):
        class _C:
            def complete(self, provider, model_id, messages, request_kind=None):
                return MagicMock(content="草稿正文。")

        return _C(), object(), "m"

    monkeypatch.setattr("app.providers.selection.pick_llm", fake_pick)
    client.post(f"/api/thesis/chapters/{ch1}/draft")
    assert len(client.get(f"/api/thesis/chapters/{ch1}/drafts").json()) == 1
    assert client.get(f"/api/thesis/chapters/{ch2}/drafts").json() == []


def test_acceptance_five_papers_draft_keys_match_bib(client, monkeypatch):
    """P10 验收演示（代码级）：章节挂 5 篇论文 → 生成草稿 → 下载章节 .bib →
    key 与草稿 [@citation_key] 占位完全一致。"""
    specs = [
        ("Background Survey", "wang2024background"),
        ("Method Paper", "chen2024method"),
        ("Baseline Comparison", "liu2024baseline"),
        ("Evidence Study", "sun2024evidence"),
        ("Related Extension", "zhou2024related"),
    ]
    chapter_id, _ = _make_chapter_with_papers(
        client, specs, roles=["background", "method", "comparison", "evidence", "related"]
    )
    keys = [key for _title, key in specs]
    prompts: list[str] = []

    class _C:
        def complete(self, provider, model_id, messages, request_kind=None):
            prompts.append(messages[0]["content"])
            return MagicMock(content="综述正文。" + " ".join("[@" + k + "]" for k in keys))

    monkeypatch.setattr("app.providers.selection.pick_llm", lambda s, role: (_C(), object(), "m"))

    draft = client.post(f"/api/thesis/chapters/{chapter_id}/draft")
    assert draft.status_code == 201
    content = draft.json()["content"]

    bib = client.get(f"/api/thesis/chapters/{chapter_id}/bibtex").text

    for key in keys:
        assert f"citation_key={key}" in prompts[0]  # prompt carries each key
        assert f"[@{key}]" in content               # draft cites every paper
        assert f"@article{{{key}," in bib           # bib exports the same key
