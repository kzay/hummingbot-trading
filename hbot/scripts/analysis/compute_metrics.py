from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Tuple


def _load_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "ts": float(r.get("ts", 0) or 0),
                "strategy": r.get("strategy", ""),
                "connector": r.get("connector", ""),
                "pair": r.get("pair", ""),
                "side": (r.get("side", "") or "").upper(),
                "price": float(r.get("price", 0) or 0),
                "amount": float(r.get("amount", 0) or 0),
                "fee": float(r.get("fee", 0) or 0),
                "realized_pnl": float(r.get("realized_pnl", 0) or 0),
            })
    rows.sort(key=lambda x: x["ts"])
    return rows


def _match_realized_pnl(rows: List[Dict[str, Any]]) -> Tuple[List[float], float]:
    """Estimate realized PnL when DB rows do not carry realized_pnl."""
    pnl_events: List[float] = []
    pos_qty = 0.0
    avg_entry = 0.0
    turnover = 0.0

    for r in rows:
        side = r["side"]
        qty = float(r["amount"])
        px = float(r["price"])
        turnover += abs(qty * px)
        if qty <= 0 or px <= 0 or side not in {"BUY", "SELL"}:
            continue
        signed = qty if side == "BUY" else -qty

        if pos_qty == 0.0 or (pos_qty > 0 and signed > 0) or (pos_qty < 0 and signed < 0):
            new_abs = abs(pos_qty) + abs(signed)
            avg_entry = (abs(pos_qty) * avg_entry + abs(signed) * px) / max(1e-12, new_abs)
            pos_qty += signed
            continue

        close_qty = min(abs(pos_qty), abs(signed))
        if pos_qty > 0:
            realized = close_qty * (px - avg_entry)
        else:
            realized = close_qty * (avg_entry - px)
        pnl_events.append(realized)
        pos_qty += signed

        if pos_qty == 0:
            avg_entry = 0.0
        elif abs(signed) > close_qty:
            # Flipped side.
            avg_entry = px

    return pnl_events, turnover


def compute_metrics(
    rows: List[Dict[str, Any]],
    taker_fee_bps: float,
    slippage_bps: float,
    funding_bps_per_day: float,
    expected_holding_hours: float,
) -> Dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "trades": 0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "max_drawdown": 0.0,
            "sharpe_proxy": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "turnover": 0.0,
        }

    explicit_realized = [r["realized_pnl"] for r in rows if abs(r.get("realized_pnl", 0.0)) > 1e-12]
    if explicit_realized:
        pnl_events = explicit_realized
        turnover = sum(abs(r["price"] * r["amount"]) for r in rows)
    else:
        pnl_events, turnover = _match_realized_pnl(rows)

    roundtrip_cost_bps = (2 * taker_fee_bps) + (2 * slippage_bps) + (funding_bps_per_day * expected_holding_hours / 24.0)
    event_cost = turnover * (roundtrip_cost_bps / 10000.0) / max(1, len(rows))
    net_events = [p - event_cost for p in pnl_events]

    gross_pnl = sum(pnl_events)
    net_pnl = sum(net_events)
    wins = [p for p in net_events if p > 0]
    losses = [p for p in net_events if p < 0]
    win_rate = len(wins) / max(1, len(net_events))
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (float("inf") if wins else 0.0)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in net_events:
        equity += p
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    sharpe_proxy = 0.0
    if len(net_events) > 1:
        sigma = pstdev(net_events)
        if sigma > 1e-12:
            sharpe_proxy = mean(net_events) / sigma * math.sqrt(len(net_events))

    return {
        "rows": len(rows),
        "trades": len(net_events),
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "max_drawdown": max_dd,
        "sharpe_proxy": sharpe_proxy,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "turnover": turnover,
        "cost_bps_roundtrip": roundtrip_cost_bps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute cost-aware strategy metrics from extracted trade CSV.")
    parser.add_argument("--input", required=True, help="Input extracted CSV path")
    parser.add_argument("--output-json", required=True, help="Output metrics JSON path")
    parser.add_argument("--taker-fee-bps", type=float, default=6.0)
    parser.add_argument("--slippage-bps", type=float, default=4.0)
    parser.add_argument("--funding-bps-per-day", type=float, default=2.0)
    parser.add_argument("--expected-holding-hours", type=float, default=12.0)
    args = parser.parse_args()

    rows = _load_csv(args.input)
    metrics = compute_metrics(
        rows,
        taker_fee_bps=args.taker_fee_bps,
        slippage_bps=args.slippage_bps,
        funding_bps_per_day=args.funding_bps_per_day,
        expected_holding_hours=args.expected_holding_hours,
    )
    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Wrote metrics to {out}")


if __name__ == "__main__":
    main()
