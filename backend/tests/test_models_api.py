from sqlmodel import Session

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
