from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Model


def test_explicit_null_clears_role_without_changing_omitted_fields(client):
    pid = client.post('/api/providers', json={'name': 'Role owner', 'type': 'openai_chat'}).json()['id']
    model = client.post(f'/api/providers/{pid}/models', json={'model_id': 'synthetic', 'role_default': 'chat'}).json()
    response = client.patch(f"/api/models/{model['id']}", json={'display_name': 'Renamed'})
    assert response.json()['role_default'] == 'chat'
    response = client.patch(f"/api/models/{model['id']}", json={'role_default': None})
    assert response.json()['role_default'] is None


def test_concurrent_default_assignment_keeps_one_model_per_role(client):
    from concurrent.futures import ThreadPoolExecutor
    pid = client.post('/api/providers', json={'name': 'Concurrent roles', 'type': 'openai_chat'}).json()['id']
    models = [client.post(f'/api/providers/{pid}/models', json={'model_id': f'model-{i}'}).json()['id'] for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda mid: client.patch(f'/api/models/{mid}', json={'role_default': 'chat'}), models))
    assert all(row.status_code == 200 for row in results)
    assert len([row for row in client.get('/api/models').json() if row['role_default'] == 'chat']) == 1


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


def test_patch_capability_fields_roundtrip(client):
    pid = client.post("/api/providers", json={"name": "caps", "type": "openai_chat"}).json()["id"]
    m = client.post(f"/api/providers/{pid}/models", json={"model_id": "synthetic"}).json()

    r = client.patch(f"/api/models/{m['id']}", json={
        "context_window": 128000, "supports_images": True, "reasoning_effort": "high"})
    assert r.status_code == 200
    assert r.json()["context_window"] == 128000
    assert r.json()["supports_images"] is True
    assert r.json()["reasoning_effort"] == "high"

    listed = client.get("/api/models").json()
    assert listed[0]["context_window"] == 128000
    assert listed[0]["supports_images"] is True
    assert listed[0]["reasoning_effort"] == "high"

    # Explicit null clears each field back to "auto".
    r = client.patch(f"/api/models/{m['id']}", json={
        "context_window": None, "supports_images": None, "reasoning_effort": None})
    assert r.json()["context_window"] is None
    assert r.json()["supports_images"] is None
    assert r.json()["reasoning_effort"] is None


def test_patch_capability_fields_validation(client):
    pid = client.post("/api/providers", json={"name": "caps2", "type": "openai_chat"}).json()["id"]
    m = client.post(f"/api/providers/{pid}/models",
                    json={"model_id": "synthetic", "context_window": 1000}).json()

    # Omitted fields stay untouched.
    r = client.patch(f"/api/models/{m['id']}", json={"display_name": "X"})
    assert r.json()["context_window"] == 1000

    assert client.patch(f"/api/models/{m['id']}", json={"context_window": 0}).status_code == 422
    assert client.patch(f"/api/models/{m['id']}", json={"context_window": -5}).status_code == 422
    assert client.patch(f"/api/models/{m['id']}", json={"reasoning_effort": "extreme"}).status_code == 422
