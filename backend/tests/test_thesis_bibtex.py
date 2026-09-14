"""P10.6 chapter/project .bib export tests."""
from sqlmodel import Session

from app.db.engine import get_engine
from app.models import Paper


def _add_paper(title: str, citation_key: str | None, **kwargs) -> int:
    with Session(get_engine()) as session:
        paper = Paper(source="manual", title=title, citation_key=citation_key, **kwargs)
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper.id


def _build_tree(client):
    """root project → chapter A (+ sub-chapter A1); child project → chapter B."""
    root = client.post("/api/thesis/projects", json={"name": "Root"}).json()
    child = client.post("/api/thesis/projects", json={"name": "Child", "parent_project_id": root["id"]}).json()
    chapter_a = client.post(f"/api/thesis/projects/{root['id']}/chapters", json={"title": "Chapter A"}).json()
    chapter_a1 = client.post(
        f"/api/thesis/projects/{root['id']}/chapters",
        json={"title": "Chapter A1", "parent_chapter_id": chapter_a["id"]},
    ).json()
    chapter_b = client.post(f"/api/thesis/projects/{child['id']}/chapters", json={"title": "Chapter B"}).json()
    return root, child, chapter_a, chapter_a1, chapter_b


def test_chapter_bibtex_includes_subchapters_and_uses_citation_keys(client):
    root, _child, chapter_a, chapter_a1, _chapter_b = _build_tree(client)
    p1 = _add_paper("Alpha Paper", "alpha2024alpha", year=2024, authors_json='["A. Alpha"]')
    p2 = _add_paper("Beta Paper", "beta2023beta", year=2023, authors_json='["B. Beta"]')
    p3 = _add_paper("Gamma Paper", "gamma2022gamma", year=2022, authors_json='["G. Gamma"]')
    assert client.post(f"/api/papers/{p1}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p2}/thesis-links", json={"chapter_id": chapter_a1["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p3}/thesis-links", json={"project_id": root["id"]}).status_code == 201

    resp = client.get(f"/api/thesis/chapters/{chapter_a['id']}/bibtex")
    assert resp.status_code == 200
    assert "x-bibtex" in resp.headers["content-type"]
    body = resp.text
    assert "@article{alpha2024alpha," in body
    assert "@article{beta2023beta," in body  # sub-chapter recursion
    assert "gamma2022gamma" not in body  # project-only link not in chapter scope


def test_project_bibtex_includes_subtree_projects_and_chapters(client):
    root, child, chapter_a, _chapter_a1, chapter_b = _build_tree(client)
    p1 = _add_paper("Alpha Paper", "alpha2024alpha", year=2024)
    p2 = _add_paper("Beta Paper", "beta2023beta", year=2023)
    p3 = _add_paper("Gamma Paper", "gamma2022gamma", year=2022)
    p4 = _add_paper("Delta Paper", "delta2021delta", year=2021)
    assert client.post(f"/api/papers/{p1}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p2}/thesis-links", json={"project_id": root["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p3}/thesis-links", json={"chapter_id": chapter_b["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p4}/thesis-links", json={"project_id": child["id"]}).status_code == 201

    resp = client.get(f"/api/thesis/projects/{root['id']}/bibtex")
    assert resp.status_code == 200
    body = resp.text
    for key in ("alpha2024alpha", "beta2023beta", "gamma2022gamma", "delta2021delta"):
        assert f"@article{{{key}," in body


def test_project_bibtex_excludes_soft_deleted_papers(client):
    root, _child, chapter_a, _a1, _b = _build_tree(client)
    live = _add_paper("Live Paper", "live2024paper", year=2024)
    dead = _add_paper("Dead Paper", "dead2024paper", year=2024)
    assert client.post(f"/api/papers/{live}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201
    assert client.post(f"/api/papers/{dead}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201
    with Session(get_engine()) as session:
        row = session.get(Paper, dead)
        row.is_deleted = True
        session.add(row)
        session.commit()

    body = client.get(f"/api/thesis/chapters/{chapter_a['id']}/bibtex").text
    assert "live2024paper" in body
    assert "dead2024paper" not in body


def test_bibtex_export_suffixes_colliding_lazy_keys(client):
    """Legacy rows without stored keys can collide after lazy generation —
    the export must still produce unique keys."""
    root, _child, chapter_a, _a1, _b = _build_tree(client)
    p1 = _add_paper("Deep Learning", None, year=2024)  # → lee2024deep? no author → anon
    p2 = _add_paper("Deep Learning", None, year=2024)  # same base → collision
    assert client.post(f"/api/papers/{p1}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201
    assert client.post(f"/api/papers/{p2}/thesis-links", json={"chapter_id": chapter_a["id"]}).status_code == 201

    body = client.get(f"/api/thesis/chapters/{chapter_a['id']}/bibtex").text
    assert "@article{anon2024deep," in body
    assert "@article{anon2024deep2," in body  # numeric suffix keeps .bib parseable
    assert body.count("@article{") == 2


def test_bibtex_export_404_for_missing_targets(client):
    assert client.get("/api/thesis/chapters/9999/bibtex").status_code == 404
    assert client.get("/api/thesis/projects/9999/bibtex").status_code == 404


def test_bibtex_export_empty_scope_returns_empty_content(client):
    root, _child, chapter_a, _a1, _b = _build_tree(client)
    resp = client.get(f"/api/thesis/chapters/{chapter_a['id']}/bibtex")
    assert resp.status_code == 200
    assert resp.text == ""
