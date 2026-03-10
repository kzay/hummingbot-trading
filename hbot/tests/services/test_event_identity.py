from __future__ import annotations

from services.contracts.event_identity import required_identity_fields, validate_event_identity


def test_required_identity_fields_for_bot_fill() -> None:
    assert required_identity_fields("bot_fill") == (
        "instance_name",
        "connector_name",
        "trading_pair",
        "order_id",
    )


def test_required_identity_fields_for_execution_intent() -> None:
    assert required_identity_fields("execution_intent") == (
        "instance_name",
        "controller_id",
    )


def test_validate_event_identity_rejects_missing_bot_fill_instance() -> None:
    ok, reason = validate_event_identity(
        {
            "event_type": "bot_fill",
            "instance_name": "",
            "connector_name": "bitget",
            "trading_pair": "BTC-USDT",
            "order_id": "ord-1",
        }
    )
    assert ok is False
    assert reason == "bot_fill_missing_instance_name"


def test_validate_event_identity_rejects_missing_execution_intent_controller() -> None:
    ok, reason = validate_event_identity(
        {
            "event_type": "execution_intent",
            "instance_name": "bot1",
            "controller_id": "",
            "action": "resume",
        }
    )
    assert ok is False
    assert reason == "execution_intent_missing_controller_id"


def test_validate_event_identity_rejects_missing_strategy_signal_instance() -> None:
    ok, reason = validate_event_identity(
        {
            "event_type": "strategy_signal",
            "instance_name": "",
            "signal_name": "inventory_rebalance",
        }
    )
    assert ok is False
    assert reason == "strategy_signal_missing_instance_name"


def test_validate_event_identity_rejects_missing_audit_instance() -> None:
    ok, reason = validate_event_identity(
        {
            "event_type": "audit",
            "instance_name": "",
            "category": "risk_decision",
        }
    )
    assert ok is False
    assert reason == "audit_missing_instance_name"


def test_validate_event_identity_accepts_nested_payload_with_option_enabled() -> None:
    ok, reason = validate_event_identity(
        {
            "event_type": "paper_exchange_command",
            "payload": {
                "instance_name": "bot1",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
            },
        },
        allow_nested_payload=True,
    )
    assert ok is True
    assert reason == ""


def test_validate_event_identity_ignores_unknown_event_type() -> None:
    ok, reason = validate_event_identity({"event_type": "market_quote", "connector_name": "bitget"})
    assert ok is True
    assert reason == ""
