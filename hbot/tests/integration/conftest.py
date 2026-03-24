"""Integration test fixtures.

These tests require running docker-compose services.
Run with: PYTHONPATH=hbot python -m pytest hbot/tests/integration/ -v
"""
from __future__ import annotations

import os

import pytest

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
API_BASE = os.environ.get("API_BASE", "http://localhost:9910")
PROMETHEUS_BASE = os.environ.get("PROMETHEUS_BASE", "http://localhost:9090")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def redis_client():
    """Connect to the running Redis instance."""
    try:
        import redis

        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception:
        pytest.skip("Redis not available")


@pytest.fixture(scope="session")
def api_base():
    """Return the API base URL for realtime_ui_api."""
    return API_BASE


@pytest.fixture(scope="session")
def prometheus_base():
    """Return the Prometheus base URL."""
    return PROMETHEUS_BASE
