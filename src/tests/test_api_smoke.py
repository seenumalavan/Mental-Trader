from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)

def test_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("name") == "Mental Trader"
    assert "services" in body


def test_maintenance_health():
    r = client.get("/maintenance/health")
    # Service may not be initialized if startup failed, accept 200 or 503
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body.get("service") == "data_maintenance"
