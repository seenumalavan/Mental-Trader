from fastapi.testclient import TestClient
from src.app import app
from src.config import settings

# These tests are illustrative; without a valid token auto-start will skip.

def test_root_contains_auto_start_flags():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "auto_start" in body
    auto = body["auto_start"]
    assert "scalper" in auto and "intraday" in auto


def test_startup_log_endpoint():
    client = TestClient(app)
    r = client.get("/startup/log")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert isinstance(body["events"], list)
