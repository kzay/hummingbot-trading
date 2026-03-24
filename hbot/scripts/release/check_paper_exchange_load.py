#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from platform_lib.contracts.stream_names import (
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
)

MISSING_LATENCY_SENTINEL_MS = 10_000_000.0
MISSING_BACKLOG_GROWTH_SENTINEL_PCT = 1_000.0
MISSING_RESTART_SENTINEL_COUNT = 999


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


def _decode_stream_payload(data: dict[str, object]) -> dict[str, object]:
    payload = data.get("payload")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _stream_id_ms(stream_id: object) -> int:
    text = str(stream_id or "")
    if "-" not in text:
        return 0
    return _safe_int(text.split("-", 1)[0], 0)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(max(0, min(len(sorted_vals) - 1, (len(sorted_vals) - 1) * p)))
    return float(sorted_vals[idx])


def _parse_xinfo_groups(raw: object) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name", ""))
            if not name:
                continue
            out[name] = {
                "lag": _safe_int(item.get("lag"), -1),
                "pending": _safe_int(item.get("pending"), -1),
            }
            continue
        if isinstance(item, (list, tuple)):
            try:
                mapped = {item[i]: item[i + 1] for i in range(0, len(item), 2)}
                name = str(mapped.get("name", ""))
                if not name:
                    continue
                out[name] = {
                    "lag": _safe_int(mapped.get("lag"), -1),
                    "pending": _safe_int(mapped.get("pending"), -1),
                }
            except Exception:
                continue
    return out


