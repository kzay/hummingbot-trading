from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pandas_ta as ta  # noqa: F401


def load_ohlcv_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(set(df.columns))
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_50"] = ta.ema(out["close"], length=50)
    out["ema_200"] = ta.ema(out["close"], length=200)
    macd = ta.macd(out["close"], fast=12, slow=26, signal=9)
    out["macd"] = macd[[c for c in macd.columns if c.startswith("MACD_")][0]]
    out["macd_signal"] = macd[[c for c in macd.columns if c.startswith("MACDs_")][0]]
    adx = ta.adx(out["high"], out["low"], out["close"], length=14)
    out["adx"] = adx[[c for c in adx.columns if c.startswith("ADX")][0]]
    out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["atr_pct"] = out["atr"] / out["close"]
    out["vol_ema_12"] = ta.ema(out["volume"], length=12)
    out["vol_ema_26"] = ta.ema(out["volume"], length=26)
    out["vol_osc"] = (out["vol_ema_12"] - out["vol_ema_26"]) / out["vol_ema_26"]
    out["ret_fwd_1"] = out["close"].shift(-1) / out["close"] - 1.0
    return out.dropna().reset_index(drop=True)


def _ai_prob_proxy(row: pd.Series) -> float:
    x = 0.0
    x += 2.2 * ((row["ema_50"] - row["ema_200"]) / max(1e-12, row["close"]))
    x += 3.5 * (row["macd"] - row["macd_signal"])
    x += 1.5 * (row["adx"] / 100.0)
    x += 1.8 * row["vol_osc"]
    return 1.0 / (1.0 + math.exp(-max(-8.0, min(8.0, x))))


def run_backtest(
    df: pd.DataFrame,
    fee_bps: float,
    slippage_bps: float,
    funding_bps_per_day: float,
    threshold: float,
) -> Dict[str, float]:
    trades: List[float] = []
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    rounds = 0

    roundtrip_cost = (2.0 * fee_bps + 2.0 * slippage_bps + funding_bps_per_day / 24.0) / 10_000.0
    for _, row in df.iterrows():
        prob_up = _ai_prob_proxy(row)
        long_ok = (
            row["ema_50"] > row["ema_200"]
            and row["adx"] > 25.0
            and row["macd"] > row["macd_signal"]
            and row["vol_osc"] > 0
            and prob_up >= threshold
        )
        short_ok = (
            row["ema_50"] < row["ema_200"]
            and row["adx"] > 25.0
            and row["macd"] < row["macd_signal"]
            and row["vol_osc"] < 0
            and (1.0 - prob_up) >= threshold
        )
        if not long_ok and not short_ok:
            continue

        raw_ret = row["ret_fwd_1"] if long_ok else -row["ret_fwd_1"]
        net_ret = float(raw_ret - roundtrip_cost)
        trades.append(net_ret)
        rounds += 1

        equity += net_ret
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    if not trades:
        return {"trades": 0.0, "net_return": 0.0, "sharpe_proxy": 0.0, "max_drawdown": 0.0, "win_rate": 0.0}

    mean_ret = sum(trades) / len(trades)
    var = sum((x - mean_ret) ** 2 for x in trades) / max(1, len(trades) - 1)
    stdev = math.sqrt(max(1e-12, var))
    sharpe_proxy = mean_ret / stdev * math.sqrt(len(trades))
    win_rate = sum(1 for x in trades if x > 0) / len(trades)
    return {
        "trades": float(rounds),
        "net_return": float(sum(trades)),
        "sharpe_proxy": float(sharpe_proxy),
        "max_drawdown": float(max_dd),
        "win_rate": float(win_rate),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick cost-aware backtest for ai_trend_following_v1.")
    parser.add_argument("--input-csv", required=True, help="CSV with OHLCV columns")
    parser.add_argument("--output-json", default="hbot/scripts/analysis/reports/ai_trend_following_v1_backtest.json")
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--funding-bps-per-day", type=float, default=4.0)
    parser.add_argument("--threshold", type=float, default=0.70)
    args = parser.parse_args()

    df = load_ohlcv_csv(args.input_csv)
    feat = add_features(df)
    metrics = run_backtest(
        feat,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        funding_bps_per_day=args.funding_bps_per_day,
        threshold=args.threshold,
    )

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Backtest metrics written to: {out}")


if __name__ == "__main__":
    main()
