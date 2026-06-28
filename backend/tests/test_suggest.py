import json

from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.knowledge.suggest import (
    HUB_THRESHOLD,
    concept_hubs,
    concept_links_for_paper,
    generate_all,
)
from app.models import Concept, Paper, PaperConcept, Suggestion


def _mk_paper(s: Session, title: str) -> Paper:
    p = Paper(source="bibtex", title=title)
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


def _mk_concept(s: Session, name: str) -> Concept:
    c = Concept(name=name, normalized_key=name.lower())
    s.add(c)
    s.commit()
    s.refresh(c)
    return c


def _link(s: Session, paper_id: int, concept_id: int) -> None:
    s.add(PaperConcept(paper_id=paper_id, concept_id=concept_id, weight=1.0))
    s.commit()


def _engine(tmp_path):
    eng = make_engine(tmp_path / "sug.sqlite")
    SQLModel.metadata.create_all(eng)
    return eng


def test_concept_links_connects_papers_sharing_concepts(tmp_path):
    eng = _engine(tmp_path)
    with Session(eng) as s:
        a = _mk_paper(s, "Paper A")
        b = _mk_paper(s, "Paper B")
        c = _mk_paper(s, "Paper C (unrelated)")
        transformers = _mk_concept(s, "transformers")
        attention = _mk_concept(s, "attention")
        cnn = _mk_concept(s, "CNN")
        _link(s, a.id, transformers.id)
        _link(s, a.id, attention.id)
        _link(s, b.id, transformers.id)  # A and B share "transformers"
        _link(s, c.id, cnn.id)  # C is unrelated

        created = concept_links_for_paper(s, a)
        b_id = b.id

    assert created == 1  # only B shares a concept with A
    with Session(eng) as s:
        rows = s.exec(select(Suggestion)).all()
    assert len(rows) == 1
    sug = rows[0]
    assert sug.kind == "concept_link"
    assert sug.related_paper_id == b_id
    detail = json.loads(sug.detail_json)
    assert detail["shared_concepts"] == ["transformers"]
    assert sug.weight == 1.0


def test_concept_links_idempotent_on_rescan(tmp_path):
    eng = _engine(tmp_path)
    with Session(eng) as s:
        a = _mk_paper(s, "A")
        b = _mk_paper(s, "B")
        c = _mk_concept(s, "shared")
        _link(s, a.id, c.id)
        _link(s, b.id, c.id)
        first = concept_links_for_paper(s, a)
        second = concept_links_for_paper(s, a)  # rescan — nothing new
    assert first == 1
    assert second == 0
    with Session(eng) as s:
        assert len(s.exec(select(Suggestion)).all()) == 1


def test_concept_links_no_concepts_returns_zero(tmp_path):
    eng = _engine(tmp_path)
    with Session(eng) as s:
        a = _mk_paper(s, "lonely")
        assert concept_links_for_paper(s, a) == 0


def test_concept_links_handles_missing_title(tmp_path):
    """A paper with a null title must not render 'None' in the suggestion title."""
    eng = _engine(tmp_path)
    with Session(eng) as s:
        titled = _mk_paper(s, "Titled Paper")
        untitled = Paper(source="pdf")  # no title
        s.add(untitled)
        s.commit()
        s.refresh(untitled)
        c = _mk_concept(s, "shared")
        _link(s, titled.id, c.id)
        _link(s, untitled.id, c.id)
        concept_links_for_paper(s, untitled)
        rows = s.exec(select(Suggestion)).all()
    titles = " ".join(r.title for r in rows)
    assert "None" not in titles
    assert "#1" in titles or "#2" in titles  # falls back to the id


def test_concept_hubs_flags_central_themes(tmp_path):
    eng = _engine(tmp_path)
    with Session(eng) as s:
        theme = _mk_concept(s, "DeepLearning")
        minor = _mk_concept(s, "obscure")
        for i in range(HUB_THRESHOLD):
            _link(s, _mk_paper(s, f"P{i}").id, theme.id)
        _link(s, _mk_paper(s, "Px").id, minor.id)  # only 1 paper
        created = concept_hubs(s)
    assert created == 1
    with Session(eng) as s:
        rows = s.exec(select(Suggestion).where(Suggestion.kind == "concept_hub")).all()
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert detail["concept"] == "DeepLearning"
    assert detail["papers"] >= HUB_THRESHOLD


def test_generate_all_runs_both_kinds(tmp_path):
    eng = _engine(tmp_path)
    with Session(eng) as s:
        a = _mk_paper(s, "A")
        b = _mk_paper(s, "B")
        theme = _mk_concept(s, "theme")
        _link(s, a.id, theme.id)
        _link(s, b.id, theme.id)
        for i in range(HUB_THRESHOLD):
            _link(s, _mk_paper(s, f"H{i}").id, theme.id)
        created = generate_all(s)
    # at least one concept_link (A-B pair) + one concept_hub
    assert created >= 2
    with Session(eng) as s:
        kinds = {r.kind for r in s.exec(select(Suggestion)).all()}
    assert kinds == {"concept_link", "concept_hub"}
