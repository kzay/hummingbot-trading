#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from scripts.release.check_paper_exchange_thresholds import THRESHOLD_CLAUSES


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


def _command_journal_metrics(command_journal: Dict[str, object]) -> Dict[str, float]:
    raw_commands = command_journal.get("commands", {})
    if not isinstance(raw_commands, dict):
        return {}

    privileged_total = 0
    privileged_metadata_complete = 0
    privileged_missing_audit = 0
    required_privileged_fields = ("operator", "reason", "change_ticket", "trace_id")

    for record in raw_commands.values():
        if not isinstance(record, dict):
            continue
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
        return {
            "p1_20_privileged_command_attribution_complete_rate_pct": 100.0,
            "p1_20_privileged_command_missing_audit_event_rate_pct": 0.0,
        }

    return {
        "p1_20_privileged_command_attribution_complete_rate_pct": (
            100.0 * float(privileged_metadata_complete) / float(privileged_total)
        ),
        "p1_20_privileged_command_missing_audit_event_rate_pct": (
            100.0 * float(privileged_missing_audit) / float(privileged_total)
        ),
    }


def _extract_parity_metric_max_abs_delta(parity: Dict[str, object], metric_name: str) -> Optional[float]:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return None
    vals: List[float] = []
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


def _extract_parity_equity_delta_pct(parity: Dict[str, object]) -> Optional[float]:
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return None
    vals: List[float] = []
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


def _read_manual_metrics(path: Path) -> Dict[str, float]:
    payload = _read_json(path)
    if not payload:
        return {}
    maybe_metrics = payload.get("metrics", payload)
    if not isinstance(maybe_metrics, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in maybe_metrics.items():
        v = _to_float(value)
        if v is not None:
            out[str(key)] = float(v)
    return out


def _read_artifact_metrics(path: Path) -> Dict[str, float]:
    payload = _read_json(path)
    raw_metrics = payload.get("metrics", {})
    if not isinstance(raw_metrics, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw_metrics.items():
        parsed = _to_float(value)
        if parsed is None:
            continue
        out[str(key)] = float(parsed)
    return out


def _artifact_info(path: Path, now_ts: float) -> Dict[str, object]:
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
    now_ts: Optional[float] = None,
    max_source_age_min: float = 20.0,
    manual_metrics_path: Optional[Path] = None,
) -> Dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    reports = root / "reports"
    manual_path = manual_metrics_path or (reports / "verification" / "paper_exchange_threshold_metrics_manual.json")

    parity_path = reports / "parity" / "latest.json"
    reliability_path = reports / "ops" / "reliability_slo_latest.json"
    tests_path = reports / "tests" / "latest.json"
    promotion_path = reports / "promotion_gates" / "latest.json"
    strict_cycle_path = reports / "promotion_gates" / "strict_cycle_latest.json"
    command_journal_path = reports / "verification" / "paper_exchange_command_journal_latest.json"
    paper_exchange_load_path = reports / "verification" / "paper_exchange_load_latest.json"

    parity = _read_json(parity_path)
    reliability = _read_json(reliability_path)
    tests = _read_json(tests_path)
    promotion = _read_json(promotion_path)
    strict_cycle = _read_json(strict_cycle_path)
    command_journal = _read_json(command_journal_path)
    paper_exchange_load_metrics = _read_artifact_metrics(paper_exchange_load_path)

    source_artifacts = {
        "parity_latest": _artifact_info(parity_path, now_ts),
        "reliability_slo_latest": _artifact_info(reliability_path, now_ts),
        "tests_latest": _artifact_info(tests_path, now_ts),
        "promotion_gates_latest": _artifact_info(promotion_path, now_ts),
        "strict_cycle_latest": _artifact_info(strict_cycle_path, now_ts),
        "paper_exchange_command_journal_latest": _artifact_info(command_journal_path, now_ts),
        "paper_exchange_load_latest": _artifact_info(paper_exchange_load_path, now_ts),
        "manual_metrics": _artifact_info(manual_path, now_ts),
    }

    computed_metrics: Dict[str, float] = {}

    # From tests gate
    tests_status = str(tests.get("status", "")).strip().lower()
    tests_pass_rate = 100.0 if tests_status == "pass" else 0.0
    computed_metrics["p0_1_contract_tests_pass_rate_pct"] = tests_pass_rate
    computed_metrics["p1_17_gate_path_tests_pass_rate_pct"] = tests_pass_rate

    # Promotion checks include paper exchange gates when wired/enabled.
    check_names: List[str] = []
    checks = promotion.get("checks", [])
    if isinstance(checks, list):
        for c in checks:
            if isinstance(c, dict):
                check_names.append(str(c.get("name", "")).strip())
    required_checks = {"paper_exchange_preflight", "paper_exchange_thresholds"}
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

    # Strict-cycle signal used by item 18
    strict_gate_rc = _to_float(strict_cycle.get("strict_gate_rc"))
    if strict_gate_rc is not None:
        computed_metrics["p0_18_strict_cycle_invocation_success_rate_pct"] = 100.0 if int(strict_gate_rc) == 0 else 0.0

    # Privileged command attribution/audit semantics from idempotency journal.
    computed_metrics.update(_command_journal_metrics(command_journal))
    computed_metrics["p1_20_security_policy_test_suite_pass_rate_pct"] = tests_pass_rate

    # Desk-scale load/backpressure evidence.
    for metric_name, value in paper_exchange_load_metrics.items():
        if str(metric_name).startswith("p1_19_"):
            computed_metrics[str(metric_name)] = float(value)

    manual_metrics = _read_manual_metrics(manual_path)
    merged_metrics: Dict[str, float] = dict(computed_metrics)
    # Manual values have highest precedence for calibrated threshold evidence.
    merged_metrics.update(manual_metrics)

    required_metric_names = sorted({clause.metric for clause in THRESHOLD_CLAUSES})
    unresolved_metrics = sorted([name for name in required_metric_names if name not in merged_metrics])

    stale_sources = [
        name
        for name, info in source_artifacts.items()
        if bool(info.get("exists", False)) and float(info.get("age_min", 1e9)) > float(max_source_age_min)
    ]

    status = "ok"
    if unresolved_metrics:
        status = "warning"
    if stale_sources:
        status = "warning"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "metrics": merged_metrics,
        "diagnostics": {
            "required_metric_count": len(required_metric_names),
            "computed_metric_count": len(computed_metrics),
            "manual_metric_count": len(manual_metrics),
            "resolved_metric_count": len(merged_metrics),
            "unresolved_metric_count": len(unresolved_metrics),
            "unresolved_metrics": unresolved_metrics,
            "stale_sources": stale_sources,
            "max_source_age_min": float(max_source_age_min),
        },
        "source_artifacts": source_artifacts,
        "notes": {
            "manual_metrics_override_path": str(manual_path),
            "manual_metrics_override_precedence": "manual_over_computed",
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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

