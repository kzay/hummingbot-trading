from __future__ import annotations

import json
from pathlib import Path

from scripts.release.finalize_readiness_decision import run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_finalize_readiness_decision_blocks_stale_runtime_performance_evidence(tmp_path: Path) -> None:
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"strict_gate_status": "PASS"})
    _write_json(tmp_path / "reports" / "promotion_gates" / "latest.json", {"status": "PASS"})
    _write_json(tmp_path / "reports" / "soak" / "latest.json", {"status": "ready"})
    _write_json(tmp_path / "reports" / "event_store" / "day2_gate_eval_latest.json", {"go": True})
    _write_json(tmp_path / "reports" / "reconciliation" / "latest.json", {"status": "pass"})
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"status": "pass"})
    _write_json(tmp_path / "reports" / "portfolio_risk" / "latest.json", {"status": "ok"})
    _write_json(
        tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json",
        {"status": "pass", "ts_utc": "2020-01-01T00:00:00Z"},
    )

    payload, _md = run(tmp_path, max_artifact_age_min=20.0)

    assert payload["status"] == "HOLD"
    assert "stale_evidence:runtime_performance_budgets" in payload["blockers"]
    assert payload["summary"]["runtime_performance_status"] == "pass"
    freshness = payload["diagnostics"]["artifact_freshness"]["runtime_performance_budgets"]
    assert freshness["fresh"] is False


def test_finalize_readiness_decision_go_requires_fresh_runtime_performance_pass(tmp_path: Path) -> None:
    fresh_ts = "3026-03-09T00:00:00Z"
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json",
        {"strict_gate_status": "PASS", "ts_utc": fresh_ts},
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"status": "PASS", "ts_utc": fresh_ts},
    )
    _write_json(tmp_path / "reports" / "soak" / "latest.json", {"status": "ready", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "event_store" / "day2_gate_eval_latest.json", {"go": True, "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "reconciliation" / "latest.json", {"status": "pass", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"status": "pass", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "portfolio_risk" / "latest.json", {"status": "ok", "ts_utc": fresh_ts})
    _write_json(
        tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json",
        {"status": "pass", "ts_utc": fresh_ts},
    )

    payload, _md = run(tmp_path, max_artifact_age_min=20.0)

    assert payload["status"] == "GO"
    assert payload["blockers"] == []


def test_finalize_readiness_decision_blocks_newer_failed_promotion_gate_snapshot(tmp_path: Path) -> None:
    strict_ts = "3026-03-09T00:00:00Z"
    newer_fail_ts = "3026-03-09T00:05:00Z"
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json",
        {"strict_gate_status": "PASS", "ts_utc": strict_ts},
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"status": "FAIL", "critical_failures": ["realtime_l2_data_quality"], "ts_utc": newer_fail_ts},
    )
    _write_json(tmp_path / "reports" / "soak" / "latest.json", {"status": "ready", "ts_utc": strict_ts})
    _write_json(tmp_path / "reports" / "event_store" / "day2_gate_eval_latest.json", {"go": True, "ts_utc": strict_ts})
    _write_json(tmp_path / "reports" / "reconciliation" / "latest.json", {"status": "pass", "ts_utc": strict_ts})
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"status": "pass", "ts_utc": strict_ts})
    _write_json(tmp_path / "reports" / "portfolio_risk" / "latest.json", {"status": "ok", "ts_utc": strict_ts})
    _write_json(
        tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json",
        {"status": "pass", "ts_utc": strict_ts},
    )

    payload, _md = run(tmp_path, max_artifact_age_min=20.0)

    assert payload["status"] == "HOLD"
    assert "promotion_gates_latest_not_pass" in payload["blockers"]
    assert "promotion_gate_status_mismatch" in payload["blockers"]
    assert "promotion_gates_latest_newer_than_strict_cycle" in payload["blockers"]
    assert payload["summary"]["promotion_gates_latest_status"] == "FAIL"


def test_finalize_readiness_decision_blocks_non_pass_reconciliation_status(tmp_path: Path) -> None:
    fresh_ts = "3026-03-09T00:00:00Z"
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json",
        {"strict_gate_status": "PASS", "ts_utc": fresh_ts},
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"status": "PASS", "ts_utc": fresh_ts},
    )
    _write_json(tmp_path / "reports" / "soak" / "latest.json", {"status": "ready", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "event_store" / "day2_gate_eval_latest.json", {"go": True, "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "reconciliation" / "latest.json", {"status": "warning", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"status": "pass", "ts_utc": fresh_ts})
    _write_json(tmp_path / "reports" / "portfolio_risk" / "latest.json", {"status": "ok", "ts_utc": fresh_ts})
    _write_json(
        tmp_path / "reports" / "verification" / "runtime_performance_budgets_latest.json",
        {"status": "pass", "ts_utc": fresh_ts},
    )

    payload, _md = run(tmp_path, max_artifact_age_min=20.0)

    assert payload["status"] == "HOLD"
    assert "reconciliation_not_pass" in payload["blockers"]
