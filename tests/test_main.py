"""Testes do app FastAPI mínimo (health check)."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_responde_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
