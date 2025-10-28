from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)

# These tests expect 401 until authentication is performed.

def test_control_start_unauthorized():
    r = client.post("/control/start", json={"service": "scalper", "instruments": "nifty"})
    assert r.status_code == 401


def test_control_stop_unauthorized():
    r = client.post("/control/stop", json={"service": "scalper"})
    assert r.status_code == 401
