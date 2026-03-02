#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from services.contracts.stream_names import (
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _stream_id_ms(stream_id: object) -> int:
    text = str(stream_id or "")
    if "-" not in text:
        return 0
    return _safe_int(text.split("-", 1)[0], 0)


def _decode_stream_payload(data: Dict[str, object]) -> Dict[str, object]:
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


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(max(0, min(len(sorted_vals) - 1, (len(sorted_vals) - 1) * p)))
    return float(sorted_vals[idx])


def _heartbeat_info(r: Any, heartbeat_stream: str, now_ms: int) -> Dict[str, object]:
    try:
        rows = r.xrevrange(heartbeat_stream, "+", "-", count=1)
    except Exception as exc:
        return {
            "present": False,
            "timestamp_ms": 0,
            "age_s": 1e9,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not rows:
        return {"present": False, "timestamp_ms": 0, "age_s": 1e9, "error": ""}
    stream_id, data = rows[0]
    payload = _decode_stream_payload(data if isinstance(data, dict) else {})
    ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
    age_s = max(0.0, (float(now_ms) - float(ts_ms)) / 1000.0) if ts_ms > 0 else 1e9
    return {
        "present": ts_ms > 0,
        "timestamp_ms": int(ts_ms),
        "age_s": float(age_s),
        "error": "",
    }


def _build_sync_state_command(
    *,
    event_id: str,
    producer: str,
    timestamp_ms: int,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    run_id: str,
) -> Dict[str, object]:
    return {
        "schema_version": "1.0",
        "event_type": "paper_exchange_command",
        "event_id": event_id,
        "producer": str(producer),
        "timestamp_ms": int(timestamp_ms),
        "instance_name": str(instance_name),
        "command": "sync_state",
        "connector_name": str(connector_name),
        "trading_pair": str(trading_pair),
        "metadata": {
            "load_harness": "1",
            "load_run_id": str(run_id),
        },
    }


def _publish_sync_state_burst(
    *,
    r: Any,
    command_stream: str,
    maxlen: Optional[int],
    run_id: str,
    duration_sec: float,
    target_cmd_rate: float,
    producer: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
) -> Dict[str, object]:
    start_perf = time.perf_counter()
    end_perf = start_perf + max(0.1, float(duration_sec))
    interval_s = 1.0 / max(1.0, float(target_cmd_rate))

    sent_ts_by_event_id: Dict[str, int] = {}
    publish_failures = 0
    seq = 0
    next_emit = start_perf
    while True:
        now_perf = time.perf_counter()
        if now_perf >= end_perf:
            break
        if now_perf < next_emit:
            time.sleep(min(0.005, max(0.0, next_emit - now_perf)))
            continue
        event_id = f"pe-load-{run_id}-{seq}"
        ts_ms = int(time.time() * 1000)
        payload = _build_sync_state_command(
            event_id=event_id,
            producer=producer,
            timestamp_ms=ts_ms,
            instance_name=instance_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
            run_id=run_id,
        )
        body = {"payload": json.dumps(payload)}
        kwargs: Dict[str, object] = {"name": command_stream, "fields": body}
        if maxlen is not None:
            kwargs["maxlen"] = int(maxlen)
            kwargs["approximate"] = True
        try:
            result = r.xadd(**kwargs)
            if result is None:
                publish_failures += 1
            else:
                sent_ts_by_event_id[event_id] = ts_ms
        except Exception:
            publish_failures += 1
        seq += 1
        next_emit += interval_s

    elapsed_sec = max(1e-6, time.perf_counter() - start_perf)
    return {
        "sent_ts_by_event_id": sent_ts_by_event_id,
        "publish_failures": int(publish_failures),
        "elapsed_sec": float(elapsed_sec),
    }


def _collect_result_ts_by_command_id(
    *,
    r: Any,
    event_stream: str,
    sent_ts_by_event_id: Dict[str, int],
    timeout_sec: float,
    poll_interval_ms: int,
    scan_count: int,
) -> Dict[str, int]:
    pending = set(sent_ts_by_event_id.keys())
    matched_ts_by_id: Dict[str, int] = {}
    deadline = time.time() + max(0.0, float(timeout_sec))
    while pending and time.time() < deadline:
        try:
            rows = r.xrevrange(event_stream, "+", "-", count=max(1, int(scan_count)))
        except Exception:
            rows = []
        for stream_id, data in rows:
            payload = _decode_stream_payload(data if isinstance(data, dict) else {})
            command_event_id = str(payload.get("command_event_id", "")).strip()
            if command_event_id not in pending:
                continue
            ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
            if ts_ms <= 0:
                continue
            existing = matched_ts_by_id.get(command_event_id)
            matched_ts_by_id[command_event_id] = ts_ms if existing is None else min(existing, ts_ms)
        pending = {event_id for event_id in pending if event_id not in matched_ts_by_id}
        if pending:
            time.sleep(max(0.01, float(poll_interval_ms) / 1000.0))
    return matched_ts_by_id


def build_report(
    root: Path,
    *,
    redis_client: Optional[Any],
    command_stream: str,
    event_stream: str,
    heartbeat_stream: str,
    command_maxlen: int,
    duration_sec: float,
    target_cmd_rate: float,
    producer: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    result_timeout_sec: float,
    poll_interval_ms: int,
    scan_count: int,
    require_heartbeat_fresh: bool,
    heartbeat_max_age_s: float,
    min_commands: int,
    min_publish_success_rate_pct: float,
    min_result_match_rate_pct: float,
) -> Dict[str, object]:
    now_ms = int(time.time() * 1000)
    redis_ok = redis_client is not None
    heartbeat = (
        _heartbeat_info(redis_client, heartbeat_stream, now_ms)
        if redis_client is not None
        else {"present": False, "timestamp_ms": 0, "age_s": 1e9, "error": "redis_client_unavailable"}
    )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    publish_result = {
        "sent_ts_by_event_id": {},
        "publish_failures": 0,
        "elapsed_sec": 0.0,
    }
    result_ts_by_command_id: Dict[str, int] = {}
    if redis_client is not None:
        publish_result = _publish_sync_state_burst(
            r=redis_client,
            command_stream=command_stream,
            maxlen=int(command_maxlen) if command_maxlen > 0 else None,
            run_id=run_id,
            duration_sec=float(duration_sec),
            target_cmd_rate=float(target_cmd_rate),
            producer=producer,
            instance_name=instance_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
        )
        sent_ts_by_event_id = publish_result["sent_ts_by_event_id"]
        if isinstance(sent_ts_by_event_id, dict) and sent_ts_by_event_id:
            result_ts_by_command_id = _collect_result_ts_by_command_id(
                r=redis_client,
                event_stream=event_stream,
                sent_ts_by_event_id=sent_ts_by_event_id,
                timeout_sec=float(result_timeout_sec),
                poll_interval_ms=int(poll_interval_ms),
                scan_count=int(scan_count),
            )

    sent_ts = publish_result["sent_ts_by_event_id"]
    sent_ts = sent_ts if isinstance(sent_ts, dict) else {}
    published_count = len(sent_ts)
    publish_failures = _safe_int(publish_result.get("publish_failures"), 0)
    elapsed_sec = max(1e-6, _safe_float(publish_result.get("elapsed_sec"), 0.0))

    matched_ids = sorted(set(sent_ts.keys()) & set(result_ts_by_command_id.keys()))
    latencies_ms = sorted(
        [
            float(max(0, int(result_ts_by_command_id[event_id]) - int(sent_ts[event_id])))
            for event_id in matched_ids
        ]
    )
    matched_count = len(matched_ids)
    attempted_count = published_count + publish_failures
    publish_success_rate_pct = (100.0 * float(published_count) / float(attempted_count)) if attempted_count > 0 else 0.0
    result_match_rate_pct = (100.0 * float(matched_count) / float(published_count)) if published_count > 0 else 0.0
    achieved_publish_rate = float(published_count) / float(elapsed_sec)

    checks = {
        "redis_connected": bool(redis_ok),
        "heartbeat_recent": (
            (not require_heartbeat_fresh)
            or (bool(heartbeat.get("present", False)) and float(heartbeat.get("age_s", 1e9)) <= heartbeat_max_age_s)
        ),
        "min_commands_published": int(published_count) >= int(max(1, min_commands)),
        "publish_success_rate": float(publish_success_rate_pct) >= float(min_publish_success_rate_pct),
        "result_match_rate": float(result_match_rate_pct) >= float(min_result_match_rate_pct),
    }
    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    status = "pass" if not failed_checks else "fail"

    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "metrics": {
            "published_commands": int(published_count),
            "publish_failures": int(publish_failures),
            "publish_success_rate_pct": float(publish_success_rate_pct),
            "matched_results": int(matched_count),
            "result_match_rate_pct": float(result_match_rate_pct),
            "achieved_publish_rate_cmds_per_sec": float(achieved_publish_rate),
            "latency_p95_ms": float(_percentile(latencies_ms, 0.95)) if latencies_ms else 0.0,
            "latency_p99_ms": float(_percentile(latencies_ms, 0.99)) if latencies_ms else 0.0,
            "latency_samples": int(len(latencies_ms)),
        },
        "diagnostics": {
            "run_id": run_id,
            "duration_sec": float(duration_sec),
            "target_cmd_rate": float(target_cmd_rate),
            "command_stream": command_stream,
            "event_stream": event_stream,
            "heartbeat_stream": heartbeat_stream,
            "instance_name": instance_name,
            "connector_name": connector_name,
            "trading_pair": trading_pair,
            "producer": producer,
            "heartbeat": heartbeat,
            "result_timeout_sec": float(result_timeout_sec),
            "poll_interval_ms": int(poll_interval_ms),
            "scan_count": int(scan_count),
            "required_heartbeat_fresh": bool(require_heartbeat_fresh),
            "heartbeat_max_age_s": float(heartbeat_max_age_s),
            "min_commands": int(min_commands),
            "min_publish_success_rate_pct": float(min_publish_success_rate_pct),
            "min_result_match_rate_pct": float(min_result_match_rate_pct),
            "output_root": str(root),
        },
    }


