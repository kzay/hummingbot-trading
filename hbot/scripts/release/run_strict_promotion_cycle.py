from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_incident_note(incidents_path: Path, message: str) -> None:
    incidents_path.parent.mkdir(parents=True, exist_ok=True)
    if not incidents_path.exists():
        incidents_path.write_text("# Incident Playbook\n\n", encoding="utf-8")
    with incidents_path.open("a", encoding="utf-8") as f:
        f.write(f"- {_utc_now()} - {message}\n")


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, str(default))).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _check_entry(summary: dict, name: str) -> dict:
    checks = summary.get("checks", [])
    if not isinstance(checks, list):
        return {}
    for check in checks:
        if not isinstance(check, dict):
            continue
        if str(check.get("name", "")).strip() == str(name).strip():
            return check
    return {}


def _extract_threshold_diagnostics(summary: dict) -> dict:
    runtime = summary.get("runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    enabled = bool(runtime.get("check_paper_exchange_thresholds", False))
    inputs_ready = bool(runtime.get("paper_exchange_threshold_inputs_ready", False))
    inputs_status = str(runtime.get("paper_exchange_threshold_inputs_status", "")).strip().lower()
    unresolved = max(0, _to_int(runtime.get("paper_exchange_threshold_inputs_unresolved_metric_count"), 0))
    stale_sources = max(0, _to_int(runtime.get("paper_exchange_threshold_inputs_stale_source_count"), 0))
    missing_sources = max(0, _to_int(runtime.get("paper_exchange_threshold_inputs_missing_source_count"), 0))
    thresholds_rc = max(0, _to_int(runtime.get("paper_exchange_thresholds_rc"), 0))
    inputs_rc = max(0, _to_int(runtime.get("paper_exchange_threshold_inputs_rc"), 0))
    inputs_path = str(runtime.get("paper_exchange_threshold_inputs_path", "")).strip()

    inputs_check = _check_entry(summary, "paper_exchange_threshold_inputs_ready")
    thresholds_check = _check_entry(summary, "paper_exchange_thresholds")
    inputs_check_pass = bool(inputs_check.get("pass", inputs_ready if enabled else True))
    thresholds_check_pass = bool(thresholds_check.get("pass", True if not enabled else False))
    inputs_check_reason = str(inputs_check.get("reason", "")).strip()
    thresholds_check_reason = str(thresholds_check.get("reason", "")).strip()

    blocking_reasons = []
    if enabled:
        if not inputs_check_pass:
            blocking_reasons.append("inputs_not_ready")
        if unresolved > 0:
            blocking_reasons.append("unresolved_metrics")
        if stale_sources > 0:
            blocking_reasons.append("stale_sources")
        if missing_sources > 0:
            blocking_reasons.append("missing_sources")
        if not thresholds_check_pass or thresholds_rc != 0:
            blocking_reasons.append("threshold_evaluation_failed")

    action_hints = []
    if enabled:
        if unresolved > 0:
            action_hints.append(f"resolve {unresolved} unresolved metrics in threshold inputs artifact")
        if stale_sources > 0 or missing_sources > 0:
            action_hints.append("refresh stale/missing source artifacts used by threshold inputs builder")
        if not thresholds_check_pass or thresholds_rc != 0:
            action_hints.append("inspect paper_exchange_thresholds_latest.json failed clauses")
        if not inputs_check_pass and not action_hints:
            action_hints.append("inspect paper_exchange_threshold_inputs_ready gate diagnostics")

    return {
        "enabled": bool(enabled),
        "inputs_ready": bool(inputs_ready),
        "inputs_status": inputs_status,
        "inputs_unresolved_metric_count": int(unresolved),
        "inputs_stale_source_count": int(stale_sources),
        "inputs_missing_source_count": int(missing_sources),
        "inputs_rc": int(inputs_rc),
        "thresholds_rc": int(thresholds_rc),
        "inputs_path": inputs_path,
        "inputs_check_pass": bool(inputs_check_pass),
        "inputs_check_reason": inputs_check_reason,
        "thresholds_check_pass": bool(thresholds_check_pass),
        "thresholds_check_reason": thresholds_check_reason,
        "blocking_reasons": blocking_reasons,
        "action_hint": "; ".join(action_hints),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run strict promotion cycle with parity refresh.")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Max freshness window in minutes.")
    parser.add_argument(
        "--day2-max-delta",
        type=int,
        default=6,
        help="Absolute per-stream lag tolerance for day2 gate.",
    )
    parser.add_argument(
        "--append-incident-on-fail",
        action="store_true",
        help="Append a short incident note to docs/ops/incidents.md when strict gate fails.",
    )
    parser.add_argument(
        "--check-paper-exchange-thresholds",
        action="store_true",
        default=_env_bool("STRICT_REQUIRE_PAPER_EXCHANGE_THRESHOLDS", True),
        help="Enable quantitative paper-exchange threshold gate in strict cycle.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-thresholds",
        action="store_false",
        dest="check_paper_exchange_thresholds",
        help="Disable quantitative paper-exchange threshold gate in strict cycle.",
    )
    parser.add_argument(
        "--check-paper-exchange-preflight",
        action="store_true",
        default=_env_bool("STRICT_REQUIRE_PAPER_EXCHANGE_PREFLIGHT", True),
        help="Enable paper-exchange wiring preflight gate in strict cycle.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-preflight",
        action="store_false",
        dest="check_paper_exchange_preflight",
        help="Disable paper-exchange wiring preflight gate in strict cycle.",
    )
    parser.add_argument(
        "--check-paper-exchange-golden-path",
        action="store_true",
        default=_env_bool("STRICT_REQUIRE_PAPER_EXCHANGE_GOLDEN_PATH", True),
        help="Enable deterministic paper-exchange functional golden-path gate in strict cycle.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-golden-path",
        action="store_false",
        dest="check_paper_exchange_golden_path",
        help="Disable deterministic paper-exchange functional golden-path gate in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-threshold-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_MAX_AGE_MIN", "20")),
        help="Max allowed age (minutes) for paper-exchange threshold input artifact.",
    )
    parser.add_argument(
        "--check-paper-exchange-perf-regression",
        action="store_true",
        default=_env_bool("STRICT_CHECK_PAPER_EXCHANGE_PERF_REGRESSION", True),
        help="Enable paper-exchange performance regression guard in strict cycle.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-perf-regression",
        action="store_false",
        dest="check_paper_exchange_perf_regression",
        help="Disable paper-exchange performance regression guard in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PATH", ""),
        help="Optional baseline report path for performance regression guard.",
    )
    parser.add_argument(
        "--paper-exchange-perf-waiver-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_WAIVER_PATH", ""),
        help="Optional waiver artifact path for temporary approved performance degradation.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-latency-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_LATENCY_REGRESSION_PCT", "20")),
        help="Maximum tolerated p95/p99 latency regression versus baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-backlog-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_BACKLOG_REGRESSION_PCT", "25")),
        help="Maximum tolerated backlog-growth regression versus baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-min-throughput-ratio",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MIN_THROUGHPUT_RATIO", "0.85")),
        help="Minimum current/baseline throughput ratio required by perf regression guard.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-restart-regression",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_RESTART_REGRESSION", "0")),
        help="Maximum allowed restart-count increase versus baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-waiver-max-hours",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_WAIVER_MAX_HOURS", "24")),
        help="Maximum waiver validity window in hours.",
    )
    parser.add_argument(
        "--capture-paper-exchange-perf-baseline",
        action="store_true",
        default=_env_bool("STRICT_CAPTURE_PAPER_EXCHANGE_PERF_BASELINE", False),
        help="Capture paper-exchange perf baseline artifact in strict cycle.",
    )
    parser.add_argument(
        "--no-capture-paper-exchange-perf-baseline",
        action="store_false",
        dest="capture_paper_exchange_perf_baseline",
        help="Disable paper-exchange perf baseline capture in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-source-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_SOURCE_PATH", ""),
        help="Optional source report path used when capturing paper-exchange perf baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-profile-label",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PROFILE_LABEL", ""),
        help="Optional profile label attached when capturing paper-exchange perf baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-require-source-pass",
        action="store_true",
        default=_env_bool("PAPER_EXCHANGE_PERF_BASELINE_REQUIRE_SOURCE_PASS", True),
        help="Require source report status=pass for strict-cycle perf baseline capture.",
    )
    parser.add_argument(
        "--no-paper-exchange-perf-baseline-require-source-pass",
        action="store_false",
        dest="paper_exchange_perf_baseline_require_source_pass",
        help="Allow strict-cycle perf baseline capture from non-pass source report.",
    )
    parser.add_argument(
        "--run-paper-exchange-load-harness",
        action="store_true",
        default=str(os.getenv("STRICT_RUN_PAPER_EXCHANGE_LOAD_HARNESS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Inject synthetic paper-exchange load before threshold evaluation in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_DURATION_SEC", "20")),
        help="Duration for strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TARGET_CMD_RATE", "60")),
        help="Target command rate for strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_COMMANDS", "300")),
        help="Minimum commands for strict-cycle paper-exchange load harness pass criteria.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-instance-names",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAMES", "bot1,bot3,bot4"),
        help="Comma-separated instance names used by strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_INSTANCE_COVERAGE", "1")),
        help="Minimum unique instances required by strict-cycle paper-exchange load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", "hb.paper_exchange.command.v1"),
        help="Command stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", "hb.paper_exchange.event.v1"),
        help="Event stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"),
        help="Heartbeat stream used by strict-cycle paper-exchange load checks.",
    )
    parser.add_argument(
        "--paper-exchange-load-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by strict-cycle paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_LOOKBACK_SEC", "600")),
        help="Load checker lookback window for strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command window required by strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SUSTAINED_WINDOW_SEC", "0")),
        help=(
            "Sustained qualification window for strict-cycle load checker. "
            "When <= 0, checker uses min-window-sec."
        ),
    )
    parser.add_argument(
        "--paper-exchange-load-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_INSTANCE_COVERAGE", "1")),
        help="Minimum unique instance coverage required by strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-enforce-budget-checks",
        action="store_true",
        default=str(os.getenv("PAPER_EXCHANGE_LOAD_ENFORCE_BUDGET_CHECKS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable strict-cycle fail-fast budget checks in load checker.",
    )
    parser.add_argument(
        "--no-paper-exchange-load-enforce-budget-checks",
        action="store_false",
        dest="paper_exchange_load_enforce_budget_checks",
        help="Disable strict-cycle fail-fast budget checks in load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-throughput-cmds-per-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MIN_THROUGHPUT_CMDS_PER_SEC", "50")),
        help="Minimum throughput budget for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-latency-p95-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P95_MS", "500")),
        help="Maximum p95 latency budget for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-latency-p99-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P99_MS", "1000")),
        help="Maximum p99 latency budget for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-backlog-growth-pct-per-10min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_BACKLOG_GROWTH_PCT_PER_10MIN", "1")),
        help="Maximum backlog-growth budget for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-restart-count",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_RESTART_COUNT", "0")),
        help="Maximum restart-count budget for strict-cycle load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-run-id",
        default=os.getenv("PAPER_EXCHANGE_LOAD_RUN_ID", ""),
        help="Optional run_id filter forwarded to strict-cycle load checker.",
    )
    parser.add_argument(
        "--check-paper-exchange-sustained-qualification",
        action="store_true",
        default=str(os.getenv("STRICT_CHECK_PAPER_EXCHANGE_SUSTAINED_QUALIFICATION", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run sustained long-window paper-exchange qualification in strict cycle.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-sustained-qualification",
        action="store_false",
        dest="check_paper_exchange_sustained_qualification",
        help="Disable sustained long-window paper-exchange qualification in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_DURATION_SEC", "7200")),
        help="Sustained qualification harness duration in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_TARGET_CMD_RATE", "60")),
        help="Sustained qualification harness command rate in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_COMMANDS", "0")),
        help="Sustained harness minimum commands in strict cycle (<=0 auto-derive).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-command-maxlen",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_COMMAND_MAXLEN", "0")),
        help="Sustained harness command maxlen in strict cycle (<=0 auto-derive).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_INSTANCE_COVERAGE", "3")),
        help="Sustained qualification minimum unique instance coverage in strict cycle.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_LOOKBACK_SEC", "0")),
        help="Sustained load-check lookback window in strict cycle (<=0 auto-derive).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_SAMPLE_COUNT", "0")),
        help="Sustained load-check sample count in strict cycle (<=0 auto-derive).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_WINDOW_SEC", "0")),
        help="Sustained load-check qualification window in strict cycle (<=0 uses duration).",
    )
    parser.add_argument(
        "--check-dashboard-readiness",
        action="store_true",
        default=str(os.getenv("STRICT_CHECK_DASHBOARD_READINESS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enforce Grafana dashboard data readiness in strict cycle.",
    )
    parser.add_argument(
        "--no-check-dashboard-readiness",
        action="store_false",
        dest="check_dashboard_readiness",
        help="Disable dashboard readiness gate in strict cycle.",
    )
    parser.add_argument(
        "--check-canonical-plane-gates",
        action="store_true",
        default=str(
            os.getenv(
                "STRICT_REQUIRE_CANONICAL_PLANE_GATES",
                "true"
                if str(os.getenv("OPS_DATA_PLANE_MODE", "")).strip().lower() == "db_primary"
                else os.getenv("OPS_DB_READ_PREFERRED", "false"),
            )
        ).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enforce canonical-plane cutover guardrails in strict cycle.",
    )
    parser.add_argument(
        "--no-check-canonical-plane-gates",
        action="store_false",
        dest="check_canonical_plane_gates",
        help="Disable canonical-plane cutover guardrails in strict cycle.",
    )
    parser.add_argument(
        "--canonical-max-parity-delta-ratio",
        type=float,
        default=float(os.getenv("CANONICAL_MAX_PARITY_DELTA_RATIO", "0.10")),
        help="Max allowed DB-vs-CSV parity delta ratio for strict canonical guardrail.",
    )
    parser.add_argument(
        "--canonical-min-duplicate-suppression-rate",
        type=float,
        default=float(os.getenv("CANONICAL_MIN_DUP_SUPPRESSION_RATE", "0.99")),
        help="Minimum duplicate suppression rate for strict canonical guardrail.",
    )
    parser.add_argument(
        "--check-realtime-l2-data-quality",
        action="store_true",
        default=str(os.getenv("STRICT_CHECK_REALTIME_L2_DATA_QUALITY", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable strict realtime/L2 data quality gate in strict cycle.",
    )
    parser.add_argument(
        "--no-check-realtime-l2-data-quality",
        action="store_false",
        dest="check_realtime_l2_data_quality",
        help="Disable strict realtime/L2 data quality gate.",
    )
    parser.add_argument(
        "--realtime-l2-max-age-sec",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_AGE_SEC", "180")),
        help="Max age for realtime/L2 freshness evidence.",
    )
    parser.add_argument(
        "--realtime-l2-max-sequence-gap",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_SEQUENCE_GAP", "50")),
        help="Max tolerated sequence gap for strict realtime/L2 gate.",
    )
    parser.add_argument(
        "--realtime-l2-min-sampled-events",
        type=int,
        default=int(os.getenv("REALTIME_L2_MIN_SAMPLED_EVENTS", "1")),
        help="Minimum sampled events required for strict realtime/L2 gate.",
    )
    parser.add_argument(
        "--realtime-l2-max-raw-to-sampled-ratio",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_RAW_TO_SAMPLED_RATIO", "100")),
        help="Maximum raw/sampled ratio allowed for strict realtime/L2 gate.",
    )
    parser.add_argument(
        "--realtime-l2-max-depth-stream-share",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_DEPTH_STREAM_SHARE", "0.95")),
        help="Maximum depth stream share budget for strict realtime/L2 gate.",
    )
    parser.add_argument(
        "--realtime-l2-max-depth-event-bytes",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_DEPTH_EVENT_BYTES", "4000")),
        help="Maximum depth payload size budget for strict realtime/L2 gate.",
    )
    parser.add_argument(
        "--realtime-l2-lookback-events",
        type=int,
        default=int(os.getenv("REALTIME_L2_LOOKBACK_EVENTS", "5000")),
        help="Depth events scanned by strict realtime/L2 gate.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_promotion_gates.py"),
        "--ci",
        "--require-day2-go",
        "--require-day2-fresh",
        "--require-day2-lag-within-tolerance",
        "--day2-max-delta",
        str(args.day2_max_delta),
        "--attempt-day2-catchup",
        "--day2-catchup-cycles",
        "2",
        "--require-parity-informative-core",
        "--refresh-parity-once",
        "--check-bot-preflight",
        "--check-recon-exchange-preflight",
        "--collect-go-live-evidence",
        "--check-telegram-validation",
        "--check-portfolio-diversification",
        "--max-report-age-min",
        str(args.max_report_age_min),
    ]
    if args.check_paper_exchange_thresholds:
        cmd.extend(
            [
                "--check-paper-exchange-thresholds",
                "--paper-exchange-threshold-max-age-min",
                str(float(args.paper_exchange_threshold_max_age_min)),
                "--paper-exchange-load-harness-duration-sec",
                str(max(0.1, float(args.paper_exchange_load_harness_duration_sec))),
                "--paper-exchange-load-harness-target-cmd-rate",
                str(max(1.0, float(args.paper_exchange_load_harness_target_cmd_rate))),
                "--paper-exchange-load-harness-min-commands",
                str(max(1, int(args.paper_exchange_load_harness_min_commands))),
                "--paper-exchange-load-harness-instance-names",
                str(args.paper_exchange_load_harness_instance_names),
                "--paper-exchange-load-harness-min-instance-coverage",
                str(max(1, int(args.paper_exchange_load_harness_min_instance_coverage))),
                "--paper-exchange-load-command-stream",
                str(args.paper_exchange_load_command_stream),
                "--paper-exchange-load-event-stream",
                str(args.paper_exchange_load_event_stream),
                "--paper-exchange-load-heartbeat-stream",
                str(args.paper_exchange_load_heartbeat_stream),
                "--paper-exchange-load-consumer-group",
                str(args.paper_exchange_load_consumer_group),
                "--paper-exchange-load-heartbeat-consumer-group",
                str(args.paper_exchange_load_heartbeat_consumer_group),
                "--paper-exchange-load-heartbeat-consumer-name",
                str(args.paper_exchange_load_heartbeat_consumer_name),
                "--paper-exchange-load-lookback-sec",
                str(max(1, int(args.paper_exchange_load_lookback_sec))),
                "--paper-exchange-load-min-window-sec",
                str(max(1, int(args.paper_exchange_load_min_window_sec))),
                "--paper-exchange-load-sustained-window-sec",
                str(int(args.paper_exchange_load_sustained_window_sec)),
                "--paper-exchange-load-min-instance-coverage",
                str(max(1, int(args.paper_exchange_load_min_instance_coverage))),
                "--paper-exchange-load-min-throughput-cmds-per-sec",
                str(max(0.0, float(args.paper_exchange_load_min_throughput_cmds_per_sec))),
                "--paper-exchange-load-max-latency-p95-ms",
                str(max(0.0, float(args.paper_exchange_load_max_latency_p95_ms))),
                "--paper-exchange-load-max-latency-p99-ms",
                str(max(0.0, float(args.paper_exchange_load_max_latency_p99_ms))),
                "--paper-exchange-load-max-backlog-growth-pct-per-10min",
                str(max(0.0, float(args.paper_exchange_load_max_backlog_growth_pct_per_10min))),
                "--paper-exchange-load-max-restart-count",
                str(max(0.0, float(args.paper_exchange_load_max_restart_count))),
                "--paper-exchange-sustained-duration-sec",
                str(max(0.1, float(args.paper_exchange_sustained_duration_sec))),
                "--paper-exchange-sustained-target-cmd-rate",
                str(max(1.0, float(args.paper_exchange_sustained_target_cmd_rate))),
                "--paper-exchange-sustained-min-commands",
                str(int(args.paper_exchange_sustained_min_commands)),
                "--paper-exchange-sustained-command-maxlen",
                str(int(args.paper_exchange_sustained_command_maxlen)),
                "--paper-exchange-sustained-min-instance-coverage",
                str(max(1, int(args.paper_exchange_sustained_min_instance_coverage))),
                "--paper-exchange-sustained-lookback-sec",
                str(int(args.paper_exchange_sustained_lookback_sec)),
                "--paper-exchange-sustained-sample-count",
                str(int(args.paper_exchange_sustained_sample_count)),
                "--paper-exchange-sustained-window-sec",
                str(int(args.paper_exchange_sustained_window_sec)),
            ]
        )
        if args.paper_exchange_load_enforce_budget_checks:
            cmd.append("--paper-exchange-load-enforce-budget-checks")
        else:
            cmd.append("--no-paper-exchange-load-enforce-budget-checks")
        if args.check_paper_exchange_sustained_qualification:
            cmd.append("--check-paper-exchange-sustained-qualification")
        else:
            cmd.append("--no-check-paper-exchange-sustained-qualification")
        if args.run_paper_exchange_load_harness:
            cmd.append("--run-paper-exchange-load-harness")
        if str(args.paper_exchange_load_run_id).strip():
            cmd.extend(["--paper-exchange-load-run-id", str(args.paper_exchange_load_run_id).strip()])
    if args.capture_paper_exchange_perf_baseline:
        cmd.append("--capture-paper-exchange-perf-baseline")
        if str(args.paper_exchange_perf_baseline_path).strip():
            cmd.extend(["--paper-exchange-perf-baseline-path", str(args.paper_exchange_perf_baseline_path).strip()])
        if str(args.paper_exchange_perf_baseline_source_path).strip():
            cmd.extend(
                [
                    "--paper-exchange-perf-baseline-source-path",
                    str(args.paper_exchange_perf_baseline_source_path).strip(),
                ]
            )
        if str(args.paper_exchange_perf_baseline_profile_label).strip():
            cmd.extend(
                [
                    "--paper-exchange-perf-baseline-profile-label",
                    str(args.paper_exchange_perf_baseline_profile_label).strip(),
                ]
            )
        if args.paper_exchange_perf_baseline_require_source_pass:
            cmd.append("--paper-exchange-perf-baseline-require-source-pass")
        else:
            cmd.append("--no-paper-exchange-perf-baseline-require-source-pass")
    if args.check_paper_exchange_perf_regression:
        cmd.extend(
            [
                "--check-paper-exchange-perf-regression",
                "--paper-exchange-perf-max-latency-regression-pct",
                str(max(0.0, float(args.paper_exchange_perf_max_latency_regression_pct))),
                "--paper-exchange-perf-max-backlog-regression-pct",
                str(max(0.0, float(args.paper_exchange_perf_max_backlog_regression_pct))),
                "--paper-exchange-perf-min-throughput-ratio",
                str(max(0.0, float(args.paper_exchange_perf_min_throughput_ratio))),
                "--paper-exchange-perf-max-restart-regression",
                str(float(args.paper_exchange_perf_max_restart_regression)),
                "--paper-exchange-perf-waiver-max-hours",
                str(max(1.0, float(args.paper_exchange_perf_waiver_max_hours))),
            ]
        )
        if str(args.paper_exchange_perf_baseline_path).strip():
            cmd.extend(["--paper-exchange-perf-baseline-path", str(args.paper_exchange_perf_baseline_path).strip()])
        if str(args.paper_exchange_perf_waiver_path).strip():
            cmd.extend(["--paper-exchange-perf-waiver-path", str(args.paper_exchange_perf_waiver_path).strip()])
    if args.check_paper_exchange_preflight:
        cmd.append("--check-paper-exchange-preflight")
    if args.check_paper_exchange_golden_path:
        cmd.append("--check-paper-exchange-golden-path")
    if args.check_dashboard_readiness:
        cmd.append("--check-dashboard-readiness")
    if args.check_realtime_l2_data_quality:
        cmd.extend(
            [
                "--check-realtime-l2-data-quality",
                "--realtime-l2-max-age-sec",
                str(max(30, int(args.realtime_l2_max_age_sec))),
                "--realtime-l2-max-sequence-gap",
                str(max(0, int(args.realtime_l2_max_sequence_gap))),
                "--realtime-l2-min-sampled-events",
                str(max(0, int(args.realtime_l2_min_sampled_events))),
                "--realtime-l2-max-raw-to-sampled-ratio",
                str(max(1.0, float(args.realtime_l2_max_raw_to_sampled_ratio))),
                "--realtime-l2-max-depth-stream-share",
                str(max(0.0, min(1.0, float(args.realtime_l2_max_depth_stream_share)))),
                "--realtime-l2-max-depth-event-bytes",
                str(max(200, int(args.realtime_l2_max_depth_event_bytes))),
                "--realtime-l2-lookback-events",
                str(max(100, int(args.realtime_l2_lookback_events))),
            ]
        )
    if args.check_canonical_plane_gates:
        cmd.extend(
            [
                "--check-canonical-plane-gates",
                "--canonical-max-db-ingest-age-min",
                str(float(args.max_report_age_min)),
                "--canonical-max-parity-delta-ratio",
                str(float(args.canonical_max_parity_delta_ratio)),
                "--canonical-min-duplicate-suppression-rate",
                str(float(args.canonical_min_duplicate_suppression_rate)),
                "--canonical-max-replay-lag-delta",
                str(int(args.day2_max_delta)),
            ]
        )
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

    reports = root / "reports" / "promotion_gates"
    latest_path = reports / "latest.json"
    latest = {}
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            latest = {}
    threshold_diag = _extract_threshold_diagnostics(latest)

    cycle_summary = {
        "ts_utc": _utc_now(),
        "strict_gate_rc": int(proc.returncode),
        "strict_gate_status": latest.get("status", "UNKNOWN"),
        "critical_failures": latest.get("critical_failures", []),
        "gate_latest_path": str(latest_path),
        "paper_exchange_threshold_diagnostics": threshold_diag,
        "stdout": out[:4000],
    }
    cycle_path = reports / "strict_cycle_latest.json"
    cycle_path.write_text(json.dumps(cycle_summary, indent=2), encoding="utf-8")

    if proc.returncode != 0 and args.append_incident_on_fail:
        failures = latest.get("critical_failures", [])
        msg = f"strict promotion cycle failed; critical_failures={failures}; evidence={latest_path}"
        action_hint = str(threshold_diag.get("action_hint", "")).strip()
        if action_hint:
            msg = f"{msg}; threshold_action={action_hint}"
        _append_incident_note(root / "docs" / "ops" / "incidents.md", msg)

    print(f"[strict-cycle] rc={proc.returncode}")
    print(f"[strict-cycle] status={cycle_summary['strict_gate_status']}")
    if bool(threshold_diag.get("enabled", False)):
        print(
            "[strict-cycle] thresholds "
            f"inputs_ready={threshold_diag.get('inputs_ready', False)} "
            f"status={threshold_diag.get('inputs_status', '') or 'unknown'} "
            f"unresolved={threshold_diag.get('inputs_unresolved_metric_count', 0)} "
            f"stale_sources={threshold_diag.get('inputs_stale_source_count', 0)} "
            f"missing_sources={threshold_diag.get('inputs_missing_source_count', 0)} "
            f"thresholds_rc={threshold_diag.get('thresholds_rc', 0)}"
        )
        action_hint = str(threshold_diag.get("action_hint", "")).strip()
        if action_hint and int(proc.returncode) != 0:
            print(f"[strict-cycle] thresholds_action={action_hint}")
    print(f"[strict-cycle] evidence={cycle_path}")
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
