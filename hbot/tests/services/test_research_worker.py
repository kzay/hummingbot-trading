from __future__ import annotations

from starlette.testclient import TestClient

from services.research_worker.main import create_app


def test_research_worker_health_and_routes(monkeypatch) -> None:
    monkeypatch.setenv("REALTIME_UI_API_AUTH_ENABLED", "false")

    client = TestClient(create_app())

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    candidates = client.get("/api/research/candidates")
    assert candidates.status_code == 200
    assert "candidates" in candidates.json()