def run_harness(
    *,
    strict: bool,
    redis_host: str,
    redis_port: int,
    redis_db: int,
    redis_password: str,
    command_stream: str,
    event_stream: str,
    heartbeat_stream: str,
    command_maxlen: int,
    duration_sec: float,
    target_cmd_rate: float,
    producer: str,
    instance_name: str,
    connector_name: str,
    trading_pair: str,
    result_timeout_sec: float,
    poll_interval_ms: int,
    scan_count: int,
    require_heartbeat_fresh: bool,
    heartbeat_max_age_s: float,
    min_commands: int,
    min_publish_success_rate_pct: float,
    min_result_match_rate_pct: float,
) -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]

    redis_client: Optional[Any] = None
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
        command_stream=command_stream,
        event_stream=event_stream,
        heartbeat_stream=heartbeat_stream,
        command_maxlen=int(command_maxlen),
        duration_sec=float(duration_sec),
        target_cmd_rate=float(target_cmd_rate),
        producer=producer,
        instance_name=instance_name,
        connector_name=connector_name,
        trading_pair=trading_pair,
        result_timeout_sec=float(result_timeout_sec),
        poll_interval_ms=int(poll_interval_ms),
        scan_count=int(scan_count),
        require_heartbeat_fresh=bool(require_heartbeat_fresh),
        heartbeat_max_age_s=float(heartbeat_max_age_s),
        min_commands=int(min_commands),
        min_publish_success_rate_pct=float(min_publish_success_rate_pct),
        min_result_match_rate_pct=float(min_result_match_rate_pct),
    )
    if redis_error:
        report["redis_client_error"] = redis_error
        report["status"] = "fail"
        failed = report.get("failed_checks", [])
        if isinstance(failed, list) and "redis_connected" not in failed:
            failed.append("redis_connected")
            report["failed_checks"] = sorted(str(x) for x in failed)

    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"paper_exchange_load_harness_{stamp}.json"
    latest_path = out_dir / "paper_exchange_load_harness_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        "[paper-exchange-load-harness] "
        f"status={report.get('status')} "
        f"published={report.get('metrics', {}).get('published_commands', 0)} "
        f"matched={report.get('metrics', {}).get('matched_results', 0)}"
    )
    print(f"[paper-exchange-load-harness] evidence={out_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic paper-exchange command load harness.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when harness checks fail.")
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
        "--command-maxlen",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_COMMAND_STREAM_MAXLEN", "100000")),
        help="Approximate maxlen for harness-injected command stream rows.",
    )
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_DURATION_SEC", "20")),
        help="Duration of synthetic command injection.",
    )
    parser.add_argument(
        "--target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TARGET_CMD_RATE", "60")),
        help="Target publish command rate for sync_state commands.",
    )
    parser.add_argument(
        "--producer",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_PRODUCER", "hb_bridge_active_adapter"),
        help="Producer name used by harness commands.",
    )
    parser.add_argument(
        "--instance-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAME", "bot1"),
        help="Instance name used by harness commands.",
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
        "--result-timeout-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_RESULT_TIMEOUT_SEC", "30")),
        help="Timeout waiting for paper_exchange_event results.",
    )
    parser.add_argument(
        "--poll-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_POLL_INTERVAL_MS", "300")),
        help="Polling interval when collecting command results.",
    )
    parser.add_argument(
        "--scan-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_SCAN_COUNT", "20000")),
        help="Rows scanned from event stream during result collection.",
    )
    parser.add_argument(
        "--require-heartbeat-fresh",
        action="store_true",
        default=True,
        help="Require fresh paper-exchange heartbeat before load run.",
    )
    parser.add_argument(
        "--no-require-heartbeat-fresh",
        action="store_false",
        dest="require_heartbeat_fresh",
        help="Skip heartbeat freshness requirement before load run.",
    )
    parser.add_argument(
        "--heartbeat-max-age-s",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_HEARTBEAT_MAX_AGE_S", "30")),
        help="Maximum heartbeat age when freshness is required.",
    )
    parser.add_argument(
        "--min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_COMMANDS", "300")),
        help="Minimum published commands required for pass-grade evidence.",
    )
    parser.add_argument(
        "--min-publish-success-rate-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_PUBLISH_SUCCESS_RATE_PCT", "99.0")),
        help="Minimum publish success rate for pass-grade evidence.",
    )
    parser.add_argument(
        "--min-result-match-rate-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_RESULT_MATCH_RATE_PCT", "99.0")),
        help="Minimum command/result match rate for pass-grade evidence.",
    )
    args = parser.parse_args()

    return run_harness(
        strict=bool(args.strict),
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password),
        command_stream=str(args.command_stream),
        event_stream=str(args.event_stream),
        heartbeat_stream=str(args.heartbeat_stream),
        command_maxlen=max(1, int(args.command_maxlen)),
        duration_sec=max(0.1, float(args.duration_sec)),
        target_cmd_rate=max(1.0, float(args.target_cmd_rate)),
        producer=str(args.producer),
        instance_name=str(args.instance_name),
        connector_name=str(args.connector_name),
        trading_pair=str(args.trading_pair),
        result_timeout_sec=max(0.0, float(args.result_timeout_sec)),
        poll_interval_ms=max(10, int(args.poll_interval_ms)),
        scan_count=max(100, int(args.scan_count)),
        require_heartbeat_fresh=bool(args.require_heartbeat_fresh),
        heartbeat_max_age_s=max(1.0, float(args.heartbeat_max_age_s)),
        min_commands=max(1, int(args.min_commands)),
        min_publish_success_rate_pct=max(0.0, min(100.0, float(args.min_publish_success_rate_pct))),
        min_result_match_rate_pct=max(0.0, min(100.0, float(args.min_result_match_rate_pct))),
    )


if __name__ == "__main__":
    raise SystemExit(main())
