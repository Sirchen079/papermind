def test_archive_status_reports_data_health(client, env):
    from sqlmodel import Session

    from app.archive.service import archive_status
    from app.db.engine import get_engine
    from app.models import Concept, Paper, PaperChunk, PaperConcept, Provider, Summary

    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        paper = Paper(source="pdf", title="A Test Paper", pdf_path=str(pdf_dir / "paper.pdf"))
        provider = Provider(name="kimi", type="anthropic", api_key_encrypted="encrypted")
        concept = Concept(name="RAG", normalized_key="rag", type="method")
        session.add(paper)
        session.add(provider)
        session.add(concept)
        session.commit()
        session.refresh(paper)
        session.refresh(concept)
        session.add(Summary(paper_id=paper.id, content_json='{"problem":"x"}'))
        session.add(PaperConcept(paper_id=paper.id, concept_id=concept.id))
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text="chunk", embedding=b"blob"))
        session.commit()

        status = archive_status(session)

    assert status["database_exists"] is True
    assert status["master_key_exists"] is True
    assert status["pdf_count"] == 1
    assert status["paper_count"] == 1
    assert status["summary_count"] == 1
    assert status["concept_count"] == 1
    assert status["chunk_count"] == 1
    assert status["provider_count"] == 1
    assert status["latest_backup"] is None


