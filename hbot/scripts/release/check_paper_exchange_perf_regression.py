#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ts(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


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


def _resolve_path(path_value: str, default_rel: str, root: Path) -> Path:
    raw = str(path_value or "").strip() or str(default_rel)
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path


def _metric(metrics: dict[str, object], name: str) -> float | None:
    return _to_float(metrics.get(name))


def _relative_regression_pct(current: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0 if current <= 0 else 1_000_000.0
    return ((float(current) - float(baseline)) / float(baseline)) * 100.0


def _waiver_info(
    waiver_payload: dict[str, object],
    *,
    now_ts: float | None,
    max_waiver_hours: float,
) -> dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    if not waiver_payload:
        return {
            "present": False,
            "valid": False,
            "applied": False,
            "reason": "",
            "approved_by": "",
            "change_ticket": "",
            "created_ts_utc": "",
            "expires_at_utc": "",
            "validity_reason": "waiver_missing",
        }

    status = str(waiver_payload.get("status", "")).strip().lower()
    reason = str(waiver_payload.get("reason", "")).strip()
    approved_by = str(waiver_payload.get("approved_by", "")).strip()
    change_ticket = str(waiver_payload.get("change_ticket", "")).strip()
    created_ts_utc = str(waiver_payload.get("created_ts_utc", "")).strip()
    expires_at_utc = str(waiver_payload.get("expires_at_utc", "")).strip()
    created_dt = _parse_ts(created_ts_utc)
    expires_dt = _parse_ts(expires_at_utc)

    valid = True
    validity_reason = "ok"
    if status not in {"approved", "active"}:
        valid = False
        validity_reason = "invalid_status"
    elif not reason:
        valid = False
        validity_reason = "missing_reason"
    elif not approved_by:
        valid = False
        validity_reason = "missing_approved_by"
    elif not change_ticket:
        valid = False
        validity_reason = "missing_change_ticket"
    elif expires_dt is None:
        valid = False
        validity_reason = "missing_or_invalid_expires_at_utc"
    elif expires_dt.timestamp() <= float(now_ts):
        valid = False
        validity_reason = "waiver_expired"
    elif created_dt is not None and expires_dt is not None:
        duration_hours = max(0.0, (expires_dt.timestamp() - created_dt.timestamp()) / 3600.0)
        if duration_hours > float(max_waiver_hours):
            valid = False
            validity_reason = "waiver_window_exceeds_max_hours"

    return {
        "present": True,
        "valid": bool(valid),
        "applied": False,
        "reason": reason,
        "approved_by": approved_by,
        "change_ticket": change_ticket,
        "created_ts_utc": created_ts_utc,
        "expires_at_utc": expires_at_utc,
        "validity_reason": validity_reason,
    }


def build_report(
    root: Path,
    *,
    now_ts: float | None = None,
    current_report_path: Path | None = None,
    baseline_report_path: Path | None = None,
    waiver_path: Path | None = None,
    max_latency_regression_pct: float = 20.0,
    max_backlog_regression_pct: float = 25.0,
    min_throughput_ratio: float = 0.85,
    max_restart_regression: float = 0.0,
    max_waiver_hours: float = 24.0,
) -> dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    current_path = current_report_path or (root / "reports" / "verification" / "paper_exchange_load_latest.json")
    baseline_path = baseline_report_path or (root / "reports" / "verification" / "paper_exchange_load_baseline_latest.json")
    resolved_waiver_path = waiver_path or (root / "reports" / "verification" / "paper_exchange_perf_regression_waiver_latest.json")

    current_payload = _read_json(current_path)
    baseline_payload = _read_json(baseline_path)
    waiver_payload = _read_json(resolved_waiver_path)

    current_metrics = current_payload.get("metrics", {})
    current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
    baseline_metrics = baseline_payload.get("metrics", {})
    baseline_metrics = baseline_metrics if isinstance(baseline_metrics, dict) else {}

    cur_throughput = _metric(current_metrics, "p1_19_sustained_command_throughput_cmds_per_sec")
    cur_p95 = _metric(current_metrics, "p1_19_command_latency_under_load_p95_ms")
    cur_p99 = _metric(current_metrics, "p1_19_command_latency_under_load_p99_ms")
    cur_backlog = _metric(current_metrics, "p1_19_stream_backlog_growth_rate_pct_per_10min")
    cur_restart = _metric(current_metrics, "p1_19_stress_window_oom_restart_count")

    base_throughput = _metric(baseline_metrics, "p1_19_sustained_command_throughput_cmds_per_sec")
    base_p95 = _metric(baseline_metrics, "p1_19_command_latency_under_load_p95_ms")
    base_p99 = _metric(baseline_metrics, "p1_19_command_latency_under_load_p99_ms")
    base_backlog = _metric(baseline_metrics, "p1_19_stream_backlog_growth_rate_pct_per_10min")
    base_restart = _metric(baseline_metrics, "p1_19_stress_window_oom_restart_count")

    comparison_ready = all(
        value is not None
        for value in (
            cur_throughput,
            cur_p95,
            cur_p99,
            cur_backlog,
            cur_restart,
            base_throughput,
            base_p95,
            base_p99,
            base_backlog,
            base_restart,
        )
    )

    throughput_ratio = 0.0
    latency_p95_regression_pct = 0.0
    latency_p99_regression_pct = 0.0
    backlog_regression_pct = 0.0
    restart_delta = 0.0
    if comparison_ready:
        assert cur_throughput is not None
        assert cur_p95 is not None
        assert cur_p99 is not None
        assert cur_backlog is not None
        assert cur_restart is not None
        assert base_throughput is not None
        assert base_p95 is not None
        assert base_p99 is not None
        assert base_backlog is not None
        assert base_restart is not None
        throughput_ratio = (
            (float(cur_throughput) / float(base_throughput))
            if float(base_throughput) > 0
            else (1.0 if float(cur_throughput) > 0 else 0.0)
        )
        latency_p95_regression_pct = _relative_regression_pct(float(cur_p95), float(base_p95))
        latency_p99_regression_pct = _relative_regression_pct(float(cur_p99), float(base_p99))
        backlog_regression_pct = _relative_regression_pct(float(cur_backlog), float(base_backlog))
        restart_delta = float(cur_restart) - float(base_restart)

    checks = {
        "current_report_present": current_path.exists(),
        "baseline_report_present": baseline_path.exists(),
        "current_report_pass": str(current_payload.get("status", "")).strip().lower() == "pass",
        "baseline_report_pass": str(baseline_payload.get("status", "")).strip().lower() == "pass",
        "comparison_metrics_present": bool(comparison_ready),
        "throughput_within_budget": bool(comparison_ready and throughput_ratio >= float(min_throughput_ratio)),
        "latency_p95_within_budget": bool(
            comparison_ready and latency_p95_regression_pct <= float(max_latency_regression_pct)
        ),
        "latency_p99_within_budget": bool(
            comparison_ready and latency_p99_regression_pct <= float(max_latency_regression_pct)
        ),
        "backlog_within_budget": bool(
            comparison_ready and backlog_regression_pct <= float(max_backlog_regression_pct)
        ),
        "restart_within_budget": bool(comparison_ready and restart_delta <= float(max_restart_regression)),
    }
    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    base_pass = len(failed_checks) == 0

    waiver = _waiver_info(waiver_payload, now_ts=now_ts, max_waiver_hours=max_waiver_hours)
    waiver_applied = bool(waiver.get("valid", False) and not base_pass)
    waiver["applied"] = waiver_applied

    status = "pass" if base_pass else ("waived" if waiver_applied else "fail")
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "metrics": {
            "throughput_ratio": float(throughput_ratio),
            "latency_p95_regression_pct": float(latency_p95_regression_pct),
            "latency_p99_regression_pct": float(latency_p99_regression_pct),
            "backlog_regression_pct": float(backlog_regression_pct),
            "restart_delta": float(restart_delta),
            "min_throughput_ratio": float(min_throughput_ratio),
            "max_latency_regression_pct": float(max_latency_regression_pct),
            "max_backlog_regression_pct": float(max_backlog_regression_pct),
            "max_restart_regression": float(max_restart_regression),
        },
        "input": {
            "current_report_path": str(current_path),
            "current_report_status": str(current_payload.get("status", "")).strip().lower(),
            "baseline_report_path": str(baseline_path),
            "baseline_report_status": str(baseline_payload.get("status", "")).strip().lower(),
            "waiver_path": str(resolved_waiver_path),
            "max_waiver_hours": float(max_waiver_hours),
        },
        "waiver": waiver,
    }


