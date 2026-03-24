from __future__ import annotations

import json
from pathlib import Path

from services.portfolio_risk_service.main import (
    _build_portfolio_snapshot_payload,
    _severity_and_action,
    run,
)


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


def test_severity_and_action_levels() -> None:
    result_ok = _severity_and_action(value=0.01, cap=0.03, warn_buffer_ratio=0.80, hard_action="kill_switch")
    assert result_ok["severity"] == "ok"
    assert result_ok["action"] == "allow"

    result_warn = _severity_and_action(value=0.025, cap=0.03, warn_buffer_ratio=0.80, hard_action="kill_switch")
    assert result_warn["severity"] == "warning"
    assert result_warn["action"] == "soft_pause"

    result_critical = _severity_and_action(value=0.035, cap=0.03, warn_buffer_ratio=0.80, hard_action="kill_switch")
    assert result_critical["severity"] == "critical"
    assert result_critical["action"] == "kill_switch"


def test_run_once_produces_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    event_store_dir = tmp_path / "event_store"
    event_store_dir.mkdir()
    limits = {
        "version": 3,
        "global_daily_loss_cap_pct": 0.03,
        "cross_bot_net_exposure_cap_quote": 25000.0,
        "cross_bot_gross_exposure_cap_quote": 50000.0,
        "stress_scenario_drop_pct": 0.05,
        "stress_max_portfolio_loss_pct": 0.10,
        "concentration_cap_pct": 0.70,
        "concentration_min_equity_quote": 100.0,
        "warn_buffer_ratio": 0.80,
        "bot_action_scope": ["bot1", "bot6", "bot7"],
        "bot_overrides": {},
    }
    limits_path = tmp_path / "limits.json"
    limits_path.write_text(json.dumps(limits), encoding="utf-8")

    monkeypatch.setenv("PORTFOLIO_RISK_EVENT_STORE_ROOT", str(event_store_dir))
    monkeypatch.setenv("PORTFOLIO_RISK_LIMITS_PATH", str(limits_path))
    monkeypatch.setenv("PORTFOLIO_RISK_PUBLISH_ACTIONS", "false")
    monkeypatch.setenv("PORTFOLIO_RISK_REALTIME_ENABLED", "false")

    import services.portfolio_risk_service.main as prm

    root = Path(prm.__file__).resolve().parents[2]
    reports_root = root / "reports" / "portfolio_risk"

    run(once=True)

    latest = reports_root / "latest.json"
    assert latest.exists()
    report = json.loads(latest.read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["metrics"]["gross_exposure_quote"] == 0.0
    assert report["metrics"]["stress_scenario_loss_pct"] == 0.0


def test_gross_exposure_and_stress_in_config() -> None:
    limits_path = Path(__file__).resolve().parents[2] / "config" / "portfolio_limits_v1.json"
    if not limits_path.exists():
        return
    limits = json.loads(limits_path.read_text(encoding="utf-8"))
    assert limits["version"] >= 3
    assert "cross_bot_gross_exposure_cap_quote" in limits
    assert "stress_scenario_drop_pct" in limits
    assert "stress_max_portfolio_loss_pct" in limits
    assert "bot6" in limits.get("bot_action_scope", [])
    assert "bot7" in limits.get("bot_action_scope", [])
