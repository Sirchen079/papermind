"""Unit tests for the read-only research tools (against a seeded SQLite DB)."""
import json

from sqlmodel import Session, SQLModel

from app.agent.tools import (
    TOOLS,
    get_tool,
    t_find_related,
    t_get_paper,
    t_get_paper_full_text,
    t_list_concepts,
    t_search_library,
    tool_schemas,
)
from app.db.engine import make_engine


def _seed():
    """Paper A (transformers), Paper B (transformers + attention), no concepts."""
    eng = make_engine(":memory:")
    SQLModel.metadata.create_all(eng)
    from app.models import Concept, Paper, PaperConcept

    with Session(eng) as s:
        c1, c2 = Concept(name="transformers", normalized_key="transformers"), Concept(name="attention", normalized_key="attention")
        s.add_all([c1, c2])
        s.commit()
        s.refresh(c1)
        s.refresh(c2)
        a = Paper(source="bibtex", title="Attention Is All You Need", abstract="Transformer architecture.", year=2017)
        b = Paper(source="bibtex", title="BERT", abstract="Bidirectional transformers.", year=2019, full_text="Full BERT body text here.")
        s.add_all([a, b])
        s.commit()
        s.refresh(a)
        s.refresh(b)
        s.add_all([PaperConcept(paper_id=a.id, concept_id=c1.id, weight=1.0),
                   PaperConcept(paper_id=b.id, concept_id=c1.id, weight=1.0),
                   PaperConcept(paper_id=b.id, concept_id=c2.id, weight=1.0)])
        s.commit()
        ids = {"a": a.id, "b": b.id}
    return eng, ids


def test_tool_schemas_and_lookup():
    schemas = tool_schemas()
    assert len(schemas) == len(TOOLS) == 5
    assert all(s["type"] == "function" for s in schemas)
    assert get_tool("search_library") is not None
    assert get_tool("nope") is None


def test_search_library_ranks_by_keyword_overlap():
    eng, _ = _seed()
    with Session(eng) as s:
        out = json.loads(t_search_library(s, "transformers"))
    titles = [p["title"] for p in out]
    assert "Attention Is All You Need" in titles
    assert "BERT" in titles


def test_get_paper_returns_metadata_concepts_and_missing_summary():
    eng, ids = _seed()
    with Session(eng) as s:
        out = json.loads(t_get_paper(s, ids["b"]))
    assert out["title"] == "BERT"
    assert "transformers" in out["concepts"] and "attention" in out["concepts"]
    assert out["summary"] is None  # no Summary row seeded


def test_get_paper_full_text_truncates_and_empty_case():
    eng, ids = _seed()
    with Session(eng) as s:
        full = json.loads(t_get_paper_full_text(s, ids["b"]))
        empty = json.loads(t_get_paper_full_text(s, ids["a"]))
    assert "BERT body text" in full["text"]
    assert "note" in empty  # paper A has no full_text


def test_list_concepts_counts_papers():
    eng, _ = _seed()
    with Session(eng) as s:
        out = json.loads(t_list_concepts(s))
    by_name = {c["name"]: c["papers"] for c in out}
    assert by_name["transformers"] == 2
    assert by_name["attention"] == 1


def test_find_related_shares_concepts():
    eng, ids = _seed()
    with Session(eng) as s:
        out = json.loads(t_find_related(s, ids["a"]))  # A shares "transformers" with B
    assert len(out) == 1
    assert out[0]["title"] == "BERT"
    assert out[0]["shared_concepts"] == 1


def test_get_paper_missing_returns_error_json():
    eng, _ = _seed()
    with Session(eng) as s:
        out = json.loads(t_get_paper(s, 99999))
    assert "error" in out
