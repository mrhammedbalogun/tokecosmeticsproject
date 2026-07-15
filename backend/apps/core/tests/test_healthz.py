import pytest


@pytest.mark.django_db
def test_healthz_reports_ok(client):
    resp = client.get("/healthz/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert "redis" in body
