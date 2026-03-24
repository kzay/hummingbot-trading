#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _symbol_bucket(cfg: dict[str, object]) -> str:
    symbols = cfg.get("allowed_symbols", [])
    if isinstance(symbols, list):
        upper = {str(s).strip().upper() for s in symbols}
        if "BTC-USDT" in upper:
            return "btc"
        if "ETH-USDT" in upper:
            return "eth"
    pair = str(cfg.get("trading_pair", "")).strip().upper()
    if "BTC-USDT" in pair:
        return "btc"
    if "ETH-USDT" in pair:
        return "eth"
    return "other"


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    cleaned = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(cleaned.values())
    if total <= 0:
        return {k: 0.0 for k in cleaned}
    return {k: v / total for k, v in cleaned.items()}


def _bucket_allocations_from_report(report: dict[str, object]) -> dict[str, float]:
    rec = report.get("allocation_recommendation_inverse_variance", {})
    rec = rec if isinstance(rec, dict) else {}
    btc = _safe_float(rec.get("btc"), 0.0)
    eth = _safe_float(rec.get("eth"), 0.0)
    normalized = _normalize_weights({"btc": btc, "eth": eth})
    return {"btc": normalized.get("btc", 0.0), "eth": normalized.get("eth", 0.0)}


def _eligible_policy_bots(policy: dict[str, object], included_modes: list[str]) -> dict[str, dict[str, object]]:
    included = {str(mode).strip().lower() for mode in included_modes}
    bots_raw = policy.get("bots", {})
    bots_raw = bots_raw if isinstance(bots_raw, dict) else {}
    out: dict[str, dict[str, object]] = {}
    for bot, cfg_raw in bots_raw.items():
        cfg = cfg_raw if isinstance(cfg_raw, dict) else {}
        if not bool(cfg.get("enabled", False)):
            continue
        mode = str(cfg.get("mode", "")).strip().lower()
        if mode not in included:
            continue
        out[str(bot)] = cfg
    return out


def _distribute_bucket_weight(
    bucket_weight: float,
    bot_rows: list[tuple[str, dict[str, object]]],
) -> dict[str, float]:
    if not bot_rows:
        return {}
    current = {bot: max(0.0, _safe_float(cfg.get("target_alloc_pct"), 0.0)) for bot, cfg in bot_rows}
    current_total = sum(current.values())
    if current_total > 0:
        return {bot: bucket_weight * (current[bot] / current_total) for bot, _ in bot_rows}
    equal = bucket_weight / float(len(bot_rows))
    return {bot: equal for bot, _ in bot_rows}


