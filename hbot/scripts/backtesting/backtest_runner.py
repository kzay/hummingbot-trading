"""Event-driven backtest engine for EPP v2.4.

Replays historical OHLCV bars through a headless simulation of the EPP v2.4
spread model WITHOUT importing the Hummingbot runtime. All logic is reproduced
locally using the same parameters as the live controller.

Usage:
    from scripts.backtesting.backtest_runner import BacktestRunner, BacktestConfig
    cfg = BacktestConfig(parquet_path="data/historical/btc_usdt_1m.parquet")
    result = BacktestRunner(cfg).run()
    print(result.summary())
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ZERO = Decimal("0")
_ONE = Decimal("1")
_10K = Decimal("10000")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    parquet_path: str = ""
    csv_path: str = ""
    initial_equity_quote: Decimal = Decimal("500")
    maker_fee_pct: Decimal = Decimal("0.0002")
    taker_fee_pct: Decimal = Decimal("0.0006")
    slippage_bps: Decimal = Decimal("1.0")
    min_net_edge_bps: Decimal = Decimal("15")
    spread_min_pct: Decimal = Decimal("0.0025")
    spread_max_pct: Decimal = Decimal("0.0045")
    fill_factor: Decimal = Decimal("0.45")
    queue_participation: Decimal = Decimal("0.35")
    ema_period: int = 50
    atr_period: int = 14
    high_vol_band_pct: Decimal = Decimal("0.0080")
    trend_eps_pct: Decimal = Decimal("0.0010")
    shock_drift_pct: Decimal = Decimal("0.0100")
    max_base_pct: Decimal = Decimal("0.60")
    min_base_pct: Decimal = Decimal("0.0")
    total_amount_quote: Decimal = Decimal("50")
    max_daily_loss_pct: Decimal = Decimal("0.03")
    leverage: int = 1
    adverse_selection_bps: Decimal = Decimal("1.5")
    output_dir: str = "reports/backtest"


# ---------------------------------------------------------------------------
# Simple EMA / ATR helpers (no numpy, pure Python)
# ---------------------------------------------------------------------------

def _ema(prices: List[Decimal], period: int) -> Optional[Decimal]:
    if len(prices) < period:
        return None
    alpha = Decimal("2") / Decimal(period + 1)
    val = prices[-period]
    for p in prices[-period + 1:]:
        val = alpha * p + (_ONE - alpha) * val
    return val


def _atr_band_pct(highs: List[Decimal], lows: List[Decimal], closes: List[Decimal], period: int) -> Decimal:
    if len(closes) < 2 or len(highs) < 2 or len(lows) < 2:
        return _ZERO
    trs: List[Decimal] = []
    n = min(len(highs), len(lows), len(closes))
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs or closes[-1] <= _ZERO:
        return _ZERO
    p = min(period, len(trs))
    return sum(trs[-p:], _ZERO) / Decimal(p) / closes[-1]


def _detect_regime(
    mid: Decimal,
    closes: List[Decimal],
    highs: List[Decimal],
    lows: List[Decimal],
    cfg: BacktestConfig,
) -> str:
    ema50 = _ema(closes, cfg.ema_period)
    band_pct = _atr_band_pct(highs, lows, closes, cfg.atr_period)

    high_vol_mid = cfg.high_vol_band_pct * Decimal("0.5")
    if band_pct >= cfg.high_vol_band_pct:
        return "high_vol_shock"
    if ema50 is None:
        return "neutral_high_vol" if band_pct >= high_vol_mid else "neutral_low_vol"
    if mid > ema50 * (_ONE + cfg.trend_eps_pct):
        raw = "up"
    elif mid < ema50 * (_ONE - cfg.trend_eps_pct):
        raw = "down"
    else:
        raw = "neutral_high_vol" if band_pct >= high_vol_mid else "neutral_low_vol"
    return raw


# ---------------------------------------------------------------------------
# Paper fill simulation
# ---------------------------------------------------------------------------

def _simulate_fill(
    order_price: Decimal,
    bar_low: Decimal,
    bar_high: Decimal,
    side: str,
    queue_participation: Decimal,
    adverse_selection_bps: Decimal,
    mid: Decimal,
) -> Optional[Decimal]:
    """Returns fill price if order fills in this bar, else None."""
    if side == "buy":
        if order_price < bar_low:
            return None
        touched = order_price >= bar_low
    else:
        if order_price > bar_high:
            return None
        touched = order_price <= bar_high
    if not touched:
        return None
    import random
    if random.random() > float(queue_participation):
        return None
    adverse = adverse_selection_bps / _10K
    if side == "buy":
        return order_price * (_ONE - adverse)
    return order_price * (_ONE + adverse)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    config: BacktestConfig
    daily_pnl: List[Decimal] = field(default_factory=list)
    fills: List[Dict] = field(default_factory=list)
    minute_rows: List[Dict] = field(default_factory=list)
    final_equity: Decimal = _ZERO
    initial_equity: Decimal = _ZERO

    def summary(self) -> Dict:
        if not self.daily_pnl:
            return {"error": "no_data"}
        n = len(self.daily_pnl)
        mean_pnl = sum(self.daily_pnl, _ZERO) / Decimal(n)
        variance = sum((p - mean_pnl) ** 2 for p in self.daily_pnl) / Decimal(n)
        std_pnl = variance.sqrt() if variance > _ZERO else Decimal("0.0001")
        sharpe = float(mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > _ZERO else 0.0
        max_dd = _ZERO
        peak = self.initial_equity
        eq = self.initial_equity
        for pnl in self.daily_pnl:
            eq += pnl
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > _ZERO else _ZERO
            if dd > max_dd:
                max_dd = dd
        total_pnl = sum(self.daily_pnl, _ZERO)
        return {
            "n_days": n,
            "total_pnl_quote": float(total_pnl),
            "mean_daily_pnl_quote": float(mean_pnl),
            "std_daily_pnl_quote": float(std_pnl),
            "sharpe_annualized": round(sharpe, 3),
            "max_drawdown_pct": float(max_dd),
            "total_fills": len(self.fills),
            "final_equity": float(self.final_equity),
            "return_pct": float(total_pnl / self.initial_equity) if self.initial_equity > _ZERO else 0.0,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BacktestRunner:
    def __init__(self, config: BacktestConfig) -> None:
        self.cfg = config

    def _load_bars(self) -> List[Dict]:
        """Load OHLCV bars from Parquet or CSV. Returns list of dicts with keys: ts, open, high, low, close, volume."""
        bars: List[Dict] = []
        path = self.cfg.parquet_path or self.cfg.csv_path
        if not path:
            raise ValueError("Either parquet_path or csv_path must be set")
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Data file not found: {p}")

        if str(p).endswith(".parquet"):
            try:
                import pandas as pd  # type: ignore
                df = pd.read_parquet(p)
                for _, row in df.iterrows():
                    bars.append({
                        "ts": str(row.get("timestamp", row.get("ts", ""))),
                        "open": Decimal(str(row["open"])),
                        "high": Decimal(str(row["high"])),
                        "low": Decimal(str(row["low"])),
                        "close": Decimal(str(row["close"])),
                        "volume": Decimal(str(row.get("volume", 0))),
                    })
            except ImportError:
                raise ImportError("pandas and pyarrow are required for Parquet loading: pip install pandas pyarrow")
        else:
            import csv
            with open(p, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    bars.append({
                        "ts": row.get("timestamp", row.get("ts", "")),
                        "open": Decimal(str(row["open"])),
                        "high": Decimal(str(row["high"])),
                        "low": Decimal(str(row["low"])),
                        "close": Decimal(str(row["close"])),
                        "volume": Decimal(str(row.get("volume", 0))),
                    })
        return bars

    def run(self) -> BacktestResult:
        import random
        random.seed(42)
        bars = self._load_bars()
        cfg = self.cfg

        result = BacktestResult(config=cfg, initial_equity=cfg.initial_equity_quote)
        equity = cfg.initial_equity_quote
        position_base = _ZERO
        avg_entry = _ZERO
        realized_pnl_today = _ZERO
        equity_open_today = equity
        current_day = ""
        daily_pnl_today = _ZERO

        closes: List[Decimal] = []
        highs: List[Decimal] = []
        lows: List[Decimal] = []

        min_edge = cfg.min_net_edge_bps / _10K
        slippage = cfg.slippage_bps / _10K

        for bar in bars:
            mid = (bar["high"] + bar["low"]) / Decimal("2")
            closes.append(bar["close"])
            highs.append(bar["high"])
            lows.append(bar["low"])

            bar_day = str(bar["ts"])[:10]
            if bar_day != current_day:
                if current_day:
                    result.daily_pnl.append(daily_pnl_today)
                daily_pnl_today = _ZERO
                equity_open_today = equity
                realized_pnl_today = _ZERO
                current_day = bar_day
                daily_loss = _ZERO
            else:
                daily_loss = (equity_open_today - equity) / equity_open_today if equity_open_today > _ZERO else _ZERO

            if daily_loss >= cfg.max_daily_loss_pct:
                continue

            regime = _detect_regime(mid, closes, highs, lows, cfg)
            spread_pct = cfg.spread_min_pct
            if regime in ("neutral_high_vol", "up", "down"):
                spread_pct = (cfg.spread_min_pct + cfg.spread_max_pct) / Decimal("2")
            elif regime == "high_vol_shock":
                spread_pct = cfg.spread_max_pct

            spread_pct = max(spread_pct, (cfg.maker_fee_pct + slippage + min_edge) / cfg.fill_factor)

            net_edge = cfg.fill_factor * spread_pct - cfg.maker_fee_pct - slippage
            if net_edge < min_edge:
                continue

            base_val = abs(position_base) * mid
            base_pct = base_val / equity if equity > _ZERO else _ZERO

            buy_spread = spread_pct / Decimal("2")
            sell_spread = spread_pct / Decimal("2")

            if base_pct < cfg.max_base_pct:
                buy_price = mid * (_ONE - buy_spread)
                fill_px = _simulate_fill(
                    buy_price, bar["low"], bar["high"], "buy",
                    cfg.queue_participation, cfg.adverse_selection_bps, mid
                )
                if fill_px is not None:
                    amount = cfg.total_amount_quote / mid
                    fee = amount * fill_px * cfg.maker_fee_pct
                    if position_base < _ZERO:
                        close_qty = min(amount, abs(position_base))
                        close_pnl = close_qty * (avg_entry - fill_px) - fee
                        realized_pnl_today += close_pnl
                        equity += close_pnl
                    position_base += amount
                    avg_entry = fill_px
                    equity -= fee
                    daily_pnl_today += realized_pnl_today - _ZERO
                    result.fills.append({"ts": bar["ts"], "side": "buy", "price": float(fill_px), "fee": float(fee)})

            if base_pct > cfg.min_base_pct or position_base > _ZERO:
                sell_price = mid * (_ONE + sell_spread)
                fill_px = _simulate_fill(
                    sell_price, bar["low"], bar["high"], "sell",
                    cfg.queue_participation, cfg.adverse_selection_bps, mid
                )
                if fill_px is not None:
                    amount = cfg.total_amount_quote / mid
                    fee = amount * fill_px * cfg.maker_fee_pct
                    if position_base > _ZERO:
                        close_qty = min(amount, position_base)
                        close_pnl = close_qty * (fill_px - avg_entry) - fee
                        realized_pnl_today += close_pnl
                        equity += close_pnl
                    position_base -= amount
                    avg_entry = fill_px
                    equity -= fee
                    result.fills.append({"ts": bar["ts"], "side": "sell", "price": float(fill_px), "fee": float(fee)})

        if current_day:
            result.daily_pnl.append(daily_pnl_today)

        result.final_equity = equity
        return result

    def run_and_save(self, tag: str = "latest") -> BacktestResult:
        result = self.run()
        out_dir = Path(self.cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = result.summary()
        summary["tag"] = tag
        summary["config"] = {
            "spread_min_pct": float(self.cfg.spread_min_pct),
            "spread_max_pct": float(self.cfg.spread_max_pct),
            "min_net_edge_bps": float(self.cfg.min_net_edge_bps),
            "fill_factor": float(self.cfg.fill_factor),
            "initial_equity": float(self.cfg.initial_equity_quote),
        }
        (out_dir / f"backtest_{tag}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run EPP v2.4 backtest on historical OHLCV data")
    ap.add_argument("--data", required=True, help="Path to Parquet or CSV OHLCV file")
    ap.add_argument("--equity", type=float, default=500.0, help="Initial equity in USDT")
    ap.add_argument("--edge-bps", type=float, default=15.0, help="Minimum net edge in bps")
    ap.add_argument("--output", default="reports/backtest", help="Output directory")
    ap.add_argument("--tag", default="latest", help="Output tag for result file")
    args = ap.parse_args()

    cfg = BacktestConfig(
        parquet_path=args.data if args.data.endswith(".parquet") else "",
        csv_path=args.data if not args.data.endswith(".parquet") else "",
        initial_equity_quote=Decimal(str(args.equity)),
        min_net_edge_bps=Decimal(str(args.edge_bps)),
        output_dir=args.output,
    )
    runner = BacktestRunner(cfg)
    result = runner.run_and_save(tag=args.tag)
    import json as _json
    print(_json.dumps(result.summary(), indent=2))
