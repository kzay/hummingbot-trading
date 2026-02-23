"""Cross-environment parity report.

Compares fills.csv and minute.csv metrics from two environments (e.g., paper
bot3 vs testnet bot4) and flags divergences that suggest simulation gives
false confidence.

Usage::

    python scripts/analysis/parity_report.py \\
        --env-a bot3 --variant-a a \\
        --env-b bot4 --variant-b a
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.utils import safe_float, utc_now, write_json


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _compute_env_metrics(
    fills: List[Dict[str, str]],
    minutes: List[Dict[str, str]],
) -> Dict[str, object]:
    """Compute key metrics from one environment's data."""
    if not minutes:
        return {"status": "no_minute_data"}

    total_minutes = len(minutes)
    running_count = sum(1 for r in minutes if str(r.get("state", "")).strip() == "running")
    running_pct = running_count / total_minutes if total_minutes > 0 else 0

    regime_counts: Dict[str, int] = Counter()
    for r in minutes:
        regime_counts[str(r.get("regime", "unknown")).strip()] += 1
    regime_dist = {k: round(v / total_minutes, 4) for k, v in regime_counts.items()} if total_minutes > 0 else {}

    avg_spread = 0.0
    spread_values = [safe_float(r.get("spread_pct")) for r in minutes if safe_float(r.get("spread_pct")) > 0]
    if spread_values:
        avg_spread = sum(spread_values) / len(spread_values)

    avg_edge = 0.0
    edge_values = [safe_float(r.get("net_edge_pct")) for r in minutes]
    if edge_values:
        avg_edge = sum(edge_values) / len(edge_values)

    fill_count = len(fills)
    hours = total_minutes / 60.0
    fills_per_hour = fill_count / hours if hours > 0 else 0

    maker_count = sum(1 for f in fills if str(f.get("is_maker", "")).lower() == "true")
    maker_ratio = maker_count / fill_count if fill_count > 0 else 0

    total_capture = 0.0
    total_notional = 0.0
    for f in fills:
        price = safe_float(f.get("price"))
        mid = safe_float(f.get("mid_ref"))
        notional = safe_float(f.get("notional_quote"))
        side = str(f.get("side", "")).lower()
        if price <= 0 or mid <= 0 or notional <= 0:
            continue
        if side == "buy":
            capture = (mid - price) / mid * notional
        else:
            capture = (price - mid) / mid * notional
        total_capture += capture
        total_notional += notional

    avg_capture_bps = (total_capture / total_notional * 10000) if total_notional > 0 else 0

    avg_drift = 0.0
    drift_values = [safe_float(f.get("adverse_drift_30s")) for f in fills if safe_float(f.get("adverse_drift_30s")) > 0]
    if drift_values:
        avg_drift = sum(drift_values) / len(drift_values)

    return {
        "status": "ok",
        "total_minutes": total_minutes,
        "running_pct": round(running_pct, 4),
        "regime_distribution": regime_dist,
        "avg_spread_pct": round(avg_spread, 8),
        "avg_net_edge_pct": round(avg_edge, 8),
        "fill_count": fill_count,
        "fills_per_hour": round(fills_per_hour, 2),
        "maker_ratio": round(maker_ratio, 4),
        "avg_spread_capture_bps": round(avg_capture_bps, 2),
        "avg_adverse_drift": round(avg_drift, 8),
        "total_notional_quote": round(total_notional, 2),
    }


