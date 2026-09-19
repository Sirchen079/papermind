from fastapi.testclient import TestClient


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_openapi_resolves_pdf_response_and_includes_research(client):
    from app.main import create_app

    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    # Compare against the app's own version — a hardcoded literal here broke
    # on every release bump (it still said 0.5.0 when the app shipped 0.5.2).
    assert schema["info"]["version"] == create_app().version
    assert "/api/research/tasks" in schema["paths"]
    assert "/api/papers/{pid}/file" in schema["paths"]
