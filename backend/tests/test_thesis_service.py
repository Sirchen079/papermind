from sqlmodel import Session
import pytest

from app.db.engine import get_engine
from app.models import Paper


def test_thesis_service_writes_tree_and_links(client):
    from app.thesis.service import create_chapter, create_project, get_thesis_workspace, link_paper

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Tree Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        root = create_project(session, {"name": "Master Thesis", "kind": "direction"})
        child = create_project(session, {"name": "Topic A", "kind": "topic", "parent_project_id": root["id"]})
        chapter = create_chapter(session, root["id"], {"title": "Related Work"})
        link = link_paper(session, paper.id, {"project_id": child["id"], "role": "background"})
        workspace = get_thesis_workspace(session)

    assert root["name"] == "Master Thesis"
    assert child["parent_project_id"] == root["id"]
    assert chapter["project_id"] == root["id"]
    assert link["role"] == "background"
    assert workspace["projects"]


def test_thesis_workspace_only_lists_linked_papers(client):
    from app.thesis.service import create_project, get_thesis_workspace, link_paper

    with Session(get_engine()) as session:
        linked = Paper(source="manual", title="Linked Paper")
        unlinked = Paper(source="manual", title="Unlinked Paper")
        session.add(linked)
        session.add(unlinked)
        session.commit()
        session.refresh(linked)
        session.refresh(unlinked)
        linked_id = linked.id
        unlinked_id = unlinked.id

        project = create_project(session, {"name": "Direction", "kind": "direction"})
        link_paper(session, linked_id, {"project_id": project["id"], "role": "background"})
        workspace = get_thesis_workspace(session)

    paper_ids = {paper["id"] for paper in workspace["papers"]}
    assert linked_id in paper_ids
    assert unlinked_id not in paper_ids


def test_thesis_workspace_tolerates_malformed_paper_authors(client):
    from app.thesis.service import create_project, get_thesis_workspace, link_paper

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Malformed Thesis Authors", authors_json="not-json")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        project = create_project(session, {"name": "Direction", "kind": "direction"})
        link_paper(session, paper.id, {"project_id": project["id"], "role": "background"})
        workspace = get_thesis_workspace(session)

    assert workspace["papers"][0]["title"] == "Malformed Thesis Authors"
    assert workspace["papers"][0]["authors"] == []


def test_thesis_hierarchy_rejects_self_parenting(client):
    from app.thesis.service import create_chapter, create_project, patch_chapter, patch_project

    with Session(get_engine()) as session:
        project = create_project(session, {"name": "Direction", "kind": "direction"})
        chapter = create_chapter(session, project["id"], {"title": "Related Work"})

        with pytest.raises(ValueError, match="own parent"):
            patch_project(session, project["id"], {"parent_project_id": project["id"]})

        with pytest.raises(ValueError, match="own parent"):
            patch_chapter(session, chapter["id"], {"parent_chapter_id": chapter["id"]})


def test_thesis_hierarchy_rejects_descendant_parenting(client):
    from app.thesis.service import create_chapter, create_project, patch_chapter, patch_project

    with Session(get_engine()) as session:
        root = create_project(session, {"name": "Direction", "kind": "direction"})
        child = create_project(
            session,
            {"name": "Subtopic", "kind": "topic", "parent_project_id": root["id"]},
        )
        chapter = create_chapter(session, root["id"], {"title": "Related Work"})
        section = create_chapter(
            session,
            root["id"],
            {"title": "Prior Systems", "parent_chapter_id": chapter["id"]},
        )

        with pytest.raises(ValueError, match="descendant"):
            patch_project(session, root["id"], {"parent_project_id": child["id"]})

        with pytest.raises(ValueError, match="descendant"):
            patch_chapter(session, chapter["id"], {"parent_chapter_id": section["id"]})


def test_thesis_delete_rejects_non_empty_projects(client):
    from app.thesis.service import create_chapter, create_project, delete_project, link_paper

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Linked Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        root = create_project(session, {"name": "Direction", "kind": "direction"})
        child = create_project(session, {"name": "Topic", "kind": "topic", "parent_project_id": root["id"]})
        chapter_project = create_project(session, {"name": "Writing", "kind": "writing"})
        linked_project = create_project(session, {"name": "Evidence", "kind": "topic"})
        create_chapter(session, chapter_project["id"], {"title": "Related Work"})
        link_paper(session, paper.id, {"project_id": linked_project["id"], "role": "background"})

        with pytest.raises(ValueError, match="child project"):
            delete_project(session, root["id"])
        with pytest.raises(ValueError, match="chapter"):
            delete_project(session, chapter_project["id"])
        with pytest.raises(ValueError, match="linked paper"):
            delete_project(session, linked_project["id"])

        delete_project(session, child["id"])


def test_thesis_delete_rejects_non_empty_chapters(client):
    from app.thesis.service import create_chapter, create_project, delete_chapter, link_paper

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Linked Chapter Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        project = create_project(session, {"name": "Direction", "kind": "direction"})
        parent = create_chapter(session, project["id"], {"title": "Related Work"})
        child = create_chapter(session, project["id"], {"title": "Prior Systems", "parent_chapter_id": parent["id"]})
        linked = create_chapter(session, project["id"], {"title": "Evidence"})
        link_paper(session, paper.id, {"chapter_id": linked["id"], "role": "evidence"})

        with pytest.raises(ValueError, match="child chapter"):
            delete_chapter(session, parent["id"])
        with pytest.raises(ValueError, match="linked paper"):
            delete_chapter(session, linked["id"])

        delete_chapter(session, child["id"])
