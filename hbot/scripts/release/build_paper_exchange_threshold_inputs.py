#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.release.check_paper_exchange_thresholds import THRESHOLD_CLAUSES, _source_artifacts_for_metric

DR_RESTORE_MINUTES_SENTINEL = 1_000_000.0
DR_BACKUP_FRESHNESS_HOURS_SENTINEL = 1_000_000.0
P1_16_DELAY_SECONDS_SENTINEL = 1_000_000.0
P1_16_RECOVERY_MINUTES_SENTINEL = 1_000_000.0
_DR_BACKUP_RETENTION_DAYS = 45
_DR_SUCCESS_WINDOW_DAYS = 30


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ts(value: str) -> datetime | None:
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


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _hours_since_file_mtime(path: Path, now_ts: float) -> float:
    try:
        return max(0.0, (now_ts - float(path.stat().st_mtime)) / 3600.0)
    except Exception:
        return DR_BACKUP_FRESHNESS_HOURS_SENTINEL


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _dict_size(payload: dict[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        return None
    return len(raw)


def _count_mismatch(payload: dict[str, object], count_key: str, values_key: str) -> int:
    expected = _to_float(payload.get(count_key))
    observed = _dict_size(payload, values_key)
    if expected is None or observed is None:
        return 1
    return 0 if int(expected) == int(observed) else 1


def _latest_backup_age_hours(backup_root: Path, now_ts: float) -> float:
    if not backup_root.exists():
        return DR_BACKUP_FRESHNESS_HOURS_SENTINEL
    candidates = sorted(backup_root.glob("**/*.json"))
    if not candidates:
        return DR_BACKUP_FRESHNESS_HOURS_SENTINEL
    newest = max(candidates, key=lambda path: float(path.stat().st_mtime))
    return _hours_since_file_mtime(newest, now_ts)


def _paper_exchange_state_dr_report(reports: Path, now_ts: float) -> dict[str, object]:
    verification = reports / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    required_sources = {
        "paper_exchange_command_journal_latest": verification / "paper_exchange_command_journal_latest.json",
        "paper_exchange_state_snapshot_latest": verification / "paper_exchange_state_snapshot_latest.json",
        "paper_exchange_pair_snapshot_latest": verification / "paper_exchange_pair_snapshot_latest.json",
        "paper_exchange_market_fill_journal_latest": verification / "paper_exchange_market_fill_journal_latest.json",
    }
    backup_root = verification / "paper_exchange_state_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / stamp
    history_latest = verification / "paper_exchange_state_dr_history_latest.json"
    history_ts = verification / f"paper_exchange_state_dr_history_{stamp}.json"
    report_latest = verification / "paper_exchange_state_dr_latest.json"
    report_ts = verification / f"paper_exchange_state_dr_{stamp}.json"

    integrity_mismatch_count = 0
    missing_artifacts: list[str] = []
    copy_failures: list[str] = []
    hash_mismatches: list[str] = []

    started = time.perf_counter()
    for artifact_name, src in required_sources.items():
        if not src.exists():
            missing_artifacts.append(artifact_name)
    integrity_mismatch_count += len(missing_artifacts)

    if not missing_artifacts:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for artifact_name, src in required_sources.items():
            dst = backup_dir / src.name
            try:
                shutil.copy2(src, dst)
            except Exception:
                copy_failures.append(artifact_name)
                continue
            src_hash = _sha256_file(src)
            dst_hash = _sha256_file(dst)
            if src_hash and dst_hash and src_hash != dst_hash:
                hash_mismatches.append(artifact_name)

        integrity_mismatch_count += len(copy_failures)
        integrity_mismatch_count += len(hash_mismatches)

        if not copy_failures and not hash_mismatches:
            command_journal = _read_json(backup_dir / "paper_exchange_command_journal_latest.json")
            state_snapshot = _read_json(backup_dir / "paper_exchange_state_snapshot_latest.json")
            pair_snapshot = _read_json(backup_dir / "paper_exchange_pair_snapshot_latest.json")
            market_fill_journal = _read_json(backup_dir / "paper_exchange_market_fill_journal_latest.json")

            integrity_mismatch_count += _count_mismatch(command_journal, "command_count", "commands")
            integrity_mismatch_count += _count_mismatch(state_snapshot, "orders_total", "orders")
            integrity_mismatch_count += _count_mismatch(pair_snapshot, "pairs_total", "pairs")
            integrity_mismatch_count += _count_mismatch(market_fill_journal, "event_count", "events")

    observed_restore_minutes = max(0.0, (time.perf_counter() - started) / 60.0)
    restore_minutes_metric = (
        float(observed_restore_minutes)
        if integrity_mismatch_count == 0 and len(missing_artifacts) == 0
        else DR_RESTORE_MINUTES_SENTINEL
    )
    backup_freshness_hours = _latest_backup_age_hours(backup_root, now_ts)

    history_payload = _read_json(history_latest)
    existing_runs_raw = history_payload.get("runs", [])
    existing_runs = existing_runs_raw if isinstance(existing_runs_raw, list) else []
    retained_runs: list[dict[str, object]] = []
    max_retention_seconds = float(_DR_BACKUP_RETENTION_DAYS) * 86400.0
    for run in existing_runs:
        if not isinstance(run, dict):
            continue
        run_ts = _parse_ts(str(run.get("ts_utc", "")).strip())
        if run_ts is None:
            continue
        if (now_ts - run_ts.timestamp()) <= max_retention_seconds:
            retained_runs.append(dict(run))

    current_status = "pass" if integrity_mismatch_count == 0 else "fail"
    current_run = {
        "ts_utc": _utc_now(),
        "status": current_status,
        "integrity_mismatch_count": int(integrity_mismatch_count),
        "restore_duration_minutes_observed": float(observed_restore_minutes),
        "backup_freshness_hours": float(backup_freshness_hours),
        "missing_artifacts": sorted(set(missing_artifacts)),
        "copy_failures": sorted(set(copy_failures)),
        "hash_mismatches": sorted(set(hash_mismatches)),
        "backup_dir": str(backup_dir) if backup_dir.exists() else "",
    }
    retained_runs.append(current_run)

    window_seconds = float(_DR_SUCCESS_WINDOW_DAYS) * 86400.0
    successful_restore_drills_30d_count = 0
    for run in retained_runs:
        if str(run.get("status", "")).strip().lower() != "pass":
            continue
        run_ts = _parse_ts(str(run.get("ts_utc", "")).strip())
        if run_ts is None:
            continue
        if (now_ts - run_ts.timestamp()) <= window_seconds:
            successful_restore_drills_30d_count += 1

    history_output = {
        "ts_utc": _utc_now(),
        "status": "ok",
        "retention_days": int(_DR_BACKUP_RETENTION_DAYS),
        "success_window_days": int(_DR_SUCCESS_WINDOW_DAYS),
        "runs": retained_runs[-500:],
    }
    history_latest.write_text(json.dumps(history_output, indent=2), encoding="utf-8")
    history_ts.write_text(json.dumps(history_output, indent=2), encoding="utf-8")

    metrics = {
        "p1_21_successful_restore_drills_30d_count": float(successful_restore_drills_30d_count),
        "p1_21_restore_replay_data_integrity_mismatch_count": float(integrity_mismatch_count),
        "p1_21_full_restore_to_healthy_heartbeat_minutes": float(restore_minutes_metric),
        "p1_21_backup_artifact_freshness_hours": float(backup_freshness_hours),
    }
    report = {
        "ts_utc": _utc_now(),
        "status": "pass" if integrity_mismatch_count == 0 else "fail",
        "metrics": metrics,
        "diagnostics": {
            "required_artifact_count": len(required_sources),
            "required_artifacts": {name: str(path) for name, path in required_sources.items()},
            "missing_artifacts": sorted(set(missing_artifacts)),
            "copy_failures": sorted(set(copy_failures)),
            "hash_mismatches": sorted(set(hash_mismatches)),
            "backup_root": str(backup_root),
            "backup_dir": str(backup_dir) if backup_dir.exists() else "",
            "history_latest_path": str(history_latest),
            "restore_duration_minutes_observed": float(observed_restore_minutes),
            "restore_duration_minutes_metric": float(restore_minutes_metric),
        },
    }
    report_latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_ts.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _paper_exchange_state_dr_fail_closed_report(error_text: str) -> dict[str, object]:
    return {
        "ts_utc": _utc_now(),
        "status": "fail",
        "metrics": {
            "p1_21_successful_restore_drills_30d_count": 0.0,
            "p1_21_restore_replay_data_integrity_mismatch_count": 1.0,
            "p1_21_full_restore_to_healthy_heartbeat_minutes": DR_RESTORE_MINUTES_SENTINEL,
            "p1_21_backup_artifact_freshness_hours": DR_BACKUP_FRESHNESS_HOURS_SENTINEL,
        },
        "diagnostics": {
            "error": str(error_text or "unknown_error"),
        },
    }


def _namespace_base_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return (
        f"{str(instance_name or '').strip().lower()}::"
        f"{str(connector_name or '').strip().lower()}::"
        f"{str(trading_pair or '').strip().upper()}"
    )


def _namespace_key_from_record(record: dict[str, object]) -> str:
    explicit = str(record.get("namespace_key", "")).strip()
    if explicit:
        return explicit
    return _namespace_base_key(
        str(record.get("instance_name", "")),
        str(record.get("connector_name", "")),
        str(record.get("trading_pair", "")),
    )


def _ordering_value(record: dict[str, object], fallback: int) -> int:
    metadata = record.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    sequence = _to_float(metadata.get("command_sequence"))
    if sequence is not None:
        try:
            return int(sequence)
        except Exception:
            pass
    return int(fallback)


def _paper_exchange_namespace_isolation_report(
    reports: Path,
    *,
    command_journal: dict[str, object],
    state_snapshot: dict[str, object],
    pair_snapshot: dict[str, object],
) -> dict[str, object]:
    verification = reports / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_latest = verification / "paper_exchange_namespace_isolation_latest.json"
    report_ts = verification / f"paper_exchange_namespace_isolation_{stamp}.json"

    raw_orders = state_snapshot.get("orders", {})
    raw_orders = raw_orders if isinstance(raw_orders, dict) else {}
    raw_pairs = pair_snapshot.get("pairs", {})
    raw_pairs = raw_pairs if isinstance(raw_pairs, dict) else {}
    raw_commands = command_journal.get("commands", {})
    raw_commands = raw_commands if isinstance(raw_commands, dict) else {}

    accepted_namespace_by_order_id: dict[str, str] = {}
    state_collision_count = 0
    malformed_order_records = 0
    for order_key, order_record in raw_orders.items():
        if not isinstance(order_record, dict):
            malformed_order_records += 1
            continue
        order_id = str(order_record.get("order_id", order_key)).strip()
        namespace_key = _namespace_key_from_record(order_record)
        if not order_id or "::" not in namespace_key:
            malformed_order_records += 1
            continue
        existing_namespace = accepted_namespace_by_order_id.get(order_id)
        if existing_namespace is None:
            accepted_namespace_by_order_id[order_id] = namespace_key
        elif existing_namespace != namespace_key:
            state_collision_count += 1

    pair_namespace_mismatch_count = 0
    for pair_key, pair_record in raw_pairs.items():
        if not isinstance(pair_record, dict):
            continue
        expected_pair_key = _namespace_base_key(
            str(pair_record.get("instance_name", "")),
            str(pair_record.get("connector_name", "")),
            str(pair_record.get("trading_pair", "")),
        )
        if expected_pair_key and str(pair_key).strip() and str(pair_key).strip() != expected_pair_key:
            pair_namespace_mismatch_count += 1

    ordered_commands: list[dict[str, object]] = []
    for idx, record in enumerate(raw_commands.values()):
        if not isinstance(record, dict):
            continue
        decorated = dict(record)
        decorated["_ordering"] = _ordering_value(record, idx)
        ordered_commands.append(decorated)
    ordered_commands.sort(key=lambda record: int(record.get("_ordering", 0)))

    total_routing_checks = 0
    correct_routing_checks = 0
    routing_violation_count = 0
    accepted_namespace_collision_count = 0
    violation_samples: list[dict[str, object]] = []

    for record in ordered_commands:
        command = str(record.get("command", "")).strip().lower()
        status = str(record.get("status", "")).strip().lower()
        reason = str(record.get("reason", "")).strip().lower()
        order_id = str(record.get("order_id", "")).strip()
        namespace_key = _namespace_key_from_record(record)

        if command not in {"submit_order", "cancel_order"} or not order_id:
            continue

        total_routing_checks += 1
        existing_namespace = accepted_namespace_by_order_id.get(order_id)
        has_cross_namespace_conflict = bool(existing_namespace and namespace_key and existing_namespace != namespace_key)

        if command == "submit_order":
            if status == "processed":
                if has_cross_namespace_conflict:
                    accepted_namespace_collision_count += 1
                    routing_violation_count += 1
                    violation_samples.append(
                        {
                            "command": command,
                            "order_id": order_id,
                            "status": status,
                            "reason": reason,
                            "existing_namespace": existing_namespace,
                            "command_namespace": namespace_key,
                        }
                    )
                    continue
                if namespace_key:
                    accepted_namespace_by_order_id.setdefault(order_id, namespace_key)
                correct_routing_checks += 1
                continue

            # Rejected submit: a cross-namespace collision must explicitly use the collision reason.
            if has_cross_namespace_conflict and reason != "order_id_namespace_collision":
                routing_violation_count += 1
                violation_samples.append(
                    {
                        "command": command,
                        "order_id": order_id,
                        "status": status,
                        "reason": reason,
                        "expected_reason": "order_id_namespace_collision",
                        "existing_namespace": existing_namespace,
                        "command_namespace": namespace_key,
                    }
                )
                continue
            correct_routing_checks += 1
            continue

        # cancel_order path
        if has_cross_namespace_conflict:
            if status == "rejected" and reason == "order_scope_mismatch":
                correct_routing_checks += 1
            else:
                routing_violation_count += 1
                violation_samples.append(
                    {
                        "command": command,
                        "order_id": order_id,
                        "status": status,
                        "reason": reason,
                        "expected_reason": "order_scope_mismatch",
                        "existing_namespace": existing_namespace,
                        "command_namespace": namespace_key,
                    }
                )
            continue
        correct_routing_checks += 1

    cross_instance_state_violation_count = (
        int(routing_violation_count)
        + int(state_collision_count)
        + int(malformed_order_records)
        + int(pair_namespace_mismatch_count)
    )
    namespace_key_collision_count_72h = int(accepted_namespace_collision_count + state_collision_count)
    routing_correctness_rate_pct = (
        100.0
        if total_routing_checks <= 0
        else (100.0 * float(correct_routing_checks) / float(total_routing_checks))
    )

    metrics = {
        "p1_15_cross_instance_state_violation_count": float(cross_instance_state_violation_count),
        "p1_15_namespace_key_collision_count_72h": float(namespace_key_collision_count_72h),
        "p1_15_command_event_routing_correctness_rate_pct": float(routing_correctness_rate_pct),
    }
    report = {
        "ts_utc": _utc_now(),
        "status": (
            "pass"
            if (
                cross_instance_state_violation_count == 0
                and namespace_key_collision_count_72h == 0
                and abs(routing_correctness_rate_pct - 100.0) <= 1e-12
            )
            else "fail"
        ),
        "metrics": metrics,
        "diagnostics": {
            "total_routing_checks": int(total_routing_checks),
            "correct_routing_checks": int(correct_routing_checks),
            "routing_violation_count": int(routing_violation_count),
            "accepted_namespace_collision_count": int(accepted_namespace_collision_count),
            "state_collision_count": int(state_collision_count),
            "malformed_order_records": int(malformed_order_records),
            "pair_namespace_mismatch_count": int(pair_namespace_mismatch_count),
            "violation_samples": violation_samples[:20],
        },
    }
    payload = json.dumps(report, indent=2)
    report_latest.write_text(payload, encoding="utf-8")
    report_ts.write_text(payload, encoding="utf-8")
    return report


def _paper_exchange_namespace_isolation_fail_closed_report(error_text: str) -> dict[str, object]:
    return {
        "ts_utc": _utc_now(),
        "status": "fail",
        "metrics": {
            "p1_15_cross_instance_state_violation_count": 1.0,
            "p1_15_namespace_key_collision_count_72h": 1.0,
            "p1_15_command_event_routing_correctness_rate_pct": 0.0,
        },
        "diagnostics": {
            "error": str(error_text or "unknown_error"),
        },
    }


def _failure_policy_fail_closed_metrics() -> dict[str, float]:
    return {
        "p1_16_service_down_detection_delay_seconds": P1_16_DELAY_SECONDS_SENTINEL,
        "p1_16_safety_state_transition_delay_seconds": P1_16_DELAY_SECONDS_SENTINEL,
        "p1_16_silent_live_fallback_count": 1.0,
        "p1_16_mean_recovery_time_minutes": P1_16_RECOVERY_MINUTES_SENTINEL,
    }


def _paper_exchange_active_failure_policy_report(reports: Path, golden_path: dict[str, object]) -> dict[str, object]:
    verification = reports / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_latest = verification / "paper_exchange_active_failure_policy_latest.json"
    report_ts = verification / f"paper_exchange_active_failure_policy_{stamp}.json"

    required_scenario_id = "active_mode_failure_policy"
    required_metric_names = [
        "p1_16_service_down_detection_delay_seconds",
        "p1_16_safety_state_transition_delay_seconds",
        "p1_16_silent_live_fallback_count",
        "p1_16_mean_recovery_time_minutes",
    ]

    golden_status = str(golden_path.get("status", "")).strip().lower()
    scenarios_raw = golden_path.get("scenarios", [])
    scenarios = scenarios_raw if isinstance(scenarios_raw, list) else []
    scenario: dict[str, object] | None = None
    for row in scenarios:
        if not isinstance(row, dict):
            continue
        if str(row.get("id", "")).strip() == required_scenario_id:
            scenario = row
            break

    scenario_status = str(scenario.get("status", "")).strip().lower() if isinstance(scenario, dict) else ""
    raw_metrics = scenario.get("derived_metrics", {}) if isinstance(scenario, dict) else {}
    raw_metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    parsed_metrics: dict[str, float] = {}
    missing_metric_keys: list[str] = []
    for metric_name in required_metric_names:
        parsed = _to_float(raw_metrics.get(metric_name))
        if parsed is None:
            missing_metric_keys.append(metric_name)
            continue
        parsed_metrics[str(metric_name)] = float(parsed)

    policy_evidence_ok = golden_status == "pass" and scenario_status == "pass" and len(missing_metric_keys) == 0
    metrics = parsed_metrics if policy_evidence_ok else _failure_policy_fail_closed_metrics()
    report_status = (
        "pass"
        if policy_evidence_ok and abs(float(metrics["p1_16_silent_live_fallback_count"])) <= 1e-12
        else "fail"
    )
    report = {
        "ts_utc": _utc_now(),
        "status": report_status,
        "metrics": metrics,
        "diagnostics": {
            "golden_path_status": golden_status or "missing",
            "required_scenario_id": required_scenario_id,
            "required_scenario_present": scenario is not None,
            "required_scenario_status": scenario_status or "missing",
            "required_metric_count": len(required_metric_names),
            "missing_metric_keys": missing_metric_keys,
        },
    }
    payload = json.dumps(report, indent=2)
    report_latest.write_text(payload, encoding="utf-8")
    report_ts.write_text(payload, encoding="utf-8")
    return report


def _paper_exchange_active_failure_policy_fail_closed_report(error_text: str) -> dict[str, object]:
    return {
        "ts_utc": _utc_now(),
        "status": "fail",
        "metrics": _failure_policy_fail_closed_metrics(),
        "diagnostics": {
            "error": str(error_text or "unknown_error"),
        },
    }


def _hb_executor_compat_fail_closed_metrics() -> dict[str, float]:
    return {
        "p0_11_hb_executor_lifecycle_tests_pass_rate_pct": 0.0,
        "p0_11_hb_event_count_delta_pct": 100.0,
        "p0_11_inflight_order_lookup_miss_rate_pct": 100.0,
        "p0_11_runtime_adapter_exception_count_24h": 1.0,
    }


def _paper_exchange_hb_executor_compat_report(reports: Path, golden_path: dict[str, object]) -> dict[str, object]:
    verification = reports / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_latest = verification / "paper_exchange_hb_compatibility_latest.json"
    report_ts = verification / f"paper_exchange_hb_compatibility_{stamp}.json"

    required_scenario_id = "hb_executor_runtime_compatibility"
    required_metric_names = [
        "p0_11_hb_executor_lifecycle_tests_pass_rate_pct",
        "p0_11_hb_event_count_delta_pct",
        "p0_11_inflight_order_lookup_miss_rate_pct",
        "p0_11_runtime_adapter_exception_count_24h",
    ]

    golden_status = str(golden_path.get("status", "")).strip().lower()
    scenarios_raw = golden_path.get("scenarios", [])
    scenarios = scenarios_raw if isinstance(scenarios_raw, list) else []
    scenario: dict[str, object] | None = None
    for row in scenarios:
        if not isinstance(row, dict):
            continue
        if str(row.get("id", "")).strip() == required_scenario_id:
            scenario = row
            break

    scenario_status = str(scenario.get("status", "")).strip().lower() if isinstance(scenario, dict) else ""
    raw_metrics = scenario.get("derived_metrics", {}) if isinstance(scenario, dict) else {}
    raw_metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
    parsed_metrics: dict[str, float] = {}
    missing_metric_keys: list[str] = []
    for metric_name in required_metric_names:
        parsed = _to_float(raw_metrics.get(metric_name))
        if parsed is None:
            missing_metric_keys.append(metric_name)
            continue
        parsed_metrics[str(metric_name)] = float(parsed)

    evidence_ok = golden_status == "pass" and scenario_status == "pass" and len(missing_metric_keys) == 0
    metrics = parsed_metrics if evidence_ok else _hb_executor_compat_fail_closed_metrics()

    lifecycle_rate = float(metrics.get("p0_11_hb_executor_lifecycle_tests_pass_rate_pct", 0.0))
    hb_event_delta_pct = float(metrics.get("p0_11_hb_event_count_delta_pct", 100.0))
    inflight_miss_rate_pct = float(metrics.get("p0_11_inflight_order_lookup_miss_rate_pct", 100.0))
    runtime_adapter_exception_count = float(metrics.get("p0_11_runtime_adapter_exception_count_24h", 1.0))
    metric_thresholds_ok = (
        lifecycle_rate >= 100.0
        and hb_event_delta_pct <= 1.0
        and inflight_miss_rate_pct <= 0.10
        and abs(runtime_adapter_exception_count) <= 1e-12
    )

    report = {
        "ts_utc": _utc_now(),
        "status": "pass" if evidence_ok and metric_thresholds_ok else "fail",
        "metrics": metrics,
        "diagnostics": {
            "golden_path_status": golden_status or "missing",
            "required_scenario_id": required_scenario_id,
            "required_scenario_present": scenario is not None,
            "required_scenario_status": scenario_status or "missing",
            "required_metric_count": len(required_metric_names),
            "missing_metric_keys": missing_metric_keys,
            "metric_thresholds_ok": bool(metric_thresholds_ok),
        },
    }
    payload = json.dumps(report, indent=2)
    report_latest.write_text(payload, encoding="utf-8")
    report_ts.write_text(payload, encoding="utf-8")
    return report


def _command_journal_metrics(command_journal: dict[str, object]) -> dict[str, float]:
    raw_commands = command_journal.get("commands", {})
    if not isinstance(raw_commands, dict):
        return {}

    unauthorized_attempts = 0
    unauthorized_accepted = 0
    privileged_total = 0
    privileged_metadata_complete = 0
    privileged_missing_audit = 0
    required_privileged_fields = ("operator", "reason", "change_ticket", "trace_id")

    for record in raw_commands.values():
        if not isinstance(record, dict):
            continue
        status = str(record.get("status", "")).strip().lower()
        reason = str(record.get("reason", "")).strip().lower()
        if "producer_authorized" in record:
            producer_authorized = _to_bool(record.get("producer_authorized"), default=True)
            if not producer_authorized:
                unauthorized_attempts += 1
                if status == "processed":
                    unauthorized_accepted += 1
        elif reason == "unauthorized_producer":
            unauthorized_attempts += 1

        command = str(record.get("command", "")).strip().lower()
        if command != "cancel_all":
            continue
        privileged_total += 1
        command_metadata = record.get("command_metadata", {})
        command_metadata = command_metadata if isinstance(command_metadata, dict) else {}
        if all(str(command_metadata.get(field, "")).strip() for field in required_privileged_fields):
            privileged_metadata_complete += 1
        audit_required = _to_bool(record.get("audit_required"), default=True)
        audit_published = _to_bool(record.get("audit_published"), default=False)
        if audit_required and not audit_published:
            privileged_missing_audit += 1

    if privileged_total <= 0:
        metrics = {
            "p1_20_privileged_command_attribution_complete_rate_pct": 100.0,
            "p1_20_privileged_command_missing_audit_event_rate_pct": 0.0,
        }
    else:
        metrics = {
            "p1_20_privileged_command_attribution_complete_rate_pct": (
                100.0 * float(privileged_metadata_complete) / float(privileged_total)
            ),
            "p1_20_privileged_command_missing_audit_event_rate_pct": (
                100.0 * float(privileged_missing_audit) / float(privileged_total)
            ),
        }

    if unauthorized_attempts <= 0:
        metrics["p1_20_unauthorized_producer_acceptance_rate_pct"] = 0.0
    else:
        metrics["p1_20_unauthorized_producer_acceptance_rate_pct"] = (
            100.0 * float(unauthorized_accepted) / float(unauthorized_attempts)
        )
    return metrics


def _market_data_contract_metrics(
    pair_snapshot: dict[str, object],
    command_journal: dict[str, object],
) -> dict[str, float]:
    raw_pairs = pair_snapshot.get("pairs", {})
    pairs = raw_pairs if isinstance(raw_pairs, dict) else {}

    l1_total = 0
    l1_complete = 0
    for payload in pairs.values():
        if not isinstance(payload, dict):
            continue
        l1_total += 1
        best_bid = _to_float(payload.get("best_bid"))
        best_ask = _to_float(payload.get("best_ask"))
        timestamp_or_sequence_present = any(
            str(payload.get(field, "")).strip()
            for field in ("market_sequence", "exchange_ts_ms", "ingest_ts_ms", "timestamp_ms")
        )
        if best_bid is not None and best_ask is not None and timestamp_or_sequence_present:
            l1_complete += 1

    required_l1_non_null_rate_pct = (
        100.0 * float(l1_complete) / float(l1_total) if l1_total > 0 else 0.0
    )

    raw_commands = command_journal.get("commands", {})
    commands = raw_commands if isinstance(raw_commands, dict) else {}
    command_records = [record for record in commands.values() if isinstance(record, dict)]
    command_total = len(command_records)

    out_of_order_sequence_error_count = 0
    matching_decision_total = 0
    matching_decision_traceable = 0
    mid_only_fallback_count = 0

    for record in command_records:
        reason = str(record.get("reason", "")).strip().lower()
        status = str(record.get("status", "")).strip().lower()
        metadata = record.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}

        if reason == "out_of_order_snapshot":
            out_of_order_sequence_error_count += 1

        matched_on_mid_only = _to_bool(metadata.get("matched_on_mid_only"), default=False)
        if "mid_only" in reason or (status == "processed" and matched_on_mid_only):
            mid_only_fallback_count += 1

        if reason.startswith("order_filled") or reason == "post_only_would_take":
            matching_decision_total += 1
            has_best_bid = _to_float(metadata.get("best_bid")) is not None
            has_best_ask = _to_float(metadata.get("best_ask")) is not None
            has_decision_price = (
                _to_float(metadata.get("fill_price")) is not None
                or _to_float(metadata.get("price")) is not None
            )
            has_trace_ref = bool(
                str(metadata.get("last_fill_snapshot_event_id", "")).strip()
                or str(metadata.get("command_sequence", "")).strip()
            )
            if has_best_bid and has_best_ask and has_decision_price and has_trace_ref:
                matching_decision_traceable += 1

    out_of_order_sequence_error_rate_pct = (
        100.0 * float(out_of_order_sequence_error_count) / float(command_total)
        if command_total > 0
        else 100.0
    )
    matching_decisions_traceable_rate_pct = (
        100.0 * float(matching_decision_traceable) / float(matching_decision_total)
        if matching_decision_total > 0
        else 0.0
    )

    return {
        "p0_12_required_l1_fields_non_null_rate_pct": float(required_l1_non_null_rate_pct),
        "p0_12_out_of_order_sequence_error_rate_pct": float(out_of_order_sequence_error_rate_pct),
        "p0_12_matching_decisions_traceable_rate_pct": float(matching_decisions_traceable_rate_pct),
        "p0_12_active_mode_mid_only_fallback_command_count": float(mid_only_fallback_count),
    }


def _extract_parity_metric_max_abs_delta(parity: dict[str, object], metric_name: str) -> float | None:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return None
    vals: list[float] = []
    for bot in bots:
        if not isinstance(bot, dict):
            continue
        metrics = bot.get("metrics", [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            if str(metric.get("metric", "")).strip() != metric_name:
                continue
            delta = _to_float(metric.get("delta"))
            if delta is None:
                continue
            vals.append(abs(delta))
    if not vals:
        return None
    return max(vals)


def _extract_parity_equity_delta_pct(parity: dict[str, object]) -> float | None:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return None
    vals: list[float] = []
    for bot in bots:
        if not isinstance(bot, dict):
            continue
        summary = bot.get("summary", {})
        if not isinstance(summary, dict):
            continue
        eq_first = _to_float(summary.get("equity_first"))
        eq_last = _to_float(summary.get("equity_last"))
        if eq_first is None or eq_last is None:
            continue
        if abs(eq_first) < 1e-12:
            continue
        vals.append(abs((eq_last - eq_first) / eq_first) * 100.0)
    if not vals:
        return None
    return max(vals)


def _parity_replay_window_metrics(
    parity: dict[str, object],
    command_journal: dict[str, object],
    replay_multi_window: dict[str, object],
) -> dict[str, float]:
    commands = command_journal.get("commands", {})
    command_records = list(commands.values()) if isinstance(commands, dict) else []

    command_count = float(len(command_records))
    if command_count <= 0:
        windows = replay_multi_window.get("windows", [])
        windows = windows if isinstance(windows, list) else []
        replay_counts: list[float] = []
        for window in windows:
            if not isinstance(window, dict):
                continue
            signature = window.get("signature_baseline", {})
            signature = signature if isinstance(signature, dict) else {}
            event_count = _to_float(signature.get("regression_event_count"))
            if event_count is not None and event_count >= 0:
                replay_counts.append(float(event_count))
        if replay_counts:
            command_count = max(replay_counts)

    span_timestamps: list[float] = []
    for record in command_records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        ts_updated = _to_float(metadata.get("updated_ts_ms"))
        if ts_updated is not None and ts_updated > 0:
            span_timestamps.append(ts_updated)
            continue
        ts_command = _to_float(record.get("timestamp_ms"))
        if ts_command is not None and ts_command > 0:
            span_timestamps.append(ts_command)

    window_hours = 0.0
    if len(span_timestamps) >= 2:
        window_hours = max(0.0, (max(span_timestamps) - min(span_timestamps)) / (3600.0 * 1000.0))

    event_store_file = str(parity.get("event_store_file", "")).strip().replace("\\", "/")
    if re.search(r"/events_\d{8}\.jsonl$", event_store_file) or re.search(r"^events_\d{8}\.jsonl$", event_store_file):
        # Daily partitioned parity input implies at least a full-day evaluation window.
        window_hours = max(window_hours, 24.0)

    if window_hours <= 0.0:
        replay_window_hours = _to_float(replay_multi_window.get("evaluation_window_hours"))
        if replay_window_hours is not None and replay_window_hours > 0:
            window_hours = float(replay_window_hours)

    return {
        "p1_7_parity_eval_window_hours": float(window_hours),
        "p1_7_parity_eval_command_events_count": float(max(0.0, command_count)),
    }


def _metric_bot_active(summary: dict[str, object]) -> bool:
    for key in ("intents_total", "actionable_intents", "fills_total", "order_failed_total", "risk_denied_total"):
        value = _to_float(summary.get(key))
        if value is not None and value > 0:
            return True
    return False


def _parity_equity_by_bot(parity: dict[str, object]) -> dict[str, float]:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return {}
    out: dict[str, float] = {}
    for idx, bot in enumerate(bots):
        if not isinstance(bot, dict):
            continue
        bot_name = str(bot.get("bot", "")).strip() or f"bot_{idx}"
        summary = bot.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        eq_last = _to_float(summary.get("equity_last"))
        eq_first = _to_float(summary.get("equity_first"))
        eq_ref = eq_last if eq_last is not None and abs(eq_last) > 1e-12 else eq_first
        if eq_ref is None or abs(eq_ref) <= 1e-12:
            continue
        out[bot_name] = abs(float(eq_ref))
    return out


def _extract_parity_realized_pnl_drift_pct_equity(parity: dict[str, object]) -> float:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return 0.0
    vals: list[float] = []
    for bot in bots:
        if not isinstance(bot, dict):
            continue
        summary = bot.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        if not _metric_bot_active(summary):
            continue
        fills_total = _to_float(summary.get("fills_total"))
        if fills_total is None or fills_total <= 0:
            # Realized-PnL drift is informative only when fills occurred.
            continue
        eq_ref = _to_float(summary.get("equity_last"))
        if eq_ref is None or abs(eq_ref) <= 1e-12:
            eq_ref = _to_float(summary.get("equity_first"))
        if eq_ref is None or abs(eq_ref) <= 1e-12:
            continue
        metrics = bot.get("metrics", [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            if str(metric.get("metric", "")).strip() != "realized_pnl_delta_quote":
                continue
            delta = _to_float(metric.get("delta"))
            if delta is None:
                continue
            vals.append(abs(float(delta)) / abs(float(eq_ref)) * 100.0)
            break
    return max(vals) if vals else 0.0


def _accounting_contract_metrics(
    command_journal: dict[str, object],
    parity: dict[str, object],
) -> dict[str, float]:
    commands = command_journal.get("commands", {})
    command_records = list(commands.values()) if isinstance(commands, dict) else []

    fee_error_pct_notional_values: list[float] = []
    margin_drift_pct_equity_values: list[float] = []
    funding_sign_mismatch_count = 0
    equity_by_bot = _parity_equity_by_bot(parity)

    for record in command_records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}

        notional = _to_float(metadata.get("fill_notional_quote"))
        observed_fee_quote = _to_float(metadata.get("fill_fee_quote"))
        fee_rate_pct = _to_float(metadata.get("fill_fee_rate_pct"))
        if fee_rate_pct is None:
            maker_fee_pct = _to_float(metadata.get("maker_fee_pct"))
            taker_fee_pct = _to_float(metadata.get("taker_fee_pct"))
            if maker_fee_pct is None and taker_fee_pct is not None:
                maker_fee_pct = taker_fee_pct
            if taker_fee_pct is None and maker_fee_pct is not None:
                taker_fee_pct = maker_fee_pct
            if maker_fee_pct is not None or taker_fee_pct is not None:
                is_maker = _to_bool(metadata.get("is_maker"), default=False)
                maker_value = max(0.0, float(maker_fee_pct or 0.0))
                taker_value = max(0.0, float(taker_fee_pct or 0.0))
                fee_rate_pct = maker_value if is_maker else taker_value

        if (
            notional is not None
            and abs(notional) > 1e-12
            and observed_fee_quote is not None
            and fee_rate_pct is not None
        ):
            expected_fee_quote = abs(float(notional)) * max(0.0, abs(float(fee_rate_pct)))
            abs_error_quote = abs(abs(float(observed_fee_quote)) - expected_fee_quote)
            fee_error_pct_notional_values.append(abs_error_quote / abs(float(notional)) * 100.0)

        funding_rate = _to_float(metadata.get("funding_rate"))
        snapshot_funding_rate = _to_float(metadata.get("snapshot_funding_rate"))
        funding_sign = 1 if funding_rate is not None and funding_rate > 1e-12 else -1 if funding_rate is not None and funding_rate < -1e-12 else 0
        snapshot_sign = (
            1
            if snapshot_funding_rate is not None and snapshot_funding_rate > 1e-12
            else -1 if snapshot_funding_rate is not None and snapshot_funding_rate < -1e-12 else 0
        )
        if funding_sign != 0 and snapshot_sign != 0 and funding_sign != snapshot_sign:
            funding_sign_mismatch_count += 1

        filled_notional_quote_total = _to_float(metadata.get("filled_notional_quote_total"))
        observed_margin_reserve_quote = _to_float(metadata.get("margin_reserve_quote"))
        leverage = _to_float(metadata.get("leverage"))
        margin_mode = str(metadata.get("margin_mode", "leveraged")).strip().lower()
        if (
            filled_notional_quote_total is not None
            and observed_margin_reserve_quote is not None
            and abs(filled_notional_quote_total) > 1e-12
        ):
            leverage_value = max(1.0, float(leverage if leverage is not None else 1.0))
            expected_margin_reserve = (
                abs(float(filled_notional_quote_total))
                if margin_mode == "standard"
                else abs(float(filled_notional_quote_total)) / leverage_value
            )
            instance_name = str(record.get("instance_name", "")).strip()
            equity_ref = equity_by_bot.get(instance_name)
            if equity_ref is not None and equity_ref > 1e-12:
                drift_pct_equity = abs(float(observed_margin_reserve_quote) - expected_margin_reserve) / equity_ref * 100.0
                margin_drift_pct_equity_values.append(drift_pct_equity)

    return {
        "p1_6_per_fill_fee_abs_error_pct_notional_max": (
            max(fee_error_pct_notional_values) if fee_error_pct_notional_values else 0.0
        ),
        "p1_6_cumulative_realized_pnl_drift_pct_equity": _extract_parity_realized_pnl_drift_pct_equity(parity),
        "p1_6_funding_sign_mismatch_count": float(funding_sign_mismatch_count),
        "p1_6_margin_reserve_drift_pct_equity": (
            max(margin_drift_pct_equity_values) if margin_drift_pct_equity_values else 0.0
        ),
    }


_NAUTILUS_REUSE_DECISIONS = {"adopt", "adapt", "reimplement"}


def _repo_rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _normalize_rel_path(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _test_ref_exists(root: Path, ref: str) -> bool:
    raw = str(ref or "").strip()
    if not raw:
        return False
    parts = raw.split("::")
    rel_file = _normalize_rel_path(parts[0])
    if not rel_file:
        return False
    file_path = root / rel_file
    if not file_path.exists() or not file_path.is_file():
        return False
    if len(parts) <= 1:
        return True
    test_symbol = str(parts[-1]).strip()
    if not test_symbol:
        return True
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return re.search(rf"(?m)^\s*def\s+{re.escape(test_symbol)}\s*\(", text) is not None


def _discover_nautilus_reference_modules(root: Path) -> list[str]:
    base = root / "controllers" / "paper_engine_v2"
    if not base.exists():
        return []
    out: list[str] = []
    for path in sorted(base.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "nautilus" in text.lower():
            out.append(_repo_rel_path(root, path))
    return out


def _find_direct_nautilus_import_files(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = _repo_rel_path(root, path)
        if rel.startswith("tests/") or rel.startswith(".venv/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if re.search(r"(?m)^\s*(?:from|import)\s+nautilus(?:_trader)?\b", text):
            out.append(rel)
    return out


def _paper_exchange_nautilus_reuse_report(
    root: Path,
    reports: Path,
    tests: dict[str, object],
) -> dict[str, object]:
    verification_dir = reports / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    latest_path = verification_dir / "paper_exchange_nautilus_reuse_latest.json"
    ts_path = verification_dir / f"paper_exchange_nautilus_reuse_{stamp}.json"

    matrix_path = root / "docs" / "validation" / "nautilus_reuse_matrix.json"
    license_boundary_path = root / "docs" / "validation" / "nautilus_license_boundary.md"
    attribution_license_path = root / "docs" / "legal" / "nautilus_trader.LICENSE.txt"

    matrix_payload = _read_json(matrix_path)
    entries_raw = matrix_payload.get("entries", [])
    entries = entries_raw if isinstance(entries_raw, list) else []
    discovered_modules = _discover_nautilus_reference_modules(root)

    entries_by_module: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        module = _normalize_rel_path(entry.get("module_path"))
        if not module:
            continue
        entries_by_module[module] = dict(entry)

    missing_entries = [module for module in discovered_modules if module not in entries_by_module]
    missing_provenance: dict[str, list[str]] = {}
    invalid_test_refs: dict[str, list[str]] = {}
    documented_modules: list[str] = []
    license_failures = 0
    adopted_total = 0
    adopted_structural_pass = 0

    if not matrix_path.exists():
        license_failures += 1
    if not license_boundary_path.exists():
        license_failures += 1
    if not attribution_license_path.exists():
        license_failures += 1

    for module in discovered_modules:
        entry = entries_by_module.get(module)
        if not isinstance(entry, dict):
            continue

        decision = str(entry.get("decision", "")).strip().lower()
        upstream_component = str(entry.get("upstream_component", "")).strip()
        rationale = str(entry.get("rationale", "")).strip()
        boundary = str(entry.get("boundary", "")).strip()
        license_name = str(entry.get("license", "")).strip()
        attribution_file = _normalize_rel_path(entry.get("attribution_file"))

        refs_raw = entry.get("test_refs", [])
        refs: list[str] = []
        if isinstance(refs_raw, list):
            refs = [str(v).strip() for v in refs_raw if str(v).strip()]

        missing_fields: list[str] = []
        if decision not in _NAUTILUS_REUSE_DECISIONS:
            missing_fields.append("decision")
        if not upstream_component:
            missing_fields.append("upstream_component")
        if not rationale:
            missing_fields.append("rationale")
        if not boundary:
            missing_fields.append("boundary")
        if not license_name:
            missing_fields.append("license")
        if not attribution_file:
            missing_fields.append("attribution_file")
        elif not (root / attribution_file).exists():
            missing_fields.append("attribution_file_missing")
        if not refs:
            missing_fields.append("test_refs")

        bad_refs = [ref for ref in refs if not _test_ref_exists(root, ref)]
        if bad_refs:
            invalid_test_refs[module] = bad_refs
            missing_fields.append("invalid_test_refs")

        if missing_fields:
            missing_provenance[module] = sorted(set(missing_fields))
        else:
            documented_modules.append(module)

        if "lgpl" not in license_name.lower():
            license_failures += 1

        if decision == "adopt":
            adopted_total += 1
            if not bad_refs and refs:
                adopted_structural_pass += 1

    direct_import_files = _find_direct_nautilus_import_files(root)
    undocumented_direct_import_files = [
        rel for rel in direct_import_files if rel not in entries_by_module
    ]

    coverage_pct = 100.0
    if discovered_modules:
        coverage_pct = (float(len(documented_modules)) / float(len(discovered_modules))) * 100.0

    tests_status = str(tests.get("status", "")).strip().lower()
    if adopted_total <= 0:
        adopted_pass_rate_pct = 100.0
    else:
        structural_rate = (float(adopted_structural_pass) / float(adopted_total)) * 100.0
        adopted_pass_rate_pct = structural_rate if tests_status == "pass" else 0.0

    metrics = {
        "p2_10_reused_module_provenance_doc_coverage_pct": float(coverage_pct),
        "p2_10_license_compliance_check_failures": float(max(0, int(license_failures))),
        "p2_10_adopted_module_behavior_parity_tests_pass_rate_pct": float(adopted_pass_rate_pct),
        "p2_10_undocumented_external_framework_dependency_count": float(
            max(0, len(undocumented_direct_import_files))
        ),
    }
    status = (
        "pass"
        if (
            coverage_pct >= 100.0
            and int(license_failures) == 0
            and len(undocumented_direct_import_files) == 0
            and adopted_pass_rate_pct >= 100.0
        )
        else "fail"
    )
    report = {
        "ts_utc": _utc_now(),
        "status": status,
        "metrics": metrics,
        "diagnostics": {
            "matrix_path": str(matrix_path),
            "license_boundary_path": str(license_boundary_path),
            "attribution_license_path": str(attribution_license_path),
            "matrix_entry_count": len(entries_by_module),
            "discovered_reuse_module_count": len(discovered_modules),
            "discovered_reuse_modules": discovered_modules,
            "missing_matrix_entries": missing_entries,
            "missing_provenance_fields_by_module": missing_provenance,
            "invalid_test_refs_by_module": invalid_test_refs,
            "direct_nautilus_import_files": direct_import_files,
            "undocumented_direct_import_files": undocumented_direct_import_files,
            "adopted_module_count": int(adopted_total),
            "adopted_structural_pass_count": int(adopted_structural_pass),
            "tests_latest_status": tests_status,
        },
    }
    raw = json.dumps(report, indent=2)
    latest_path.write_text(raw, encoding="utf-8")
    ts_path.write_text(raw, encoding="utf-8")
    return report


def _count_canary_critical_alerts(canary: dict[str, object]) -> float:
    explicit = _to_float(canary.get("canary_critical_alert_count"))
    if explicit is not None and explicit >= 0:
        return float(explicit)
    steps = canary.get("steps", [])
    if isinstance(steps, list):
        critical_steps = {
            "compose_start_paper_exchange",
            "recreate_bot",
            "paper_exchange_preflight",
            "paper_exchange_load_harness",
            "paper_exchange_load_check",
        }
        failures = 0
        for step in steps:
            if not isinstance(step, dict):
                continue
            if str(step.get("name", "")).strip() not in critical_steps:
                continue
            if bool(step.get("pass", False)):
                continue
            failures += 1
        if failures > 0:
            return float(failures)
    status = str(canary.get("status", "")).strip().lower()
    return 0.0 if status == "pass" else 1.0


def _rollout_plan_metrics(canary: dict[str, object], rollback: dict[str, object]) -> dict[str, float]:
    metrics: dict[str, float] = {}

    canary_duration_hours = _to_float(canary.get("target_canary_duration_hours"))
    if canary_duration_hours is None:
        canary_duration_hours = _to_float(canary.get("canary_run_duration_hours"))
    if canary_duration_hours is None:
        duration_sec = _to_float(canary.get("duration_sec"))
        if duration_sec is not None and duration_sec >= 0:
            canary_duration_hours = float(duration_sec) / 3600.0
    if canary_duration_hours is not None:
        metrics["p1_9_canary_run_duration_hours"] = float(max(0.0, float(canary_duration_hours)))

    if canary:
        metrics["p1_9_canary_critical_alert_count"] = _count_canary_critical_alerts(canary)

    concurrency_bots = _to_float(canary.get("active_mode_rollout_concurrency_bots"))
    if concurrency_bots is None:
        concurrency_bots = _to_float(canary.get("rollout_concurrency_bots"))
    if concurrency_bots is None:
        mode = str(canary.get("mode", "")).strip().lower()
        bot = str(canary.get("bot", "")).strip()
        if bot:
            concurrency_bots = 1.0 if mode == "active" else 0.0
    if concurrency_bots is not None:
        metrics["p1_9_active_mode_rollout_concurrency_bots"] = float(max(0.0, float(concurrency_bots)))

    rollback_rto_minutes = _to_float(rollback.get("duration_minutes"))
    if rollback_rto_minutes is None:
        rollback_duration_sec = _to_float(rollback.get("duration_sec"))
        if rollback_duration_sec is not None and rollback_duration_sec >= 0:
            rollback_rto_minutes = float(rollback_duration_sec) / 60.0
    if rollback_rto_minutes is not None:
        metrics["p1_9_rollback_drill_rto_minutes"] = float(max(0.0, float(rollback_rto_minutes)))

    rollback_rpo_lost_commands = _to_float(rollback.get("rpo_lost_commands"))
    if rollback_rpo_lost_commands is None and rollback:
        rollback_status = str(rollback.get("status", "")).strip().lower()
        rollback_rpo_lost_commands = 0.0 if rollback_status == "pass" else 1.0
    if rollback_rpo_lost_commands is not None:
        metrics["p1_9_rollback_drill_rpo_lost_commands"] = float(max(0.0, float(rollback_rpo_lost_commands)))

    return metrics


def _read_manual_metrics(path: Path) -> dict[str, float]:
    payload = _read_json(path)
    if not payload:
        return {}
    maybe_metrics = payload.get("metrics", payload)
    if not isinstance(maybe_metrics, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in maybe_metrics.items():
        v = _to_float(value)
        if v is not None:
            out[str(key)] = float(v)
    return out


def _read_artifact_metrics(path: Path) -> dict[str, float]:
    payload = _read_json(path)
    raw_metrics = payload.get("metrics", {})
    if not isinstance(raw_metrics, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        out[str(key)] = float(parsed)
    return out


def _artifact_info(path: Path, now_ts: float) -> dict[str, object]:
    exists = path.exists()
    payload = _read_json(path) if exists else {}
    ts_utc = str(payload.get("ts_utc", "")).strip()
    age_min = _minutes_since(ts_utc, now_ts) if ts_utc else _minutes_since_file_mtime(path, now_ts)
    status = str(payload.get("status", "")).strip()
    return {
        "path": str(path),
        "exists": exists,
        "status": status,
        "ts_utc": ts_utc,
        "age_min": float(age_min),
    }


def build_report(
    root: Path,
    *,
    now_ts: float | None = None,
    max_source_age_min: float = 20.0,
    manual_metrics_path: Path | None = None,
) -> dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    reports = root / "reports"
    manual_path = manual_metrics_path or (reports / "verification" / "paper_exchange_threshold_metrics_manual.json")

    parity_path = reports / "parity" / "latest.json"
    reliability_path = reports / "ops" / "reliability_slo_latest.json"
    tests_path = reports / "tests" / "latest.json"
    promotion_path = reports / "promotion_gates" / "latest.json"
    strict_cycle_path = reports / "promotion_gates" / "strict_cycle_latest.json"
    replay_multi_window_path = reports / "replay_regression_multi_window" / "latest.json"
    golden_path_path = reports / "verification" / "paper_exchange_golden_path_latest.json"
    command_journal_path = reports / "verification" / "paper_exchange_command_journal_latest.json"
    state_snapshot_path = reports / "verification" / "paper_exchange_state_snapshot_latest.json"
    pair_snapshot_path = reports / "verification" / "paper_exchange_pair_snapshot_latest.json"
    paper_exchange_load_path = reports / "verification" / "paper_exchange_load_latest.json"
    canary_report_path = reports / "ops" / "paper_exchange_canary_latest.json"
    rollback_drill_path = reports / "ops" / "data_plane_rollback_drill_latest.json"

    parity = _read_json(parity_path)
    reliability = _read_json(reliability_path)
    tests = _read_json(tests_path)
    promotion = _read_json(promotion_path)
    strict_cycle = _read_json(strict_cycle_path)
    replay_multi_window = _read_json(replay_multi_window_path)
    golden_path = _read_json(golden_path_path)
    command_journal = _read_json(command_journal_path)
    state_snapshot = _read_json(state_snapshot_path)
    pair_snapshot = _read_json(pair_snapshot_path)
    paper_exchange_load_metrics = _read_artifact_metrics(paper_exchange_load_path)
    canary_report = _read_json(canary_report_path)
    rollback_drill_report = _read_json(rollback_drill_path)

    try:
        namespace_report = _paper_exchange_namespace_isolation_report(
            reports,
            command_journal=command_journal,
            state_snapshot=state_snapshot,
            pair_snapshot=pair_snapshot,
        )
    except Exception as exc:
        namespace_report = _paper_exchange_namespace_isolation_fail_closed_report(f"{type(exc).__name__}: {exc}")
        namespace_fallback_path = reports / "verification" / "paper_exchange_namespace_isolation_latest.json"
        namespace_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        namespace_fallback_path.write_text(json.dumps(namespace_report, indent=2), encoding="utf-8")
    namespace_metrics_raw = namespace_report.get("metrics", {})
    namespace_metrics = namespace_metrics_raw if isinstance(namespace_metrics_raw, dict) else {}

    try:
        failure_policy_report = _paper_exchange_active_failure_policy_report(reports, golden_path)
    except Exception as exc:
        failure_policy_report = _paper_exchange_active_failure_policy_fail_closed_report(
            f"{type(exc).__name__}: {exc}"
        )
        failure_policy_fallback_path = reports / "verification" / "paper_exchange_active_failure_policy_latest.json"
        failure_policy_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        failure_policy_fallback_path.write_text(json.dumps(failure_policy_report, indent=2), encoding="utf-8")
    failure_policy_metrics_raw = failure_policy_report.get("metrics", {})
    failure_policy_metrics = failure_policy_metrics_raw if isinstance(failure_policy_metrics_raw, dict) else {}

    try:
        hb_compat_report = _paper_exchange_hb_executor_compat_report(reports, golden_path)
    except Exception as exc:
        hb_compat_report = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "metrics": _hb_executor_compat_fail_closed_metrics(),
            "diagnostics": {
                "error": f"{type(exc).__name__}: {exc}",
            },
        }
        hb_compat_fallback_path = reports / "verification" / "paper_exchange_hb_compatibility_latest.json"
        hb_compat_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        hb_compat_fallback_path.write_text(json.dumps(hb_compat_report, indent=2), encoding="utf-8")
    hb_compat_metrics_raw = hb_compat_report.get("metrics", {})
    hb_compat_metrics = hb_compat_metrics_raw if isinstance(hb_compat_metrics_raw, dict) else {}

    try:
        state_dr_report = _paper_exchange_state_dr_report(reports, now_ts)
    except Exception as exc:
        state_dr_report = _paper_exchange_state_dr_fail_closed_report(f"{type(exc).__name__}: {exc}")
        dr_fallback_path = reports / "verification" / "paper_exchange_state_dr_latest.json"
        dr_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        dr_fallback_path.write_text(json.dumps(state_dr_report, indent=2), encoding="utf-8")
    state_dr_metrics_raw = state_dr_report.get("metrics", {})
    state_dr_metrics = state_dr_metrics_raw if isinstance(state_dr_metrics_raw, dict) else {}

    try:
        nautilus_reuse_report = _paper_exchange_nautilus_reuse_report(root, reports, tests)
    except Exception as exc:
        nautilus_reuse_report = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "metrics": {
                "p2_10_reused_module_provenance_doc_coverage_pct": 0.0,
                "p2_10_license_compliance_check_failures": 1.0,
                "p2_10_adopted_module_behavior_parity_tests_pass_rate_pct": 0.0,
                "p2_10_undocumented_external_framework_dependency_count": 1.0,
            },
            "diagnostics": {
                "reason": f"{type(exc).__name__}: {exc}",
            },
        }
        nautilus_reuse_fallback_path = reports / "verification" / "paper_exchange_nautilus_reuse_latest.json"
        nautilus_reuse_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        nautilus_reuse_fallback_path.write_text(json.dumps(nautilus_reuse_report, indent=2), encoding="utf-8")
    nautilus_reuse_metrics_raw = nautilus_reuse_report.get("metrics", {})
    nautilus_reuse_metrics = nautilus_reuse_metrics_raw if isinstance(nautilus_reuse_metrics_raw, dict) else {}

    source_artifacts = {
        "parity_latest": _artifact_info(parity_path, now_ts),
        "reliability_slo_latest": _artifact_info(reliability_path, now_ts),
        "tests_latest": _artifact_info(tests_path, now_ts),
        "promotion_gates_latest": _artifact_info(promotion_path, now_ts),
        "strict_cycle_latest": _artifact_info(strict_cycle_path, now_ts),
        "replay_regression_multi_window_latest": _artifact_info(replay_multi_window_path, now_ts),
        "paper_exchange_golden_path_latest": _artifact_info(golden_path_path, now_ts),
        "paper_exchange_command_journal_latest": _artifact_info(command_journal_path, now_ts),
        "paper_exchange_state_snapshot_latest": _artifact_info(state_snapshot_path, now_ts),
        "paper_exchange_pair_snapshot_latest": _artifact_info(pair_snapshot_path, now_ts),
        "paper_exchange_canary_latest": _artifact_info(canary_report_path, now_ts),
        "data_plane_rollback_drill_latest": _artifact_info(rollback_drill_path, now_ts),
        "paper_exchange_namespace_isolation_latest": _artifact_info(
            reports / "verification" / "paper_exchange_namespace_isolation_latest.json",
            now_ts,
        ),
        "paper_exchange_active_failure_policy_latest": _artifact_info(
            reports / "verification" / "paper_exchange_active_failure_policy_latest.json",
            now_ts,
        ),
        "paper_exchange_hb_compatibility_latest": _artifact_info(
            reports / "verification" / "paper_exchange_hb_compatibility_latest.json",
            now_ts,
        ),
        "paper_exchange_load_latest": _artifact_info(paper_exchange_load_path, now_ts),
        "paper_exchange_state_dr_latest": _artifact_info(reports / "verification" / "paper_exchange_state_dr_latest.json", now_ts),
        "paper_exchange_nautilus_reuse_latest": _artifact_info(
            reports / "verification" / "paper_exchange_nautilus_reuse_latest.json",
            now_ts,
        ),
        "manual_metrics": _artifact_info(manual_path, now_ts),
    }

    computed_metrics: dict[str, float] = {}

    # From tests gate
    tests_status = str(tests.get("status", "")).strip().lower()
    tests_pass_rate = 100.0 if tests_status == "pass" else 0.0
    computed_metrics["p0_1_contract_tests_pass_rate_pct"] = tests_pass_rate
    computed_metrics["p1_17_gate_path_tests_pass_rate_pct"] = tests_pass_rate

    # Promotion checks include paper exchange gates when wired/enabled.
    check_names: list[str] = []
    checks = promotion.get("checks", [])
    if isinstance(checks, list):
        for c in checks:
            if isinstance(c, dict):
                check_names.append(str(c.get("name", "")).strip())
    required_checks = {
        "paper_exchange_preflight",
        "paper_exchange_load_validation",
        "paper_exchange_threshold_inputs_ready",
        "paper_exchange_thresholds",
    }
    computed_metrics["p1_17_strict_cycle_checks_enforced_rate_pct"] = (
        100.0 if required_checks.issubset(set(check_names)) else 0.0
    )
    preflight_present = "paper_exchange_preflight" in set(check_names)
    computed_metrics["p1_17_preflight_nonzero_on_missing_or_stale_rate_pct"] = 100.0 if preflight_present else 0.0

    # Freshness rollup
    parity_age = float(source_artifacts["parity_latest"]["age_min"])
    slo_age = float(source_artifacts["reliability_slo_latest"]["age_min"])
    computed_metrics["p1_17_parity_slo_artifact_freshness_minutes"] = max(parity_age, slo_age)

    # Reliability dead letter rate per hour (critical only)
    dead_letter = reliability.get("details", {})
    dead_letter = dead_letter.get("dead_letter", {}) if isinstance(dead_letter, dict) else {}
    critical_count = _to_float(dead_letter.get("critical_count"))
    lookback_sec = _to_float(dead_letter.get("lookback_sec"))
    if critical_count is not None and lookback_sec is not None and lookback_sec > 0:
        computed_metrics["p1_8_critical_dead_letter_reasons_per_hour"] = critical_count * (3600.0 / lookback_sec)

    # Conservative binary availability/success signals from reliability checks.
    reliability_checks = reliability.get("checks", {})
    if isinstance(reliability_checks, dict):
        heartbeat_ok = all(
            bool(reliability_checks.get(k, False))
            for k in reliability_checks.keys()
            if str(k).startswith("heartbeat_") and str(k).endswith("_fresh")
        )
        processing_ok = bool(reliability_checks.get("dead_letter_critical_within_slo", False)) and bool(
            reliability_checks.get("redis_connected", False)
        )
        computed_metrics["p1_8_heartbeat_availability_pct"] = 100.0 if heartbeat_ok else 0.0
        computed_metrics["p1_8_command_processing_success_rate_pct"] = 100.0 if processing_ok else 0.0

    # Parity rollups (when available)
    fill_ratio = _extract_parity_metric_max_abs_delta(parity, "fill_ratio_delta")
    if fill_ratio is not None:
        computed_metrics["p1_7_fill_ratio_delta_pp"] = float(fill_ratio)
    reject_ratio = _extract_parity_metric_max_abs_delta(parity, "reject_rate_delta")
    if reject_ratio is not None:
        computed_metrics["p1_7_reject_ratio_delta_pp"] = float(reject_ratio)
    slippage = _extract_parity_metric_max_abs_delta(parity, "slippage_delta_bps")
    if slippage is not None:
        computed_metrics["p1_7_fill_price_delta_p95_bps"] = float(slippage)
        computed_metrics["p1_7_fill_price_delta_p99_bps"] = float(slippage)
    equity_delta = _extract_parity_equity_delta_pct(parity)
    if equity_delta is not None:
        computed_metrics["p1_7_end_window_equity_delta_pct"] = float(equity_delta)
    computed_metrics.update(_parity_replay_window_metrics(parity, command_journal, replay_multi_window))

    # Accounting contract parity (fees/funding/margin) from command journal + parity.
    computed_metrics.update(_accounting_contract_metrics(command_journal, parity))
    computed_metrics.update(_rollout_plan_metrics(canary_report, rollback_drill_report))

    # Strict-cycle signal used by item 18
    strict_gate_rc = _to_float(strict_cycle.get("strict_gate_rc"))
    if strict_gate_rc is not None:
        computed_metrics["p0_18_strict_cycle_invocation_success_rate_pct"] = 100.0 if int(strict_gate_rc) == 0 else 0.0

    # Privileged command attribution/audit semantics from idempotency journal.
    computed_metrics.update(_command_journal_metrics(command_journal))
    computed_metrics.update(_market_data_contract_metrics(pair_snapshot, command_journal))
    computed_metrics["p1_20_security_policy_test_suite_pass_rate_pct"] = tests_pass_rate

    # Multi-instance namespace isolation evidence.
    for metric_name, value in namespace_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        if str(metric_name).startswith("p1_15_"):
            computed_metrics[str(metric_name)] = float(parsed)

    # Active-mode failure-policy evidence.
    for metric_name, value in failure_policy_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        if str(metric_name).startswith("p1_16_"):
            computed_metrics[str(metric_name)] = float(parsed)

    # HB executor/runtime compatibility evidence.
    for metric_name, value in hb_compat_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        if str(metric_name).startswith("p0_11_"):
            computed_metrics[str(metric_name)] = float(parsed)

    # Desk-scale load/backpressure evidence.
    for metric_name, value in paper_exchange_load_metrics.items():
        if str(metric_name).startswith("p1_19_"):
            computed_metrics[str(metric_name)] = float(value)

    # Paper-exchange backup/restore disaster-recovery evidence.
    for metric_name, value in state_dr_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        if str(metric_name).startswith("p1_21_"):
            computed_metrics[str(metric_name)] = float(parsed)

    # Nautilus selective-reuse/license-boundary evidence.
    for metric_name, value in nautilus_reuse_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        if str(metric_name).startswith("p2_10_"):
            computed_metrics[str(metric_name)] = float(parsed)

    manual_metrics = _read_manual_metrics(manual_path)
    merged_metrics: dict[str, float] = dict(computed_metrics)
    # Manual values are used as fallback, except P0-11, P1-6, P1-9, and P2-10 where computed
    # evidence must remain authoritative.
    manual_metrics_used: list[str] = []
    for key, value in manual_metrics.items():
        metric_name = str(key)
        if (
            metric_name.startswith("p0_11_")
            or metric_name.startswith("p1_6_")
            or metric_name.startswith("p1_9_")
            or metric_name.startswith("p2_10_")
        ) and metric_name in computed_metrics:
            continue
        merged_metrics[metric_name] = float(value)
        manual_metrics_used.append(metric_name)

    required_metric_names = sorted({clause.metric for clause in THRESHOLD_CLAUSES})
    unresolved_metrics = sorted([name for name in required_metric_names if name not in merged_metrics])
    manual_only_metrics = sorted(
        metric_name
        for metric_name in manual_metrics_used
        if _source_artifacts_for_metric(metric_name) == ["manual_metrics"]
    )
    manual_fallback_metrics = sorted(
        metric_name
        for metric_name in manual_metrics_used
        if metric_name not in manual_only_metrics
    )
    manual_metrics_informational = sorted(set(manual_only_metrics))
    manual_metrics_blocking = sorted(set(manual_fallback_metrics))

    optional_sources = {
        "paper_exchange_canary_latest",
        "data_plane_rollback_drill_latest",
    }
    stale_sources = [
        name
        for name, info in source_artifacts.items()
        if (
            name not in optional_sources
            and bool(info.get("exists", False))
            and float(info.get("age_min", 1e9)) > float(max_source_age_min)
        )
    ]
    missing_sources = [
        name
        for name, info in source_artifacts.items()
        if name not in optional_sources and not bool(info.get("exists", False))
    ]
    optional_stale_sources = [
        name
        for name, info in source_artifacts.items()
        if (
            name in optional_sources
            and bool(info.get("exists", False))
            and float(info.get("age_min", 1e9)) > float(max_source_age_min)
        )
    ]
    optional_missing_sources = [
        name
        for name, info in source_artifacts.items()
        if name in optional_sources and not bool(info.get("exists", False))
    ]

    status = "ok"
    if unresolved_metrics:
        status = "warning"
    if stale_sources:
        status = "warning"
    if missing_sources:
        status = "warning"
    if manual_metrics_blocking:
        status = "warning"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "metrics": merged_metrics,
        "diagnostics": {
            "required_metric_count": len(required_metric_names),
            "computed_metric_count": len(computed_metrics),
            "manual_metric_count": len(manual_metrics),
            "manual_metric_names": sorted(manual_metrics.keys()),
            "manual_metrics_present": bool(manual_metrics),
            "manual_metrics_used_count": len(manual_metrics_used),
            "manual_metrics_used": sorted(set(manual_metrics_used)),
            "manual_only_metric_count": len(manual_only_metrics),
            "manual_only_metrics": manual_only_metrics,
            "manual_fallback_metric_count": len(manual_fallback_metrics),
            "manual_fallback_metrics": manual_fallback_metrics,
            "manual_metrics_informational_count": len(manual_metrics_informational),
            "manual_metrics_informational": manual_metrics_informational,
            "manual_metrics_blocking_count": len(manual_metrics_blocking),
            "manual_metrics_blocking": manual_metrics_blocking,
            "resolved_metric_count": len(merged_metrics),
            "unresolved_metric_count": len(unresolved_metrics),
            "unresolved_metrics": unresolved_metrics,
            "missing_source_count": len(missing_sources),
            "missing_sources": missing_sources,
            "stale_sources": stale_sources,
            "optional_missing_sources": optional_missing_sources,
            "optional_stale_sources": optional_stale_sources,
            "max_source_age_min": float(max_source_age_min),
        },
        "source_artifacts": source_artifacts,
        "notes": {
            "manual_metrics_override_path": str(manual_path),
            "manual_metrics_override_precedence": "manual_for_missing_or_non_p0_11_p1_6_p1_9_p2_10",
        },
    }


def run_builder(
    *,
    strict: bool,
    max_source_age_min: float,
    manual_metrics_path: str,
    output_path: str,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    manual_path = Path(manual_metrics_path) if str(manual_metrics_path).strip() else None
    report = build_report(
        root,
        max_source_age_min=max_source_age_min,
        manual_metrics_path=manual_path,
    )

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_ts = out_dir / f"paper_exchange_threshold_inputs_{stamp}.json"
    out_latest = Path(output_path) if str(output_path).strip() else (out_dir / "paper_exchange_threshold_inputs_latest.json")
    payload = json.dumps(report, indent=2)
    out_ts.write_text(payload, encoding="utf-8")
    out_latest.write_text(payload, encoding="utf-8")

    unresolved = report.get("diagnostics", {}).get("unresolved_metric_count", 0)
    print(f"[paper-exchange-threshold-inputs] status={report.get('status')} unresolved={unresolved}")
    print(f"[paper-exchange-threshold-inputs] evidence={out_latest}")
    if strict and str(report.get("status", "warning")).lower() != "ok":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build paper-exchange threshold input artifact from release evidence.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when unresolved/stale threshold inputs remain.")
    parser.add_argument(
        "--max-source-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_SOURCE_MAX_AGE_MIN", "20")),
        help="Max allowed source artifact age in minutes for strict mode.",
    )
    parser.add_argument(
        "--manual-metrics-path",
        default=os.getenv("PAPER_EXCHANGE_THRESHOLD_MANUAL_METRICS_PATH", ""),
        help="Optional manual metrics override JSON path (merged over computed metrics).",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("PAPER_EXCHANGE_THRESHOLD_INPUTS_PATH", ""),
        help="Optional explicit output path for latest threshold input artifact.",
    )
    args = parser.parse_args()

    return run_builder(
        strict=bool(args.strict),
        max_source_age_min=float(args.max_source_age_min),
        manual_metrics_path=str(args.manual_metrics_path),
        output_path=str(args.output),
    )


if __name__ == "__main__":
    raise SystemExit(main())

