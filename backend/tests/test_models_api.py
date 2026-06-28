from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model


def test_models_list_and_role(client):
    pid = client.post("/api/providers", json={"name": "oai", "type": "openai_chat"}).json()["id"]
    # Seed a model directly via the app's engine (bypassing the refresh path).
    with Session(get_engine()) as s:
        s.add(Model(provider_id=pid, model_id="gpt-4o", display_name="GPT-4o"))
        s.commit()

    models = client.get("/api/models").json()
    assert len(models) == 1
    assert models[0]["model_id"] == "gpt-4o"
    assert models[0]["provider_name"] == "oai"

    mid = models[0]["id"]
    patched = client.patch(f"/api/models/{mid}", json={"role_default": "chat"})
    assert patched.json()["role_default"] == "chat"


def test_role_assignment_is_unique_per_role(client):
    """Assigning a role to one model clears it from any other — one model per
    role, so pick_llm is deterministic and you can't get two embedding models."""
    pid = client.post("/api/providers", json={"name": "oai", "type": "openai_chat"}).json()["id"]
    with Session(get_engine()) as s:
        s.add(Model(provider_id=pid, model_id="bge-m3", role_default="embedding"))
        s.add(Model(provider_id=pid, model_id="bge-reranker"))
        s.commit()
        reranker_id, embedder_id = None, None
        for m in s.exec(select(Model).where(Model.provider_id == pid)).all():
            if m.model_id == "bge-reranker":
                reranker_id = m.id
            elif m.model_id == "bge-m3":
                embedder_id = m.id

    # (Mis)label the reranker as embedding too — must steal the role from bge-m3.
    client.patch(f"/api/models/{reranker_id}", json={"role_default": "embedding"})
    with Session(get_engine()) as s:
        roles = {m.model_id: m.role_default for m in s.exec(select(Model).where(Model.provider_id == pid)).all()}
    assert roles["bge-reranker"] == "embedding"
    assert roles["bge-m3"] is None  # cleared — only one embedding model
