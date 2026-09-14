"""Unit tests for the read-only research tools (against a seeded SQLite DB)."""
import json

from sqlmodel import Session, SQLModel, select

from app.agent.tools import (
    TOOLS,
    get_tool,
    t_find_related,
    t_add_paper_to_collection,
    t_tag_paper,
    t_get_paper,
    t_get_paper_full_text,
    t_list_concepts,
    t_search_library,
    t_search_research_notes,
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
    assert len(schemas) == len(TOOLS) == 10
    assert get_tool("ask_user") is not None
    assert all(s["type"] == "function" for s in schemas)
    assert get_tool("search_library") is not None
    assert get_tool("search_research_notes") is not None
    assert get_tool("tag_paper") is not None
    assert get_tool("add_paper_to_collection") is not None
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


def test_get_paper_tolerates_non_list_authors_json():
    eng, ids = _seed()
    from app.models import Paper

    with Session(eng) as s:
        paper = s.get(Paper, ids["b"])
        paper.authors_json = '{"bad":"shape"}'
        s.add(paper)
        s.commit()

        out = json.loads(t_get_paper(s, ids["b"]))

    assert out["title"] == "BERT"
    assert out["authors"] == []


def test_get_paper_tolerates_non_object_summary_json():
    eng, ids = _seed()
    from app.models import Summary

    with Session(eng) as s:
        s.add(Summary(paper_id=ids["b"], content_json='["not", "a", "summary"]'))
        s.commit()

        out = json.loads(t_get_paper(s, ids["b"]))

    assert out["title"] == "BERT"
    assert out["summary"] is None


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


def test_list_concepts_ignores_deleted_paper_links():
    eng, _ = _seed()
    from app.models import Concept, Paper, PaperConcept

    with Session(eng) as s:
        deleted = Paper(source="manual", title="Deleted Contributor", is_deleted=True)
        stale = Concept(name="stale-only", normalized_key="stale-only")
        s.add(deleted)
        s.add(stale)
        s.commit()
        s.refresh(deleted)
        s.refresh(stale)
        s.add(PaperConcept(paper_id=deleted.id, concept_id=stale.id))
        transformer = s.exec(select(Concept).where(Concept.name == "transformers")).one()
        s.add(PaperConcept(paper_id=deleted.id, concept_id=transformer.id))
        s.commit()

        out = json.loads(t_list_concepts(s, min_papers=2))

    by_name = {c["name"]: c["papers"] for c in out if "name" in c}
    assert by_name == {"transformers": 2}


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


def test_tag_paper_creates_tag_and_attaches_it():
    eng, ids = _seed()
    from app.models import PaperTag, Tag

    with Session(eng) as s:
        out = json.loads(t_tag_paper(s, ids["a"], " 核心方法 ", color="#2563eb"))
        tag = s.exec(select(Tag).where(Tag.name == "核心方法")).one()
        link = s.exec(select(PaperTag).where(PaperTag.paper_id == ids["a"], PaperTag.tag_id == tag.id)).one()

    assert out["ok"] is True
    assert out["paper_id"] == ids["a"]
    assert out["tag"]["name"] == "核心方法"
    assert link.paper_id == ids["a"]


def test_add_paper_to_collection_creates_collection_and_membership():
    eng, ids = _seed()
    from app.models import Collection, CollectionPaper

    with Session(eng) as s:
        out = json.loads(
            t_add_paper_to_collection(
                s,
                ids["b"],
                "研究论文必读",
                description="论文写作阶段反复阅读",
            )
        )
        collection = s.exec(select(Collection).where(Collection.name == "研究论文必读")).one()
        link = s.exec(
            select(CollectionPaper).where(
                CollectionPaper.collection_id == collection.id,
                CollectionPaper.paper_id == ids["b"],
            )
        ).one()

    assert out["ok"] is True
    assert out["paper_id"] == ids["b"]
    assert out["collection"]["name"] == "研究论文必读"
    assert link.paper_id == ids["b"]


def test_agent_organization_tools_do_not_create_orphans_for_missing_paper():
    eng, _ = _seed()
    from app.models import Collection, Tag

    with Session(eng) as s:
        tag_out = json.loads(t_tag_paper(s, 99999, "不存在论文标签"))
        collection_out = json.loads(t_add_paper_to_collection(s, 99999, "不存在论文合集"))
        tags = s.exec(select(Tag).where(Tag.name == "不存在论文标签")).all()
        collections = s.exec(select(Collection).where(Collection.name == "不存在论文合集")).all()

    assert tag_out["ok"] is False
    assert collection_out["ok"] is False
    assert tags == []
    assert collections == []


# ---- T7：检索用户自己的研究知识（笔记 / 摘录 / 审阅矩阵） ----


def _seed_research_knowledge():
    eng = make_engine(":memory:")
    SQLModel.metadata.create_all(eng)
    from app.models import Paper, PaperExcerpt, PaperNote, ReviewMatrixEntry

    with Session(eng) as s:
        p1 = Paper(source="manual", title="知识检索论文")
        p2 = Paper(source="manual", title="已删除论文", is_deleted=True)
        s.add_all([p1, p2])
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        s.add(PaperNote(paper_id=p1.id, kind="critique", content="实验样本量太小的批注", tags_json="[]"))
        s.add(PaperNote(paper_id=p2.id, kind="note", content="样本量 已删除论文的笔记", tags_json="[]"))
        s.add(PaperExcerpt(paper_id=p1.id, quote="The sample size is limited to 30.", page=5, section="4.1"))
        s.add(PaperExcerpt(paper_id=p2.id, quote="sample size of deleted paper", page=1))
        s.add(ReviewMatrixEntry(paper_id=p1.id, problem="样本量不足导致结论不稳", method="小样本方法"))
        s.add(ReviewMatrixEntry(paper_id=p2.id, problem="样本量 已删除矩阵"))
        s.commit()
        ids = {"p1": p1.id, "p2": p2.id}
    return eng, ids


def test_search_research_notes_matches_all_asset_types():
    eng, ids = _seed_research_knowledge()
    with Session(eng) as s:
        out = json.loads(t_search_research_notes(s, "样本量"))
    assert out, "should match note/excerpt-free Chinese keyword"
    types = {row["type"] for row in out}
    assert {"note", "matrix"} <= types
    for row in out:
        assert row["paper_id"] == ids["p1"]
        assert row["title"] == "知识检索论文"
        assert row["snippet"]
        assert len(row["snippet"]) <= 300


def test_search_research_notes_matches_english_excerpt_and_returns_locator():
    eng, ids = _seed_research_knowledge()
    with Session(eng) as s:
        out = json.loads(t_search_research_notes(s, "sample size"))
    excerpt = next(row for row in out if row["type"] == "excerpt")
    assert excerpt["paper_id"] == ids["p1"]
    assert excerpt["locator"]["page"] == 5
    assert excerpt["locator"]["section"] == "4.1"


def test_search_research_notes_excludes_soft_deleted_papers():
    eng, _ids = _seed_research_knowledge()
    with Session(eng) as s:
        out = json.loads(t_search_research_notes(s, "已删除"))
    assert out == [{"note": "no matching research notes"}]


def test_search_research_notes_no_match_returns_empty_note():
    eng, _ids = _seed_research_knowledge()
    with Session(eng) as s:
        out = json.loads(t_search_research_notes(s, "完全不相关的关键词"))
        blank = json.loads(t_search_research_notes(s, "   "))
    assert out == [{"note": "no matching research notes"}]
    assert blank == [{"note": "no matching research notes"}]


def test_search_research_notes_caps_results_and_snippet_length():
    eng = make_engine(":memory:")
    SQLModel.metadata.create_all(eng)
    from app.models import Paper, PaperNote

    with Session(eng) as s:
        paper = Paper(source="manual", title="多篇笔记论文")
        s.add(paper)
        s.commit()
        s.refresh(paper)
        for i in range(12):
            s.add(PaperNote(paper_id=paper.id, kind="note", content=f"目标词 第{i}条 " + "长" * 500))
        s.commit()

        out = json.loads(t_search_research_notes(s, "目标词"))
    assert len(out) == 8  # 默认 top_k=8
    assert all(len(row["snippet"]) <= 300 for row in out)
    assert all(row["snippet"].endswith("…") for row in out)