def _extract_command_timestamps(
    rows: Iterable[tuple[object, dict[str, object]]],
    *,
    cutoff_ms: int,
    load_run_id: str = "",
) -> tuple[dict[str, int], dict[str, int]]:
    out: dict[str, int] = {}
    counts_by_instance: dict[str, int] = {}
    run_id_filter = str(load_run_id or "").strip()
    for stream_id, data in rows:
        payload = _decode_stream_payload(data if isinstance(data, dict) else {})
        if str(payload.get("event_type", "")).strip() not in {"paper_exchange_command", ""}:
            continue
        if run_id_filter:
            metadata = payload.get("metadata", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            row_run_id = str(metadata.get("load_run_id", "")).strip()
            if row_run_id != run_id_filter:
                continue
        event_id = str(payload.get("event_id", "")).strip()
        if not event_id:
            continue
        ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
        if ts_ms < cutoff_ms:
            continue
        out[event_id] = max(_safe_int(out.get(event_id), 0), ts_ms)
        instance_name = str(payload.get("instance_name", "")).strip() or "__unknown__"
        counts_by_instance[instance_name] = int(counts_by_instance.get(instance_name, 0)) + 1
    return out, counts_by_instance


def _extract_result_timestamps(
    rows: Iterable[tuple[object, dict[str, object]]],
    *,
    cutoff_ms: int,
) -> dict[str, int]:
    out: dict[str, int] = {}
    for stream_id, data in rows:
        payload = _decode_stream_payload(data if isinstance(data, dict) else {})
        if str(payload.get("event_type", "")).strip() not in {"paper_exchange_event", ""}:
            continue
        command_event_id = str(payload.get("command_event_id", "")).strip()
        if not command_event_id:
            continue
        ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
        if ts_ms < cutoff_ms:
            continue
        previous = out.get(command_event_id)
        out[command_event_id] = ts_ms if previous is None else min(previous, ts_ms)
    return out


def _extract_heartbeat_processed_counters(
    rows: Iterable[tuple[object, dict[str, object]]],
    *,
    cutoff_ms: int,
    window_start_ms: int | None = None,
    window_end_ms: int | None = None,
    consumer_group_filter: str = "",
    consumer_name_filter: str = "",
) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for stream_id, data in rows:
        payload = _decode_stream_payload(data if isinstance(data, dict) else {})
        if str(payload.get("event_type", "")).strip() not in {"paper_exchange_heartbeat", ""}:
            continue
        ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
        if ts_ms < cutoff_ms:
            continue
        if window_start_ms is not None and ts_ms < int(window_start_ms):
            continue
        if window_end_ms is not None and ts_ms > int(window_end_ms):
            continue
        metadata = payload.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        if str(consumer_group_filter or "").strip():
            row_group = str(metadata.get("consumer_group", "")).strip()
            if row_group != str(consumer_group_filter).strip():
                continue
        if str(consumer_name_filter or "").strip():
            row_name = str(metadata.get("consumer_name", "")).strip()
            if row_name != str(consumer_name_filter).strip():
                continue
        processed_commands = _safe_int(metadata.get("processed_commands"), -1)
        if processed_commands < 0:
            continue
        out.append((ts_ms, processed_commands))
    out.sort(key=lambda item: (item[0], item[1]))
    return out


def build_report(
    root: Path,
    *,
    now_ts: float | None = None,
    redis_client: Any | None = None,
    command_stream: str = PAPER_EXCHANGE_COMMAND_STREAM,
    event_stream: str = PAPER_EXCHANGE_EVENT_STREAM,
    heartbeat_stream: str = PAPER_EXCHANGE_HEARTBEAT_STREAM,
    consumer_group: str = "hb_group_paper_exchange",
    heartbeat_consumer_group: str = "",
    heartbeat_consumer_name: str = "",
    lookback_sec: int = 600,
    sample_count: int = 8000,
    min_latency_samples: int = 200,
    min_window_sec: int = 120,
    sustained_window_sec: int = 0,
    min_instance_coverage: int = 1,
    enforce_budget_checks: bool = False,
    min_throughput_cmds_per_sec: float = 50.0,
    max_latency_p95_ms: float = 500.0,
    max_latency_p99_ms: float = 1000.0,
    max_backlog_growth_pct_per_10min: float = 1.0,
    max_restart_count: float = 0.0,
    load_run_id: str = "",
) -> dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    now_ms = int(now_ts * 1000)
    cutoff_ms = now_ms - max(1, int(lookback_sec)) * 1000

    redis_ok = redis_client is not None
    redis_error = ""
    command_rows: list[tuple[object, dict[str, object]]] = []
    result_rows: list[tuple[object, dict[str, object]]] = []
    heartbeat_rows: list[tuple[object, dict[str, object]]] = []
    group_stats: dict[str, dict[str, int]] = {}
    if redis_client is not None:
        try:
            command_rows = redis_client.xrevrange(command_stream, "+", "-", count=max(1, int(sample_count)))
            result_rows = redis_client.xrevrange(event_stream, "+", "-", count=max(1, int(sample_count)))
            heartbeat_rows = redis_client.xrevrange(heartbeat_stream, "+", "-", count=max(1, int(sample_count)))
            raw_groups = redis_client.execute_command("XINFO", "GROUPS", command_stream)
            group_stats = _parse_xinfo_groups(raw_groups)
        except Exception as exc:
            redis_ok = False
            redis_error = f"{type(exc).__name__}: {exc}"
    else:
        redis_ok = False
        redis_error = "redis_client_unavailable"

    command_ts_by_id, command_count_by_instance = _extract_command_timestamps(
        command_rows,
        cutoff_ms=cutoff_ms,
        load_run_id=str(load_run_id or "").strip(),
    )
    result_ts_by_cmd = _extract_result_timestamps(result_rows, cutoff_ms=cutoff_ms)
    matched_command_ids = sorted(set(command_ts_by_id.keys()) & set(result_ts_by_cmd.keys()))
    latency_ms_values = sorted(
        [
            float(max(0, int(result_ts_by_cmd[command_id]) - int(command_ts_by_id[command_id])))
            for command_id in matched_command_ids
        ]
    )

    command_window_start_ms: int | None = None
    command_window_end_ms: int | None = None
    if command_ts_by_id:
        command_ts_vals = sorted(command_ts_by_id.values())
        window_sec = max(1.0, (float(command_ts_vals[-1]) - float(command_ts_vals[0])) / 1000.0)
        command_window_start_ms = int(command_ts_vals[0])
        command_window_end_ms = int(command_ts_vals[-1])
    else:
        window_sec = 0.0

    command_count = len(command_ts_by_id)
    instance_coverage_count = sum(1 for count in command_count_by_instance.values() if _safe_int(count, 0) > 0)
    processed_count = len(matched_command_ids)
    requested_sustained_window_sec = int(_safe_int(sustained_window_sec, 0))
    required_sustained_window_sec = (
        max(1, requested_sustained_window_sec)
        if requested_sustained_window_sec > 0
        else max(1, int(min_window_sec))
    )

    heartbeat_window_start_ms = command_window_start_ms
    heartbeat_window_end_ms = (
        int(command_window_end_ms + 30_000) if command_window_end_ms is not None else None
    )
    heartbeat_samples = _extract_heartbeat_processed_counters(
        heartbeat_rows,
        cutoff_ms=cutoff_ms,
        window_start_ms=heartbeat_window_start_ms,
        window_end_ms=heartbeat_window_end_ms,
        consumer_group_filter=str(heartbeat_consumer_group or "").strip(),
        consumer_name_filter=str(heartbeat_consumer_name or "").strip(),
    )
    restart_count = 0
    if heartbeat_samples:
        prev = heartbeat_samples[0][1]
        for _ts_ms, current in heartbeat_samples[1:]:
            if int(current) < int(prev):
                restart_count += 1
            prev = current
    else:
        restart_count = MISSING_RESTART_SENTINEL_COUNT

    processed_count_from_results = len(matched_command_ids)
    processed_count_effective = int(processed_count_from_results)
    if window_sec <= 0 or command_count <= 0:
        backlog_growth_rate_pct_per_10min = MISSING_BACKLOG_GROWTH_SENTINEL_PCT
    else:
        imbalance = max(0.0, float(command_count - processed_count_effective))
        backlog_growth_rate_pct_per_10min = (
            (imbalance / max(1.0, float(processed_count_effective))) * (600.0 / max(1.0, window_sec)) * 100.0
        )

    metrics = {
        "p1_19_sustained_command_throughput_cmds_per_sec": (
            float(processed_count_effective) / float(window_sec) if window_sec > 0 else 0.0
        ),
        "p1_19_command_latency_under_load_p95_ms": (
            float(_percentile(latency_ms_values, 0.95)) if latency_ms_values else MISSING_LATENCY_SENTINEL_MS
        ),
        "p1_19_command_latency_under_load_p99_ms": (
            float(_percentile(latency_ms_values, 0.99)) if latency_ms_values else MISSING_LATENCY_SENTINEL_MS
        ),
        "p1_19_stream_backlog_growth_rate_pct_per_10min": float(backlog_growth_rate_pct_per_10min),
        "p1_19_stress_window_oom_restart_count": float(restart_count),
        "p1_19_command_instance_coverage_count": float(instance_coverage_count),
        "p1_19_sustained_window_observed_sec": float(window_sec),
        "p1_19_sustained_window_required_sec": float(required_sustained_window_sec),
        "p1_19_sustained_window_qualification_rate_pct": (
            100.0 if (float(window_sec) + 1.0) >= float(required_sustained_window_sec) else 0.0
        ),
    }
    sustained_window_qualified = bool(metrics["p1_19_sustained_window_qualification_rate_pct"] >= 100.0)
    throughput_cmds_per_sec = float(metrics["p1_19_sustained_command_throughput_cmds_per_sec"])
    checks = {
        "redis_connected": bool(redis_ok),
        "consumer_group_present": str(consumer_group or "").strip() in group_stats,
        "minimum_instance_coverage": int(instance_coverage_count) >= int(max(1, min_instance_coverage)),
        "minimum_command_samples": int(command_count) >= int(max(1, min_latency_samples)),
        "minimum_latency_samples": len(latency_ms_values) >= int(max(1, min_latency_samples)),
        "minimum_window_seconds": (float(window_sec) + 1.0) >= float(max(1, min_window_sec)),
        "minimum_sustained_window_seconds": bool(sustained_window_qualified),
        "heartbeat_samples_present": len(heartbeat_samples) > 0,
    }
    budget_checks: dict[str, bool] = {}
    if bool(enforce_budget_checks):
        budget_checks = {
            "throughput_within_budget": float(throughput_cmds_per_sec) >= float(min_throughput_cmds_per_sec),
            "latency_p95_within_budget": float(metrics["p1_19_command_latency_under_load_p95_ms"])
            <= float(max_latency_p95_ms),
            "latency_p99_within_budget": float(metrics["p1_19_command_latency_under_load_p99_ms"])
            <= float(max_latency_p99_ms),
            "backlog_growth_within_budget": float(backlog_growth_rate_pct_per_10min)
            <= float(max_backlog_growth_pct_per_10min),
            "restart_count_within_budget": float(restart_count) <= float(max_restart_count),
        }
        checks.update(budget_checks)
    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    status = "pass" if len(failed_checks) == 0 else ("fail" if bool(enforce_budget_checks) else "warning")

    current_group = group_stats.get(str(consumer_group or "").strip(), {})
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "metrics": metrics,
        "diagnostics": {
            "lookback_sec": int(lookback_sec),
            "sample_count": int(sample_count),
            "load_run_id": str(load_run_id or ""),
            "command_stream": command_stream,
            "event_stream": event_stream,
            "heartbeat_stream": heartbeat_stream,
            "consumer_group": consumer_group,
            "heartbeat_consumer_group": str(heartbeat_consumer_group or "").strip(),
            "heartbeat_consumer_name": str(heartbeat_consumer_name or "").strip(),
            "window_sec": float(window_sec),
            "sustained_window_observed_sec": float(window_sec),
            "sustained_window_required_sec": float(required_sustained_window_sec),
            "sustained_window_qualified": bool(sustained_window_qualified),
            "window_start_ms": int(command_window_start_ms or 0),
            "window_end_ms": int(command_window_end_ms or 0),
            "command_count": int(command_count),
            "command_instance_coverage_count": int(instance_coverage_count),
            "command_count_by_instance": {
                str(name): int(_safe_int(count, 0))
                for name, count in command_count_by_instance.items()
                if str(name).strip()
            },
            "processed_count": int(processed_count_effective),
            "processed_count_from_result_matches": int(processed_count_from_results),
            "processed_count_effective": int(processed_count_effective),
            "matched_latency_samples": len(latency_ms_values),
            "heartbeat_sample_count": len(heartbeat_samples),
            "heartbeat_window_start_ms": int(heartbeat_window_start_ms or 0),
            "heartbeat_window_end_ms": int(heartbeat_window_end_ms or 0),
            "consumer_group_lag": _safe_int(current_group.get("lag"), -1),
            "consumer_group_pending": _safe_int(current_group.get("pending"), -1),
            "group_stats": group_stats,
            "redis_error": redis_error,
            "budget_checks_enforced": bool(enforce_budget_checks),
            "budget_thresholds": {
                "min_throughput_cmds_per_sec": float(min_throughput_cmds_per_sec),
                "max_latency_p95_ms": float(max_latency_p95_ms),
                "max_latency_p99_ms": float(max_latency_p99_ms),
                "max_backlog_growth_pct_per_10min": float(max_backlog_growth_pct_per_10min),
                "max_restart_count": float(max_restart_count),
                "min_instance_coverage": int(max(1, min_instance_coverage)),
            },
            "budget_failed_checks": sorted([name for name, ok in budget_checks.items() if not ok]),
        },
    }