def run_check(
    *,
    strict: bool,
    current_report_path: str,
    baseline_report_path: str,
    waiver_path: str,
    max_latency_regression_pct: float,
    max_backlog_regression_pct: float,
    min_throughput_ratio: float,
    max_restart_regression: float,
    max_waiver_hours: float,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    report = build_report(
        root,
        current_report_path=_resolve_path(
            current_report_path, "reports/verification/paper_exchange_load_latest.json", root
        ),
        baseline_report_path=_resolve_path(
            baseline_report_path, "reports/verification/paper_exchange_load_baseline_latest.json", root
        ),
        waiver_path=_resolve_path(
            waiver_path, "reports/verification/paper_exchange_perf_regression_waiver_latest.json", root
        ),
        max_latency_regression_pct=float(max_latency_regression_pct),
        max_backlog_regression_pct=float(max_backlog_regression_pct),
        min_throughput_ratio=float(min_throughput_ratio),
        max_restart_regression=float(max_restart_regression),
        max_waiver_hours=float(max_waiver_hours),
    )

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_exchange_perf_regression_{stamp}.json"
    latest_path = out_dir / "paper_exchange_perf_regression_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        "[paper-exchange-perf-regression] "
        f"status={report.get('status')} "
        f"failed_checks={report.get('failed_checks', [])}"
    )
    print(f"[paper-exchange-perf-regression] evidence={out_path}")
    if strict and str(report.get("status", "fail")).lower() not in {"pass", "waived"}:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare paper-exchange load evidence against baseline and enforce regression budgets."
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when regression check fails.")
    parser.add_argument(
        "--current-report-path",
        default=os.getenv("PAPER_EXCHANGE_LOAD_REPORT_PATH", ""),
        help="Current load report path (defaults to reports/verification/paper_exchange_load_latest.json).",
    )
    parser.add_argument(
        "--baseline-report-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PATH", ""),
        help="Baseline load report path.",
    )
    parser.add_argument(
        "--waiver-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_WAIVER_PATH", ""),
        help="Optional waiver artifact path for temporary approved degradation.",
    )
    parser.add_argument(
        "--max-latency-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_LATENCY_REGRESSION_PCT", "20")),
        help="Maximum allowed positive regression percent for p95/p99 latency.",
    )
    parser.add_argument(
        "--max-backlog-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_BACKLOG_REGRESSION_PCT", "25")),
        help="Maximum allowed positive regression percent for backlog growth metric.",
    )
    parser.add_argument(
        "--min-throughput-ratio",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MIN_THROUGHPUT_RATIO", "0.85")),
        help="Minimum required throughput ratio current/baseline.",
    )
    parser.add_argument(
        "--max-restart-regression",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_RESTART_REGRESSION", "0")),
        help="Maximum allowed increase in restart count over baseline.",
    )
    parser.add_argument(
        "--max-waiver-hours",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_WAIVER_MAX_HOURS", "24")),
        help="Maximum allowed waiver validity window in hours.",
    )
    args = parser.parse_args()

    return run_check(
        strict=bool(args.strict),
        current_report_path=str(args.current_report_path),
        baseline_report_path=str(args.baseline_report_path),
        waiver_path=str(args.waiver_path),
        max_latency_regression_pct=float(args.max_latency_regression_pct),
        max_backlog_regression_pct=float(args.max_backlog_regression_pct),
        min_throughput_ratio=float(args.min_throughput_ratio),
        max_restart_regression=float(args.max_restart_regression),
        max_waiver_hours=float(args.max_waiver_hours),
    )


if __name__ == "__main__":
    raise SystemExit(main())

