def test_settings_crud(client):
    assert client.get("/api/settings").json() == {}

    put = client.put("/api/settings/theme", json={"value": "dark"})
    assert put.status_code == 200
    assert put.json() == {"key": "theme", "value": "dark"}

    assert client.get("/api/settings/theme").json()["value"] == "dark"

    put2 = client.put("/api/settings/theme", json={"value": "light"})
    assert put2.json()["value"] == "light"

    missing = client.get("/api/settings/nope")
    assert missing.status_code == 404

    deleted = client.delete("/api/settings/theme")
    assert deleted.status_code == 204
    assert client.get("/api/settings/theme").status_code == 404
