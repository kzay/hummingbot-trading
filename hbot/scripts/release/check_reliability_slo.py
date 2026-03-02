#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

DEFAULT_NON_CRITICAL_DEAD_LETTER_REASONS = [
    "local_authority_reject",
    "expired_intent",
]


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


def _parse_ts(ts_utc: str) -> Optional[datetime]:
    s = (ts_utc or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _read_json(path: Path) -> Dict[str, object]:
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


def _parse_xinfo_groups(raw: object) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
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
    dead_rows: Iterable[Tuple[object, Dict[str, object]]],
    now_ms: int,
    lookback_sec: int,
    non_critical_reasons: Iterable[str],
) -> Dict[str, object]:
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
    now_ts: Optional[float] = None,
    redis_client: Optional[Any] = None,
    required_groups: Optional[List[str]] = None,
    bots: Optional[List[str]] = None,
    lookback_sec: int = 900,
    max_critical_dead_letters: int = 0,
    max_group_lag: int = 0,
    max_group_pending: int = 0,
    heartbeat_max_age_s: int = 120,
    snapshot_max_age_s: int = 180,
    dead_letter_scan_count: int = 5000,
    non_critical_dead_letter_reasons: Optional[List[str]] = None,
) -> Dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    now_ms = int(now_ts * 1000)
    required_groups = required_groups or ["hb_group_bot1", "hb_group_bot3", "hb_group_bot4"]
    bots = bots or ["bot1", "bot3", "bot4"]
    non_critical_dead_letter_reasons = (
        non_critical_dead_letter_reasons or list(DEFAULT_NON_CRITICAL_DEAD_LETTER_REASONS)
    )

    checks: Dict[str, bool] = {}
    details: Dict[str, object] = {}

    # 1) Heartbeat freshness per bot
    heartbeat_info: Dict[str, Dict[str, object]] = {}
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
    group_stats: Dict[str, Dict[str, int]] = {}
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
    required_groups: List[str],
    bots: List[str],
    lookback_sec: int,
    max_critical_dead_letters: int,
    max_group_lag: int,
    max_group_pending: int,
    heartbeat_max_age_s: int,
    snapshot_max_age_s: int,
    dead_letter_scan_count: int,
    non_critical_dead_letter_reasons: List[str],
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"reliability_slo_{stamp}.json"
    latest_path = out_dir / "reliability_slo_latest.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[reliability-slo] status={report.get('status')} failed={report.get('failed_checks', [])}")
    print(f"[reliability-slo] evidence={out_path}")
    if strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


def _csv_list(value: str) -> List[str]:
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
    )


if __name__ == "__main__":
    raise SystemExit(main())

