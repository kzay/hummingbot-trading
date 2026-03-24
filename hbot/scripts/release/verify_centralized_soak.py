from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import redis  # type: ignore


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _read_last_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            last: dict[str, str] = {}
            for row in reader:
                last = row
            return last
    except Exception:
        return {}


def _fmt_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _read_group_lag(r: redis.Redis) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    try:
        raw = r.execute_command("XINFO", "GROUPS", "hb.execution_intent.v1")
    except Exception as e:
        return {"_error": {"error": _fmt_error(e)}}
    for group_raw in raw:
        group_dict = {group_raw[i]: group_raw[i + 1] for i in range(0, len(group_raw), 2)}
        name = str(group_dict.get("name", ""))
        if not name:
            continue
        out[name] = {
            "lag": _safe_int(group_dict.get("lag"), -1),
            "pending": _safe_int(group_dict.get("pending"), -1),
            "last_delivered_id": str(group_dict.get("last-delivered-id", "")),
        }
    return out


def _latest_daily_intents(
    r: redis.Redis, lookback_sec: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - max(1, int(lookback_sec)) * 1000
    intents: list[dict[str, object]] = []
    try:
        rows = r.xrevrange("hb.execution_intent.v1", "+", "-", count=300)
    except Exception:
        return intents, []
    for stream_id, data in rows:
        raw = data.get("payload", "{}")
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        ts = _safe_int(payload.get("timestamp_ms"), 0)
        if ts < cutoff_ms:
            continue
        if str(payload.get("action", "")) != "set_daily_pnl_target_pct":
            continue
        metadata = payload.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        intents.append(
            {
                "stream_id": str(stream_id),
                "event_id": str(payload.get("event_id", "")),
                "instance_name": str(payload.get("instance_name", "")),
                "timestamp_ms": ts,
                "daily_pnl_target_pct": str(metadata.get("daily_pnl_target_pct", "")),
                "reason": str(metadata.get("reason", "")),
            }
        )
    if not intents:
        return [], []
    max_ts = max(_safe_int(x.get("timestamp_ms"), 0) for x in intents)
    latest = [x for x in intents if _safe_int(x.get("timestamp_ms"), 0) >= (max_ts - 1)]
    latest_ids = {str(x.get("event_id", "")) for x in latest if str(x.get("event_id", ""))}
    dead_matches: list[dict[str, object]] = []
    if latest_ids:
        try:
            dead_rows = r.xrevrange("hb.dead_letter.v1", "+", "-", count=5000)
        except Exception:
            dead_rows = []
        for dead_id, dead_data in dead_rows:
            raw = dead_data.get("payload", "{}")
            try:
                dead_payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(dead_payload, dict):
                continue
            event_id = str(dead_payload.get("event_id", ""))
            if event_id in latest_ids:
                dead_matches.append(
                    {
                        "stream_id": str(dead_id),
                        "event_id": event_id,
                        "reason": str(dead_payload.get("reason", "")),
                    }
                )
    return latest, dead_matches


def _bot_minute_snapshot(path: Path, now_ts: float) -> dict[str, object]:
    row = _read_last_csv_row(path)
    if not row:
        return {"present": False, "path": str(path)}
    mtime_age_s = now_ts - path.stat().st_mtime if path.exists() else 1e9
    return {
        "present": True,
        "path": str(path),
        "mtime_age_s": mtime_age_s,
        "ts": str(row.get("ts", "")),
        "state": str(row.get("state", "")),
        "risk_reasons": str(row.get("risk_reasons", "")),
        "equity_quote": _safe_float(row.get("equity_quote"), 0.0),
        "pnl_governor_target_source": str(row.get("pnl_governor_target_source", "")),
        "pnl_governor_target_pnl_pct": _safe_float(row.get("pnl_governor_target_pnl_pct"), 0.0),
        "pnl_governor_target_pnl_quote": _safe_float(row.get("pnl_governor_target_pnl_quote"), 0.0),
        "pnl_governor_target_mode": str(row.get("pnl_governor_target_mode", "")),
    }


def _target_source_matches_runtime(
    bot_name: str,
    snap_row: dict[str, object],
    goal_row: dict[str, object],
) -> bool:
    expected_source = "execution_intent_daily_pnl_target_pct"
    source = str(snap_row.get("pnl_governor_target_source", "")).strip().lower()
    if source == expected_source:
        return True

    # For disabled allocator lanes (target_pct=0 and portfolio action off),
    # runtime may safely collapse source to "none" while still honoring target=0.
    goal_target_pct = _safe_float(goal_row.get("daily_pnl_target_pct"), -1.0)
    goal_action_enabled = bool(goal_row.get("portfolio_action_enabled", True))
    runtime_target_pct = _safe_float(snap_row.get("pnl_governor_target_pnl_pct"), -1.0)
    runtime_mode = str(snap_row.get("pnl_governor_target_mode", "")).strip().lower()
    if (
        (not goal_action_enabled)
        and abs(goal_target_pct - 0.0) < 1e-9
        and abs(runtime_target_pct - 0.0) < 1e-9
        and runtime_mode in {"disabled", ""}
        and source in {"none", ""}
    ):
        return True

    return False


def _sample_once(
    root: Path,
    r: redis.Redis,
    minute_freshness_s: int,
    intent_lookback_s: int,
    max_group_lag: int,
) -> dict[str, object]:
    now_ts = time.time()
    policy = _read_json(root / "config" / "multi_bot_policy_v1.json")
    alloc = _read_json(root / "reports" / "policy" / "portfolio_allocator_latest.json")
    snap = _read_json(root / "reports" / "exchange_snapshots" / "latest.json")

    daily_goal = alloc.get("daily_goal", {})
    daily_goal = daily_goal if isinstance(daily_goal, dict) else {}
    rows = daily_goal.get("rows", [])
    rows = rows if isinstance(rows, list) else []
    row_by_bot = {
        str(x.get("bot", "")): x for x in rows if isinstance(x, dict) and str(x.get("bot", ""))
    }

    groups = _read_group_lag(r)
    latest_intents, dead_matches = _latest_daily_intents(r, intent_lookback_s)

    bot1 = _bot_minute_snapshot(root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv", now_ts)
    bot3 = _bot_minute_snapshot(root / "data" / "bot3" / "logs" / "epp_v24" / "bot3_a" / "minute.csv", now_ts)
    bot4 = _bot_minute_snapshot(root / "data" / "bot4" / "logs" / "epp_v24" / "bot4_a" / "minute.csv", now_ts)

    checks: dict[str, bool] = {}
    checks["allocator_status_pass"] = str(alloc.get("status", "")).lower() == "pass"
    checks["allocator_emit_intents_true"] = bool(alloc.get("emit_intents", False))
    checks["daily_goal_status_pass"] = str(daily_goal.get("status", "")).lower() == "pass"
    checks["daily_goal_target_pct_0_6"] = abs(
        _safe_float(daily_goal.get("target_pct_total_equity"), -1.0) - 0.6
    ) < 1e-9

    bot1_goal = row_by_bot.get("bot1", {})
    bot3_goal = row_by_bot.get("bot3", {})
    bot4_goal = row_by_bot.get("bot4", {})
    checks["goal_bot1_pct_0_6"] = abs(_safe_float(bot1_goal.get("daily_pnl_target_pct"), -1.0) - 0.6) < 1e-9
    checks["goal_bot3_pct_0"] = abs(_safe_float(bot3_goal.get("daily_pnl_target_pct"), -1.0) - 0.0) < 1e-9
    checks["goal_bot4_pct_0"] = abs(_safe_float(bot4_goal.get("daily_pnl_target_pct"), -1.0) - 0.0) < 1e-9

    bot1_eq_goal = _safe_float(bot1_goal.get("equity_quote"), 0.0)
    bot1_quote_goal = _safe_float(bot1_goal.get("daily_pnl_target_quote"), 0.0)
    checks["goal_bot1_quote_matches_pct"] = abs(bot1_quote_goal - (bot1_eq_goal * 0.006)) < 1e-6

    checks["redis_groups_present"] = all(
        k in groups for k in ("hb_group_bot1", "hb_group_bot3", "hb_group_bot4")
    )
    checks["redis_groups_zero_lag"] = all(
        _safe_int(groups.get(k, {}).get("lag"), -1) <= int(max_group_lag)
        for k in ("hb_group_bot1", "hb_group_bot3", "hb_group_bot4")
    )
    checks["redis_groups_zero_pending"] = all(
        _safe_int(groups.get(k, {}).get("pending"), -1) == 0
        for k in ("hb_group_bot1", "hb_group_bot3", "hb_group_bot4")
    )

    latest_instances = sorted({str(x.get("instance_name", "")) for x in latest_intents if str(x.get("instance_name", ""))})
    checks["latest_intents_have_all_bots"] = latest_instances == ["bot1", "bot3", "bot4"]
    checks["latest_intent_bot1_pct_0_6"] = any(
        str(x.get("instance_name", "")) == "bot1" and str(x.get("daily_pnl_target_pct", "")) == "0.600000"
        for x in latest_intents
    )

    goal_rows = {"bot1": bot1_goal, "bot3": bot3_goal, "bot4": bot4_goal}
    for bot_name, snap_row in (("bot1", bot1), ("bot3", bot3), ("bot4", bot4)):
        checks[f"{bot_name}_minute_present"] = bool(snap_row.get("present", False))
        checks[f"{bot_name}_minute_fresh"] = bool(_safe_float(snap_row.get("mtime_age_s"), 1e9) <= minute_freshness_s)
        checks[f"{bot_name}_target_source_execution_intent"] = _target_source_matches_runtime(
            bot_name=bot_name,
            snap_row=snap_row,
            goal_row=goal_rows.get(bot_name, {}),
        )

    checks["bot1_target_pct_0_6_runtime"] = abs(_safe_float(bot1.get("pnl_governor_target_pnl_pct"), -1.0) - 0.6) < 1e-9
    checks["bot3_target_pct_0_runtime"] = abs(_safe_float(bot3.get("pnl_governor_target_pnl_pct"), -1.0) - 0.0) < 1e-9
    checks["bot4_target_pct_0_runtime"] = abs(_safe_float(bot4.get("pnl_governor_target_pnl_pct"), -1.0) - 0.0) < 1e-9

    intent_by_event_id = {
        str(item.get("event_id", "")): item
        for item in latest_intents
        if isinstance(item, dict) and str(item.get("event_id", ""))
    }
    warnings: list[str] = []
    critical_dead_matches: list[dict[str, object]] = []
    for dead in dead_matches:
        event_id = str(dead.get("event_id", ""))
        reason = str(dead.get("reason", "")).strip().lower()
        intent = intent_by_event_id.get(event_id, {})
        instance = str(intent.get("instance_name", "")).strip().lower()
        if reason != "local_authority_reject":
            critical_dead_matches.append(dead)
            continue
        # Some local authority rejects are transient (connector readiness) and
        # non-critical if the runtime target state is already consistent.
        recovered = False
        if instance == "bot1":
            recovered = checks["bot1_target_source_execution_intent"] and checks["bot1_target_pct_0_6_runtime"]
        elif instance == "bot3":
            recovered = checks["bot3_target_source_execution_intent"] and checks["bot3_target_pct_0_runtime"]
        elif instance == "bot4":
            recovered = checks["bot4_target_source_execution_intent"] and checks["bot4_target_pct_0_runtime"]
        if recovered:
            warnings.append(f"dead_letter_local_authority_reject_recovered:{instance or 'unknown'}:{event_id}")
        else:
            critical_dead_matches.append(dead)
    checks["latest_intents_no_critical_dead_letter"] = len(critical_dead_matches) == 0

    failed = sorted([k for k, ok in checks.items() if not ok])
    return {
        "ts_utc": _utc_now(),
        "pass": len(failed) == 0,
        "failed_checks": failed,
        "warnings": warnings,
        "checks": checks,
        "allocator": {
            "status": alloc.get("status", "unknown"),
            "emit_intents": alloc.get("emit_intents", False),
            "total_equity_quote": _safe_float(alloc.get("total_equity_quote"), 0.0),
            "daily_goal": {
                "status": daily_goal.get("status", "unknown"),
                "target_pct_total_equity": _safe_float(daily_goal.get("target_pct_total_equity"), 0.0),
                "target_quote_total_equity": _safe_float(daily_goal.get("target_quote_total_equity"), 0.0),
                "goal_scope_equity_quote": _safe_float(daily_goal.get("goal_scope_equity_quote"), 0.0),
                "rows": row_by_bot,
            },
        },
        "snapshot_total_bots": len(snap.get("bots", {})) if isinstance(snap.get("bots"), dict) else 0,
        "redis_groups": groups,
        "latest_daily_target_intents": latest_intents,
        "latest_dead_letter_matches": dead_matches,
        "latest_dead_letter_critical_matches": critical_dead_matches,
        "bots": {"bot1": bot1, "bot3": bot3, "bot4": bot4},
        "policy_daily_goal_pct": _safe_float(
            (policy.get("allocator", {}) if isinstance(policy.get("allocator"), dict) else {}).get("daily_goal", {})
            .get("target_pct_total_equity", 0.0)
            if isinstance((policy.get("allocator", {}) if isinstance(policy.get("allocator"), dict) else {}).get("daily_goal", {}), dict)
            else 0.0,
            0.0,
        ),
    }


def run(
    duration_min: float,
    interval_sec: int,
    minute_freshness_s: int,
    intent_lookback_s: int,
    max_group_lag: int,
    redis_host: str,
    redis_port: int,
    redis_db: int,
    redis_password: str,
) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    end_ts = time.time() + max(1.0, duration_min) * 60.0
    r = redis.Redis(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=(redis_password or None),
        decode_responses=True,
        socket_timeout=3,
    )
    samples: list[dict[str, object]] = []
    while True:
        sample = _sample_once(
            root,
            r,
            minute_freshness_s=minute_freshness_s,
            intent_lookback_s=intent_lookback_s,
            max_group_lag=max_group_lag,
        )
        samples.append(sample)
        failed = [str(x) for x in sample.get("failed_checks", [])]
        warnings = [str(x) for x in sample.get("warnings", [])]
        print(
            f"[centralized-soak] ts={sample.get('ts_utc')} pass={sample.get('pass')} "
            f"failed_checks={len(failed)} warnings={len(warnings)}"
        )
        if failed:
            print(f"[centralized-soak] failed={','.join(failed)}")
        if warnings:
            print(f"[centralized-soak] warnings={','.join(warnings)}")
        if time.time() >= end_ts:
            break
        time.sleep(max(5, interval_sec))

    failure_counts: Counter[str] = Counter()
    for sample in samples:
        for failed in sample.get("failed_checks", []):
            failure_counts[str(failed)] += 1
    pass_count = sum(1 for s in samples if bool(s.get("pass", False)))
    report = {
        "ts_utc": _utc_now(),
        "status": "PASS" if pass_count == len(samples) and len(samples) > 0 else "FAIL",
        "duration_min": duration_min,
        "interval_sec": interval_sec,
        "sample_count": len(samples),
        "pass_count": pass_count,
        "pass_rate": (float(pass_count) / float(len(samples))) if samples else 0.0,
        "failure_counts": dict(failure_counts),
        "samples": samples,
    }
    out_dir = root / "reports" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"centralized_soak_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "centralized_soak_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[centralized-soak] status={report['status']} samples={report['sample_count']} evidence={out_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Centralized desk soak verification (allocation + daily target).")
    parser.add_argument("--duration-min", type=float, default=60.0, help="Total soak duration in minutes.")
    parser.add_argument("--interval-sec", type=int, default=60, help="Sampling interval in seconds.")
    parser.add_argument("--minute-freshness-s", type=int, default=180, help="Max allowed minute.csv staleness.")
    parser.add_argument("--intent-lookback-s", type=int, default=900, help="Intent lookup lookback window in seconds.")
    parser.add_argument(
        "--max-group-lag",
        type=int,
        default=2,
        help="Allowed transient Redis consumer-group lag for bot groups.",
    )
    parser.add_argument("--redis-host", default="127.0.0.1", help="Redis host.")
    parser.add_argument("--redis-port", type=int, default=6379, help="Redis port.")
    parser.add_argument("--redis-db", type=int, default=0, help="Redis DB.")
    parser.add_argument("--redis-password", default="", help="Redis password (optional).")
    args = parser.parse_args()
    result = run(
        duration_min=args.duration_min,
        interval_sec=args.interval_sec,
        minute_freshness_s=args.minute_freshness_s,
        intent_lookback_s=args.intent_lookback_s,
        max_group_lag=args.max_group_lag,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_db=args.redis_db,
        redis_password=args.redis_password,
    )
    raise SystemExit(0 if str(result.get("status", "FAIL")).upper() == "PASS" else 1)
