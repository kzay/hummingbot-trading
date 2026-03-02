"""Transaction Cost Analysis (TCA) report for bot1.

Analyses fill quality from fills.csv joined with minute.csv. For each fill:
- implementation_shortfall: fill_price vs mid at order placement (from mid_ref column)
- market_impact: price move 60s after fill (t+1 minute row mid)
- adverse_selection_flag: pnl_vs_mid < 0

Aggregates by: regime, hour-of-day, order side, spread level.

Usage:
    python hbot/scripts/analysis/bot1_tca_report.py --start 2026-01-01 --end 2026-01-20
    python hbot/scripts/analysis/bot1_tca_report.py --day 2026-02-27 --save
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ZERO = Decimal("0")
_10K = Decimal("10000")
_REPORTS_DIR = Path("hbot/reports/strategy")


def _d(x) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return _ZERO


def _parse_ts(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


@dataclass
class FillRecord:
    ts: datetime
    side: str
    fill_price: Decimal
    mid_ref: Decimal
    fee_quote: Decimal
    notional: Decimal
    is_maker: bool
    regime: str = "unknown"
    spread_pct: Decimal = _ZERO

    @property
    def implementation_shortfall_bps(self) -> Decimal:
        if self.mid_ref <= _ZERO:
            return _ZERO
        if self.side == "buy":
            is_cost = (self.fill_price - self.mid_ref) / self.mid_ref * _10K
        else:
            is_cost = (self.mid_ref - self.fill_price) / self.mid_ref * _10K
        return is_cost

    @property
    def adverse_flag(self) -> bool:
        return self.implementation_shortfall_bps < _ZERO


@dataclass
class TcaBucket:
    label: str
    fills: int = 0
    buys: int = 0
    sells: int = 0
    adverse_fills: int = 0
    is_bps_sum: Decimal = _ZERO
    market_impact_bps_sum: Decimal = _ZERO
    fees_sum: Decimal = _ZERO
    notional_sum: Decimal = _ZERO

    def add(self, rec: FillRecord, market_impact_bps: Decimal) -> None:
        self.fills += 1
        if rec.side == "buy":
            self.buys += 1
        else:
            self.sells += 1
        if rec.adverse_flag:
            self.adverse_fills += 1
        self.is_bps_sum += rec.implementation_shortfall_bps
        self.market_impact_bps_sum += market_impact_bps
        self.fees_sum += rec.fee_quote
        self.notional_sum += rec.notional

    def to_dict(self) -> Dict:
        n = max(1, self.fills)
        adverse_rate = self.adverse_fills / self.fills if self.fills else 0.0
        return {
            "label": self.label,
            "fills": self.fills,
            "buys": self.buys,
            "sells": self.sells,
            "adverse_fills": self.adverse_fills,
            "adverse_selection_rate": round(adverse_rate, 4),
            "avg_implementation_shortfall_bps": float(self.is_bps_sum / n),
            "avg_market_impact_bps": float(self.market_impact_bps_sum / n),
            "total_fees_quote": float(self.fees_sum),
            "total_notional_quote": float(self.notional_sum),
            "fee_rate_bps": float(self.fees_sum / self.notional_sum * _10K) if self.notional_sum > _ZERO else 0.0,
        }


def _load_fills(fills_path: Path, start: Optional[datetime], end: Optional[datetime]) -> List[Dict]:
    rows = []
    if not fills_path.exists():
        return rows
    with fills_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row.get("ts", ""))
            if ts is None:
                continue
            if start and ts < start:
                continue
            if end and ts >= end:
                continue
            # Keep parsed datetime under "ts" (don't let CSV string overwrite it).
            rows.append({**row, "ts": ts})
    return rows


def _load_minute(minute_path: Path, start: Optional[datetime], end: Optional[datetime]) -> List[Dict]:
    rows = []
    if not minute_path.exists():
        return rows
    with minute_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = _parse_ts(row.get("ts", ""))
            if ts is None:
                continue
            if start and ts < start:
                continue
            if end and ts >= end:
                continue
            # Keep parsed datetime under "ts" (don't let CSV string overwrite it).
            rows.append({**row, "ts": ts})
    return rows


def _build_minute_index(minute_rows: List[Dict]) -> Dict[int, Dict]:
    """Index minute rows by truncated unix minute timestamp for fast lookup."""
    idx: Dict[int, Dict] = {}
    for row in minute_rows:
        ts = row["ts"]
        if not isinstance(ts, datetime):
            ts = _parse_ts(str(ts))
            if ts is None:
                continue
        minute_key = int(ts.timestamp() // 60)
        idx[minute_key] = row
    return idx


def _get_minute_mid(minute_idx: Dict[int, Dict], ts: datetime, offset_minutes: int = 0) -> Optional[Decimal]:
    key = int(ts.timestamp() // 60) + offset_minutes
    row = minute_idx.get(key)
    if row is None:
        return None
    mid = _d(row.get("mid", "0"))
    return mid if mid > _ZERO else None


def run_tca(
    fills_path: Path,
    minute_path: Path,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    save: bool = False,
) -> Dict:
    fills_raw = _load_fills(fills_path, start, end)
    minute_raw = _load_minute(minute_path, start, end)

    if not fills_raw:
        return {"error": "no_fills_in_range"}

    minute_idx = _build_minute_index(minute_raw)

    records: List[Tuple[FillRecord, Decimal]] = []

    for row in fills_raw:
        ts = row["ts"]
        side = str(row.get("side", "")).lower().strip()
        fill_price = _d(row.get("price", "0"))
        mid_ref = _d(row.get("mid_ref", "0"))
        fee_quote = _d(row.get("fee_quote", "0"))
        notional = _d(row.get("notional_quote", "0"))
        is_maker = str(row.get("is_maker", "false")).lower().strip() in {"true", "1", "yes"}

        minute_row = minute_idx.get(int(ts.timestamp() // 60))
        regime = "unknown"
        spread_pct = _ZERO
        if minute_row:
            regime = str(minute_row.get("regime", "unknown"))
            spread_pct = _d(minute_row.get("spread_pct", "0"))

        rec = FillRecord(
            ts=ts,
            side=side,
            fill_price=fill_price,
            mid_ref=mid_ref,
            fee_quote=fee_quote,
            notional=notional,
            is_maker=is_maker,
            regime=regime,
            spread_pct=spread_pct,
        )

        mid_t1 = _get_minute_mid(minute_idx, ts, offset_minutes=1)
        if mid_t1 is not None and mid_ref > _ZERO:
            if side == "buy":
                market_impact = (mid_ref - mid_t1) / mid_ref * _10K
            else:
                market_impact = (mid_t1 - mid_ref) / mid_ref * _10K
        else:
            market_impact = _ZERO

        records.append((rec, market_impact))

    # Overall bucket
    overall = TcaBucket(label="overall")
    by_regime: Dict[str, TcaBucket] = defaultdict(lambda: TcaBucket(label=""))
    by_hour: Dict[int, TcaBucket] = defaultdict(lambda: TcaBucket(label=""))
    by_side: Dict[str, TcaBucket] = defaultdict(lambda: TcaBucket(label=""))
    by_spread: Dict[str, TcaBucket] = defaultdict(lambda: TcaBucket(label=""))
    by_maker: Dict[str, TcaBucket] = defaultdict(lambda: TcaBucket(label=""))

    for rec, mi in records:
        overall.add(rec, mi)

        regime_bucket = by_regime[rec.regime]
        regime_bucket.label = rec.regime
        regime_bucket.add(rec, mi)

        hour = rec.ts.hour
        hour_bucket = by_hour[hour]
        hour_bucket.label = f"hour_{hour:02d}"
        hour_bucket.add(rec, mi)

        side_bucket = by_side[rec.side]
        side_bucket.label = rec.side
        side_bucket.add(rec, mi)

        spread_label = "tight" if rec.spread_pct < Decimal("0.003") else "medium" if rec.spread_pct < Decimal("0.006") else "wide"
        spread_bucket = by_spread[spread_label]
        spread_bucket.label = spread_label
        spread_bucket.add(rec, mi)

        maker_label = "maker" if rec.is_maker else "taker"
        maker_bucket = by_maker[maker_label]
        maker_bucket.label = maker_label
        maker_bucket.add(rec, mi)

    # Worst regimes by adverse selection
    regime_ranked = sorted(by_regime.values(), key=lambda b: b.adverse_fills / max(1, b.fills), reverse=True)

    output = {
        "period": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "overall": overall.to_dict(),
        "by_regime": [b.to_dict() for b in sorted(by_regime.values(), key=lambda b: -b.fills)],
        "by_hour": [b.to_dict() for b in sorted(by_hour.values(), key=lambda b: b.label)],
        "by_side": [b.to_dict() for b in sorted(by_side.values(), key=lambda b: b.label)],
        "by_spread_level": [b.to_dict() for b in sorted(by_spread.values(), key=lambda b: b.label)],
        "by_maker_taker": [b.to_dict() for b in sorted(by_maker.values(), key=lambda b: b.label)],
        "worst_regimes_by_adverse_rate": [b.to_dict() for b in regime_ranked[:3]],
        "insights": _generate_insights(overall, by_regime, by_hour, by_side),
    }

    if save:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _REPORTS_DIR / "tca_latest.json"
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"Saved TCA report to {out_path}", file=sys.stderr)

    return output


def _generate_insights(
    overall: TcaBucket,
    by_regime: Dict[str, TcaBucket],
    by_hour: Dict[int, TcaBucket],
    by_side: Dict[str, TcaBucket],
) -> List[str]:
    insights = []
    if overall.fills == 0:
        return insights

    adverse_rate = overall.adverse_fills / overall.fills
    if adverse_rate > 0.60:
        insights.append(f"HIGH adverse selection rate {adverse_rate:.1%} — consider widening min_net_edge_bps")

    worst_regime = max(by_regime.values(), key=lambda b: b.adverse_fills / max(1, b.fills), default=None)
    if worst_regime and worst_regime.fills >= 10:
        r = worst_regime.adverse_fills / worst_regime.fills
        insights.append(f"Regime '{worst_regime.label}' has worst adverse rate {r:.1%} ({worst_regime.fills} fills) — consider wider spreads in this regime")

    worst_hour = max(by_hour.values(), key=lambda b: b.adverse_fills / max(1, b.fills), default=None)
    if worst_hour and worst_hour.fills >= 5:
        r = worst_hour.adverse_fills / worst_hour.fills
        insights.append(f"Hour {worst_hour.label} UTC has worst adverse rate {r:.1%} — consider pausing during this hour")

    avg_is = float(overall.is_bps_sum / max(1, overall.fills))
    if avg_is > 2.0:
        insights.append(f"Avg implementation shortfall {avg_is:.2f} bps suggests fills are hitting adverse prices — check queue participation setting")
    elif avg_is < -1.0:
        insights.append(f"Avg implementation shortfall {avg_is:.2f} bps (positive edge capture) — fills are landing at good prices")

    return insights


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="TCA report for bot1 fills")
    ap.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    ap.add_argument("--day", default=None, help="Single day YYYY-MM-DD (overrides --start/--end)")
    ap.add_argument("--root", default="hbot/data/bot1/logs/epp_v24/bot1_a")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    fills_path = root / "fills.csv"
    minute_path = root / "minute.csv"

    start_dt = end_dt = None
    if args.day:
        start_dt = _parse_date(args.day)
        end_dt = start_dt + timedelta(days=1)
    elif args.start:
        start_dt = _parse_date(args.start)
        end_dt = _parse_date(args.end) + timedelta(days=1) if args.end else None

    result = run_tca(fills_path, minute_path, start=start_dt, end=end_dt, save=args.save)
    print(json.dumps(result, indent=2))