def run_check(
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
    lookback_sec: int,
    sample_count: int,
    min_latency_samples: int,
    min_window_sec: int,
    sustained_window_sec: int,
    min_instance_coverage: int,
    enforce_budget_checks: bool,
    min_throughput_cmds_per_sec: float,
    max_latency_p95_ms: float,
    max_latency_p99_ms: float,
    max_backlog_growth_pct_per_10min: float,
    max_restart_count: float,
    load_run_id: str,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]

    redis_client: Any | None = None
    redis_error = ""
    if redis is None:
        redis_error = "redis_python_module_missing"
    else:
        try:
            redis_client = redis.Redis(
                host=redis_host,
                port=int(redis_port),
                db=int(redis_db),
                password=(redis_password or None),
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            redis_client.ping()
        except Exception as exc:
            redis_error = f"{type(exc).__name__}: {exc}"
            redis_client = None

    report = build_report(
        root=root,
        redis_client=redis_client,
        command_stream=str(command_stream),
        event_stream=str(event_stream),
        heartbeat_stream=str(heartbeat_stream),
        consumer_group=str(consumer_group),
        heartbeat_consumer_group=str(heartbeat_consumer_group or "").strip(),
        heartbeat_consumer_name=str(heartbeat_consumer_name or "").strip(),
        lookback_sec=int(lookback_sec),
        sample_count=int(sample_count),
        min_latency_samples=int(min_latency_samples),
        min_window_sec=int(min_window_sec),
        sustained_window_sec=int(sustained_window_sec),
        min_instance_coverage=int(min_instance_coverage),
        enforce_budget_checks=bool(enforce_budget_checks),
        min_throughput_cmds_per_sec=float(min_throughput_cmds_per_sec),
        max_latency_p95_ms=float(max_latency_p95_ms),
        max_latency_p99_ms=float(max_latency_p99_ms),
        max_backlog_growth_pct_per_10min=float(max_backlog_growth_pct_per_10min),
        max_restart_count=float(max_restart_count),
        load_run_id=str(load_run_id or ""),
    )
    if redis_error:
        report["redis_client_error"] = redis_error
        report["status"] = "fail" if bool(enforce_budget_checks) else "warning"
        failed = report.get("failed_checks", [])
        if isinstance(failed, list) and "redis_connected" not in failed:
            failed.append("redis_connected")
            report["failed_checks"] = sorted(str(x) for x in failed)

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_exchange_load_{stamp}.json"
    latest_path = out_dir / "paper_exchange_load_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        "[paper-exchange-load] "
        f"status={report.get('status')} "
        f"throughput={report.get('metrics', {}).get('p1_19_sustained_command_throughput_cmds_per_sec', 0)}"
    )
    print(f"[paper-exchange-load] evidence={out_path}")
    if strict and str(report.get("status", "warning")).lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper-exchange desk-scale load/backpressure validator.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when data quality checks fail.")
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
        help="Paper-exchange result event stream.",
    )
    parser.add_argument(
        "--heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", PAPER_EXCHANGE_HEARTBEAT_STREAM),
        help="Paper-exchange heartbeat stream.",
    )
    parser.add_argument(
        "--consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by paper-exchange service on command stream.",
    )
    parser.add_argument(
        "--heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for restart counter isolation.",
    )
    parser.add_argument(
        "--heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for restart counter isolation.",
    )
    parser.add_argument(
        "--lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_LOOKBACK_SEC", "600")),
        help="Load/stress window in seconds.",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SAMPLE_COUNT", "8000")),
        help="Max rows fetched per stream for window evaluation.",
    )
    parser.add_argument(
        "--min-latency-samples",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_LATENCY_SAMPLES", "200")),
        help="Minimum matched command/result samples required for pass-grade evidence.",
    )
    parser.add_argument(
        "--min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command observation window required for pass-grade evidence.",
    )
    parser.add_argument(
        "--sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SUSTAINED_WINDOW_SEC", "0")),
        help=(
            "Sustained qualification window required for p1_19 sustained-window metric. "
            "When <= 0, falls back to --min-window-sec."
        ),
    )
    parser.add_argument(
        "--min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_INSTANCE_COVERAGE", "1")),
        help="Minimum unique instance_name coverage required in command sample window.",
    )
    parser.add_argument(
        "--enforce-budget-checks",
        action="store_true",
        default=str(os.getenv("PAPER_EXCHANGE_LOAD_ENFORCE_BUDGET_CHECKS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable fail-fast budget checks for throughput/latency/backlog/restart thresholds.",
    )
    parser.add_argument(
        "--no-enforce-budget-checks",
        action="store_false",
        dest="enforce_budget_checks",
        help="Disable fail-fast budget checks.",
    )
    parser.add_argument(
        "--min-throughput-cmds-per-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MIN_THROUGHPUT_CMDS_PER_SEC", "50")),
        help="Minimum sustained throughput required when budget checks are enforced.",
    )
    parser.add_argument(
        "--max-latency-p95-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P95_MS", "500")),
        help="Maximum p95 command latency allowed when budget checks are enforced.",
    )
    parser.add_argument(
        "--max-latency-p99-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P99_MS", "1000")),
        help="Maximum p99 command latency allowed when budget checks are enforced.",
    )
    parser.add_argument(
        "--max-backlog-growth-pct-per-10min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_BACKLOG_GROWTH_PCT_PER_10MIN", "1")),
        help="Maximum backlog-growth rate allowed when budget checks are enforced.",
    )
    parser.add_argument(
        "--max-restart-count",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_RESTART_COUNT", "0")),
        help="Maximum restart-count allowed when budget checks are enforced.",
    )
    parser.add_argument(
        "--load-run-id",
        default=os.getenv("PAPER_EXCHANGE_LOAD_RUN_ID", ""),
        help="Optional load_harness run_id filter (metadata.load_run_id) for isolated metric windows.",
    )
    args = parser.parse_args()

    return run_check(
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
        lookback_sec=max(1, int(args.lookback_sec)),
        sample_count=max(1, int(args.sample_count)),
        min_latency_samples=max(1, int(args.min_latency_samples)),
        min_window_sec=max(1, int(args.min_window_sec)),
        sustained_window_sec=int(args.sustained_window_sec),
        min_instance_coverage=max(1, int(args.min_instance_coverage)),
        enforce_budget_checks=bool(args.enforce_budget_checks),
        min_throughput_cmds_per_sec=max(0.0, float(args.min_throughput_cmds_per_sec)),
        max_latency_p95_ms=max(0.0, float(args.max_latency_p95_ms)),
        max_latency_p99_ms=max(0.0, float(args.max_latency_p99_ms)),
        max_backlog_growth_pct_per_10min=max(0.0, float(args.max_backlog_growth_pct_per_10min)),
        max_restart_count=max(0.0, float(args.max_restart_count)),
        load_run_id=str(args.load_run_id or ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
