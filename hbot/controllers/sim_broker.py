"""
SimBroker — shadow executor for live-vs-paper calibration.

Receives processed_data each tick and simulates what would have happened
with a more realistic fill model. Produces shadow_minute.csv for comparison.
"""

import atexit
import csv
import logging
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass
class SimBrokerConfig:
    enabled: bool = False
    prob_fill_on_limit: float = 0.35
    log_dir: str = ""
    # If live fills are available, compare
    compare_with_live: bool = True


@dataclass
class ShadowPosition:
    base: Decimal = _ZERO
    avg_entry: Decimal = _ZERO
    realized_pnl: Decimal = _ZERO
    fill_count: int = 0
    adverse_fills: int = 0


class SimBroker:
    """Shadow executor for live-vs-paper calibration."""

    def __init__(self, config: SimBrokerConfig):
        self.config = config
        self._position = ShadowPosition()
        self._tick_count: int = 0
        self._fill_count: int = 0
        self._shadow_csv_path: Path | None = None
        self._csv_writer = None
        self._csv_file = None
        self._last_mid: Decimal = _ZERO
        self._started = False
        # Track for metrics
        self._session_fills: int = 0
        self._session_adverse: int = 0

    def start(self, log_dir: str) -> None:
        """Initialize CSV output."""
        if not self.config.enabled:
            return
        if self._csv_file is not None:
            self.stop()
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        self._shadow_csv_path = path / "shadow_minute.csv"
        write_header = not self._shadow_csv_path.exists()
        fp = open(self._shadow_csv_path, "a", newline="")  # noqa: SIM115
        try:
            writer = csv.writer(fp)
            if write_header:
                writer.writerow([
                    "ts", "mid", "shadow_position", "shadow_pnl",
                    "shadow_fill_count", "shadow_adverse_fills",
                    "shadow_fill_rate", "prob_fill", "tick_count",
                ])
            self._csv_file = fp
            self._csv_writer = writer
        except Exception:
            fp.close()
            raise
        self._started = True
        atexit.register(self.stop)

    def on_tick(self, processed_data: dict[str, Any]) -> dict[str, Any]:
        """Process one tick of shadow execution.

        Returns shadow metrics dict for inclusion in processed_data.
        """
        if not self.config.enabled or not self._started:
            return {}

        self._tick_count += 1

        # Extract data from processed_data
        try:
            mid = Decimal(str(processed_data.get("mid_price", 0)))
        except Exception:
            return {}
        if mid.is_nan() or mid.is_infinite() or mid <= 0:
            return {}
        self._last_mid = mid

        # Get proposed levels from processed_data
        buy_prices = processed_data.get("buy_prices", [])
        sell_prices = processed_data.get("sell_prices", [])
        buy_amounts = processed_data.get("buy_amounts", [])
        sell_amounts = processed_data.get("sell_amounts", [])

        # Simulate fills with queue probability
        for i, bp in enumerate(buy_prices[:len(buy_amounts)]):
            price = Decimal(str(bp)) if not isinstance(bp, Decimal) else bp
            amount = Decimal(str(buy_amounts[i])) if not isinstance(buy_amounts[i], Decimal) else buy_amounts[i]
            if random.random() < self.config.prob_fill_on_limit:
                self._simulate_fill("buy", price, amount, mid)

        for i, sp in enumerate(sell_prices[:len(sell_amounts)]):
            price = Decimal(str(sp)) if not isinstance(sp, Decimal) else sp
            amount = Decimal(str(sell_amounts[i])) if not isinstance(sell_amounts[i], Decimal) else sell_amounts[i]
            if random.random() < self.config.prob_fill_on_limit:
                self._simulate_fill("sell", price, amount, mid)

        # Compute metrics
        fill_rate = self._fill_count / max(self._tick_count, 1)
        adverse_rate = self._position.adverse_fills / max(self._position.fill_count, 1)

        metrics = {
            "shadow_position": str(self._position.base),
            "shadow_pnl": str(self._position.realized_pnl),
            "shadow_fill_count": self._position.fill_count,
            "shadow_fill_rate": f"{fill_rate:.4f}",
            "shadow_adverse_rate": f"{adverse_rate:.4f}",
        }

        # Write to CSV every 60 ticks (~1 min at 1s ticks)
        if self._tick_count % 60 == 0 and self._csv_writer:
            self._csv_writer.writerow([
                int(time.time()), str(mid),
                str(self._position.base), str(self._position.realized_pnl),
                self._position.fill_count, self._position.adverse_fills,
                f"{fill_rate:.4f}", self.config.prob_fill_on_limit,
                self._tick_count,
            ])
            if self._csv_file:
                self._csv_file.flush()

        return metrics

    def _simulate_fill(self, side: str, price: Decimal, amount: Decimal, mid: Decimal) -> None:
        """Simulate a single fill."""
        self._fill_count += 1
        self._position.fill_count += 1

        sign = _ONE if side == "buy" else Decimal("-1")
        old_base = self._position.base
        new_base = old_base + sign * amount

        # Check adverse: did we buy above mid or sell below mid?
        if mid <= _ZERO:
            return
        edge_bps = (price - mid) / mid * Decimal("10000") * sign
        if edge_bps < Decimal("-2"):  # worse than -2 bps
            self._position.adverse_fills += 1

        # Track PnL on position reduction
        if old_base != _ZERO and ((old_base > 0 and sign < 0) or (old_base < 0 and sign > 0)):
            reduce_qty = min(abs(amount), abs(old_base))
            pnl = (price - self._position.avg_entry) * reduce_qty
            if old_base < 0:
                pnl = -pnl
            self._position.realized_pnl += pnl

        # Update avg entry
        if new_base != _ZERO:
            if (old_base >= 0 and sign > 0) or (old_base <= 0 and sign < 0):
                # Adding to position
                total_cost = self._position.avg_entry * abs(old_base) + price * amount
                self._position.avg_entry = total_cost / abs(new_base) if new_base != _ZERO else _ZERO
            # On reduction, avg_entry stays
        else:
            self._position.avg_entry = _ZERO

        self._position.base = new_base

    def stop(self) -> None:
        """Close CSV file. Safe to call multiple times."""
        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception:
                pass  # best-effort on shutdown
            self._csv_file = None
            self._csv_writer = None
