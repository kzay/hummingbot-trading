from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.release.build_paper_exchange_threshold_inputs import build_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_report_merges_computed_and_manual_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bots": [
                {
                    "bot": "bot1",
                    "summary": {"equity_first": 100.0, "equity_last": 101.0},
                    "metrics": [
                        {"metric": "fill_ratio_delta", "delta": 0.5},
                        {"metric": "reject_rate_delta", "delta": 0.1},
                        {"metric": "slippage_delta_bps", "delta": 1.2},
                    ],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {
                "heartbeat_bot1_fresh": True,
                "redis_connected": True,
                "dead_letter_critical_within_slo": True,
            },
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(
        tmp_path / "reports" / "tests" / "latest.json",
        {"ts_utc": now_iso, "status": "pass"},
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "PASS",
            "checks": [
                {"name": "paper_exchange_preflight", "pass": True},
                {"name": "paper_exchange_load_validation", "pass": True},
                {"name": "paper_exchange_threshold_inputs_ready", "pass": True},
                {"name": "paper_exchange_thresholds", "pass": True},
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json",
        {"ts_utc": now_iso, "strict_gate_rc": 0},
    )
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p1_8_command_latency_p95_ms": 111.0,
                "p1_8_command_latency_p99_ms": 222.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )

    assert report["status"] == "warning"  # expected: unresolved metrics still exist.
    metrics = report["metrics"]
    assert float(metrics["p0_1_contract_tests_pass_rate_pct"]) == 100.0
    assert float(metrics["p1_17_strict_cycle_checks_enforced_rate_pct"]) == 100.0
    assert float(metrics["p1_8_command_latency_p95_ms"]) == 111.0
    assert float(metrics["p1_8_command_latency_p99_ms"]) == 222.0
    diagnostics = report["diagnostics"]
    assert diagnostics["manual_metrics_used_count"] == 2
    assert diagnostics["manual_fallback_metric_count"] == 2
    assert diagnostics["manual_metrics_blocking_count"] == 2


def test_build_report_treats_manual_only_metrics_as_informational(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p0_1_schema_validation_error_rate_pct": 0.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    diagnostics = report["diagnostics"]
    assert diagnostics["manual_only_metric_count"] == 1
    assert diagnostics["manual_metrics_informational_count"] == 1
    assert diagnostics["manual_metrics_blocking_count"] == 0


def test_build_report_marks_stale_sources(tmp_path: Path) -> None:
    stale_iso = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {"ts_utc": stale_iso, "status": "pass", "bots": []},
    )
    report = build_report(
        tmp_path,
        now_ts=datetime.now(UTC).timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    stale_sources = report["diagnostics"]["stale_sources"]
    missing_sources = report["diagnostics"]["missing_sources"]
    assert "parity_latest" in stale_sources
    assert "reliability_slo_latest" in missing_sources


def test_build_report_derives_privileged_command_metrics_from_journal(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "commands": {
                "cmd-1": {
                    "command": "cancel_all",
                    "audit_required": True,
                    "audit_published": True,
                    "command_metadata": {
                        "operator": "desk_ops",
                        "reason": "risk_pause",
                        "change_ticket": "CHG-1",
                        "trace_id": "trace-1",
                    },
                },
                "cmd-2": {
                    "command": "cancel_all",
                    "audit_required": True,
                    "audit_published": False,
                    "command_metadata": {
                        "operator": "desk_ops",
                        "reason": "risk_pause",
                        "change_ticket": "CHG-2",
                        "trace_id": "",
                    },
                },
            },
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_20_privileged_command_attribution_complete_rate_pct"]) == 50.0
    assert float(metrics["p1_20_privileged_command_missing_audit_event_rate_pct"]) == 50.0
    assert float(metrics["p1_20_security_policy_test_suite_pass_rate_pct"]) == 100.0
    assert float(metrics["p1_20_unauthorized_producer_acceptance_rate_pct"]) == 0.0


def test_build_report_derives_unauthorized_producer_acceptance_rate_from_authorization_flags(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "command_count": 2,
            "commands": {
                "cmd-unauth-rejected": {
                    "command": "submit_order",
                    "status": "rejected",
                    "reason": "unauthorized_producer",
                    "producer_authorized": False,
                },
                "cmd-unauth-accepted": {
                    "command": "sync_state",
                    "status": "processed",
                    "reason": "sync_state_accepted",
                    "producer_authorized": False,
                },
            },
        },
    )
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_20_unauthorized_producer_acceptance_rate_pct"]) == 50.0


def test_build_report_derives_market_data_contract_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json",
        {
            "ts_utc": now_iso,
            "pairs_total": 2,
            "pairs": {
                "bot1::bitget_perpetual::BTC-USDT": {
                    "best_bid": 10000.0,
                    "best_ask": 10000.1,
                    "timestamp_ms": 1_700_000_000_000,
                },
                "bot3::bitget_perpetual::ETH-USDT": {
                    "best_bid": 2000.0,
                    "best_ask": None,
                    "timestamp_ms": 1_700_000_000_001,
                },
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "command_count": 4,
            "commands": {
                "cmd-filled": {
                    "command": "submit_order",
                    "status": "processed",
                    "reason": "order_filled_market",
                    "metadata": {
                        "best_bid": "9999.9",
                        "best_ask": "10000.1",
                        "fill_price": "10000.1",
                        "command_sequence": "1",
                    },
                },
                "cmd-post-only": {
                    "command": "submit_order",
                    "status": "rejected",
                    "reason": "post_only_would_take",
                    "metadata": {
                        "best_bid": "9999.9",
                        "best_ask": "10000.1",
                        "price": "10000.1",
                        "command_sequence": "2",
                    },
                },
                "cmd-mid-only": {
                    "command": "submit_order",
                    "status": "processed",
                    "reason": "mid_only_fallback",
                    "metadata": {},
                },
                "cmd-out-of-order": {
                    "command": "sync_state",
                    "status": "rejected",
                    "reason": "out_of_order_snapshot",
                    "metadata": {},
                },
            },
        },
    )
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p0_12_required_l1_fields_non_null_rate_pct"]) == 50.0
    assert float(metrics["p0_12_out_of_order_sequence_error_rate_pct"]) == 25.0
    assert float(metrics["p0_12_matching_decisions_traceable_rate_pct"]) == 100.0
    assert float(metrics["p0_12_active_mode_mid_only_fallback_command_count"]) == 1.0


def test_build_report_derives_accounting_contract_metrics_and_keeps_p1_6_computed(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bots": [
                {
                    "bot": "bot1",
                    "summary": {
                        "intents_total": 2,
                        "actionable_intents": 1,
                        "fills_total": 2,
                        "equity_first": 1000.0,
                        "equity_last": 1000.0,
                    },
                    "metrics": [
                        {"metric": "realized_pnl_delta_quote", "delta": -0.5},
                    ],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "command_count": 2,
            "commands": {
                "cmd-fee-margin-ok": {
                    "instance_name": "bot1",
                    "status": "processed",
                    "reason": "order_filled_market",
                    "metadata": {
                        "fill_notional_quote": "100.0",
                        "fill_fee_quote": "0.06",
                        "fill_fee_rate_pct": "0.0006",
                        "is_maker": "0",
                        "filled_notional_quote_total": "100.0",
                        "margin_reserve_quote": "20.0",
                        "leverage": "5",
                        "margin_mode": "leveraged",
                        "funding_rate": "-0.0001",
                        "snapshot_funding_rate": "-0.0002",
                    },
                },
                "cmd-funding-mismatch": {
                    "instance_name": "bot1",
                    "status": "processed",
                    "reason": "resting_order_partial_fill",
                    "metadata": {
                        "fill_notional_quote": "50.0",
                        "fill_fee_quote": "0.03",
                        "fill_fee_rate_pct": "0.0006",
                        "is_maker": "0",
                        "filled_notional_quote_total": "50.0",
                        "margin_reserve_quote": "50.0",
                        "leverage": "4",
                        "margin_mode": "standard",
                        "funding_rate": "0.0001",
                        "snapshot_funding_rate": "-0.0002",
                    },
                },
            },
        },
    )
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p1_6_per_fill_fee_abs_error_pct_notional_max": 99.0,
                "p1_6_cumulative_realized_pnl_drift_pct_equity": 77.0,
                "p1_6_funding_sign_mismatch_count": 0.0,
                "p1_6_margin_reserve_drift_pct_equity": 88.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    metrics = report["metrics"]
    assert float(metrics["p1_6_per_fill_fee_abs_error_pct_notional_max"]) == 0.0
    assert abs(float(metrics["p1_6_cumulative_realized_pnl_drift_pct_equity"]) - 0.05) < 1e-12
    assert float(metrics["p1_6_funding_sign_mismatch_count"]) == 1.0
    assert float(metrics["p1_6_margin_reserve_drift_pct_equity"]) == 0.0


def test_build_report_derives_p1_7_window_and_command_count(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    event_store_file = tmp_path / "reports" / "event_store" / "events_20260304.jsonl"
    event_store_file.parent.mkdir(parents=True, exist_ok=True)
    event_store_file.write_text("{\"event_type\":\"heartbeat\"}\n", encoding="utf-8")

    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "event_store_file": str(event_store_file),
            "bots": [],
        },
    )
    _write_json(
        tmp_path / "reports" / "replay_regression_multi_window" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "windows": [
                {"signature_baseline": {"regression_event_count": 12345}},
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "command_count": 2,
            "commands": {
                "cmd-1": {"metadata": {"updated_ts_ms": "1700000000000"}},
                "cmd-2": {"metadata": {"updated_ts_ms": "1700000001000"}},
            },
        },
    )
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_7_parity_eval_window_hours"]) == 24.0
    assert float(metrics["p1_7_parity_eval_command_events_count"]) == 2.0


def test_build_report_derives_p1_9_rollout_metrics_and_keeps_computed(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "ops" / "paper_exchange_canary_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bot": "bot3",
            "mode": "active",
            "target_canary_duration_hours": 30.0,
            "canary_critical_alert_count": 0.0,
            "active_mode_rollout_concurrency_bots": 1.0,
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "data_plane_rollback_drill_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "duration_minutes": 3.5,
            "rpo_lost_commands": 0.0,
        },
    )
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p1_9_canary_run_duration_hours": 12.0,
                "p1_9_canary_critical_alert_count": 9.0,
                "p1_9_rollback_drill_rto_minutes": 99.0,
                "p1_9_rollback_drill_rpo_lost_commands": 5.0,
                "p1_9_active_mode_rollout_concurrency_bots": 7.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    metrics = report["metrics"]
    assert float(metrics["p1_9_canary_run_duration_hours"]) == 30.0
    assert float(metrics["p1_9_canary_critical_alert_count"]) == 0.0
    assert float(metrics["p1_9_rollback_drill_rto_minutes"]) == 3.5
    assert float(metrics["p1_9_rollback_drill_rpo_lost_commands"]) == 0.0
    assert float(metrics["p1_9_active_mode_rollout_concurrency_bots"]) == 1.0


