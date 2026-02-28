from __future__ import annotations

import argparse
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from services.common.utils import safe_bool as _safe_bool, safe_float as _safe_float
from services.contracts.stream_names import EXECUTION_INTENT_STREAM, STREAM_RETENTION_MAXLEN
from services.hb_bridge.redis_client import RedisStreamClient


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_policy(path: Path) -> Dict[str, object]:
    default = {
        "version": 1,
        "allocator": {
            "enabled": False,
            "rebalance_cooldown_hours": 24,
            "variance_window_days": 20,
            "min_total_equity_quote": 100.0,
        },
        "bots": {},
    }
    payload = _read_json(path)
    if not payload:
        return default
    merged = dict(default)
    merged.update(payload)
    return merged


def _symbol_bucket_from_cfg(cfg: Dict[str, object]) -> str:
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


def _eligible_bots(policy: Dict[str, object], snapshots: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    bots_cfg = policy.get("bots", {})
    snap_bots = snapshots.get("bots", {}) if isinstance(snapshots.get("bots"), dict) else {}
    if not isinstance(bots_cfg, dict):
        return out

    for bot, cfg_raw in bots_cfg.items():
        cfg = cfg_raw if isinstance(cfg_raw, dict) else {}
        enabled = bool(cfg.get("enabled", False))
        mode = str(cfg.get("mode", "")).strip().lower()
        if (not enabled) or mode == "disabled":
            continue
        snap = snap_bots.get(bot, {}) if isinstance(snap_bots.get(bot, {}), dict) else {}
        equity = _safe_float(snap.get("equity_quote"), 0.0)
        if equity <= 0.0:
            continue
        variance = _safe_float(cfg.get("alloc_variance_proxy"), 1.0)
        if variance <= 0.0:
            variance = 1.0
        max_alloc = _safe_float(cfg.get("max_alloc_pct"), 1.0)
        max_alloc = max(0.0, min(1.0, max_alloc))
        out[str(bot)] = {
            "equity_quote": equity,
            "variance": variance,
            "max_alloc_pct": max_alloc,
            "portfolio_action_enabled": 1.0 if bool(cfg.get("portfolio_action_enabled", False)) else 0.0,
            "variance_source": "policy_proxy",
            "symbol_bucket": _symbol_bucket_from_cfg(cfg),
        }
    return out


def _apply_diversification_variance_overrides(
    bots: Dict[str, Dict[str, object]],
    report: Dict[str, object],
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
    updated = {bot: dict(info) for bot, info in bots.items()}
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    inputs = report.get("inputs", {}) if isinstance(report.get("inputs"), dict) else {}
    btc_var = _safe_float(metrics.get("btc_variance"), 0.0)
    eth_var = _safe_float(metrics.get("eth_variance"), 0.0)
    corr = metrics.get("btc_eth_return_correlation")
    corr_float = _safe_float(corr, float("nan")) if corr is not None else float("nan")
    corr_available = not math.isnan(corr_float)
    max_abs_allowed = _safe_float(inputs.get("max_abs_correlation"), 0.70)
    corr_ok = (abs(corr_float) < max_abs_allowed) if corr_available else None

    overrides = 0
    for bot, info in updated.items():
        bucket = str(info.get("symbol_bucket", "other"))
        if bucket == "btc" and btc_var > 0.0:
            info["variance"] = btc_var
            info["variance_source"] = "diversification_report"
            overrides += 1
        elif bucket == "eth" and eth_var > 0.0:
            info["variance"] = eth_var
            info["variance_source"] = "diversification_report"
            overrides += 1

    return updated, {
        "report_status": str(report.get("status", "missing")),
        "correlation": (corr_float if corr_available else None),
        "max_abs_correlation": max_abs_allowed,
        "correlation_available": corr_available,
        "correlation_ok": corr_ok,
        "btc_variance": btc_var if btc_var > 0.0 else None,
        "eth_variance": eth_var if eth_var > 0.0 else None,
        "overrides_applied": overrides,
    }


def _compute_inverse_variance_allocations(bots: Dict[str, Dict[str, object]]) -> Dict[str, float]:
    if not bots:
        return {}
    raw: Dict[str, float] = {}
    denom = 0.0
    for bot, info in bots.items():
        variance = _safe_float(info.get("variance"), 1.0)
        w = 1.0 / max(variance, 1e-9)
        raw[bot] = w
        denom += w
    if denom <= 0:
        n = len(bots)
        return {k: 1.0 / n for k in bots.keys()}
    alloc = {bot: w / denom for bot, w in raw.items()}

    # Respect per-bot max caps; redistribute remainder among non-capped bots.
    capped = {bot: False for bot in alloc.keys()}
    for _ in range(len(alloc) + 2):
        changed = False
        overflow = 0.0
        for bot, pct in list(alloc.items()):
            cap = _safe_float(bots[bot].get("max_alloc_pct"), 1.0)
            if pct > cap + 1e-12:
                overflow += pct - cap
                alloc[bot] = cap
                capped[bot] = True
                changed = True
        if not changed or overflow <= 0:
            break
        receivers = [b for b in alloc.keys() if not capped[b]]
        if not receivers:
            break
        total_recv = sum(alloc[b] for b in receivers)
        if total_recv <= 0:
            share = overflow / len(receivers)
            for b in receivers:
                alloc[b] += share
        else:
            for b in receivers:
                alloc[b] += overflow * (alloc[b] / total_recv)
    total = sum(alloc.values())
    if total > 0:
        alloc = {bot: pct / total for bot, pct in alloc.items()}
    return alloc


def _build_proposals(
    bots: Dict[str, Dict[str, object]], allocations: Dict[str, float]
) -> Tuple[List[Dict[str, object]], float]:
    total_equity = sum(_safe_float(info.get("equity_quote"), 0.0) for info in bots.values())
    proposals: List[Dict[str, object]] = []
    for bot, info in sorted(bots.items()):
        alloc_pct = allocations.get(bot, 0.0)
        target_notional = alloc_pct * total_equity
        proposals.append(
            {
                "bot": bot,
                "equity_quote": _safe_float(info.get("equity_quote"), 0.0),
                "variance_proxy": _safe_float(info.get("variance"), 1.0),
                "variance_source": str(info.get("variance_source", "policy_proxy")),
                "symbol_bucket": str(info.get("symbol_bucket", "other")),
                "max_alloc_pct": _safe_float(info.get("max_alloc_pct"), 1.0),
                "allocation_pct": alloc_pct,
                "target_notional_quote": target_notional,
                "portfolio_action_enabled": bool(_safe_float(info.get("portfolio_action_enabled"), 0.0) > 0.5),
            }
        )
    return proposals, total_equity


def _publish_allocator_intent(
    client: RedisStreamClient, bot: str, allocation_pct: float, target_notional: float
) -> None:
    event_id = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    payload = {
        "schema_version": "1.0",
        "event_type": "execution_intent",
        "event_id": event_id,
        "correlation_id": event_id,
        "producer": "portfolio_allocator_service",
        "timestamp_ms": now_ms,
        "instance_name": bot,
        "controller_id": "epp_v2_4",
        "action": "resume",
        "target_base_pct": None,
        "expires_at_ms": now_ms + 300000,
        "metadata": {
            "reason": "portfolio_allocation_proposal",
            "allocation_pct": f"{allocation_pct:.6f}",
            "target_notional_quote": f"{target_notional:.6f}",
        },
    }
    client.xadd(
        EXECUTION_INTENT_STREAM,
        payload,
        maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
    )


def run(once: bool = False) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    policy_path = Path(os.getenv("MULTI_BOT_POLICY_PATH", str(root / "config" / "multi_bot_policy_v1.json")))
    snapshots_path = Path(
        os.getenv("EXCHANGE_SNAPSHOT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json"))
    )
    diversification_path = Path(
        os.getenv(
            "PORTFOLIO_DIVERSIFICATION_REPORT_PATH",
            str(root / "reports" / "policy" / "portfolio_diversification_latest.json"),
        )
    )
    report_path = Path(
        os.getenv("PORTFOLIO_ALLOCATOR_REPORT_PATH", str(root / "reports" / "policy" / "portfolio_allocator_latest.json"))
    )
    interval_sec = int(os.getenv("PORTFOLIO_ALLOCATOR_INTERVAL_SEC", "300"))
    emit_intents = _safe_bool(os.getenv("PORTFOLIO_ALLOCATOR_PUBLISH_INTENTS", "false"), False)
    enforce_diversification = _safe_bool(os.getenv("PORTFOLIO_ALLOCATOR_ENFORCE_DIVERSIFICATION", "false"), False)
    redis_client = RedisStreamClient(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD", "") or None,
        enabled=emit_intents,
    )

    while True:
        policy = _load_policy(policy_path)
        allocator_cfg = policy.get("allocator", {}) if isinstance(policy.get("allocator"), dict) else {}
        allocator_enabled = bool(allocator_cfg.get("enabled", False))
        min_total_equity = _safe_float(allocator_cfg.get("min_total_equity_quote"), 100.0)
        snapshots = _read_json(snapshots_path)
        eligible = _eligible_bots(policy, snapshots)
        diversification_report = _read_json(diversification_path)
        eligible, diversification_diag = _apply_diversification_variance_overrides(eligible, diversification_report)
        allocations = _compute_inverse_variance_allocations(eligible)
        proposals, total_equity = _build_proposals(eligible, allocations)
        status = "pass"
        reasons: List[str] = []
        if not allocator_enabled:
            status = "disabled"
            reasons.append("allocator_disabled_in_policy")
        if total_equity < min_total_equity:
            status = "blocked"
            reasons.append("insufficient_total_equity")
        if not proposals:
            status = "blocked"
            reasons.append("no_eligible_bots")
        if (
            enforce_diversification
            and diversification_diag.get("correlation_available") is True
            and diversification_diag.get("correlation_ok") is False
        ):
            status = "blocked"
            reasons.append("diversification_correlation_exceeds_threshold")

        if emit_intents and redis_client.enabled and status == "pass":
            for row in proposals:
                if not bool(row.get("portfolio_action_enabled", False)):
                    continue
                _publish_allocator_intent(
                    redis_client,
                    bot=str(row["bot"]),
                    allocation_pct=float(row["allocation_pct"]),
                    target_notional=float(row["target_notional_quote"]),
                )

        report = {
            "ts_utc": _utc_now(),
            "status": status,
            "reasons": reasons,
            "allocator_enabled": allocator_enabled,
            "emit_intents": bool(emit_intents),
            "policy_path": str(policy_path),
            "snapshots_path": str(snapshots_path),
            "diversification_report_path": str(diversification_path),
            "enforce_diversification": bool(enforce_diversification),
            "diversification": diversification_diag,
            "total_equity_quote": total_equity,
            "proposals": proposals,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        if once:
            break
        time.sleep(max(5, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Portfolio allocator scaffold service.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    args = parser.parse_args()
    run(once=args.once)
