#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from platform_lib.contracts.stream_names import PAPER_EXCHANGE_HEARTBEAT_STREAM

DEFAULT_NON_CRITICAL_DEAD_LETTER_REASONS = [
    "local_authority_reject",
    "expired_intent",
]


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


def _parse_ts(ts_utc: str) -> datetime | None:
    s = (ts_utc or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
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


def _age_seconds_from_ts_or_mtime(ts_utc: str, path: Path, now_ts: float) -> float:
    dt = _parse_ts(ts_utc)
    if dt is not None:
        return max(0.0, now_ts - dt.timestamp())
    if path.exists():
        return max(0.0, now_ts - path.stat().st_mtime)
    return 1e9


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
                d = {item[i]: item[i + 1] for i in range(0, len(item), 2)}
                name = str(d.get("name", ""))
                if not name:
                    continue
                out[name] = {
                    "lag": _safe_int(d.get("lag"), -1),
                    "pending": _safe_int(d.get("pending"), -1),
                }
            except Exception:
                continue
    return out


def _dead_letter_stats(
    dead_rows: Iterable[tuple[object, dict[str, object]]],
    now_ms: int,
    lookback_sec: int,
    non_critical_reasons: Iterable[str],
) -> dict[str, object]:
    cutoff_ms = now_ms - max(1, int(lookback_sec)) * 1000
    allow = {str(x).strip().lower() for x in non_critical_reasons if str(x).strip()}
    reason_counts: Counter[str] = Counter()
    critical_count = 0
    scanned = 0
    in_window = 0
    latest_ts_ms = 0

    for stream_id, data in dead_rows:
        scanned += 1
        payload = _decode_stream_payload(data if isinstance(data, dict) else {})
        ts_ms = _safe_int(payload.get("timestamp_ms"), 0)
        if ts_ms <= 0:
            stream_id_str = str(stream_id)
            stream_ms = stream_id_str.split("-", 1)[0]
            ts_ms = _safe_int(stream_ms, 0)
        if ts_ms < cutoff_ms:
            continue
        in_window += 1
        if ts_ms > latest_ts_ms:
            latest_ts_ms = ts_ms
        reason = str(payload.get("reason", "unknown")).strip().lower() or "unknown"
        reason_counts[reason] += 1
        if reason not in allow:
            critical_count += 1

    return {
        "scanned": scanned,
        "in_lookback_window": in_window,
        "critical_count": critical_count,
        "reason_counts": dict(reason_counts),
        "latest_timestamp_ms": latest_ts_ms,
    }


def build_report(
    root: Path,
    *,
    now_ts: float | None = None,
    redis_client: Any | None = None,
    required_groups: list[str] | None = None,
    bots: list[str] | None = None,
    lookback_sec: int = 900,
    max_critical_dead_letters: int = 0,
    max_group_lag: int = 0,
    max_group_pending: int = 0,
    heartbeat_max_age_s: int = 120,
    snapshot_max_age_s: int = 180,
    dead_letter_scan_count: int = 5000,
    non_critical_dead_letter_reasons: list[str] | None = None,
    check_paper_exchange: bool = False,
    paper_exchange_heartbeat_stream: str = PAPER_EXCHANGE_HEARTBEAT_STREAM,
    paper_exchange_heartbeat_max_age_s: int = 30,
    max_paper_exchange_reject_rate_pct: float = 25.0,
    max_paper_exchange_stale_pairs: int = 0,
    paper_exchange_load_report_max_age_s: int = 1800,
    max_paper_exchange_backlog_growth_pct_per_10min: float = 5.0,
    max_paper_exchange_latency_p95_ms: float = 500.0,
    max_paper_exchange_latency_p99_ms: float = 1000.0,
) -> dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    now_ms = int(now_ts * 1000)
    required_groups = required_groups or ["hb_group_bot1", "hb_group_bot3", "hb_group_bot4"]
    bots = bots or ["bot1", "bot3", "bot4"]
    non_critical_dead_letter_reasons = (
        non_critical_dead_letter_reasons or list(DEFAULT_NON_CRITICAL_DEAD_LETTER_REASONS)
    )

    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    # 1) Heartbeat freshness per bot
    heartbeat_info: dict[str, dict[str, object]] = {}
    for bot in bots:
        hb_path = root / "data" / bot / "logs" / "heartbeat" / "strategy_heartbeat.json"
        hb_payload = _read_json(hb_path)
        age_s = _age_seconds_from_ts_or_mtime(str(hb_payload.get("ts_utc", "")), hb_path, now_ts)
        present = hb_path.exists()
        fresh = present and (age_s <= float(heartbeat_max_age_s))
        checks[f"heartbeat_{bot}_present"] = present
        checks[f"heartbeat_{bot}_fresh"] = fresh
        heartbeat_info[bot] = {
            "path": str(hb_path),
            "present": present,
            "age_s": age_s,
            "ts_utc": str(hb_payload.get("ts_utc", "")),
            "reason": str(hb_payload.get("reason", "")),
        }
    details["heartbeats"] = heartbeat_info

    # 2) Exchange snapshot freshness
    snapshot_path = root / "reports" / "exchange_snapshots" / "latest.json"
    snapshot_payload = _read_json(snapshot_path)
    snapshot_age_s = _age_seconds_from_ts_or_mtime(str(snapshot_payload.get("ts_utc", "")), snapshot_path, now_ts)
    snapshot_present = snapshot_path.exists()
    snapshot_fresh = snapshot_present and snapshot_age_s <= float(snapshot_max_age_s)
    checks["exchange_snapshot_present"] = snapshot_present
    checks["exchange_snapshot_fresh"] = snapshot_fresh
    details["exchange_snapshot"] = {
        "path": str(snapshot_path),
        "present": snapshot_present,
        "age_s": snapshot_age_s,
        "ts_utc": str(snapshot_payload.get("ts_utc", "")),
    }

    # 3) Redis stream SLOs (consumer lag/pending + dead letters)
    group_stats: dict[str, dict[str, int]] = {}
    dead_letter = {
        "scanned": 0,
        "in_lookback_window": 0,
        "critical_count": 0,
        "reason_counts": {},
        "latest_timestamp_ms": 0,
    }
    redis_ok = redis_client is not None
    redis_error = ""

    if redis_client is not None:
        try:
            raw_groups = redis_client.execute_command("XINFO", "GROUPS", "hb.execution_intent.v1")
            group_stats = _parse_xinfo_groups(raw_groups)
            raw_dead = redis_client.xrevrange(
                "hb.dead_letter.v1", "+", "-", count=max(1, int(dead_letter_scan_count))
            )
            dead_letter = _dead_letter_stats(
                raw_dead if isinstance(raw_dead, list) else [],
                now_ms=now_ms,
                lookback_sec=lookback_sec,
                non_critical_reasons=non_critical_dead_letter_reasons,
            )
        except Exception as exc:
            redis_ok = False
            redis_error = f"{type(exc).__name__}: {exc}"
    else:
        redis_ok = False
        redis_error = "redis_client_unavailable"

    checks["redis_connected"] = redis_ok
    checks["redis_groups_present"] = all(group in group_stats for group in required_groups)
    checks["redis_groups_lag_within_slo"] = all(
        _safe_int(group_stats.get(group, {}).get("lag"), 10**9) <= int(max_group_lag)
        for group in required_groups
    )
    checks["redis_groups_pending_within_slo"] = all(
        _safe_int(group_stats.get(group, {}).get("pending"), 10**9) <= int(max_group_pending)
        for group in required_groups
    )
    checks["dead_letter_critical_within_slo"] = (
        _safe_int(dead_letter.get("critical_count"), 10**9) <= int(max_critical_dead_letters)
    )

    details["redis"] = {
        "connected": redis_ok,
        "error": redis_error,
        "required_groups": required_groups,
        "group_stats": group_stats,
        "max_group_lag": int(max_group_lag),
        "max_group_pending": int(max_group_pending),
    }
    details["dead_letter"] = {
        **dead_letter,
        "lookback_sec": int(lookback_sec),
        "max_critical_dead_letters": int(max_critical_dead_letters),
        "non_critical_reasons": list(non_critical_dead_letter_reasons),
    }

    # 4) Optional paper-exchange reliability checks
    if bool(check_paper_exchange):
        paper_exchange_heartbeat = {
            "stream": str(paper_exchange_heartbeat_stream),
            "present": False,
            "ts_ms": 0,
            "age_s": 1e9,
            "processed_commands": 0,
            "rejected_commands": 0,
            "reject_rate_pct": 100.0,
            "stale_pairs": 0,
            "error": "",
        }
        if redis_client is not None:
            try:
                rows = redis_client.xrevrange(
                    str(paper_exchange_heartbeat_stream),
                    "+",
                    "-",
                    count=1,
                )
                if isinstance(rows, list) and len(rows) > 0:
                    stream_id, data = rows[0]
                    payload = _decode_stream_payload(data if isinstance(data, dict) else {})
                    ts_ms = _safe_int(payload.get("timestamp_ms"), 0) or _stream_id_ms(stream_id)
                    metadata = payload.get("metadata", {})
                    metadata = metadata if isinstance(metadata, dict) else {}
                    processed_commands = _safe_int(metadata.get("processed_commands"), 0)
                    rejected_commands = _safe_int(metadata.get("rejected_commands"), 0)
                    stale_pairs = _safe_int(metadata.get("stale_pairs"), 0)
                    reject_rate_pct = (
                        100.0 * float(rejected_commands) / float(processed_commands)
                        if processed_commands > 0
                        else 0.0
                    )
                    paper_exchange_heartbeat = {
                        "stream": str(paper_exchange_heartbeat_stream),
                        "present": ts_ms > 0,
                        "ts_ms": int(ts_ms),
                        "age_s": max(0.0, (now_ms - int(ts_ms)) / 1000.0) if ts_ms > 0 else 1e9,
                        "processed_commands": int(processed_commands),
                        "rejected_commands": int(rejected_commands),
                        "reject_rate_pct": float(reject_rate_pct),
                        "stale_pairs": int(stale_pairs),
                        "error": "",
                    }
            except Exception as exc:
                paper_exchange_heartbeat["error"] = f"{type(exc).__name__}: {exc}"
        else:
            paper_exchange_heartbeat["error"] = "redis_client_unavailable"

        load_report_path = root / "reports" / "verification" / "paper_exchange_load_latest.json"
        load_report = _read_json(load_report_path)
        load_present = load_report_path.exists()
        load_status = str(load_report.get("status", "")).strip().lower()
        load_age_s = _age_seconds_from_ts_or_mtime(str(load_report.get("ts_utc", "")), load_report_path, now_ts)
        load_metrics = load_report.get("metrics", {})
        load_metrics = load_metrics if isinstance(load_metrics, dict) else {}
        load_backlog_growth = _safe_float(
            load_metrics.get("p1_19_stream_backlog_growth_rate_pct_per_10min"),
            1_000_000.0,
        )
        load_latency_p95 = _safe_float(load_metrics.get("p1_19_command_latency_under_load_p95_ms"), 1_000_000.0)
        load_latency_p99 = _safe_float(load_metrics.get("p1_19_command_latency_under_load_p99_ms"), 1_000_000.0)

        checks["paper_exchange_heartbeat_present"] = bool(paper_exchange_heartbeat.get("present", False))
        checks["paper_exchange_heartbeat_fresh"] = (
            bool(paper_exchange_heartbeat.get("present", False))
            and float(paper_exchange_heartbeat.get("age_s", 1e9)) <= float(paper_exchange_heartbeat_max_age_s)
        )
        checks["paper_exchange_reject_rate_within_slo"] = float(
            paper_exchange_heartbeat.get("reject_rate_pct", 1e9)
        ) <= float(max_paper_exchange_reject_rate_pct)
        checks["paper_exchange_stale_pairs_within_slo"] = _safe_int(
            paper_exchange_heartbeat.get("stale_pairs"),
            10**9,
        ) <= int(max_paper_exchange_stale_pairs)
        checks["paper_exchange_load_report_present"] = bool(load_present)
        checks["paper_exchange_load_report_fresh"] = bool(load_present) and float(load_age_s) <= float(
            paper_exchange_load_report_max_age_s
        )
        checks["paper_exchange_load_report_pass"] = load_status == "pass"
        checks["paper_exchange_backlog_growth_within_slo"] = float(load_backlog_growth) <= float(
            max_paper_exchange_backlog_growth_pct_per_10min
        )
        checks["paper_exchange_latency_p95_within_slo"] = float(load_latency_p95) <= float(
            max_paper_exchange_latency_p95_ms
        )
        checks["paper_exchange_latency_p99_within_slo"] = float(load_latency_p99) <= float(
            max_paper_exchange_latency_p99_ms
        )
        details["paper_exchange_heartbeat"] = {
            **paper_exchange_heartbeat,
            "max_age_s": float(paper_exchange_heartbeat_max_age_s),
            "max_reject_rate_pct": float(max_paper_exchange_reject_rate_pct),
            "max_stale_pairs": int(max_paper_exchange_stale_pairs),
        }
        details["paper_exchange_load"] = {
            "path": str(load_report_path),
            "present": bool(load_present),
            "status": load_status,
            "age_s": float(load_age_s),
            "max_age_s": float(paper_exchange_load_report_max_age_s),
            "backlog_growth_pct_per_10min": float(load_backlog_growth),
            "max_backlog_growth_pct_per_10min": float(max_paper_exchange_backlog_growth_pct_per_10min),
            "latency_p95_ms": float(load_latency_p95),
            "max_latency_p95_ms": float(max_paper_exchange_latency_p95_ms),
            "latency_p99_ms": float(load_latency_p99),
            "max_latency_p99_ms": float(max_paper_exchange_latency_p99_ms),
        }

    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    status = "pass" if len(failed_checks) == 0 else "fail"
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "details": details,
    }


