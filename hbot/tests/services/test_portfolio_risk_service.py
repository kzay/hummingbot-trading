from __future__ import annotations

from services.portfolio_risk_service.main import _build_portfolio_snapshot_payload


def test_build_portfolio_snapshot_payload_shape() -> None:
    payload = _build_portfolio_snapshot_payload(
        portfolio_action="kill_switch",
        status="critical",
        critical_count=2,
        warning_count=1,
        risk_scope_bots=["bot1", "bot3"],
        metrics={"portfolio_daily_loss_pct": 0.042},
    )
    assert payload["event_type"] == "portfolio_risk_snapshot"
    assert payload["portfolio_action"] == "kill_switch"
    assert payload["status"] == "critical"
    assert payload["critical_count"] == 2
    assert payload["warning_count"] == 1
    assert payload["risk_scope_bots"] == ["bot1", "bot3"]
    assert "timestamp_ms" in payload
    assert int(payload["timestamp_ms"]) > 0


def test_build_portfolio_snapshot_payload_has_ids() -> None:
    payload = _build_portfolio_snapshot_payload(
        portfolio_action="allow",
        status="ok",
        critical_count=0,
        warning_count=0,
        risk_scope_bots=[],
        metrics={},
    )
    assert isinstance(payload["event_id"], str) and payload["event_id"]
    assert payload["correlation_id"] == payload["event_id"]
