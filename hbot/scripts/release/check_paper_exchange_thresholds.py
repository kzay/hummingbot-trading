#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ThresholdClause:
    item_id: str
    metric: str
    op: str  # "le" | "ge" | "eq"
    target: float


THRESHOLD_CLAUSES: List[ThresholdClause] = [
    # [P0-PAPER-SVC-20260301-1]
    ThresholdClause("P0-PAPER-SVC-20260301-1", "p0_1_schema_validation_error_rate_pct", "le", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-1", "p0_1_heartbeat_p99_gap_ms", "le", 5000.0),
    ThresholdClause("P0-PAPER-SVC-20260301-1", "p0_1_heartbeat_max_gap_ms", "le", 15000.0),
    ThresholdClause("P0-PAPER-SVC-20260301-1", "p0_1_unsupported_command_reject_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-1", "p0_1_contract_tests_pass_rate_pct", "ge", 100.0),
    # [P0-PAPER-SVC-20260301-2]
    ThresholdClause("P0-PAPER-SVC-20260301-2", "p0_2_stale_commands_processed_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-2", "p0_2_allowlisted_connector_provenance_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-2", "p0_2_complete_provenance_fields_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-2", "p0_2_reject_decision_latency_p95_ms", "le", 200.0),
    # [P0-PAPER-SVC-20260301-3]
    ThresholdClause("P0-PAPER-SVC-20260301-3", "p0_3_shadow_parity_artifact_generation_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-3", "p0_3_fill_count_delta_pct", "le", 1.0),
    ThresholdClause("P0-PAPER-SVC-20260301-3", "p0_3_end_equity_delta_pct", "le", 0.25),
    ThresholdClause("P0-PAPER-SVC-20260301-3", "p0_3_control_state_divergence_count", "eq", 0.0),
    # [P0-PAPER-SVC-20260301-4]
    ThresholdClause("P0-PAPER-SVC-20260301-4", "p0_4_deterministic_replay_identical_ratio_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-4", "p0_4_deterministic_replay_run_count", "ge", 20.0),
    ThresholdClause("P0-PAPER-SVC-20260301-4", "p0_4_terminal_order_state_coverage_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-4", "p0_4_post_only_violation_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-4", "p0_4_cancel_race_misclassification_rate_pct", "le", 0.10),
    # [P0-PAPER-SVC-20260301-5]
    ThresholdClause("P0-PAPER-SVC-20260301-5", "p0_5_crash_restart_cycles_tested_count", "ge", 50.0),
    ThresholdClause("P0-PAPER-SVC-20260301-5", "p0_5_lost_commands_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-5", "p0_5_duplicate_fills_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-5", "p0_5_restart_to_healthy_heartbeat_seconds", "le", 30.0),
    ThresholdClause("P0-PAPER-SVC-20260301-5", "p0_5_pending_entries_over_60s_count", "eq", 0.0),
    # [P1-PAPER-SVC-20260301-6]
    ThresholdClause("P1-PAPER-SVC-20260301-6", "p1_6_per_fill_fee_abs_error_pct_notional_max", "le", 0.01),
    ThresholdClause("P1-PAPER-SVC-20260301-6", "p1_6_cumulative_realized_pnl_drift_pct_equity", "le", 0.10),
    ThresholdClause("P1-PAPER-SVC-20260301-6", "p1_6_funding_sign_mismatch_count", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-6", "p1_6_margin_reserve_drift_pct_equity", "le", 0.10),
    # [P1-PAPER-SVC-20260301-7]
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_parity_eval_window_hours", "ge", 24.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_parity_eval_command_events_count", "ge", 5000.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_fill_ratio_delta_pp", "le", 2.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_reject_ratio_delta_pp", "le", 1.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_fill_price_delta_p95_bps", "le", 3.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_fill_price_delta_p99_bps", "le", 6.0),
    ThresholdClause("P1-PAPER-SVC-20260301-7", "p1_7_end_window_equity_delta_pct", "le", 0.30),
    # [P1-PAPER-SVC-20260301-8]
    ThresholdClause("P1-PAPER-SVC-20260301-8", "p1_8_heartbeat_availability_pct", "ge", 99.90),
    ThresholdClause("P1-PAPER-SVC-20260301-8", "p1_8_command_processing_success_rate_pct", "ge", 99.50),
    ThresholdClause("P1-PAPER-SVC-20260301-8", "p1_8_command_latency_p95_ms", "le", 250.0),
    ThresholdClause("P1-PAPER-SVC-20260301-8", "p1_8_command_latency_p99_ms", "le", 500.0),
    ThresholdClause("P1-PAPER-SVC-20260301-8", "p1_8_critical_dead_letter_reasons_per_hour", "eq", 0.0),
    # [P1-PAPER-SVC-20260301-9]
    ThresholdClause("P1-PAPER-SVC-20260301-9", "p1_9_canary_run_duration_hours", "ge", 24.0),
    ThresholdClause("P1-PAPER-SVC-20260301-9", "p1_9_canary_critical_alert_count", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-9", "p1_9_rollback_drill_rto_minutes", "le", 5.0),
    ThresholdClause("P1-PAPER-SVC-20260301-9", "p1_9_rollback_drill_rpo_lost_commands", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-9", "p1_9_active_mode_rollout_concurrency_bots", "le", 1.0),
    # [P2-PAPER-SVC-20260301-10]
    ThresholdClause("P2-PAPER-SVC-20260301-10", "p2_10_reused_module_provenance_doc_coverage_pct", "ge", 100.0),
    ThresholdClause("P2-PAPER-SVC-20260301-10", "p2_10_license_compliance_check_failures", "eq", 0.0),
    ThresholdClause("P2-PAPER-SVC-20260301-10", "p2_10_adopted_module_behavior_parity_tests_pass_rate_pct", "ge", 100.0),
    ThresholdClause("P2-PAPER-SVC-20260301-10", "p2_10_undocumented_external_framework_dependency_count", "eq", 0.0),
    # [P0-PAPER-SVC-20260301-11]
    ThresholdClause("P0-PAPER-SVC-20260301-11", "p0_11_hb_executor_lifecycle_tests_pass_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-11", "p0_11_hb_event_count_delta_pct", "le", 1.0),
    ThresholdClause("P0-PAPER-SVC-20260301-11", "p0_11_inflight_order_lookup_miss_rate_pct", "le", 0.10),
    ThresholdClause("P0-PAPER-SVC-20260301-11", "p0_11_runtime_adapter_exception_count_24h", "eq", 0.0),
    # [P0-PAPER-SVC-20260301-12]
    ThresholdClause("P0-PAPER-SVC-20260301-12", "p0_12_required_l1_fields_non_null_rate_pct", "ge", 99.90),
    ThresholdClause("P0-PAPER-SVC-20260301-12", "p0_12_out_of_order_sequence_error_rate_pct", "le", 0.01),
    ThresholdClause("P0-PAPER-SVC-20260301-12", "p0_12_matching_decisions_traceable_rate_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-12", "p0_12_active_mode_mid_only_fallback_command_count", "eq", 0.0),
    # [P0-PAPER-SVC-20260301-13]
    ThresholdClause("P0-PAPER-SVC-20260301-13", "p0_13_duplicate_command_side_effect_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-13", "p0_13_pending_reclaim_time_p95_seconds", "le", 30.0),
    ThresholdClause("P0-PAPER-SVC-20260301-13", "p0_13_unacked_entries_over_120s_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-13", "p0_13_duplicate_command_detection_rate_pct", "ge", 100.0),
    # [P0-PAPER-SVC-20260301-14]
    ThresholdClause("P0-PAPER-SVC-20260301-14", "p0_14_quote_before_sync_violation_count", "eq", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-14", "p0_14_sync_handshake_completion_p95_seconds", "le", 20.0),
    ThresholdClause("P0-PAPER-SVC-20260301-14", "p0_14_sync_handshake_completion_max_seconds", "le", 30.0),
    ThresholdClause("P0-PAPER-SVC-20260301-14", "p0_14_sync_timeout_to_hard_stop_seconds", "le", 5.0),
    ThresholdClause("P0-PAPER-SVC-20260301-14", "p0_14_startup_sync_success_rate_pct", "ge", 99.0),
    # [P1-PAPER-SVC-20260301-15]
    ThresholdClause("P1-PAPER-SVC-20260301-15", "p1_15_cross_instance_state_violation_count", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-15", "p1_15_namespace_key_collision_count_72h", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-15", "p1_15_command_event_routing_correctness_rate_pct", "ge", 100.0),
    # [P1-PAPER-SVC-20260301-16]
    ThresholdClause("P1-PAPER-SVC-20260301-16", "p1_16_service_down_detection_delay_seconds", "le", 5.0),
    ThresholdClause("P1-PAPER-SVC-20260301-16", "p1_16_safety_state_transition_delay_seconds", "le", 10.0),
    ThresholdClause("P1-PAPER-SVC-20260301-16", "p1_16_silent_live_fallback_count", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-16", "p1_16_mean_recovery_time_minutes", "le", 10.0),
    # [P1-PAPER-SVC-20260301-17]
    ThresholdClause("P1-PAPER-SVC-20260301-17", "p1_17_strict_cycle_checks_enforced_rate_pct", "ge", 100.0),
    ThresholdClause("P1-PAPER-SVC-20260301-17", "p1_17_preflight_nonzero_on_missing_or_stale_rate_pct", "ge", 100.0),
    ThresholdClause("P1-PAPER-SVC-20260301-17", "p1_17_parity_slo_artifact_freshness_minutes", "le", 20.0),
    ThresholdClause("P1-PAPER-SVC-20260301-17", "p1_17_gate_path_tests_pass_rate_pct", "ge", 100.0),
    # [P0-PAPER-SVC-20260301-18]
    ThresholdClause("P0-PAPER-SVC-20260301-18", "p0_18_evaluator_output_determinism_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-18", "p0_18_threshold_clause_coverage_pct", "ge", 100.0),
    ThresholdClause("P0-PAPER-SVC-20260301-18", "p0_18_false_pass_rate_pct", "le", 0.0),
    ThresholdClause("P0-PAPER-SVC-20260301-18", "p0_18_strict_cycle_invocation_success_rate_pct", "ge", 100.0),
    # [P1-PAPER-SVC-20260301-19]
    ThresholdClause("P1-PAPER-SVC-20260301-19", "p1_19_sustained_command_throughput_cmds_per_sec", "ge", 50.0),
    ThresholdClause("P1-PAPER-SVC-20260301-19", "p1_19_command_latency_under_load_p95_ms", "le", 500.0),
    ThresholdClause("P1-PAPER-SVC-20260301-19", "p1_19_command_latency_under_load_p99_ms", "le", 1000.0),
    ThresholdClause("P1-PAPER-SVC-20260301-19", "p1_19_stream_backlog_growth_rate_pct_per_10min", "le", 1.0),
    ThresholdClause("P1-PAPER-SVC-20260301-19", "p1_19_stress_window_oom_restart_count", "eq", 0.0),
    # [P1-PAPER-SVC-20260301-20]
    ThresholdClause("P1-PAPER-SVC-20260301-20", "p1_20_unauthorized_producer_acceptance_rate_pct", "le", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-20", "p1_20_privileged_command_attribution_complete_rate_pct", "ge", 100.0),
    ThresholdClause("P1-PAPER-SVC-20260301-20", "p1_20_security_policy_test_suite_pass_rate_pct", "ge", 100.0),
    ThresholdClause("P1-PAPER-SVC-20260301-20", "p1_20_privileged_command_missing_audit_event_rate_pct", "le", 0.0),
    # [P1-PAPER-SVC-20260301-21]
    ThresholdClause("P1-PAPER-SVC-20260301-21", "p1_21_successful_restore_drills_30d_count", "ge", 2.0),
    ThresholdClause("P1-PAPER-SVC-20260301-21", "p1_21_restore_replay_data_integrity_mismatch_count", "eq", 0.0),
    ThresholdClause("P1-PAPER-SVC-20260301-21", "p1_21_full_restore_to_healthy_heartbeat_minutes", "le", 15.0),
    ThresholdClause("P1-PAPER-SVC-20260301-21", "p1_21_backup_artifact_freshness_hours", "le", 24.0),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> Optional[datetime]:
    s = str(value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _minutes_since(ts_utc: str, now_ts: float) -> float:
    dt = _parse_ts(ts_utc)
    if dt is None:
        return 1e9
    return max(0.0, (now_ts - dt.timestamp()) / 60.0)


def _minutes_since_file_mtime(path: Path, now_ts: float) -> float:
    try:
        return max(0.0, (now_ts - float(path.stat().st_mtime)) / 60.0)
    except Exception:
        return 1e9


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _compare(observed: float, op: str, target: float) -> bool:
    if op == "le":
        return observed <= target
    if op == "ge":
        return observed >= target
    if op == "eq":
        return abs(observed - target) <= 1e-12
    raise ValueError(f"unsupported comparator: {op}")


def default_pass_metrics() -> Dict[str, float]:
    out: Dict[str, float] = {}
    for clause in THRESHOLD_CLAUSES:
        out[clause.metric] = float(clause.target)
    return out


def evaluate_thresholds(metrics: Dict[str, object]) -> Dict[str, object]:
    working_metrics = dict(metrics)
    clause_count = len(THRESHOLD_CLAUSES)
    coverage_pct = 100.0 if clause_count > 0 else 0.0
    # Auto-populated metric so item 18 can validate matrix coverage deterministically.
    working_metrics["p0_18_threshold_clause_coverage_pct"] = coverage_pct

    clause_results: List[Dict[str, object]] = []
    per_item: Dict[str, Dict[str, object]] = {}
    failed_items: List[str] = []
    passed_clauses = 0

    for clause in THRESHOLD_CLAUSES:
        item_bucket = per_item.setdefault(
            clause.item_id,
            {"item_id": clause.item_id, "status": "pass", "failed_clauses": [], "clause_count": 0},
        )
        item_bucket["clause_count"] = int(item_bucket["clause_count"]) + 1

        observed_raw = working_metrics.get(clause.metric)
        observed_num = _to_float(observed_raw)
        if observed_raw is None:
            passed = False
            reason = "missing_metric"
        elif observed_num is None:
            passed = False
            reason = "non_numeric_metric"
        else:
            passed = _compare(observed_num, clause.op, clause.target)
            reason = "pass" if passed else "threshold_breach"

        if passed:
            passed_clauses += 1
        else:
            item_bucket["status"] = "fail"
            item_bucket["failed_clauses"].append(clause.metric)

        clause_results.append(
            {
                "item_id": clause.item_id,
                "metric": clause.metric,
                "op": clause.op,
                "target": clause.target,
                "observed": observed_raw,
                "pass": passed,
                "reason": reason,
            }
        )

    for item_id, bucket in per_item.items():
        if str(bucket.get("status", "pass")).lower() != "pass":
            failed_items.append(item_id)

    return {
        "clause_results": clause_results,
        "item_results": [per_item[item_id] for item_id in sorted(per_item.keys())],
        "failed_items": sorted(failed_items),
        "summary": {
            "total_items": len(per_item),
            "total_clauses": clause_count,
            "passed_clauses": passed_clauses,
            "failed_clauses": clause_count - passed_clauses,
            "coverage_pct": coverage_pct,
        },
    }


def build_report(
    root: Path,
    *,
    now_ts: Optional[float] = None,
    max_input_age_min: float = 20.0,
    require_input_fresh: bool = True,
    inputs_path: Optional[Path] = None,
    inputs_payload: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    resolved_inputs_path = inputs_path or (root / "reports" / "verification" / "paper_exchange_threshold_inputs_latest.json")

    payload: Dict[str, object] = dict(inputs_payload or {})
    source = "inline_payload" if inputs_payload is not None else str(resolved_inputs_path)
    input_present = bool(payload) if inputs_payload is not None else resolved_inputs_path.exists()
    if inputs_payload is None:
        payload = _read_json(resolved_inputs_path)

    payload_ts = str(payload.get("ts_utc", "")).strip()
    payload_age_min = (
        _minutes_since(payload_ts, now_ts)
        if payload_ts
        else _minutes_since_file_mtime(resolved_inputs_path, now_ts)
    )
    input_fresh = input_present and (payload_age_min <= float(max_input_age_min))
    metrics = payload.get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}

    eval_result = evaluate_thresholds(metrics)
    failed_items = eval_result.get("failed_items", [])
    failed_items = failed_items if isinstance(failed_items, list) else []

    checks = {
        "input_artifact_present": bool(input_present),
        "input_artifact_fresh": bool(input_fresh) if require_input_fresh else True,
        "threshold_matrix_complete": bool(eval_result.get("summary", {}).get("coverage_pct", 0.0) >= 100.0),
        "all_item_thresholds_passed": len(failed_items) == 0,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    status = "pass" if not failed_checks else "fail"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "input": {
            "source": source,
            "path": str(resolved_inputs_path),
            "present": bool(input_present),
            "fresh": bool(input_fresh),
            "age_min": float(payload_age_min),
            "max_input_age_min": float(max_input_age_min),
            "require_input_fresh": bool(require_input_fresh),
        },
        "evaluation": eval_result,
    }


def run_check(
    *,
    strict: bool,
    max_input_age_min: float,
    require_input_fresh: bool,
    inputs_path: str,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    resolved_inputs_path = Path(inputs_path) if str(inputs_path).strip() else None
    report = build_report(
        root,
        max_input_age_min=max_input_age_min,
        require_input_fresh=require_input_fresh,
        inputs_path=resolved_inputs_path,
    )

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_exchange_thresholds_{stamp}.json"
    latest_path = out_dir / "paper_exchange_thresholds_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    failed_items = report.get("evaluation", {}).get("failed_items", [])
    print(f"[paper-exchange-thresholds] status={report.get('status')} failed_items={failed_items}")
    print(f"[paper-exchange-thresholds] evidence={out_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate paper-exchange quantitative GO/NO-GO thresholds.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on threshold failures.")
    parser.add_argument(
        "--max-input-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_MAX_AGE_MIN", "20")),
        help="Maximum allowed age for threshold input artifact.",
    )
    parser.add_argument(
        "--inputs",
        default=os.getenv("PAPER_EXCHANGE_THRESHOLD_INPUTS_PATH", ""),
        help="Optional explicit path to threshold input artifact JSON.",
    )
    parser.add_argument(
        "--require-input-fresh",
        action="store_true",
        default=True,
        help="Require threshold input artifact freshness.",
    )
    parser.add_argument(
        "--no-require-input-fresh",
        action="store_false",
        dest="require_input_fresh",
        help="Do not fail when input artifact is stale.",
    )
    args = parser.parse_args()

    return run_check(
        strict=bool(args.strict),
        max_input_age_min=float(args.max_input_age_min),
        require_input_fresh=bool(args.require_input_fresh),
        inputs_path=str(args.inputs),
    )


if __name__ == "__main__":
    raise SystemExit(main())

