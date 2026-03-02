"""Walk-forward backtest for EPP v2.4.

Splits OHLCV data into 3 temporal windows and runs:
  - fit window: parameter calibration (min_net_edge_bps sweep)
  - validate window: parameter selection
  - test window: out-of-sample evaluation (never seen during fit/validate)

Each window is tested independently. If OOS Sharpe >= 1.0 on all 3 test
windows, the strategy passes the walk-forward gate.

Usage:
    python -m scripts.backtesting.walk_forward --data data/historical/btc_1m.parquet
    python -m scripts.backtesting.walk_forward --data data/historical/btc_1m.parquet --edge-sweep "10,15,20,25"
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from scripts.backtesting.backtest_runner import BacktestConfig, BacktestRunner, BacktestResult

_ZERO = Decimal("0")


@dataclass
class WalkForwardWindow:
    name: str
    start_idx: int
    end_idx: int
    best_edge_bps: Optional[Decimal] = None
    fit_sharpe: Optional[float] = None
    validate_sharpe: Optional[float] = None
    test_sharpe: Optional[float] = None
    test_result: Optional[BacktestResult] = None

    def passed(self, min_oos_sharpe: float = 1.0) -> bool:
        return self.test_sharpe is not None and self.test_sharpe >= min_oos_sharpe


def _run_with_config(bars: List[Dict], cfg: BacktestConfig) -> BacktestResult:
    """Run backtest on a pre-sliced list of bars."""
    import tempfile
    import csv
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for bar in bars:
            writer.writerow({
                "timestamp": bar["ts"],
                "open": bar.get("open", bar["close"]),
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar.get("volume", 0),
            })
        tmp_path = f.name

    try:
        cfg_copy = BacktestConfig(
            csv_path=tmp_path,
            initial_equity_quote=cfg.initial_equity_quote,
            maker_fee_pct=cfg.maker_fee_pct,
            taker_fee_pct=cfg.taker_fee_pct,
            slippage_bps=cfg.slippage_bps,
            min_net_edge_bps=cfg.min_net_edge_bps,
            spread_min_pct=cfg.spread_min_pct,
            spread_max_pct=cfg.spread_max_pct,
            fill_factor=cfg.fill_factor,
            queue_participation=cfg.queue_participation,
            ema_period=cfg.ema_period,
            atr_period=cfg.atr_period,
            high_vol_band_pct=cfg.high_vol_band_pct,
            trend_eps_pct=cfg.trend_eps_pct,
            max_daily_loss_pct=cfg.max_daily_loss_pct,
            total_amount_quote=cfg.total_amount_quote,
            output_dir=cfg.output_dir,
        )
        return BacktestRunner(cfg_copy).run()
    finally:
        os.unlink(tmp_path)


class WalkForwardBacktest:
    """3-window walk-forward: 50% fit / 25% validate / 25% test."""

    def __init__(
        self,
        data_path: str,
        base_config: BacktestConfig,
        edge_bps_candidates: Optional[List[Decimal]] = None,
        n_windows: int = 3,
        min_oos_sharpe: float = 1.0,
        output_dir: str = "reports/backtest",
    ) -> None:
        self.data_path = data_path
        self.base_config = base_config
        self.edge_candidates = edge_bps_candidates or [
            Decimal("10"), Decimal("12"), Decimal("15"), Decimal("18"), Decimal("20"), Decimal("25"),
        ]
        self.n_windows = n_windows
        self.min_oos_sharpe = min_oos_sharpe
        self.output_dir = Path(output_dir)

    def _load_bars(self) -> List[Dict]:
        runner = BacktestRunner(self.base_config)
        runner.cfg.parquet_path = self.data_path if self.data_path.endswith(".parquet") else ""
        runner.cfg.csv_path = self.data_path if not self.data_path.endswith(".parquet") else ""
        return runner._load_bars()

    def _run_window(self, bars: List[Dict], edge_bps: Decimal) -> BacktestResult:
        cfg = BacktestConfig(
            initial_equity_quote=self.base_config.initial_equity_quote,
            maker_fee_pct=self.base_config.maker_fee_pct,
            slippage_bps=self.base_config.slippage_bps,
            min_net_edge_bps=edge_bps,
            spread_min_pct=self.base_config.spread_min_pct,
            spread_max_pct=self.base_config.spread_max_pct,
            fill_factor=self.base_config.fill_factor,
            output_dir=str(self.output_dir),
        )
        return _run_with_config(bars, cfg)

    def _sharpe(self, result: BacktestResult) -> float:
        s = result.summary()
        return float(s.get("sharpe_annualized", 0.0))

    def run(self) -> Dict:
        bars = self._load_bars()
        n = len(bars)
        if n < 1000:
            raise ValueError(f"Need at least 1000 bars for walk-forward, got {n}")

        window_size = n // (self.n_windows + 1)
        fit_size = window_size * 2
        validate_size = window_size
        test_size = n - fit_size - validate_size

        windows: List[WalkForwardWindow] = []
        results_per_window: List[Dict] = []

        for w in range(self.n_windows):
            offset = w * (test_size // max(1, self.n_windows))
            fit_start = offset
            fit_end = offset + fit_size
            val_start = fit_end
            val_end = val_start + validate_size
            test_start = val_end
            test_end = min(test_start + test_size, n)

            if test_end > n or test_start >= n:
                break

            fit_bars = bars[fit_start:fit_end]
            val_bars = bars[val_start:val_end]
            test_bars = bars[test_start:test_end]

            best_edge = self.edge_candidates[0]
            best_val_sharpe = -999.0

            for edge_bps in self.edge_candidates:
                val_result = self._run_window(val_bars, edge_bps)
                val_sharpe = self._sharpe(val_result)
                if val_sharpe > best_val_sharpe:
                    best_val_sharpe = val_sharpe
                    best_edge = edge_bps

            fit_result = self._run_window(fit_bars, best_edge)
            test_result = self._run_window(test_bars, best_edge)

            wf = WalkForwardWindow(
                name=f"window_{w + 1}",
                start_idx=fit_start,
                end_idx=test_end,
                best_edge_bps=best_edge,
                fit_sharpe=self._sharpe(fit_result),
                validate_sharpe=best_val_sharpe,
                test_sharpe=self._sharpe(test_result),
                test_result=test_result,
            )
            windows.append(wf)

            window_summary = {
                "window": w + 1,
                "fit_bars": len(fit_bars),
                "validate_bars": len(val_bars),
                "test_bars": len(test_bars),
                "best_edge_bps": float(best_edge),
                "fit_sharpe": wf.fit_sharpe,
                "validate_sharpe": wf.validate_sharpe,
                "test_sharpe": wf.test_sharpe,
                "test_summary": test_result.summary(),
                "passed": wf.passed(self.min_oos_sharpe),
            }
            results_per_window.append(window_summary)

        all_passed = all(w.passed(self.min_oos_sharpe) for w in windows)
        mean_oos = sum(w.test_sharpe or 0.0 for w in windows) / max(1, len(windows))

        output = {
            "gate": "PASS" if all_passed else "FAIL",
            "n_windows": len(windows),
            "min_oos_sharpe_threshold": self.min_oos_sharpe,
            "mean_oos_sharpe": round(mean_oos, 3),
            "all_windows_passed": all_passed,
            "windows": results_per_window,
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "walk_forward_latest.json").write_text(
            json.dumps(output, indent=2), encoding="utf-8"
        )
        print(f"Walk-forward complete: {output['gate']}  mean_oos_sharpe={mean_oos:.3f}")
        return output


if __name__ == "__main__":
    import argparse
    from decimal import Decimal

    ap = argparse.ArgumentParser(description="Walk-forward backtest for EPP v2.4")
    ap.add_argument("--data", required=True, help="Path to OHLCV Parquet or CSV")
    ap.add_argument("--equity", type=float, default=500.0)
    ap.add_argument("--edge-sweep", default="10,12,15,18,20,25", help="Comma-separated edge_bps candidates")
    ap.add_argument("--windows", type=int, default=3)
    ap.add_argument("--min-sharpe", type=float, default=1.0, help="Minimum OOS Sharpe to pass gate")
    ap.add_argument("--output", default="reports/backtest")
    args = ap.parse_args()

    edge_candidates = [Decimal(x.strip()) for x in args.edge_sweep.split(",")]
    base_cfg = BacktestConfig(initial_equity_quote=Decimal(str(args.equity)))
    wf = WalkForwardBacktest(
        data_path=args.data,
        base_config=base_cfg,
        edge_bps_candidates=edge_candidates,
        n_windows=args.windows,
        min_oos_sharpe=args.min_sharpe,
        output_dir=args.output,
    )
    result = wf.run()
    print(json.dumps(result, indent=2))