def test_build_report_p1_9_duration_falls_back_to_manual_when_missing(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "ops" / "paper_exchange_canary_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bot": "bot3",
            "mode": "shadow",
            "canary_critical_alert_count": 0.0,
            "active_mode_rollout_concurrency_bots": 0.0,
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "data_plane_rollback_drill_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "duration_minutes": 2.0,
            "rpo_lost_commands": 0.0,
        },
    )
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p1_9_canary_run_duration_hours": 24.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    metrics = report["metrics"]
    assert float(metrics["p1_9_canary_run_duration_hours"]) == 24.0
    assert float(metrics["p1_9_canary_critical_alert_count"]) == 0.0
    assert float(metrics["p1_9_rollback_drill_rto_minutes"]) == 2.0
    assert float(metrics["p1_9_rollback_drill_rpo_lost_commands"]) == 0.0
    assert float(metrics["p1_9_active_mode_rollout_concurrency_bots"]) == 0.0


def test_build_report_derives_p2_10_metrics_from_nautilus_matrix_and_keeps_computed(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    (tmp_path / "controllers" / "paper_engine_v2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "controllers" / "paper_engine_v2" / "accounting.py").write_text(
        '"""Inspired by Nautilus semantics."""\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "controllers" / "test_paper_engine_v2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "controllers" / "test_paper_engine_v2" / "test_accounting.py").write_text(
        "def test_accounting_parity_contract():\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "validation").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "validation" / "nautilus_license_boundary.md").write_text(
        "# Nautilus boundary\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "docs" / "validation" / "nautilus_reuse_matrix.json",
        {
            "entries": [
                {
                    "module_path": "controllers/paper_engine_v2/accounting.py",
                    "decision": "reimplement",
                    "upstream_component": "position accounting semantics",
                    "rationale": "pure-python deterministic accounting",
                    "boundary": "local module only",
                    "license": "LGPL-3.0-or-later",
                    "attribution_file": "docs/legal/nautilus_trader.LICENSE.txt",
                    "test_refs": [
                        "tests/controllers/test_paper_engine_v2/test_accounting.py::test_accounting_parity_contract"
                    ],
                }
            ]
        },
    )
    (tmp_path / "docs" / "legal").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "legal" / "nautilus_trader.LICENSE.txt").write_text(
        "LGPL attribution\n",
        encoding="utf-8",
    )

    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p2_10_reused_module_provenance_doc_coverage_pct": 0.0,
                "p2_10_license_compliance_check_failures": 7.0,
                "p2_10_adopted_module_behavior_parity_tests_pass_rate_pct": 0.0,
                "p2_10_undocumented_external_framework_dependency_count": 9.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    metrics = report["metrics"]
    assert float(metrics["p2_10_reused_module_provenance_doc_coverage_pct"]) == 100.0
    assert float(metrics["p2_10_license_compliance_check_failures"]) == 0.0
    assert float(metrics["p2_10_adopted_module_behavior_parity_tests_pass_rate_pct"]) == 100.0
    assert float(metrics["p2_10_undocumented_external_framework_dependency_count"]) == 0.0


