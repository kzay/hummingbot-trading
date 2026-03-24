from __future__ import annotations

from platform_lib.contracts.event_schemas import AuditEvent, BotFillEvent, MarketQuoteEvent
from services.hb_bridge.publisher import HBEventPublisher


class _FakeRedisClient:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = []

    def ping(self) -> bool:
        return True

    def xadd(self, stream: str, payload: dict, maxlen=None):
        self.calls.append((stream, payload, maxlen))
        return "1-0"


def test_publish_fill_drops_payload_when_identity_missing() -> None:
    redis = _FakeRedisClient()
    publisher = HBEventPublisher(redis_client=redis, producer="hb_test")
    event = BotFillEvent(
        producer="",
        instance_name="",
        controller_id="ctrl-1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        price=10_000.0,
        amount_base=0.01,
        notional_quote=100.0,
        fee_quote=0.01,
        order_id="ord-1",
    )

    result = publisher.publish_fill(event)

    assert result is None
    assert redis.calls == []


def test_publish_fill_emits_when_identity_present() -> None:
    redis = _FakeRedisClient()
    publisher = HBEventPublisher(redis_client=redis, producer="hb_test")
    event = BotFillEvent(
        producer="",
        instance_name="bot1",
        controller_id="ctrl-1",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        side="buy",
        price=10_000.0,
        amount_base=0.01,
        notional_quote=100.0,
        fee_quote=0.01,
        order_id="ord-2",
    )

    result = publisher.publish_fill(event)

    assert result == "1-0"
    assert len(redis.calls) == 1


def test_publish_market_quote_remains_allowed_without_bot_scope() -> None:
    redis = _FakeRedisClient()
    publisher = HBEventPublisher(redis_client=redis, producer="hb_test")
    event = MarketQuoteEvent(
        producer="",
        connector_name="bitget_perpetual",
        trading_pair="BTC-USDT",
        best_bid=9_999.0,
        best_ask=10_001.0,
    )

    result = publisher.publish_market_quote(event)

    assert result == "1-0"
    assert len(redis.calls) == 1


def test_publish_audit_drops_payload_when_identity_missing() -> None:
    redis = _FakeRedisClient()
    publisher = HBEventPublisher(redis_client=redis, producer="hb_test")
    event = AuditEvent(
        producer="",
        instance_name="",
        severity="warning",
        category="risk_decision",
        message="missing instance scope",
    )

    result = publisher.publish_audit(event)

    assert result is None
    assert redis.calls == []