def build_rebalance_plan(
    *,
    policy: dict[str, object],
    diversification_report: dict[str, object],
    included_modes: list[str],
    update_max_alloc: bool,
) -> dict[str, object]:
    eligible = _eligible_policy_bots(policy, included_modes=included_modes)
    by_bucket: dict[str, list[tuple[str, dict[str, object]]]] = {"btc": [], "eth": []}
    for bot, cfg in eligible.items():
        bucket = _symbol_bucket(cfg)
        if bucket in by_bucket:
            by_bucket[bucket].append((bot, cfg))

    bucket_alloc = _bucket_allocations_from_report(diversification_report)
    metrics = diversification_report.get("metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    btc_var = _safe_float(metrics.get("btc_variance"), 0.0)
    eth_var = _safe_float(metrics.get("eth_variance"), 0.0)

    updates: dict[str, dict[str, object]] = {}
    target_alloc_map: dict[str, float] = {}
    target_alloc_map.update(_distribute_bucket_weight(bucket_alloc.get("btc", 0.0), by_bucket["btc"]))
    target_alloc_map.update(_distribute_bucket_weight(bucket_alloc.get("eth", 0.0), by_bucket["eth"]))

    for bot, cfg in eligible.items():
        old_target = max(0.0, _safe_float(cfg.get("target_alloc_pct"), 0.0))
        old_var = max(0.0, _safe_float(cfg.get("alloc_variance_proxy"), 0.0))
        old_max = max(0.0, _safe_float(cfg.get("max_alloc_pct"), 0.0))
        bucket = _symbol_bucket(cfg)
        new_target = max(0.0, min(1.0, target_alloc_map.get(bot, old_target)))
        new_var = old_var
        if bucket == "btc" and btc_var > 0.0:
            new_var = btc_var
        elif bucket == "eth" and eth_var > 0.0:
            new_var = eth_var
        new_max = old_max
        if update_max_alloc:
            new_max = max(old_max, new_target)
        updates[bot] = {
            "bucket": bucket,
            "old_target_alloc_pct": old_target,
            "new_target_alloc_pct": new_target,
            "old_alloc_variance_proxy": old_var,
            "new_alloc_variance_proxy": new_var,
            "old_max_alloc_pct": old_max,
            "new_max_alloc_pct": new_max,
            "changed": (
                abs(new_target - old_target) > 1e-12
                or abs(new_var - old_var) > 1e-12
                or abs(new_max - old_max) > 1e-12
            ),
        }

    update_count = sum(1 for row in updates.values() if bool(row.get("changed", False)))
    report_status = str(diversification_report.get("status", "missing")).strip().lower()
    correlation = _safe_float(metrics.get("btc_eth_return_correlation"), 0.0)
    plan_ready = (
        report_status == "pass"
        and len(by_bucket["btc"]) > 0
        and len(by_bucket["eth"]) > 0
        and sum(bucket_alloc.values()) > 0.0
    )
    blocking_reasons: list[str] = []
    if report_status != "pass":
        blocking_reasons.append(f"diversification_report_status={report_status or 'missing'}")
    if len(by_bucket["btc"]) == 0:
        blocking_reasons.append("no_btc_strategy_bot_in_policy")
    if len(by_bucket["eth"]) == 0:
        blocking_reasons.append("no_eth_strategy_bot_in_policy")
    if sum(bucket_alloc.values()) <= 0.0:
        blocking_reasons.append("allocation_recommendation_missing_or_zero")

    return {
        "ts_utc": _utc_now(),
        "status": "pass" if plan_ready else "fail",
        "plan_ready": plan_ready,
        "blocking_reasons": blocking_reasons,
        "included_modes": sorted({str(m).strip().lower() for m in included_modes}),
        "diversification": {
            "report_status": report_status,
            "btc_eth_return_correlation": correlation,
            "bucket_allocations": bucket_alloc,
            "btc_variance": btc_var if btc_var > 0.0 else None,
            "eth_variance": eth_var if eth_var > 0.0 else None,
        },
        "strategy_buckets": {
            "btc_bots": sorted(bot for bot, _ in by_bucket["btc"]),
            "eth_bots": sorted(bot for bot, _ in by_bucket["eth"]),
        },
        "updates": updates,
        "update_count": update_count,
    }


def apply_rebalance_to_policy(policy: dict[str, object], plan: dict[str, object]) -> dict[str, object]:
    bots = policy.get("bots", {})
    bots = bots if isinstance(bots, dict) else {}
    updates_raw = plan.get("updates", {})
    updates = updates_raw if isinstance(updates_raw, dict) else {}
    for bot, row_raw in updates.items():
        if bot not in bots:
            continue
        cfg = bots.get(bot, {})
        if not isinstance(cfg, dict):
            continue
        row = row_raw if isinstance(row_raw, dict) else {}
        cfg["target_alloc_pct"] = float(_safe_float(row.get("new_target_alloc_pct"), _safe_float(cfg.get("target_alloc_pct"), 0.0)))
        cfg["alloc_variance_proxy"] = float(
            _safe_float(row.get("new_alloc_variance_proxy"), _safe_float(cfg.get("alloc_variance_proxy"), 1.0))
        )
        cfg["max_alloc_pct"] = float(_safe_float(row.get("new_max_alloc_pct"), _safe_float(cfg.get("max_alloc_pct"), 1.0)))
        bots[bot] = cfg
    policy["bots"] = bots
    return policy


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description="Apply ROAD-9 inverse-variance rebalance to multi-bot policy.")
    parser.add_argument("--policy-path", default=str(root / "config" / "multi_bot_policy_v1.json"))
    parser.add_argument(
        "--diversification-report-path",
        default=str(root / "reports" / "policy" / "portfolio_diversification_latest.json"),
    )
    parser.add_argument(
        "--out-path",
        default=str(root / "reports" / "policy" / "road9_allocation_latest.json"),
    )
    parser.add_argument(
        "--included-modes",
        default="live,paper_only",
        help="Comma-separated policy bot modes eligible for ROAD-9 rebalance.",
    )
    parser.add_argument(
        "--update-max-alloc",
        action="store_true",
        help="Raise max_alloc_pct to at least new target allocation when needed.",
    )
    parser.add_argument("--apply", action="store_true", help="Persist rebalance into policy file.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when plan is not ready.")
    args = parser.parse_args()

    policy_path = Path(args.policy_path)
    report_path = Path(args.diversification_report_path)
    out_path = Path(args.out_path)
    included_modes = [m.strip() for m in str(args.included_modes).split(",") if m.strip()]

    policy = _read_json(policy_path)
    report = _read_json(report_path)
    plan = build_rebalance_plan(
        policy=policy,
        diversification_report=report,
        included_modes=included_modes,
        update_max_alloc=bool(args.update_max_alloc),
    )
    payload: dict[str, object] = {
        "ts_utc": _utc_now(),
        "policy_path": str(policy_path),
        "diversification_report_path": str(report_path),
        "apply_requested": bool(args.apply),
        "plan": plan,
        "applied": False,
    }
    if bool(args.apply) and bool(plan.get("plan_ready", False)):
        updated_policy = apply_rebalance_to_policy(dict(policy), plan)
        policy_path.write_text(json.dumps(updated_policy, indent=2), encoding="utf-8")
        payload["applied"] = True
        payload["applied_ts_utc"] = _utc_now()
    elif bool(args.apply):
        payload["apply_blocked_reason"] = "plan_not_ready"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[road9-allocation] status={plan.get('status', 'fail')} applied={payload.get('applied', False)}")
    print(f"[road9-allocation] evidence={out_path}")
    if bool(args.strict) and not bool(plan.get("plan_ready", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
