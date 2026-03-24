"""Verify that docker-compose service health endpoints respond.

Run with: PYTHONPATH=hbot python -m pytest hbot/tests/integration/test_service_health.py -v
This test is excluded from the normal test suite (``--ignore=hbot/tests/integration``).
"""
from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.integration


def test_redis_ping(redis_client):
    """Redis should respond to PING."""
    assert redis_client.ping() is True


def test_api_health(api_base):
    """GET /health should return 200."""
    try:
        resp = requests.get(f"{api_base}/health", timeout=5)
    except requests.ConnectionError:
        pytest.skip("API not reachable")
    assert resp.status_code == 200


def test_api_state(api_base):
    """GET /api/v1/state should return 200."""
    try:
        resp = requests.get(f"{api_base}/api/v1/state", timeout=5)
    except requests.ConnectionError:
        pytest.skip("API not reachable")
    assert resp.status_code == 200


def test_prometheus_targets_up(prometheus_base):
    """Prometheus should report at least one active target."""
    try:
        resp = requests.get(f"{prometheus_base}/api/v1/targets", timeout=5)
    except requests.ConnectionError:
        pytest.skip("Prometheus not reachable")
    assert resp.status_code == 200
    data = resp.json()
    active = data.get("data", {}).get("activeTargets", [])
    assert len(active) >= 1, "Expected at least 1 active Prometheus target"
