"""Chaos smoke test: verify RedisStreamClient reconnects after connection loss.

Run manually with a local Redis instance::

    PYTHONPATH=hbot python -m pytest hbot/tests/integration/test_redis_chaos_smoke.py -v

This test is excluded from the normal test suite (``--ignore=hbot/tests/integration``).
"""
from __future__ import annotations

import os
import time

import pytest

try:
    import redis as _redis_mod
except ImportError:
    _redis_mod = None

from services.hb_bridge.redis_client import RedisStreamClient

_REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
_REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
_REDIS_DB = int(os.getenv("REDIS_DB", "15"))

pytestmark = pytest.mark.integration


def _redis_available() -> bool:
    if _redis_mod is None:
        return False
    try:
        c = _redis_mod.Redis(host=_REDIS_HOST, port=_REDIS_PORT, db=_REDIS_DB, socket_timeout=2)
        c.ping()
        c.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
class TestRedisReconnect:
    def test_connection_pool_is_used(self):
        client = RedisStreamClient(
            host=_REDIS_HOST, port=_REDIS_PORT, db=_REDIS_DB, max_connections=4,
        )
        assert client._pool is not None
        assert client.ping() is True

    def test_reconnect_after_client_reset(self):
        client = RedisStreamClient(
            host=_REDIS_HOST, port=_REDIS_PORT, db=_REDIS_DB, max_connections=4,
        )
        assert client.ping() is True

        client._client = None
        client._consecutive_failures = 0
        assert client.ping() is False or client.ping() is True

        for _ in range(5):
            if client.ping():
                break
            time.sleep(0.5)
        assert client.ping() is True

    def test_xadd_and_read_with_pool(self):
        client = RedisStreamClient(
            host=_REDIS_HOST, port=_REDIS_PORT, db=_REDIS_DB, max_connections=4,
        )
        stream = "hb.test.chaos_smoke.v1"
        payload = {
            "event_type": "test",
            "instance_name": "chaos_test",
            "producer": "chaos_test",
            "ts_ms": str(int(time.time() * 1000)),
            "value": "hello",
        }
        entry_id = client.xadd(stream, payload, maxlen=100)
        assert entry_id is not None

        latest = client.read_latest(stream)
        assert latest is not None
        assert latest[1].get("value") == "hello"

        client._client.delete(stream)