def test_create_backup_writes_manifest_sqlite_key_and_pdfs(client, env):
    import json
    import zipfile

    from sqlmodel import Session

    from app.archive.service import create_backup
    from app.db.engine import get_engine
    from app.models import Paper

    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "nested").mkdir()
    (pdf_dir / "nested" / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        session.add(Paper(source="pdf", title="Backup Paper"))
        session.commit()
        backup = create_backup(session)

    assert backup["filename"].startswith("papermind-backup-")
    assert backup["filename"].endswith(".zip")
    assert backup["size_bytes"] > 0

    with zipfile.ZipFile(backup["path"]) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "papermind.sqlite" in names
        assert "master.key" in names
        assert "pdfs/nested/paper.pdf" in names
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["archive_schema_version"] == 1
    assert manifest["paper_count"] == 1
    assert manifest["master_key"]["present"] is True
    assert manifest["pdfs"]["count"] == 1
    assert manifest["database"]["sha256"]


def test_verify_backup_checks_manifest_hashes_and_sqlite_integrity(client, env):
    import zipfile

    from sqlmodel import Session

    from app.archive.service import create_backup, verify_backup
    from app.db.engine import get_engine
    from app.models import Paper

    pdf_dir = env / "data" / "pdfs"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
    (env / "master.key").write_bytes(b"secret-key")

    with Session(get_engine()) as session:
        session.add(Paper(source="pdf", title="Verified Backup Paper"))
        session.commit()
        backup = create_backup(session)

    result = verify_backup(backup["filename"])

    assert result["ok"] is True
    assert result["filename"] == backup["filename"]
    assert result["archive_type"] == "full-backup"
    assert result["database"]["present"] is True
    assert result["database"]["sha256_ok"] is True
    assert result["database"]["integrity_ok"] is True
    assert result["master_key"]["present"] is True
    assert result["master_key"]["sha256_ok"] is True
    assert result["pdfs"]["expected_count"] == 1
    assert result["pdfs"]["verified_count"] == 1
    assert result["errors"] == []

    tampered_path = env / "data" / "backups" / "tampered.zip"
    with zipfile.ZipFile(backup["path"]) as src, zipfile.ZipFile(tampered_path, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "pdfs/paper.pdf":
                data = b"tampered"
            dst.writestr(info, data)

    tampered = verify_backup("tampered.zip")

    assert tampered["ok"] is False
    assert tampered["pdfs"]["failed_count"] == 1
    assert any("pdfs/paper.pdf" in error for error in tampered["errors"])


def test_list_backups_includes_malformed_zip_without_crashing(client, env):
    from sqlmodel import Session

    from app.archive.service import create_backup, list_backups
    from app.db.engine import get_engine

    with Session(get_engine()) as session:
        create_backup(session)

    bad = env / "data" / "backups" / "bad.zip"
    bad.write_text("not a zip", encoding="utf-8")

    rows = list_backups()

    assert len(rows) == 2
    assert any(row["filename"] == "bad.zip" and row["error"] for row in rows)


def test_resolve_backup_rejects_path_traversal(env):
    import pytest

    from app.archive.service import resolve_backup

    backup_dir = env / "data" / "backups"
    backup_dir.mkdir(parents=True)
    (backup_dir / "ok.zip").write_bytes(b"zip")

    assert resolve_backup("ok.zip") == backup_dir / "ok.zip"
    with pytest.raises(FileNotFoundError):
        resolve_backup("../master.key")
    with pytest.raises(FileNotFoundError):
        resolve_backup("missing.zip")


def test_export_json_excludes_secrets_and_embedding_blobs(client, env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import Model, Paper, PaperChunk, Provider, Summary

    with Session(get_engine()) as session:
        provider = Provider(
            name="sf",
            type="openai_compat",
            api_key_encrypted="ciphertext",
            extra_headers_json='{"Authorization":"Bearer secret"}',
        )
        paper = Paper(source="arxiv", title="Vector Paper", authors_json='["Ada Lovelace"]')
        session.add(provider)
        session.add(paper)
        session.commit()
        session.refresh(provider)
        session.refresh(paper)
        session.add(Model(provider_id=provider.id, model_id="BAAI/bge-m3", role_default="embedding"))
        session.add(Summary(paper_id=paper.id, content_json='{"method":"retrieval"}'))
        session.add(
            PaperChunk(
                paper_id=paper.id,
                ordinal=0,
                text="chunk text",
                embedding=b"secret-vector",
                embedding_model="BAAI/bge-m3",
            )
        )
        session.commit()

        exported = export_json(session)

    assert exported["archive_schema_version"] == 1
    assert exported["papers"][0]["title"] == "Vector Paper"
    assert exported["providers"][0]["name"] == "sf"
    assert "api_key_encrypted" not in exported["providers"][0]
    assert "extra_headers" not in exported["providers"][0]
    assert "extra_headers_json" not in exported["providers"][0]
    assert exported["chunks"][0]["text"] == "chunk text"
    assert "embedding" not in exported["chunks"][0]


def test_export_json_tolerates_malformed_paper_authors(client, env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import Paper

    with Session(get_engine()) as session:
        session.add(Paper(source="manual", title="Malformed Export Authors", authors_json="not-json"))
        session.commit()

        exported = export_json(session)

    assert exported["papers"][0]["title"] == "Malformed Export Authors"
    assert exported["papers"][0]["authors"] == []
    assert "authors_json" not in exported["papers"][0]


def test_export_json_omits_deleted_papers_and_attached_rows(client, env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import (
        Concept,
        Paper,
        PaperChunk,
        PaperConcept,
        PaperExcerpt,
        PaperLink,
        PaperNote,
        PaperReadingState,
        Project,
        ReviewMatrixEntry,
        Summary,
    )

    with Session(get_engine()) as session:
        active = Paper(source="manual", title="Active Export Paper")
        deleted = Paper(source="manual", title="Deleted Export Paper", is_deleted=True)
        active_concept = Concept(name="Active Concept", normalized_key="active", type="method")
        deleted_concept = Concept(name="Deleted Concept", normalized_key="deleted", type="method")
        project = Project(name="Export Project", kind="topic")
        session.add(active)
        session.add(deleted)
        session.add(active_concept)
        session.add(deleted_concept)
        session.add(project)
        session.commit()
        session.refresh(active)
        session.refresh(deleted)
        session.refresh(active_concept)
        session.refresh(deleted_concept)
        session.refresh(project)
        session.add(Summary(paper_id=active.id, content_json='{"keep":true}'))
        session.add(Summary(paper_id=deleted.id, content_json='{"drop":true}'))
        session.add(PaperConcept(paper_id=active.id, concept_id=active_concept.id))
        session.add(PaperConcept(paper_id=deleted.id, concept_id=deleted_concept.id))
        session.add(PaperChunk(paper_id=active.id, ordinal=0, text="active chunk", embedding=b"active"))
        session.add(PaperChunk(paper_id=deleted.id, ordinal=0, text="deleted chunk", embedding=b"deleted"))
        session.add(PaperReadingState(paper_id=active.id, status="read"))
        session.add(PaperReadingState(paper_id=deleted.id, status="read"))
        session.add(PaperNote(paper_id=active.id, kind="note", content="active note"))
        session.add(PaperNote(paper_id=deleted.id, kind="note", content="deleted note"))
        session.add(PaperExcerpt(paper_id=active.id, quote="active quote"))
        session.add(PaperExcerpt(paper_id=deleted.id, quote="deleted quote"))
        session.add(ReviewMatrixEntry(paper_id=active.id, problem="active problem"))
        session.add(ReviewMatrixEntry(paper_id=deleted.id, problem="deleted problem"))
        session.add(PaperLink(paper_id=active.id, project_id=project.id, role="background"))
        session.add(PaperLink(paper_id=deleted.id, project_id=project.id, role="background"))
        session.commit()

        exported = export_json(session)

    assert [paper["title"] for paper in exported["papers"]] == ["Active Export Paper"]
    assert [summary["paper_id"] for summary in exported["summaries"]] == [active.id]
    assert [link["paper_id"] for link in exported["paper_concepts"]] == [active.id]
    assert [concept["name"] for concept in exported["concepts"]] == ["Active Concept"]
    assert [chunk["text"] for chunk in exported["chunks"]] == ["active chunk"]
    assert [state["paper_id"] for state in exported["reading_states"]] == [active.id]
    assert [note["content"] for note in exported["paper_notes"]] == ["active note"]
    assert [excerpt["quote"] for excerpt in exported["paper_excerpts"]] == ["active quote"]
    assert [entry["problem"] for entry in exported["review_matrix_entries"]] == ["active problem"]
    assert [link["paper_id"] for link in exported["paper_links"]] == [active.id]


def test_export_bibtex_formats_doi_arxiv_author_venue_and_abstract(client, env):
    from sqlmodel import Session

    from app.archive.service import export_bibtex
    from app.db.engine import get_engine
    from app.models import Paper

    with Session(get_engine()) as session:
        session.add(
            Paper(
                source="arxiv",
                title="Attention Is All You Need",
                authors_json='["Ashish Vaswani", "Noam Shazeer"]',
                abstract="Transformer model",
                year=2017,
                venue="NeurIPS",
                doi="10.5555/test",
                arxiv_id="1706.03762",
            )
        )
        session.commit()

        bibtex = export_bibtex(session)

    assert "@article{vaswani2017attention" in bibtex
    assert "title = {Attention Is All You Need}" in bibtex
    assert "author = {Ashish Vaswani and Noam Shazeer}" in bibtex
    assert "year = {2017}" in bibtex
    assert "journal = {NeurIPS}" in bibtex
    assert "doi = {10.5555/test}" in bibtex
    assert "eprint = {1706.03762}" in bibtex
    assert "archivePrefix = {arXiv}" in bibtex
    assert "abstract = {Transformer model}" in bibtex


def test_export_bibtex_prefers_saved_citation_key(client, env):
    from sqlmodel import Session

    from app.archive.service import export_bibtex
    from app.db.engine import get_engine
    from app.models import Paper

    with Session(get_engine()) as session:
        paper = Paper(
            source="manual",
            citation_key="custom2026key",
            title="Generated Title Would Differ",
            authors_json='["Ada Lovelace"]',
            year=2026,
        )
        session.add(paper)
        session.commit()

        bibtex = export_bibtex(session)

    assert "@article{custom2026key" in bibtex
    assert "@article{lovelace2026generated" not in bibtex


def test_export_ris_formats_zotero_endnote_compatible_records(client, env):
    from sqlmodel import Session

    from app.archive.service import export_ris
    from app.db.engine import get_engine
    from app.models import Paper

    with Session(get_engine()) as session:
        session.add(
            Paper(
                source="arxiv",
                title="Attention Is All You Need",
                authors_json='["Ashish Vaswani", "Noam Shazeer"]',
                abstract="Transformer model",
                year=2017,
                venue="NeurIPS",
                doi="10.5555/test",
                arxiv_id="1706.03762",
            )
        )
        session.add(Paper(source="manual", title="Deleted RIS Paper", is_deleted=True))
        session.commit()

        ris = export_ris(session)

    assert "TY  - JOUR" in ris
    assert "TI  - Attention Is All You Need" in ris
    assert "AU  - Ashish Vaswani" in ris
    assert "AU  - Noam Shazeer" in ris
    assert "PY  - 2017" in ris
    assert "JO  - NeurIPS" in ris
    assert "DO  - 10.5555/test" in ris
    assert "AB  - Transformer model" in ris
    assert "UR  - https://arxiv.org/abs/1706.03762" in ris
    assert ris.strip().endswith("ER  -")
    assert "Deleted RIS Paper" not in ris


def test_export_json_includes_reading_workspace_data(client, env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import Paper, PaperExcerpt, PaperNote, PaperReadingState, ReviewMatrixEntry

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Reading Export Paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        session.add(PaperReadingState(paper_id=paper.id, status="read", priority="high", relevance=5))
        session.add(
            PaperNote(
                paper_id=paper.id,
                kind="note",
                content="Export this note",
                tags_json='["portable", "note"]',
            )
        )
        session.add(
            PaperExcerpt(
                paper_id=paper.id,
                quote="Export this quote",
                page=4,
                tags_json='["evidence", "quote"]',
            )
        )
        session.add(ReviewMatrixEntry(paper_id=paper.id, problem="Export problem", method="Export method"))
        session.commit()

        exported = export_json(session)

    assert exported["reading_states"][0]["status"] == "read"
    assert exported["paper_notes"][0]["content"] == "Export this note"
    assert exported["paper_notes"][0]["tags"] == ["portable", "note"]
    assert "tags_json" not in exported["paper_notes"][0]
    assert exported["paper_excerpts"][0]["quote"] == "Export this quote"
    assert exported["paper_excerpts"][0]["tags"] == ["evidence", "quote"]
    assert "tags_json" not in exported["paper_excerpts"][0]
    assert exported["review_matrix_entries"][0]["problem"] == "Export problem"


def test_export_json_includes_thesis_organization_data(client, env):
    from sqlmodel import Session

    from app.archive.service import export_json
    from app.db.engine import get_engine
    from app.models import Chapter, Paper, PaperLink, Project

    with Session(get_engine()) as session:
        paper = Paper(source="manual", title="Thesis Export Paper")
        project = Project(name="Research Direction", kind="direction")
        session.add(paper)
        session.add(project)
        session.commit()
        session.refresh(paper)
        session.refresh(project)
        chapter = Chapter(project_id=project.id, title="Related Work")
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        session.add(PaperLink(paper_id=paper.id, project_id=project.id, role="background"))
        session.add(PaperLink(paper_id=paper.id, chapter_id=chapter.id, role="evidence"))
        session.commit()

        exported = export_json(session)

    assert exported["projects"][0]["name"] == "Research Direction"
    assert exported["chapters"][0]["title"] == "Related Work"
    assert {link["role"] for link in exported["paper_links"]} == {"background", "evidence"}
