#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

REQUIRED_METRICS = [
    "p1_19_sustained_command_throughput_cmds_per_sec",
    "p1_19_command_latency_under_load_p95_ms",
    "p1_19_command_latency_under_load_p99_ms",
    "p1_19_stream_backlog_growth_rate_pct_per_10min",
    "p1_19_stress_window_oom_restart_count",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_float(value: object) -> Optional[float]:
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


def build_report(
    root: Path,
    *,
    source_report_path: Optional[Path] = None,
    baseline_output_path: Optional[Path] = None,
    require_source_pass: bool = True,
    profile_label: str = "",
) -> Dict[str, object]:
    source_path = source_report_path or (root / "reports" / "verification" / "paper_exchange_load_latest.json")
    output_path = baseline_output_path or (root / "reports" / "verification" / "paper_exchange_load_baseline_latest.json")
    source_payload = _read_json(source_path)
    source_status = str(source_payload.get("status", "")).strip().lower()
    source_metrics_raw = source_payload.get("metrics", {})
    source_metrics = source_metrics_raw if isinstance(source_metrics_raw, dict) else {}

    missing_metrics = []
    extracted_metrics: Dict[str, float] = {}
    for metric_name in REQUIRED_METRICS:
        parsed = _to_float(source_metrics.get(metric_name))
        if parsed is None:
            missing_metrics.append(metric_name)
        else:
            extracted_metrics[metric_name] = float(parsed)

    source_present = source_path.exists()
    source_pass = source_status == "pass"
    checks = {
        "source_report_present": bool(source_present),
        "source_report_pass": bool(source_pass) if require_source_pass else True,
        "required_metrics_present": len(missing_metrics) == 0,
    }
    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    status = "pass" if len(failed_checks) == 0 else "fail"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "metrics": extracted_metrics,
        "diagnostics": {
            "required_metric_count": len(REQUIRED_METRICS),
            "missing_metrics": missing_metrics,
            "source_report_path": str(source_path),
            "source_report_status": source_status,
            "source_report_ts_utc": str(source_payload.get("ts_utc", "")).strip(),
            "baseline_output_path": str(output_path),
            "profile_label": str(profile_label or "").strip(),
            "require_source_pass": bool(require_source_pass),
        },
    }


def run_capture(
    *,
    strict: bool,
    source_report_path: str,
    baseline_output_path: str,
    require_source_pass: bool,
    profile_label: str,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    source_path = _resolve_path(source_report_path, "reports/verification/paper_exchange_load_latest.json", root)
    output_path = _resolve_path(
        baseline_output_path,
        "reports/verification/paper_exchange_load_baseline_latest.json",
        root,
    )

    report = build_report(
        root,
        source_report_path=source_path,
        baseline_output_path=output_path,
        require_source_pass=bool(require_source_pass),
        profile_label=str(profile_label or "").strip(),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    timestamped_path = output_path.with_name(f"paper_exchange_load_baseline_{stamp}.json")
    payload = json.dumps(report, indent=2)
    output_path.write_text(payload, encoding="utf-8")
    timestamped_path.write_text(payload, encoding="utf-8")

    print(
        "[paper-exchange-perf-baseline] "
        f"status={report.get('status')} "
        f"source={report.get('diagnostics', {}).get('source_report_path', '')}"
    )
    print(f"[paper-exchange-perf-baseline] evidence={output_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture current paper-exchange load report as regression baseline artifact."
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when baseline capture checks fail.")
    parser.add_argument(
        "--source-report-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_SOURCE_PATH", ""),
        help="Source load report path (defaults to reports/verification/paper_exchange_load_latest.json).",
    )
    parser.add_argument(
        "--baseline-output-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PATH", ""),
        help="Baseline output path (defaults to reports/verification/paper_exchange_load_baseline_latest.json).",
    )
    parser.add_argument(
        "--require-source-pass",
        action="store_true",
        default=str(os.getenv("PAPER_EXCHANGE_PERF_BASELINE_REQUIRE_SOURCE_PASS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Require source report status=pass before baseline capture.",
    )
    parser.add_argument(
        "--no-require-source-pass",
        action="store_false",
        dest="require_source_pass",
        help="Allow baseline capture from non-pass source report.",
    )
    parser.add_argument(
        "--profile-label",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PROFILE_LABEL", ""),
        help="Optional profile label (e.g., short_window, sustained_2h).",
    )
    args = parser.parse_args()
    return run_capture(
        strict=bool(args.strict),
        source_report_path=str(args.source_report_path),
        baseline_output_path=str(args.baseline_output_path),
        require_source_pass=bool(args.require_source_pass),
        profile_label=str(args.profile_label),
    )


if __name__ == "__main__":
    raise SystemExit(main())
