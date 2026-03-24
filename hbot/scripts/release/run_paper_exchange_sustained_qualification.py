#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.release.check_paper_exchange_load import run_check
from scripts.release.run_paper_exchange_load_harness import run_harness
from platform_lib.contracts.stream_names import (
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _default_harness_producer() -> str:
    explicit = str(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_PRODUCER", "")).strip()
    if explicit:
        return explicit
    allowed = _csv_values(str(os.getenv("PAPER_EXCHANGE_ALLOWED_COMMAND_PRODUCERS", "")))
    if allowed:
        return str(allowed[0])
    return "hb.paper_engine_v2"


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _expected_command_count(duration_sec: float, target_cmd_rate: float) -> int:
    return max(1, int(max(0.1, float(duration_sec)) * max(1.0, float(target_cmd_rate))))


def _resolve_min_commands(min_commands: int, duration_sec: float, target_cmd_rate: float) -> int:
    explicit = max(0, int(min_commands))
    if explicit > 0:
        return explicit
    expected = _expected_command_count(duration_sec, target_cmd_rate)
    return max(1, int(expected * 0.80))


def _resolve_command_maxlen(command_maxlen: int, duration_sec: float, target_cmd_rate: float) -> int:
    explicit = max(0, int(command_maxlen))
    expected = _expected_command_count(duration_sec, target_cmd_rate)
    required = max(100_000, int(expected * 1.50))
    return max(explicit, required)


def _resolve_sample_count(sample_count: int, duration_sec: float, target_cmd_rate: float) -> int:
    explicit = max(0, int(sample_count))
    expected = _expected_command_count(duration_sec, target_cmd_rate)
    required = max(8_000, int(expected * 1.20))
    return max(explicit, required)


def _resolve_lookback_sec(lookback_sec: int, duration_sec: float) -> int:
    explicit = max(0, int(lookback_sec))
    if explicit > 0:
        return explicit
    return max(600, int(max(0.1, float(duration_sec))) + 600)


def _resolve_sustained_window_sec(sustained_window_sec: int, duration_sec: float) -> int:
    explicit = max(0, int(sustained_window_sec))
    if explicit > 0:
        return explicit
    return max(1, int(max(0.1, float(duration_sec))))


def build_report(
    *,
    profile: dict[str, object],
    harness_rc: int,
    load_rc: int,
    harness_report: dict[str, object],
    load_report: dict[str, object],
) -> dict[str, object]:
    harness_status = str(harness_report.get("status", "")).strip().lower()
    load_status = str(load_report.get("status", "")).strip().lower()
    harness_failed_checks = sorted(
        [
            str(name)
            for name in (
                harness_report.get("failed_checks", [])
                if isinstance(harness_report.get("failed_checks", []), list)
                else []
            )
        ]
    )

    harness_diag_raw = harness_report.get("diagnostics", {})
    harness_diag = harness_diag_raw if isinstance(harness_diag_raw, dict) else {}
    load_diag_raw = load_report.get("diagnostics", {})
    load_diag = load_diag_raw if isinstance(load_diag_raw, dict) else {}
    load_metrics_raw = load_report.get("metrics", {})
    load_metrics = load_metrics_raw if isinstance(load_metrics_raw, dict) else {}
    harness_metrics_raw = harness_report.get("metrics", {})
    harness_metrics = harness_metrics_raw if isinstance(harness_metrics_raw, dict) else {}

    harness_run_id = str(harness_diag.get("run_id", "")).strip()
    load_run_id = str(load_diag.get("load_run_id", "")).strip()
    sustained_qualification_rate_pct = _safe_float(
        load_metrics.get("p1_19_sustained_window_qualification_rate_pct"),
        0.0,
    )
    instance_coverage_count = _safe_float(load_metrics.get("p1_19_command_instance_coverage_count"), 0.0)
    required_instance_coverage = max(1.0, _safe_float(profile.get("min_instance_coverage"), 1.0))
    budget_enforced = bool(load_diag.get("budget_checks_enforced", False))
    required_min_commands = max(1.0, _safe_float(profile.get("min_commands"), 1.0))
    required_min_publish_success_rate_pct = max(
        0.0,
        min(100.0, _safe_float(profile.get("min_publish_success_rate_pct"), 99.0)),
    )
    harness_published_commands = _safe_float(harness_metrics.get("published_commands"), 0.0)
    harness_instance_coverage_count = _safe_float(harness_metrics.get("instance_coverage_count"), 0.0)
    harness_publish_success_rate_pct = _safe_float(harness_metrics.get("publish_success_rate_pct"), 0.0)
    harness_publish_checks_pass = (
        harness_published_commands >= required_min_commands
        and harness_instance_coverage_count >= required_instance_coverage
        and harness_publish_success_rate_pct >= required_min_publish_success_rate_pct
    )
    harness_only_result_match_failure = (
        harness_status == "fail"
        and len(harness_failed_checks) > 0
        and all(str(name) == "result_match_rate" for name in harness_failed_checks)
    )
    harness_pass = bool(harness_publish_checks_pass) and (
        (int(harness_rc) == 0 and harness_status == "pass")
        or harness_only_result_match_failure
    )

    checks = {
        "harness_pass": bool(harness_pass),
        "load_validation_pass": int(load_rc) == 0 and load_status == "pass",
        "run_id_propagation": bool(harness_run_id) and harness_run_id == load_run_id,
        "budget_checks_enforced": bool(budget_enforced),
        "sustained_window_qualified": sustained_qualification_rate_pct >= 100.0,
        "minimum_instance_coverage": instance_coverage_count >= required_instance_coverage,
    }
    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    status = "pass" if len(failed_checks) == 0 else "fail"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "metrics": {
            "p1_19_sustained_command_throughput_cmds_per_sec": _safe_float(
                load_metrics.get("p1_19_sustained_command_throughput_cmds_per_sec"),
                0.0,
            ),
            "p1_19_command_latency_under_load_p95_ms": _safe_float(
                load_metrics.get("p1_19_command_latency_under_load_p95_ms"),
                0.0,
            ),
            "p1_19_command_latency_under_load_p99_ms": _safe_float(
                load_metrics.get("p1_19_command_latency_under_load_p99_ms"),
                0.0,
            ),
            "p1_19_stream_backlog_growth_rate_pct_per_10min": _safe_float(
                load_metrics.get("p1_19_stream_backlog_growth_rate_pct_per_10min"),
                0.0,
            ),
            "p1_19_stress_window_oom_restart_count": _safe_float(
                load_metrics.get("p1_19_stress_window_oom_restart_count"),
                0.0,
            ),
            "p1_19_command_instance_coverage_count": float(instance_coverage_count),
            "p1_19_sustained_window_observed_sec": _safe_float(
                load_metrics.get("p1_19_sustained_window_observed_sec"),
                0.0,
            ),
            "p1_19_sustained_window_required_sec": _safe_float(
                load_metrics.get("p1_19_sustained_window_required_sec"),
                0.0,
            ),
            "p1_19_sustained_window_qualification_rate_pct": float(sustained_qualification_rate_pct),
            "harness_published_commands": _safe_float(
                (harness_report.get("metrics", {}) if isinstance(harness_report.get("metrics", {}), dict) else {}).get(
                    "published_commands"
                ),
                0.0,
            ),
            "harness_result_match_rate_pct": _safe_float(
                (harness_report.get("metrics", {}) if isinstance(harness_report.get("metrics", {}), dict) else {}).get(
                    "result_match_rate_pct"
                ),
                0.0,
            ),
        },
        "diagnostics": {
            "profile": profile,
            "harness_rc": int(harness_rc),
            "harness_status": harness_status or "missing",
            "harness_failed_checks": harness_failed_checks,
            "harness_publish_checks_pass": bool(harness_publish_checks_pass),
            "harness_only_result_match_failure": bool(harness_only_result_match_failure),
            "harness_min_commands_required": float(required_min_commands),
            "harness_min_publish_success_rate_pct_required": float(required_min_publish_success_rate_pct),
            "harness_published_commands": float(harness_published_commands),
            "harness_instance_coverage_count": float(harness_instance_coverage_count),
            "harness_publish_success_rate_pct": float(harness_publish_success_rate_pct),
            "harness_run_id": harness_run_id,
            "load_rc": int(load_rc),
            "load_status": load_status or "missing",
            "load_failed_checks": sorted(
                [
                    str(name)
                    for name in (
                        load_report.get("failed_checks", [])
                        if isinstance(load_report.get("failed_checks", []), list)
                        else []
                    )
                ]
            ),
            "load_run_id": load_run_id,
            "load_budget_failed_checks": sorted(
                [
                    str(name)
                    for name in (
                        load_diag.get("budget_failed_checks", [])
                        if isinstance(load_diag.get("budget_failed_checks", []), list)
                        else []
                    )
                ]
            ),
        },
    }


def run_sustained_qualification(
    *,
    strict: bool,
    redis_host: str,
    redis_port: int,
    redis_db: int,
    redis_password: str,
    command_stream: str,
    event_stream: str,
    heartbeat_stream: str,
    consumer_group: str,
    heartbeat_consumer_group: str,
    heartbeat_consumer_name: str,
    producer: str,
    instance_name: str,
    instance_names: str,
    connector_name: str,
    trading_pair: str,
    duration_sec: float,
    target_cmd_rate: float,
    min_commands: int,
    command_maxlen: int,
    result_timeout_sec: float,
    poll_interval_ms: int,
    scan_count: int,
    require_heartbeat_fresh: bool,
    heartbeat_max_age_s: float,
    min_instance_coverage: int,
    min_publish_success_rate_pct: float,
    min_result_match_rate_pct: float,
    lookback_sec: int,
    sample_count: int,
    min_latency_samples: int,
    min_window_sec: int,
    sustained_window_sec: int,
    min_throughput_cmds_per_sec: float,
    max_latency_p95_ms: float,
    max_latency_p99_ms: float,
    max_backlog_growth_pct_per_10min: float,
    max_restart_count: float,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    expected_commands = _expected_command_count(duration_sec, target_cmd_rate)
    resolved_min_commands = _resolve_min_commands(min_commands, duration_sec, target_cmd_rate)
    resolved_command_maxlen = _resolve_command_maxlen(command_maxlen, duration_sec, target_cmd_rate)
    resolved_sample_count = _resolve_sample_count(sample_count, duration_sec, target_cmd_rate)
    resolved_lookback_sec = _resolve_lookback_sec(lookback_sec, duration_sec)
    resolved_sustained_window_sec = _resolve_sustained_window_sec(sustained_window_sec, duration_sec)

    profile = {
        "duration_sec": float(duration_sec),
        "target_cmd_rate": float(target_cmd_rate),
        "expected_commands": int(expected_commands),
        "min_commands": int(resolved_min_commands),
        "command_maxlen": int(resolved_command_maxlen),
        "sample_count": int(resolved_sample_count),
        "lookback_sec": int(resolved_lookback_sec),
        "sustained_window_sec": int(resolved_sustained_window_sec),
        "min_window_sec": int(max(1, int(min_window_sec))),
        "min_instance_coverage": int(max(1, int(min_instance_coverage))),
        "min_publish_success_rate_pct": float(min_publish_success_rate_pct),
    }

    harness_rc = run_harness(
        strict=True,
        redis_host=str(redis_host),
        redis_port=int(redis_port),
        redis_db=int(redis_db),
        redis_password=str(redis_password),
        command_stream=str(command_stream),
        event_stream=str(event_stream),
        heartbeat_stream=str(heartbeat_stream),
        command_maxlen=max(1, int(resolved_command_maxlen)),
        duration_sec=max(0.1, float(duration_sec)),
        target_cmd_rate=max(1.0, float(target_cmd_rate)),
        producer=str(producer),
        instance_name=str(instance_name),
        instance_names=str(instance_names),
        connector_name=str(connector_name),
        trading_pair=str(trading_pair),
        result_timeout_sec=max(0.0, float(result_timeout_sec)),
        poll_interval_ms=max(10, int(poll_interval_ms)),
        scan_count=max(100, int(scan_count)),
        require_heartbeat_fresh=bool(require_heartbeat_fresh),
        heartbeat_max_age_s=max(1.0, float(heartbeat_max_age_s)),
        min_commands=max(1, int(resolved_min_commands)),
        min_instance_coverage=max(1, int(min_instance_coverage)),
        min_publish_success_rate_pct=max(0.0, min(100.0, float(min_publish_success_rate_pct))),
        min_result_match_rate_pct=max(0.0, min(100.0, float(min_result_match_rate_pct))),
    )
    harness_path = root / "reports" / "verification" / "paper_exchange_load_harness_latest.json"
    harness_report = _read_json(harness_path)
    harness_diag = harness_report.get("diagnostics", {})
    harness_diag = harness_diag if isinstance(harness_diag, dict) else {}
    harness_run_id = str(harness_diag.get("run_id", "")).strip()

    if harness_run_id:
        load_rc = run_check(
            strict=True,
            redis_host=str(redis_host),
            redis_port=int(redis_port),
            redis_db=int(redis_db),
            redis_password=str(redis_password),
            command_stream=str(command_stream),
            event_stream=str(event_stream),
            heartbeat_stream=str(heartbeat_stream),
            consumer_group=str(consumer_group),
            heartbeat_consumer_group=str(heartbeat_consumer_group or "").strip(),
            heartbeat_consumer_name=str(heartbeat_consumer_name or "").strip(),
            lookback_sec=max(1, int(resolved_lookback_sec)),
            sample_count=max(1, int(resolved_sample_count)),
            min_latency_samples=max(1, int(min_latency_samples)),
            min_window_sec=max(1, int(min_window_sec)),
            sustained_window_sec=max(1, int(resolved_sustained_window_sec)),
            min_instance_coverage=max(1, int(min_instance_coverage)),
            enforce_budget_checks=True,
            min_throughput_cmds_per_sec=max(0.0, float(min_throughput_cmds_per_sec)),
            max_latency_p95_ms=max(0.0, float(max_latency_p95_ms)),
            max_latency_p99_ms=max(0.0, float(max_latency_p99_ms)),
            max_backlog_growth_pct_per_10min=max(0.0, float(max_backlog_growth_pct_per_10min)),
            max_restart_count=max(0.0, float(max_restart_count)),
            load_run_id=str(harness_run_id),
        )
        load_path = root / "reports" / "verification" / "paper_exchange_load_latest.json"
        load_report = _read_json(load_path)
    else:
        load_rc = 2
        load_report = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "failed_checks": ["missing_load_harness_run_id"],
            "metrics": {
                "p1_19_sustained_window_qualification_rate_pct": 0.0,
                "p1_19_command_instance_coverage_count": 0.0,
            },
            "diagnostics": {
                "error": "missing_load_harness_run_id",
                "load_run_id": "",
                "budget_checks_enforced": False,
                "budget_failed_checks": ["missing_load_harness_run_id"],
            },
        }

    report = build_report(
        profile=profile,
        harness_rc=int(harness_rc),
        load_rc=int(load_rc),
        harness_report=harness_report,
        load_report=load_report,
    )

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_exchange_sustained_qualification_{stamp}.json"
    latest_path = out_dir / "paper_exchange_sustained_qualification_latest.json"
    payload = json.dumps(report, indent=2)
    out_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    print(
        "[paper-exchange-sustained-qualification] "
        f"status={report.get('status')} "
        f"run_id={report.get('diagnostics', {}).get('harness_run_id', '')!s}"
    )
    print(f"[paper-exchange-sustained-qualification] evidence={out_path}")
    if strict and str(report.get("status", "fail")).strip().lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run sustained paper-exchange load qualification and emit consolidated evidence."
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when sustained qualification fails.")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-password", default=os.getenv("REDIS_PASSWORD", ""))
    parser.add_argument(
        "--command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", PAPER_EXCHANGE_COMMAND_STREAM),
        help="Paper-exchange command stream.",
    )
    parser.add_argument(
        "--event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", PAPER_EXCHANGE_EVENT_STREAM),
        help="Paper-exchange event stream.",
    )
    parser.add_argument(
        "--heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", PAPER_EXCHANGE_HEARTBEAT_STREAM),
        help="Paper-exchange heartbeat stream.",
    )
    parser.add_argument(
        "--consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by paper-exchange service for command processing.",
    )
    parser.add_argument(
        "--heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for restart diagnostics.",
    )
    parser.add_argument(
        "--heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for restart diagnostics.",
    )
    parser.add_argument(
        "--producer",
        default=_default_harness_producer(),
        help="Producer used by load harness commands.",
    )
    parser.add_argument(
        "--instance-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAME", "bot1"),
        help="Fallback single instance name if instance_names is empty.",
    )
    parser.add_argument(
        "--instance-names",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAMES", "bot1,bot3,bot4"),
        help="Comma-separated instance names for sustained profile command injection.",
    )
    parser.add_argument(
        "--connector-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_CONNECTOR_NAME", "bitget_perpetual"),
        help="Connector name used by harness commands.",
    )
    parser.add_argument(
        "--trading-pair",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TRADING_PAIR", "BTC-USDT"),
        help="Trading pair used by harness commands.",
    )
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_DURATION_SEC", "7200")),
        help="Sustained qualification harness duration in seconds (default: 2h).",
    )
    parser.add_argument(
        "--target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_TARGET_CMD_RATE", "60")),
        help="Target command publish rate during sustained run.",
    )
    parser.add_argument(
        "--min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_COMMANDS", "0")),
        help="Minimum commands required by harness (<=0 auto-derives from duration * rate).",
    )
    parser.add_argument(
        "--command-maxlen",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_COMMAND_MAXLEN", "0")),
        help="Command stream maxlen for harness writes (<=0 auto-derives sustained-safe size).",
    )
    parser.add_argument(
        "--result-timeout-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_RESULT_TIMEOUT_SEC", "30")),
        help="Timeout waiting for command results after command injection.",
    )
    parser.add_argument(
        "--poll-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_POLL_INTERVAL_MS", "300")),
        help="Polling interval for harness result collection.",
    )
    parser.add_argument(
        "--scan-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_SCAN_COUNT", "20000")),
        help="Rows scanned by harness when matching command results.",
    )
    parser.add_argument(
        "--require-heartbeat-fresh",
        action="store_true",
        default=True,
        help="Require fresh heartbeat before running sustained harness.",
    )
    parser.add_argument(
        "--no-require-heartbeat-fresh",
        action="store_false",
        dest="require_heartbeat_fresh",
        help="Skip heartbeat freshness requirement before sustained harness.",
    )
    parser.add_argument(
        "--heartbeat-max-age-s",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_HEARTBEAT_MAX_AGE_S", "30")),
        help="Max heartbeat age accepted before sustained run.",
    )
    parser.add_argument(
        "--min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_INSTANCE_COVERAGE", "3")),
        help="Minimum unique instance coverage required for sustained qualification.",
    )
    parser.add_argument(
        "--min-publish-success-rate-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_PUBLISH_SUCCESS_RATE_PCT", "99")),
        help="Minimum harness publish success rate required.",
    )
    parser.add_argument(
        "--min-result-match-rate-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_RESULT_MATCH_RATE_PCT", "99")),
        help="Minimum harness command/result match rate required.",
    )
    parser.add_argument(
        "--lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_LOOKBACK_SEC", "0")),
        help="Load checker lookback window (<=0 auto-derives as duration + 600s).",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_SAMPLE_COUNT", "0")),
        help="Load checker sample count (<=0 auto-derives sustained-safe size).",
    )
    parser.add_argument(
        "--min-latency-samples",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_LATENCY_SAMPLES", "200")),
        help="Minimum matched samples required by load checker.",
    )
    parser.add_argument(
        "--min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command window required by load checker.",
    )
    parser.add_argument(
        "--sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_WINDOW_SEC", "0")),
        help="Sustained qualification window for load checker (<=0 defaults to duration-sec).",
    )
    parser.add_argument(
        "--min-throughput-cmds-per-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MIN_THROUGHPUT_CMDS_PER_SEC", "50")),
        help="Minimum throughput budget for load checker.",
    )
    parser.add_argument(
        "--max-latency-p95-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P95_MS", "500")),
        help="Maximum p95 latency budget for load checker.",
    )
    parser.add_argument(
        "--max-latency-p99-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P99_MS", "1000")),
        help="Maximum p99 latency budget for load checker.",
    )
    parser.add_argument(
        "--max-backlog-growth-pct-per-10min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_BACKLOG_GROWTH_PCT_PER_10MIN", "1")),
        help="Maximum backlog growth budget for load checker.",
    )
    parser.add_argument(
        "--max-restart-count",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_RESTART_COUNT", "0")),
        help="Maximum restart-count budget for load checker.",
    )
    args = parser.parse_args()

    return run_sustained_qualification(
        strict=bool(args.strict),
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password),
        command_stream=str(args.command_stream),
        event_stream=str(args.event_stream),
        heartbeat_stream=str(args.heartbeat_stream),
        consumer_group=str(args.consumer_group),
        heartbeat_consumer_group=str(args.heartbeat_consumer_group or ""),
        heartbeat_consumer_name=str(args.heartbeat_consumer_name or ""),
        producer=str(args.producer),
        instance_name=str(args.instance_name),
        instance_names=str(args.instance_names),
        connector_name=str(args.connector_name),
        trading_pair=str(args.trading_pair),
        duration_sec=max(0.1, float(args.duration_sec)),
        target_cmd_rate=max(1.0, float(args.target_cmd_rate)),
        min_commands=int(args.min_commands),
        command_maxlen=int(args.command_maxlen),
        result_timeout_sec=max(0.0, float(args.result_timeout_sec)),
        poll_interval_ms=max(10, int(args.poll_interval_ms)),
        scan_count=max(100, int(args.scan_count)),
        require_heartbeat_fresh=bool(args.require_heartbeat_fresh),
        heartbeat_max_age_s=max(1.0, float(args.heartbeat_max_age_s)),
        min_instance_coverage=max(1, int(args.min_instance_coverage)),
        min_publish_success_rate_pct=max(0.0, min(100.0, float(args.min_publish_success_rate_pct))),
        min_result_match_rate_pct=max(0.0, min(100.0, float(args.min_result_match_rate_pct))),
        lookback_sec=int(args.lookback_sec),
        sample_count=int(args.sample_count),
        min_latency_samples=max(1, int(args.min_latency_samples)),
        min_window_sec=max(1, int(args.min_window_sec)),
        sustained_window_sec=int(args.sustained_window_sec),
        min_throughput_cmds_per_sec=max(0.0, float(args.min_throughput_cmds_per_sec)),
        max_latency_p95_ms=max(0.0, float(args.max_latency_p95_ms)),
        max_latency_p99_ms=max(0.0, float(args.max_latency_p99_ms)),
        max_backlog_growth_pct_per_10min=max(0.0, float(args.max_backlog_growth_pct_per_10min)),
        max_restart_count=max(0.0, float(args.max_restart_count)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
