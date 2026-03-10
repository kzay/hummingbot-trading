from __future__ import annotations

import json
import logging

from services.hb_bridge.redis_client import RedisStreamClient


class _FakeRedis:
    def __init__(self) -> None:
        self.calls = []

    def xadd(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return "1-0"


def _make_client(fake: _FakeRedis) -> RedisStreamClient:
    client = RedisStreamClient.__new__(RedisStreamClient)
    client._logger = logging.getLogger(__name__)  # type: ignore[attr-defined]
    client._enabled = True  # type: ignore[attr-defined]
    client._host = "redis"  # type: ignore[attr-defined]
    client._port = 6379  # type: ignore[attr-defined]
    client._db = 0  # type: ignore[attr-defined]
    client._password = None  # type: ignore[attr-defined]
    client._client = fake  # type: ignore[attr-defined]
    client._last_reconnect_attempt = 0.0  # type: ignore[attr-defined]
    client._consecutive_failures = 0  # type: ignore[attr-defined]
    client._redis_down_since = 0.0  # type: ignore[attr-defined]
    return client


def test_xadd_drops_execution_intent_missing_controller_identity() -> None:
    fake = _FakeRedis()
    client = _make_client(fake)

    result = client.xadd(
        "hb.execution_intent.v1",
        {
            "event_type": "execution_intent",
            "instance_name": "bot1",
            "controller_id": "",
            "action": "resume",
        },
    )

    assert result is None
    assert fake.calls == []


def test_xadd_allows_valid_strategy_signal_identity() -> None:
    fake = _FakeRedis()
    client = _make_client(fake)

    result = client.xadd(
        "hb.signal.v1",
        {
            "event_type": "strategy_signal",
            "instance_name": "bot1",
            "signal_name": "inventory_rebalance",
            "signal_value": 0.12,
        },
        maxlen=123,
    )

    assert result == "1-0"
    assert len(fake.calls) == 1
    encoded_payload = fake.calls[0]["fields"]["payload"]
    decoded_payload = json.loads(encoded_payload)
    assert decoded_payload["event_type"] == "strategy_signal"
    assert decoded_payload["instance_name"] == "bot1"
