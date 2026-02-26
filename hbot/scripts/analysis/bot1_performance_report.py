from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_ZERO = Decimal("0")
_TEN_K = Decimal("10000")


def _parse_ts(value: str) -> dt.datetime:
    # Accept "Z" and "+00:00" forms, always return tz-aware UTC.
    v = (value or "").strip()
    if not v:
        raise ValueError("empty ts")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    t = dt.datetime.fromisoformat(v)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def _d(x: object, default: Decimal = _ZERO) -> Decimal:
    if x is None:
        return default
    s = str(x).strip()
    if not s:
        return default
    try:
        return Decimal(s)
    except Exception:
        return default


def _iter_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fp:
        r = csv.DictReader(fp)
        for row in r:
            yield row


@dataclass
class FillAgg:
    fills: int = 0
    buys: int = 0
    sells: int = 0
    maker: int = 0
    taker: int = 0
    notional: Decimal = _ZERO
    fees: Decimal = _ZERO
    realized: Decimal = _ZERO
    edge_sum: Decimal = _ZERO
    edge_abs_sum: Decimal = _ZERO
    edge_pos: int = 0
    edge_n: int = 0
    spread_sum: Decimal = _ZERO
    spread_n: int = 0
    first_ts: Optional[dt.datetime] = None
    last_ts: Optional[dt.datetime] = None

    def add(self, r: Dict[str, str]) -> None:
        self.fills += 1
        side = str(r.get("side", "")).lower()
        if side == "buy":
            self.buys += 1
        elif side == "sell":
            self.sells += 1
        is_maker = str(r.get("is_maker", "")).strip().lower() == "true"
        if is_maker:
            self.maker += 1
        else:
            self.taker += 1

        self.notional += _d(r.get("notional_quote"))
        self.fees += _d(r.get("fee_quote"))
        self.realized += _d(r.get("realized_pnl_quote"))

        # Derive edge vs mid using mid_ref and fill price (fills.csv doesn't carry edge columns).
        price = _d(r.get("price"), default=Decimal("NaN"))
        mid_ref = _d(r.get("mid_ref"), default=Decimal("NaN"))
        edge = Decimal("NaN")
        if price.is_finite() and mid_ref.is_finite() and mid_ref > _ZERO:
            if side == "buy":
                edge = (mid_ref - price) / mid_ref
            elif side == "sell":
                edge = (price - mid_ref) / mid_ref
        if edge.is_finite():
            self.edge_sum += edge
            self.edge_abs_sum += abs(edge)
            self.edge_n += 1
            if edge > _ZERO:
                self.edge_pos += 1

        spread = _d(r.get("expected_spread_pct"), default=Decimal("NaN"))
        if spread.is_finite():
            self.spread_sum += spread
            self.spread_n += 1

        t = _parse_ts(str(r.get("ts", "")))
        if self.first_ts is None or t < self.first_ts:
            self.first_ts = t
        if self.last_ts is None or t > self.last_ts:
            self.last_ts = t

    def to_dict(self) -> Dict[str, object]:
        fee_rate = (self.fees / self.notional) if self.notional > 0 else _ZERO
        avg_edge = (self.edge_sum / Decimal(self.edge_n)) if self.edge_n else _ZERO
        avg_abs_edge = (self.edge_abs_sum / Decimal(self.edge_n)) if self.edge_n else _ZERO
        avg_spread = (self.spread_sum / Decimal(self.spread_n)) if self.spread_n else _ZERO
        pnl_per_notional_bps = (self.realized / self.notional * _TEN_K) if self.notional > 0 else _ZERO
        net_after_fees = self.realized - self.fees
        net_after_fees_bps = (net_after_fees / self.notional * _TEN_K) if self.notional > 0 else _ZERO
        return {
            "fills": self.fills,
            "buys": self.buys,
            "sells": self.sells,
            "maker": self.maker,
            "taker": self.taker,
            "maker_pct": float(self.maker / self.fills) if self.fills else 0.0,
            "notional_quote": str(self.notional),
            "fees_quote": str(self.fees),
            "fee_rate": str(fee_rate),
            "fee_bps": str(fee_rate * _TEN_K),
            "realized_pnl_sum_quote": str(self.realized),
            "realized_pnl_per_notional_bps": str(pnl_per_notional_bps),
            "net_pnl_after_fees_quote": str(net_after_fees),
            "net_pnl_after_fees_per_notional_bps": str(net_after_fees_bps),
            "avg_edge_vs_mid_pct": str(avg_edge),
            "avg_abs_edge_vs_mid_pct": str(avg_abs_edge),
            "avg_edge_vs_mid_bps": str(avg_edge * _TEN_K),
            "avg_abs_edge_vs_mid_bps": str(avg_abs_edge * _TEN_K),
            "pos_edge_frac": float(self.edge_pos / self.edge_n) if self.edge_n else 0.0,
            "avg_expected_spread_pct": str(avg_spread),
            "avg_expected_spread_bps": str(avg_spread * _TEN_K),
            "first_ts": self.first_ts.isoformat() if self.first_ts else None,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
        }


