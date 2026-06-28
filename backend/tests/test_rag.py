from sqlmodel import Session, SQLModel, select

from app.db.engine import make_engine
from app.models import Model, Paper, PaperChunk, Provider
from app.rag.chunker import chunk_text
from app.rag.vector import cosine, deserialize, serialize, top_k


# --- chunker -----------------------------------------------------------------

def test_chunker_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunker_short_is_one_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_chunker_packs_lines_under_target():
    text = "\n".join(f"line number {i}." for i in range(60))
    chunks = chunk_text(text, target=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "line number 0." in chunks[0]
    assert "line number 59." in chunks[-1]


def test_chunker_hard_splits_overlong_lines():
    assert chunk_text("x" * 250, target=100) == ["x" * 100, "x" * 100, "x" * 50]


# --- vector ------------------------------------------------------------------

def test_vector_roundtrip():
    v = [0.1, -0.2, 0.3, 0.0]
    rt = list(deserialize(serialize(v)))  # float32 round-trip
    assert len(rt) == len(v)
    for a, b in zip(rt, v):
        assert abs(a - b) < 1e-6


def test_cosine_identity_orthogonal_zero():
    assert cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert cosine([0, 0, 0], [1, 1, 1]) == 0.0  # zero vector guarded


def test_top_k_ranks_by_similarity():
    items = [("a", [1, 0]), ("b", [0, 1]), ("c", [0.9, 0.1])]
    ranked = top_k([1, 0], items, 2)
    assert [k for k, _ in ranked] == ["a", "c"]
    assert ranked[0][1] > ranked[1][1]


# --- indexing & retrieval ----------------------------------------------------

class _FakeEmbedClient:
    """Deterministic embeddings keyed by each input's first character."""

    def embed(self, provider, model_id, inputs, request_kind="embedding", ref_id=None):  # noqa: ANN001
        out = []
        for t in inputs:
            v = [0.0] * 8
            v[ord(t[0]) % 8] = 1.0
            out.append(v)
        return out


def test_index_paper_stores_metadata_and_text_chunks(tmp_path):
    eng = make_engine(tmp_path / "idx.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        paper = Paper(
            source="pdf",
            title="Alpha",
            abstract="An abstract here.",
            full_text="body one\nbody two\nbody three",
        )
        s.add(paper)
        s.commit()
        s.refresh(paper)

        from app.rag.index import index_paper

        n = index_paper(s, paper, _FakeEmbedClient(), object(), "emb-1")
        rows = s.exec(select(PaperChunk).where(PaperChunk.paper_id == paper.id)).all()
        # metadata chunk (title+abstract) + 1 packed full-text chunk
        assert n == len(rows) == 2
        assert all(r.embedding_model == "emb-1" for r in rows)
        assert all(r.embedding is not None for r in rows)
        assert [r.ordinal for r in rows] == [0, 1]


def test_index_paper_replaces_existing(tmp_path):
    eng = make_engine(tmp_path / "idx2.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        paper = Paper(source="pdf", title="T", abstract="A", full_text="one\ntwo")
        s.add(paper)
        s.commit()
        s.refresh(paper)

        from app.rag.index import index_paper

        index_paper(s, paper, _FakeEmbedClient(), object(), "emb")
        index_paper(s, paper, _FakeEmbedClient(), object(), "emb")  # re-index
        rows = s.exec(select(PaperChunk).where(PaperChunk.paper_id == paper.id)).all()
        assert len(rows) == 2  # metadata + 1 text chunk, no duplicates


def test_index_paper_noop_without_embedding_model(tmp_path, monkeypatch):
    eng = make_engine(tmp_path / "idx3.sqlite")
    SQLModel.metadata.create_all(eng)
    from app.rag import index as index_mod

    monkeypatch.setattr(index_mod, "pick_llm", lambda *a, **k: None)
    with Session(eng) as s:
        paper = Paper(source="pdf", title="T", abstract="A", full_text="body")
        s.add(paper)
        s.commit()
        s.refresh(paper)
        assert index_mod.index_paper(s, paper) == 0
        assert s.exec(select(PaperChunk)).all() == []


def test_retrieve_returns_closest_chunk(tmp_path, monkeypatch):
    eng = make_engine(tmp_path / "ret.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        paper = Paper(source="pdf", title="T")
        s.add(paper)
        s.commit()
        s.refresh(paper)
        s.add(
            PaperChunk(
                paper_id=paper.id, ordinal=0, text="alpha",
                embedding=serialize([1.0, 0.0, 0.0]), embedding_model="emb",
            )
        )
        s.add(
            PaperChunk(
                paper_id=paper.id, ordinal=1, text="beta",
                embedding=serialize([0.0, 1.0, 0.0]), embedding_model="emb",
            )
        )
        s.commit()

    from app.rag import index as index_mod

    class FixedClient:
        def embed(self, provider, model_id, inputs, request_kind="embedding", ref_id=None):  # noqa: ANN001
            return [[1.0, 0.0, 0.0] for _ in inputs]

    monkeypatch.setattr(index_mod, "pick_llm", lambda *a, **k: (FixedClient(), object(), "emb"))
    with Session(eng) as s:
        hits = index_mod.retrieve(s, "anything")
    assert len(hits) == 2  # only two candidates exist (k defaults above this)
    assert hits[0][0].text == "alpha"
    assert hits[0][1] == 1.0
    assert hits[1][0].text == "beta"
    assert hits[1][1] == 0.0


def test_retrieve_empty_without_embedding_model(tmp_path, monkeypatch):
    eng = make_engine(tmp_path / "ret2.sqlite")
    SQLModel.metadata.create_all(eng)
    from app.rag import index as index_mod

    monkeypatch.setattr(index_mod, "pick_llm", lambda *a, **k: None)
    with Session(eng) as s:
        assert index_mod.retrieve(s, "query") == []
        assert index_mod.retrieve(s, "") == []


# --- role-aware provider selection ------------------------------------------

def test_pick_llm_prefers_role_tagged_model_across_providers(env):
    from app.providers.selection import pick_llm

    eng = make_engine(env / "pick.sqlite")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        p1 = Provider(name="anthropic-like", type="anthropic", enabled=True)
        s.add(p1)
        s.commit()
        s.refresh(p1)
        s.add(Model(provider_id=p1.id, model_id="claude", role_default="chat"))

        p2 = Provider(name="siliconflow", type="openai_compat", base_url="https://api.siliconflow.cn/v1", enabled=True)
        s.add(p2)
        s.commit()
        s.refresh(p2)
        s.add(Model(provider_id=p2.id, model_id="BAAI/bge-m3", role_default="embedding"))
        s.commit()

        # strict embedding resolves to the dedicated model on provider 2,
        # NOT the first enabled provider's chat model.
        ctx = pick_llm(s, "embedding", strict=True)
        assert ctx is not None
        _, provider, model_id = ctx
        assert model_id == "BAAI/bge-m3"
        assert provider.id == p2.id

        # strict returns None for a role nobody holds.
        assert pick_llm(s, "extraction", strict=True) is None

        # non-strict chat still resolves (to the tagged chat model on provider 1).
        _, _, chat_id = pick_llm(s, "chat")
        assert chat_id == "claude"


# --- ProviderClient.embed (real litellm response shape) ----------------------

def test_client_embed_parses_response_and_records_usage(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from cryptography.fernet import Fernet

    from app.models import TokenUsage
    from app.providers.client import ProviderClient
    from app.security.crypto import Crypto

    eng = make_engine(tmp_path / "emb.sqlite")
    SQLModel.metadata.create_all(eng)
    crypto = Crypto(Fernet.generate_key())

    def fake_embedding(**kwargs):
        resp = MagicMock()
        resp.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3]),
            MagicMock(embedding=[0.4, 0.5, 0.6]),
        ]
        resp.usage = MagicMock(prompt_tokens=10, total_tokens=10)
        return resp

    monkeypatch.setattr("app.providers.client.litellm.embedding", fake_embedding)

    client = ProviderClient(session_factory=lambda: Session(eng), crypto=crypto)
    with Session(eng) as s:
        provider = Provider(
            name="siliconflow",
            type="openai_compat",
            base_url="https://api.siliconflow.cn/v1",
            api_key_encrypted=crypto.encrypt("sk-x"),
        )
        s.add(provider)
        s.commit()
        s.refresh(provider)
        pid = provider.id

    vecs = client.embed(provider, "BAAI/bge-m3", ["hello", "world"], request_kind="embedding")
    assert vecs == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    with Session(eng) as s:
        rows = s.exec(select(TokenUsage)).all()
    assert len(rows) == 1  # one batch of two inputs
    assert rows[0].request_kind == "embedding"
    assert rows[0].prompt_tokens == 10
    assert rows[0].model == "BAAI/bge-m3"
    assert rows[0].provider_id == pid


def test_client_embed_rejects_anthropic(tmp_path):
    import pytest
    from cryptography.fernet import Fernet

    from app.providers.client import ProviderClient
    from app.security.crypto import Crypto

    eng = make_engine(tmp_path / "emb2.sqlite")
    SQLModel.metadata.create_all(eng)
    client = ProviderClient(session_factory=lambda: Session(eng), crypto=Crypto(Fernet.generate_key()))
    with pytest.raises(ValueError):
        client.embed(Provider(name="anth", type="anthropic"), "any", ["x"])