def run_check(
    *,
    strict: bool,
    redis_host: str,
    redis_port: int,
    redis_db: int,
    redis_password: str,
    required_groups: list[str],
    bots: list[str],
    lookback_sec: int,
    max_critical_dead_letters: int,
    max_group_lag: int,
    max_group_pending: int,
    heartbeat_max_age_s: int,
    snapshot_max_age_s: int,
    dead_letter_scan_count: int,
    non_critical_dead_letter_reasons: list[str],
    check_paper_exchange: bool,
    paper_exchange_heartbeat_stream: str,
    paper_exchange_heartbeat_max_age_s: int,
    max_paper_exchange_reject_rate_pct: float,
    max_paper_exchange_stale_pairs: int,
    paper_exchange_load_report_max_age_s: int,
    max_paper_exchange_backlog_growth_pct_per_10min: float,
    max_paper_exchange_latency_p95_ms: float,
    max_paper_exchange_latency_p99_ms: float,
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
                socket_timeout=3,
                socket_connect_timeout=3,
            )
            redis_client.ping()
        except Exception as exc:
            redis_error = f"{type(exc).__name__}: {exc}"
            redis_client = None

    report = build_report(
        root=root,
        redis_client=redis_client,
        required_groups=required_groups,
        bots=bots,
        lookback_sec=lookback_sec,
        max_critical_dead_letters=max_critical_dead_letters,
        max_group_lag=max_group_lag,
        max_group_pending=max_group_pending,
        heartbeat_max_age_s=heartbeat_max_age_s,
        snapshot_max_age_s=snapshot_max_age_s,
        dead_letter_scan_count=dead_letter_scan_count,
        non_critical_dead_letter_reasons=non_critical_dead_letter_reasons,
        check_paper_exchange=bool(check_paper_exchange),
        paper_exchange_heartbeat_stream=str(paper_exchange_heartbeat_stream),
        paper_exchange_heartbeat_max_age_s=int(paper_exchange_heartbeat_max_age_s),
        max_paper_exchange_reject_rate_pct=float(max_paper_exchange_reject_rate_pct),
        max_paper_exchange_stale_pairs=int(max_paper_exchange_stale_pairs),
        paper_exchange_load_report_max_age_s=int(paper_exchange_load_report_max_age_s),
        max_paper_exchange_backlog_growth_pct_per_10min=float(max_paper_exchange_backlog_growth_pct_per_10min),
        max_paper_exchange_latency_p95_ms=float(max_paper_exchange_latency_p95_ms),
        max_paper_exchange_latency_p99_ms=float(max_paper_exchange_latency_p99_ms),
    )
    if redis_error:
        report["redis_client_error"] = redis_error
        report["status"] = "fail"
        failed = report.get("failed_checks", [])
        if isinstance(failed, list) and "redis_connected" not in failed:
            failed.append("redis_connected")
            report["failed_checks"] = sorted(str(x) for x in failed)

    out_dir = root / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"reliability_slo_{stamp}.json"
    latest_path = out_dir / "reliability_slo_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[reliability-slo] status={report.get('status')} failed={report.get('failed_checks', [])}")
    print(f"[reliability-slo] evidence={out_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reliability SLO checker for desk runtime health.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when SLOs fail.")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-password", default=os.getenv("REDIS_PASSWORD", ""))
    parser.add_argument("--required-groups", default=os.getenv("SLO_REQUIRED_GROUPS", "hb_group_bot1,hb_group_bot3,hb_group_bot4"))
    parser.add_argument("--bots", default=os.getenv("SLO_REQUIRED_BOTS", "bot1,bot3,bot4"))
    parser.add_argument("--lookback-sec", type=int, default=int(os.getenv("SLO_DEAD_LETTER_LOOKBACK_SEC", "900")))
    parser.add_argument("--max-critical-dead-letters", type=int, default=int(os.getenv("SLO_MAX_CRITICAL_DEAD_LETTERS", "0")))
    parser.add_argument("--max-group-lag", type=int, default=int(os.getenv("SLO_MAX_GROUP_LAG", "0")))
    parser.add_argument("--max-group-pending", type=int, default=int(os.getenv("SLO_MAX_GROUP_PENDING", "0")))
    parser.add_argument("--heartbeat-max-age-s", type=int, default=int(os.getenv("SLO_HEARTBEAT_MAX_AGE_S", "120")))
    parser.add_argument("--snapshot-max-age-s", type=int, default=int(os.getenv("SLO_SNAPSHOT_MAX_AGE_S", "180")))
    parser.add_argument("--dead-letter-scan-count", type=int, default=int(os.getenv("SLO_DEAD_LETTER_SCAN_COUNT", "5000")))
    parser.add_argument(
        "--non-critical-dead-letter-reasons",
        default=os.getenv(
            "SLO_NON_CRITICAL_DEAD_LETTER_REASONS",
            ",".join(DEFAULT_NON_CRITICAL_DEAD_LETTER_REASONS),
        ),
    )
    parser.add_argument(
        "--check-paper-exchange",
        action="store_true",
        default=str(os.getenv("SLO_CHECK_PAPER_EXCHANGE", "false")).strip().lower() in {"1", "true", "yes", "on"},
        help="Enable additional paper-exchange heartbeat/load reliability checks.",
    )
    parser.add_argument(
        "--paper-exchange-heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", PAPER_EXCHANGE_HEARTBEAT_STREAM),
        help="Paper-exchange heartbeat stream name for reliability checks.",
    )
    parser.add_argument(
        "--paper-exchange-heartbeat-max-age-s",
        type=int,
        default=int(os.getenv("SLO_PAPER_EXCHANGE_HEARTBEAT_MAX_AGE_S", "30")),
        help="Maximum allowed age for latest paper-exchange heartbeat when checks are enabled.",
    )
    parser.add_argument(
        "--max-paper-exchange-reject-rate-pct",
        type=float,
        default=float(os.getenv("SLO_MAX_PAPER_EXCHANGE_REJECT_RATE_PCT", "25")),
        help="Maximum allowed paper-exchange reject-rate percentage when checks are enabled.",
    )
    parser.add_argument(
        "--max-paper-exchange-stale-pairs",
        type=int,
        default=int(os.getenv("SLO_MAX_PAPER_EXCHANGE_STALE_PAIRS", "0")),
        help="Maximum allowed stale pair count reported by paper-exchange heartbeat.",
    )
    parser.add_argument(
        "--paper-exchange-load-report-max-age-s",
        type=int,
        default=int(os.getenv("SLO_PAPER_EXCHANGE_LOAD_REPORT_MAX_AGE_S", "1800")),
        help="Maximum allowed age for paper-exchange load report when checks are enabled.",
    )
    parser.add_argument(
        "--max-paper-exchange-backlog-growth-pct-per-10min",
        type=float,
        default=float(os.getenv("SLO_MAX_PAPER_EXCHANGE_BACKLOG_GROWTH_PCT_PER_10MIN", "5")),
        help="Maximum allowed paper-exchange backlog growth (pct per 10 min) when checks are enabled.",
    )
    parser.add_argument(
        "--max-paper-exchange-latency-p95-ms",
        type=float,
        default=float(os.getenv("SLO_MAX_PAPER_EXCHANGE_LATENCY_P95_MS", "500")),
        help="Maximum allowed paper-exchange load p95 latency when checks are enabled.",
    )
    parser.add_argument(
        "--max-paper-exchange-latency-p99-ms",
        type=float,
        default=float(os.getenv("SLO_MAX_PAPER_EXCHANGE_LATENCY_P99_MS", "1000")),
        help="Maximum allowed paper-exchange load p99 latency when checks are enabled.",
    )
    args = parser.parse_args()

    return run_check(
        strict=bool(args.strict),
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password),
        required_groups=_csv_list(args.required_groups),
        bots=_csv_list(args.bots),
        lookback_sec=int(args.lookback_sec),
        max_critical_dead_letters=int(args.max_critical_dead_letters),
        max_group_lag=int(args.max_group_lag),
        max_group_pending=int(args.max_group_pending),
        heartbeat_max_age_s=int(args.heartbeat_max_age_s),
        snapshot_max_age_s=int(args.snapshot_max_age_s),
        dead_letter_scan_count=int(args.dead_letter_scan_count),
        non_critical_dead_letter_reasons=_csv_list(args.non_critical_dead_letter_reasons),
        check_paper_exchange=bool(args.check_paper_exchange),
        paper_exchange_heartbeat_stream=str(args.paper_exchange_heartbeat_stream),
        paper_exchange_heartbeat_max_age_s=int(args.paper_exchange_heartbeat_max_age_s),
        max_paper_exchange_reject_rate_pct=float(args.max_paper_exchange_reject_rate_pct),
        max_paper_exchange_stale_pairs=int(args.max_paper_exchange_stale_pairs),
        paper_exchange_load_report_max_age_s=int(args.paper_exchange_load_report_max_age_s),
        max_paper_exchange_backlog_growth_pct_per_10min=float(args.max_paper_exchange_backlog_growth_pct_per_10min),
        max_paper_exchange_latency_p95_ms=float(args.max_paper_exchange_latency_p95_ms),
        max_paper_exchange_latency_p99_ms=float(args.max_paper_exchange_latency_p99_ms),
    )


if __name__ == "__main__":
    raise SystemExit(main())

