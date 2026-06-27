from unittest.mock import patch

from app.providers.client import ModelInfo


def test_create_provider_encrypts_key_and_hides_it(client):
    res = client.post(
        "/api/providers",
        json={
            "name": "deepseek",
            "type": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-secret",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "deepseek"
    assert "api_key" not in body
    assert "api_key_encrypted" not in body
    assert body["id"] is not None


def test_list_hides_keys(client):
    client.post("/api/providers", json={"name": "a", "type": "openai_chat", "api_key": "sk"})
    lst = client.get("/api/providers").json()
    assert lst and "api_key" not in lst[0]


def test_refresh_models_upserts(client):
    pid = client.post(
        "/api/providers",
        json={
            "name": "ds",
            "type": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk",
        },
    ).json()["id"]

    fake_models = [
        ModelInfo(model_id="deepseek-chat", display_name="deepseek-chat"),
        ModelInfo(model_id="deepseek-reasoner", display_name="deepseek-reasoner"),
    ]
    with patch("app.api.providers_api.ProviderClient.list_models", return_value=fake_models):
        res = client.post(f"/api/providers/{pid}/models/refresh")
    assert res.status_code == 200
    assert res.json()["count"] == 2

    models = client.get(f"/api/providers/{pid}/models").json()
    assert {m["model_id"] for m in models} == {"deepseek-chat", "deepseek-reasoner"}

    # Second refresh replaces, not duplicates.
    with patch("app.api.providers_api.ProviderClient.list_models", return_value=fake_models):
        client.post(f"/api/providers/{pid}/models/refresh")
    models = client.get(f"/api/providers/{pid}/models").json()
    assert len(models) == 2


def test_delete_provider(client):
    pid = client.post("/api/providers", json={"name": "x", "type": "openai_chat"}).json()["id"]
    assert client.delete(f"/api/providers/{pid}").status_code == 204
    assert client.get("/api/providers").json() == []


def test_delete_provider_cascades_models(client):
    pid = client.post("/api/providers", json={"name": "y", "type": "openai_chat"}).json()["id"]
    fake_models = [ModelInfo(model_id="gpt-4o", display_name="gpt-4o")]
    with patch("app.api.providers_api.ProviderClient.list_models", return_value=fake_models):
        client.post(f"/api/providers/{pid}/models/refresh")
    assert len(client.get(f"/api/providers/{pid}/models").json()) == 1
    assert client.delete(f"/api/providers/{pid}").status_code == 204
    assert client.get(f"/api/providers/{pid}/models").json() == []