@dataclass
class MinuteRow:
    ts: dt.datetime
    state: str
    turnover_x: Decimal
    fills_today: int
    risk_reasons: str
    net_edge_pct: Decimal
    orders_active: Decimal


def _read_day_rows(rows: Iterable[Dict[str, str]], day: str) -> List[Dict[str, str]]:
    y, m, d = [int(x) for x in day.split("-")]
    start = dt.datetime(y, m, d, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    out = []
    for r in rows:
        try:
            t = _parse_ts(str(r.get("ts", "")))
        except Exception:
            continue
        if start <= t < end:
            out.append(r)
    return out


def _filter_cols(rows: List[Dict[str, str]], exchange: Optional[str], pair: Optional[str]) -> List[Dict[str, str]]:
    out = rows
    if exchange:
        ex = str(exchange).strip()
        out = [r for r in out if str(r.get("exchange", "")).strip() == ex]
    if pair:
        p = str(pair).strip()
        out = [r for r in out if str(r.get("trading_pair", "")).strip() == p]
    return out


def _minute_rows(rows: List[Dict[str, str]]) -> List[MinuteRow]:
    out: List[MinuteRow] = []
    for r in rows:
        try:
            t = _parse_ts(str(r.get("ts", "")))
        except Exception:
            continue
        out.append(
            MinuteRow(
                ts=t,
                state=str(r.get("state", "")).strip(),
                turnover_x=_d(r.get("turnover_today_x")),
                fills_today=int(_d(r.get("fills_count_today"))),
                risk_reasons=str(r.get("risk_reasons", "")).strip(),
                net_edge_pct=_d(r.get("net_edge_pct")),
                orders_active=_d(r.get("orders_active")),
            )
        )
    out.sort(key=lambda x: x.ts)
    return out


def _detect_resets(mins: List[MinuteRow]) -> List[dt.datetime]:
    """Return timestamps where counters likely reset (fills_today or turnover_x drops materially)."""
    resets: List[dt.datetime] = []
    prev: Optional[MinuteRow] = None
    for r in mins:
        if prev is not None:
            # Hard drop in counters indicates restart/reset of daily state.
            if r.fills_today < prev.fills_today:
                resets.append(r.ts)
            elif r.turnover_x >= 0 and prev.turnover_x > 0 and r.turnover_x < (prev.turnover_x * Decimal("0.5")):
                resets.append(r.ts)
        prev = r
    # Dedup near-equal times (same reset detected multiple ways)
    out: List[dt.datetime] = []
    for t in resets:
        if not out or (t - out[-1]).total_seconds() > 120:
            out.append(t)
    return out


def _segments(day_start: dt.datetime, day_end: dt.datetime, reset_times: List[dt.datetime], since: Optional[dt.datetime]) -> List[Tuple[dt.datetime, dt.datetime, str]]:
    cuts = [t for t in reset_times if day_start <= t < day_end]
    bounds = [day_start] + cuts + [day_end]
    segs: List[Tuple[dt.datetime, dt.datetime, str]] = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        name = f"seg_{i+1}"
        if since and b <= since:
            continue
        if since and a < since < b:
            a = since
            name = f"{name}_since"
        segs.append((a, b, name))
    return segs


def _fills_in_range(fills: List[Dict[str, str]], a: dt.datetime, b: dt.datetime) -> List[Dict[str, str]]:
    out = []
    for r in fills:
        try:
            t = _parse_ts(str(r.get("ts", "")))
        except Exception:
            continue
        if a <= t < b:
            out.append(r)
    return out


def _minute_state_summary(mins: List[MinuteRow], a: dt.datetime, b: dt.datetime) -> Dict[str, object]:
    in_rng = [m for m in mins if a <= m.ts < b]
    if not in_rng:
        return {"rows": 0}
    counts: Dict[str, int] = {}
    hard_reasons: Dict[str, int] = {}
    avg_net_edge = _ZERO
    n_edge = 0
    max_turn = _ZERO
    for m in in_rng:
        counts[m.state] = counts.get(m.state, 0) + 1
        if m.state == "hard_stop" and m.risk_reasons:
            for rr in m.risk_reasons.split("|"):
                rr = rr.strip()
                if rr:
                    hard_reasons[rr] = hard_reasons.get(rr, 0) + 1
        if m.net_edge_pct.is_finite():
            avg_net_edge += m.net_edge_pct
            n_edge += 1
        if m.turnover_x > max_turn:
            max_turn = m.turnover_x
    avg_net_edge = (avg_net_edge / Decimal(n_edge)) if n_edge else _ZERO
    return {
        "rows": len(in_rng),
        "state_counts": counts,
        "hard_stop_reasons": hard_reasons,
        "avg_net_edge_pct": str(avg_net_edge),
        "max_turnover_x": str(max_turn),
        "last_state": in_rng[-1].state,
        "last_risk_reasons": in_rng[-1].risk_reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="UTC day, e.g. 2026-02-26")
    ap.add_argument("--root", default="hbot/data/bot1/logs/epp_v24/bot1_a", help="log root")
    ap.add_argument("--exchange", default=None)
    ap.add_argument("--pair", default=None)
    ap.add_argument("--since-ts", default=None, help="Optional ISO timestamp; analyze from this time onward")
    args = ap.parse_args()

    root = Path(args.root)
    fills_path = root / "fills.csv"
    minute_path = root / "minute.csv"
    daily_state_path = None
    for p in sorted(root.glob("daily_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        daily_state_path = p
        break
    paper_desk_path = root / "paper_desk_v2.json"

    day_start = dt.datetime.fromisoformat(args.day).replace(tzinfo=dt.timezone.utc)
    day_end = day_start + dt.timedelta(days=1)
    since = _parse_ts(args.since_ts) if args.since_ts else None

    fills_day: List[Dict[str, str]] = []
    if fills_path.exists():
        fills_day = _filter_cols(_read_day_rows(_iter_csv_rows(fills_path), args.day), args.exchange, args.pair)
    minute_day: List[Dict[str, str]] = []
    if minute_path.exists():
        minute_day = _filter_cols(_read_day_rows(_iter_csv_rows(minute_path), args.day), args.exchange, args.pair)

    mins = _minute_rows(minute_day)
    resets = _detect_resets(mins)
    segs = _segments(day_start, day_end, resets, since)

    out: Dict[str, object] = {
        "day": args.day,
        "paths": {
            "fills_csv": str(fills_path) if fills_path.exists() else None,
            "minute_csv": str(minute_path) if minute_path.exists() else None,
            "daily_state": str(daily_state_path) if daily_state_path and daily_state_path.exists() else None,
            "paper_desk_v2_json": str(paper_desk_path) if paper_desk_path.exists() else None,
        },
        "detected_resets": [t.isoformat() for t in resets],
        "segments": [],
        "daily_state_raw": None,
        "paper_desk_portfolio_raw": None,
        "fills_total_day": len(fills_day),
        "minute_rows_day": len(mins),
    }

    if daily_state_path and daily_state_path.exists():
        try:
            out["daily_state_raw"] = json.loads(daily_state_path.read_text(encoding="utf-8"))
        except Exception:
            out["daily_state_raw"] = None
    if paper_desk_path.exists():
        try:
            raw = json.loads(paper_desk_path.read_text(encoding="utf-8"))
            out["paper_desk_portfolio_raw"] = (raw or {}).get("portfolio")
        except Exception:
            out["paper_desk_portfolio_raw"] = None

    # Segment summaries
    for a, b, name in segs:
        seg_fills = _fills_in_range(fills_day, a, b)
        agg = FillAgg()
        for r in seg_fills:
            agg.add(r)
        seg = {
            "name": name,
            "start": a.isoformat(),
            "end": b.isoformat(),
            "fills": agg.to_dict(),
            "minute": _minute_state_summary(mins, a, b),
        }
        out["segments"].append(seg)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