def test_build_report_p2_10_detects_undocumented_direct_nautilus_import(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    (tmp_path / "controllers" / "paper_engine_v2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "controllers" / "paper_engine_v2" / "accounting.py").write_text(
        "import nautilus_trader\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "validation").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "validation" / "nautilus_license_boundary.md").write_text(
        "# Nautilus boundary\n",
        encoding="utf-8",
    )
    _write_json(tmp_path / "docs" / "validation" / "nautilus_reuse_matrix.json", {"entries": []})
    (tmp_path / "docs" / "legal").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "legal" / "nautilus_trader.LICENSE.txt").write_text("LGPL attribution\n", encoding="utf-8")

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p2_10_undocumented_external_framework_dependency_count"]) == 1.0


def test_build_report_p1_6_realized_pnl_drift_ignores_no_fill_bots(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(
        tmp_path / "reports" / "parity" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "bots": [
                {
                    "bot": "bot1",
                    "summary": {
                        "intents_total": 3,
                        "actionable_intents": 3,
                        "fills_total": 0,
                        "equity_first": 200.0,
                        "equity_last": 200.0,
                    },
                    "metrics": [
                        {"metric": "realized_pnl_delta_quote", "delta": 10.0},
                    ],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {"ts_utc": now_iso, "command_count": 0, "commands": {}},
    )
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_6_cumulative_realized_pnl_drift_pct_equity"]) == 0.0


def test_build_report_derives_namespace_isolation_metrics_pass_path(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json",
        {
            "ts_utc": now_iso,
            "orders_total": 1,
            "orders": {
                "ord-1": {
                    "order_id": "ord-1",
                    "instance_name": "bot1",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "state": "working",
                }
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json",
        {
            "ts_utc": now_iso,
            "pairs_total": 1,
            "pairs": {
                "bot1::bitget_perpetual::BTC-USDT": {
                    "instance_name": "bot1",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                }
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json",
        {"ts_utc": now_iso, "event_count": 0, "events": {}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "commands": {
                "cmd-1": {
                    "command": "submit_order",
                    "status": "processed",
                    "reason": "order_accepted",
                    "order_id": "ord-1",
                    "instance_name": "bot1",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "metadata": {"command_sequence": "1"},
                },
                "cmd-2": {
                    "command": "cancel_order",
                    "status": "processed",
                    "reason": "order_cancelled",
                    "order_id": "ord-1",
                    "instance_name": "bot1",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "metadata": {"command_sequence": "2"},
                },
            },
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_15_cross_instance_state_violation_count"]) == 0.0
    assert float(metrics["p1_15_namespace_key_collision_count_72h"]) == 0.0
    assert float(metrics["p1_15_command_event_routing_correctness_rate_pct"]) == 100.0


def test_build_report_derives_namespace_isolation_metrics_detects_collision_violation(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json",
        {"ts_utc": now_iso, "orders_total": 0, "orders": {}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json",
        {"ts_utc": now_iso, "pairs_total": 0, "pairs": {}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json",
        {"ts_utc": now_iso, "event_count": 0, "events": {}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {
            "ts_utc": now_iso,
            "commands": {
                "cmd-1": {
                    "command": "submit_order",
                    "status": "processed",
                    "reason": "order_accepted",
                    "order_id": "shared-order",
                    "instance_name": "bot1",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "metadata": {"command_sequence": "1"},
                },
                "cmd-2": {
                    "command": "submit_order",
                    "status": "processed",
                    "reason": "order_accepted",
                    "order_id": "shared-order",
                    "instance_name": "bot3",
                    "connector_name": "bitget_perpetual",
                    "trading_pair": "BTC-USDT",
                    "metadata": {"command_sequence": "2"},
                },
            },
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_15_cross_instance_state_violation_count"]) >= 1.0
    assert float(metrics["p1_15_namespace_key_collision_count_72h"]) >= 1.0
    assert float(metrics["p1_15_command_event_routing_correctness_rate_pct"]) < 100.0


def test_build_report_derives_active_failure_policy_metrics_from_golden_path(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_golden_path_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "scenarios": [
                {
                    "id": "active_mode_failure_policy",
                    "status": "pass",
                    "derived_metrics": {
                        "p1_16_service_down_detection_delay_seconds": 0.8,
                        "p1_16_safety_state_transition_delay_seconds": 1.1,
                        "p1_16_silent_live_fallback_count": 0.0,
                        "p1_16_mean_recovery_time_minutes": 2.5,
                    },
                }
            ],
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_16_service_down_detection_delay_seconds"]) == 0.8
    assert float(metrics["p1_16_safety_state_transition_delay_seconds"]) == 1.1
    assert float(metrics["p1_16_silent_live_fallback_count"]) == 0.0
    assert float(metrics["p1_16_mean_recovery_time_minutes"]) == 2.5


def test_build_report_active_failure_policy_metrics_fail_closed_when_required_scenario_missing(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_golden_path_latest.json",
        {"ts_utc": now_iso, "status": "pass", "scenarios": []},
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_16_silent_live_fallback_count"]) == 1.0
    assert float(metrics["p1_16_service_down_detection_delay_seconds"]) > 10_000.0
    assert float(metrics["p1_16_safety_state_transition_delay_seconds"]) > 10_000.0
    assert float(metrics["p1_16_mean_recovery_time_minutes"]) > 10_000.0


def test_build_report_derives_p0_11_hb_compat_metrics_and_keeps_computed(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_golden_path_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "scenarios": [
                {
                    "id": "active_mode_failure_policy",
                    "status": "pass",
                    "derived_metrics": {
                        "p1_16_service_down_detection_delay_seconds": 0.0,
                        "p1_16_safety_state_transition_delay_seconds": 0.0,
                        "p1_16_silent_live_fallback_count": 0.0,
                        "p1_16_mean_recovery_time_minutes": 0.0,
                    },
                },
                {
                    "id": "hb_executor_runtime_compatibility",
                    "status": "pass",
                    "derived_metrics": {
                        "p0_11_hb_executor_lifecycle_tests_pass_rate_pct": 100.0,
                        "p0_11_hb_event_count_delta_pct": 0.5,
                        "p0_11_inflight_order_lookup_miss_rate_pct": 0.05,
                        "p0_11_runtime_adapter_exception_count_24h": 0.0,
                    },
                },
            ],
        },
    )
    manual_path = tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"
    _write_json(
        manual_path,
        {
            "metrics": {
                "p0_11_hb_executor_lifecycle_tests_pass_rate_pct": 0.0,
                "p0_11_hb_event_count_delta_pct": 9.9,
                "p0_11_inflight_order_lookup_miss_rate_pct": 9.9,
                "p0_11_runtime_adapter_exception_count_24h": 3.0,
            }
        },
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=manual_path,
    )
    metrics = report["metrics"]
    assert float(metrics["p0_11_hb_executor_lifecycle_tests_pass_rate_pct"]) == 100.0
    assert float(metrics["p0_11_hb_event_count_delta_pct"]) == 0.5
    assert float(metrics["p0_11_inflight_order_lookup_miss_rate_pct"]) == 0.05
    assert float(metrics["p0_11_runtime_adapter_exception_count_24h"]) == 0.0


def test_build_report_p0_11_metrics_fail_closed_when_required_scenario_missing(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json", {"commands": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json", {"orders_total": 0, "orders": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json", {"pairs_total": 0, "pairs": {}})
    _write_json(tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json", {"event_count": 0, "events": {}})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_golden_path_latest.json",
        {"ts_utc": now_iso, "status": "pass", "scenarios": []},
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p0_11_hb_executor_lifecycle_tests_pass_rate_pct"]) == 0.0
    assert float(metrics["p0_11_hb_event_count_delta_pct"]) == 100.0
    assert float(metrics["p0_11_inflight_order_lookup_miss_rate_pct"]) == 100.0
    assert float(metrics["p0_11_runtime_adapter_exception_count_24h"]) == 1.0


def test_build_report_ingests_load_backpressure_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {
            "ts_utc": now_iso,
            "status": "PASS",
            "checks": [
                {"name": "paper_exchange_preflight", "pass": True},
                {"name": "paper_exchange_thresholds", "pass": True},
            ],
        },
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_load_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "metrics": {
                "p1_19_sustained_command_throughput_cmds_per_sec": 63.2,
                "p1_19_command_latency_under_load_p95_ms": 112.0,
                "p1_19_command_latency_under_load_p99_ms": 229.0,
                "p1_19_stream_backlog_growth_rate_pct_per_10min": 0.2,
                "p1_19_stress_window_oom_restart_count": 0.0,
                "p1_19_sustained_window_qualification_rate_pct": 100.0,
            },
        },
    )
    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"]) == 63.2
    assert float(metrics["p1_19_command_latency_under_load_p95_ms"]) == 112.0
    assert float(metrics["p1_19_command_latency_under_load_p99_ms"]) == 229.0
    assert float(metrics["p1_19_stream_backlog_growth_rate_pct_per_10min"]) == 0.2
    assert float(metrics["p1_19_stress_window_oom_restart_count"]) == 0.0
    assert float(metrics["p1_19_sustained_window_qualification_rate_pct"]) == 100.0


def test_build_report_generates_paper_exchange_state_dr_metrics(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    _write_json(tmp_path / "reports" / "parity" / "latest.json", {"ts_utc": now_iso, "status": "pass", "bots": []})
    _write_json(
        tmp_path / "reports" / "ops" / "reliability_slo_latest.json",
        {
            "ts_utc": now_iso,
            "status": "pass",
            "checks": {"heartbeat_bot1_fresh": True, "redis_connected": True, "dead_letter_critical_within_slo": True},
            "details": {"dead_letter": {"critical_count": 0, "lookback_sec": 900}},
        },
    )
    _write_json(tmp_path / "reports" / "tests" / "latest.json", {"ts_utc": now_iso, "status": "pass"})
    _write_json(
        tmp_path / "reports" / "promotion_gates" / "latest.json",
        {"ts_utc": now_iso, "status": "PASS", "checks": []},
    )
    _write_json(tmp_path / "reports" / "promotion_gates" / "strict_cycle_latest.json", {"ts_utc": now_iso, "strict_gate_rc": 0})
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_command_journal_latest.json",
        {"ts_utc": now_iso, "command_count": 1, "commands": {"cmd-1": {"status": "processed", "reason": "sync_state_accepted"}}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_state_snapshot_latest.json",
        {"ts_utc": now_iso, "orders_total": 1, "orders": {"ord-1": {"state": "working"}}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json",
        {"ts_utc": now_iso, "pairs_total": 1, "pairs": {"bitget_perpetual::BTC-USDT": {"mid_price": 10_000.0}}},
    )
    _write_json(
        tmp_path / "reports" / "verification" / "paper_exchange_market_fill_journal_latest.json",
        {"ts_utc": now_iso, "event_count": 1, "events": {"pe-fill-1": 1}},
    )

    report = build_report(
        tmp_path,
        now_ts=now.timestamp(),
        max_source_age_min=20.0,
        manual_metrics_path=tmp_path / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json",
    )
    metrics = report["metrics"]
    assert float(metrics["p1_21_successful_restore_drills_30d_count"]) >= 1.0
    assert float(metrics["p1_21_restore_replay_data_integrity_mismatch_count"]) == 0.0
    assert float(metrics["p1_21_full_restore_to_healthy_heartbeat_minutes"]) < 1.0
    assert float(metrics["p1_21_backup_artifact_freshness_hours"]) < 1.0

