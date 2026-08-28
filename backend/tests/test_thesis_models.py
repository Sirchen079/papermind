from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Paper


def test_thesis_models_roundtrip(tmp_path):
    from app.models import Chapter, PaperLink, Project

    eng = make_engine(tmp_path / "thesis.sqlite")
    SQLModel.metadata.create_all(eng)

    with Session(eng) as session:
        paper = Paper(source="manual", title="Thesis Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)

        root = Project(name="Master Thesis", kind="direction")
        session.add(root)
        session.commit()
        session.refresh(root)

        child = Project(name="Subtopic", kind="topic", parent_project_id=root.id)
        session.add(child)
        session.commit()
        session.refresh(child)

        chapter = Chapter(project_id=root.id, title="Related Work")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)

        session.add(PaperLink(paper_id=paper.id, project_id=child.id, role="background"))
        session.add(PaperLink(paper_id=paper.id, chapter_id=chapter.id, role="evidence"))
        session.commit()

        projects = session.exec(select(Project)).all()
        chapters = session.exec(select(Chapter)).all()
        links = session.exec(select(PaperLink)).all()

    assert len(projects) == 2
    assert len(chapters) == 1
    assert len(links) == 2
    assert links[0].role in {"background", "evidence"}
