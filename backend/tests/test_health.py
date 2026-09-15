from fastapi.testclient import TestClient


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_openapi_resolves_pdf_response_and_includes_research(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["version"] == "0.5.0"
    assert "/api/research/tasks" in schema["paths"]
    assert "/api/papers/{pid}/file" in schema["paths"]