def _compare(metrics_a: Dict, metrics_b: Dict) -> Dict[str, object]:
    """Compare two environments and produce parity flags."""
    if metrics_a.get("status") != "ok" or metrics_b.get("status") != "ok":
        return {"status": "insufficient_data", "warnings": ["one or both environments have no data"]}

    warnings: List[str] = []

    fph_a = float(metrics_a.get("fills_per_hour", 0))
    fph_b = float(metrics_b.get("fills_per_hour", 0))
    if fph_b > 0 and fph_a / fph_b > 3.0:
        warnings.append(f"fill_rate_ratio={fph_a/fph_b:.1f}x — env_a fills {fph_a/fph_b:.1f}x more than env_b (possible simulation bias)")
    elif fph_a > 0 and fph_b / fph_a > 3.0:
        warnings.append(f"fill_rate_ratio={fph_b/fph_a:.1f}x — env_b fills {fph_b/fph_a:.1f}x more than env_a (possible simulation bias)")

    cap_a = float(metrics_a.get("avg_spread_capture_bps", 0))
    cap_b = float(metrics_b.get("avg_spread_capture_bps", 0))
    if cap_b != 0 and abs(cap_a - cap_b) / max(abs(cap_b), 1) > 0.5:
        warnings.append(f"spread_capture_divergence: env_a={cap_a:.2f}bps vs env_b={cap_b:.2f}bps (>50% difference)")

    regime_a = metrics_a.get("regime_distribution", {})
    regime_b = metrics_b.get("regime_distribution", {})
    all_regimes = set(list(regime_a.keys()) + list(regime_b.keys()))
    regime_divergence = sum(abs(float(regime_a.get(r, 0)) - float(regime_b.get(r, 0))) for r in all_regimes) / 2
    if regime_divergence > 0.10:
        warnings.append(f"regime_distribution_divergence={regime_divergence:.2%} (>10%)")

    maker_a = float(metrics_a.get("maker_ratio", 0))
    maker_b = float(metrics_b.get("maker_ratio", 0))
    if abs(maker_a - maker_b) > 0.2:
        warnings.append(f"maker_ratio_divergence: env_a={maker_a:.2%} vs env_b={maker_b:.2%}")

    parity_score = max(0, 10 - len(warnings) * 2.5)

    return {
        "status": "ok",
        "parity_score": round(parity_score, 1),
        "warning_count": len(warnings),
        "warnings": warnings,
        "fill_rate_ratio": round(fph_a / fph_b, 2) if fph_b > 0 else None,
        "spread_capture_a_bps": cap_a,
        "spread_capture_b_bps": cap_b,
        "regime_divergence": round(regime_divergence, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-environment parity report")
    parser.add_argument("--env-a", default="bot3", help="First environment bot name")
    parser.add_argument("--variant-a", default="a")
    parser.add_argument("--env-b", default="bot4", help="Second environment bot name")
    parser.add_argument("--variant-b", default="a")
    parser.add_argument("--data-root", default=str(_HBOT_ROOT / "data"))
    args = parser.parse_args()

    data_root = Path(args.data_root)

    def _load(bot: str, variant: str) -> Tuple[List[Dict], List[Dict]]:
        base = data_root / bot / "logs" / "epp_v24" / f"{bot}_{variant}"
        return _read_csv(base / "fills.csv"), _read_csv(base / "minute.csv")

    fills_a, minutes_a = _load(args.env_a, args.variant_a)
    fills_b, minutes_b = _load(args.env_b, args.variant_b)

    metrics_a = _compute_env_metrics(fills_a, minutes_a)
    metrics_b = _compute_env_metrics(fills_b, minutes_b)
    comparison = _compare(metrics_a, metrics_b)

    result = {
        "ts_utc": utc_now(),
        "env_a": {"bot": args.env_a, "variant": args.variant_a, "metrics": metrics_a},
        "env_b": {"bot": args.env_b, "variant": args.variant_b, "metrics": metrics_b},
        "comparison": comparison,
    }

    out_dir = _HBOT_ROOT / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "parity_report.json", result)

    score = comparison.get("parity_score", 0)
    print(f"[parity] score={score}/10 warnings={comparison.get('warning_count', 0)}")
    print(f"[parity] env_a ({args.env_a}): {metrics_a.get('fill_count', 0)} fills, {metrics_a.get('fills_per_hour', 0)} fills/h")
    print(f"[parity] env_b ({args.env_b}): {metrics_b.get('fill_count', 0)} fills, {metrics_b.get('fills_per_hour', 0)} fills/h")
    for w in comparison.get("warnings", []):
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    main()
