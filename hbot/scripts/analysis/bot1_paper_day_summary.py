from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency.
    psycopg = None  # type: ignore[assignment]


_ZERO = Decimal("0")


def _parse_ts(s: str) -> dt.datetime:
    # Handles ISO like "2026-02-25T21:19:00.105090+00:00" and "...Z"
    s = (s or "").strip()
    if not s:
        raise ValueError("empty ts")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)


def _day_window_utc(day: str) -> Tuple[dt.datetime, dt.datetime]:
    d = dt.date.fromisoformat(day)
    start = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    return start, end


def _d(x: object) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return _ZERO


def _safe_bool(x: object) -> bool:
    return str(x).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _infer_bot_variant(root: Path) -> Tuple[Optional[str], Optional[str]]:
    # Expected: data/<bot>/logs/epp_v24/<variant_folder>
    try:
        return str(root.parts[-5]).lower(), str(root.parts[-1]).lower()
    except Exception:
        return None, None


def _connect_ops_db():
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(
        host=os.getenv("OPS_DB_HOST", "postgres"),
        port=int(os.getenv("OPS_DB_PORT", "5432")),
        dbname=os.getenv("OPS_DB_NAME", "kzay_capital_ops"),
        user=os.getenv("OPS_DB_USER", "hbot"),
        password=os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password"),
    )


def _row_to_str_dict(row: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in row.items():
        if hasattr(v, "astimezone"):
            out[k] = v.astimezone(dt.timezone.utc).isoformat()
        elif isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif v is None:
            out[k] = ""
        else:
            out[k] = str(v)
    return out


def _load_day_rows_from_db(root: Path, day: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    bot, variant = _infer_bot_variant(root)
    if not bot or not variant:
        raise RuntimeError("cannot_infer_bot_variant_from_root")
    start, end = _day_window_utc(day)
    conn = _connect_ops_db()
    try:
        fills_day: List[Dict[str, str]] = []
        minute_day: List[Dict[str, str]] = []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts_utc, exchange, trading_pair, side, price, amount_base, notional_quote,
                       fee_quote, order_id, state, mid_ref, expected_spread_pct, adverse_drift_30s,
                       fee_source, is_maker, realized_pnl_quote
                FROM fills
                WHERE bot = %s AND variant = %s AND ts_utc >= %s AND ts_utc < %s
                ORDER BY ts_utc
                """,
                (bot, variant, start, end),
            )
            fill_cols = [str(desc[0]) for desc in (cur.description or [])]
            for rec in cur.fetchall() or []:
                row = _row_to_str_dict(dict(zip(fill_cols, rec)))
                row["ts"] = row.pop("ts_utc", "")
                fills_day.append(row)

            cur.execute(
                """
                SELECT ts_utc, exchange, trading_pair, state, regime, equity_quote, base_pct, target_base_pct,
                       daily_loss_pct, drawdown_pct, cancel_per_min, orders_active, fills_count_today,
                       fees_paid_today_quote, risk_reasons, bot_mode, accounting_source, mid, spread_pct,
                       net_edge_pct, turnover_today_x, raw_payload
                FROM bot_snapshot_minute
                WHERE bot = %s AND variant = %s AND ts_utc >= %s AND ts_utc < %s
                ORDER BY ts_utc
                """,
                (bot, variant, start, end),
            )
            minute_cols = [str(desc[0]) for desc in (cur.description or [])]
            for rec in cur.fetchall() or []:
                raw_row = dict(zip(minute_cols, rec))
                payload = raw_row.get("raw_payload")
                row = _row_to_str_dict(raw_row)
                row["ts"] = row.pop("ts_utc", "")
                row.pop("raw_payload", None)
                if isinstance(payload, dict):
                    # Preserve compatibility with minute.csv-only fields.
                    for k, v in payload.items():
                        if k not in row or not str(row.get(k, "")).strip():
                            row[str(k)] = "" if v is None else str(v)
                minute_day.append(row)
        return fills_day, minute_day
    finally:
        conn.close()


@dataclass
class FillsAgg:
    fills: int = 0
    buys: int = 0
    sells: int = 0
    maker: int = 0
    notional: Decimal = _ZERO
    fees: Decimal = _ZERO
    realized_pnl_sum: Decimal = _ZERO  # as logged by controller per-fill realized attribution
    edge_sum: Decimal = _ZERO          # signed edge vs mid_ref
    edge_abs_sum: Decimal = _ZERO
    edge_pos: int = 0
    first_ts: Optional[dt.datetime] = None
    last_ts: Optional[dt.datetime] = None

    def add_row(self, r: Dict[str, str]) -> None:
        t = _parse_ts(r["ts"])
        if self.first_ts is None or t < self.first_ts:
            self.first_ts = t
        if self.last_ts is None or t > self.last_ts:
            self.last_ts = t

        self.fills += 1
        side = (r.get("side") or "").lower().strip()
        if side == "buy":
            self.buys += 1
        else:
            self.sells += 1

        is_maker = str(r.get("is_maker", "")).lower().strip() in {"true", "1", "yes"}
        if is_maker:
            self.maker += 1

        n = _d(r.get("notional_quote", "0"))
        f = _d(r.get("fee_quote", "0"))
        self.notional += n
        self.fees += f

        self.realized_pnl_sum += _d(r.get("realized_pnl_quote", "0"))

        mid = _d(r.get("mid_ref", "0"))
        px = _d(r.get("price", "0"))
        if mid > _ZERO and px > _ZERO:
            edge = (mid - px) / mid if side == "buy" else (px - mid) / mid
            self.edge_sum += edge
            self.edge_abs_sum += abs(edge)
            if edge > _ZERO:
                self.edge_pos += 1

    def to_dict(self) -> Dict[str, object]:
        taker = self.fills - self.maker
        fee_rate = (self.fees / self.notional) if self.notional > _ZERO else _ZERO
        avg_edge = (self.edge_sum / self.fills) if self.fills else _ZERO
        avg_abs_edge = (self.edge_abs_sum / self.fills) if self.fills else _ZERO
        dur_s = (
            (self.last_ts - self.first_ts).total_seconds()
            if self.first_ts is not None and self.last_ts is not None
            else 0.0
        )
        fills_per_min = (self.fills / (dur_s / 60.0)) if dur_s > 0 else None
        return {
            "fills": self.fills,
            "buys": self.buys,
            "sells": self.sells,
            "maker": self.maker,
            "taker": taker,
            "maker_pct": float(self.maker / self.fills) if self.fills else 0.0,
            "notional_quote": str(self.notional),
            "fees_quote": str(self.fees),
            "fee_rate": str(fee_rate),
            "realized_pnl_sum_quote": str(self.realized_pnl_sum),
            "avg_edge_vs_mid_pct": str(avg_edge),
            "avg_abs_edge_vs_mid_pct": str(avg_abs_edge),
            "pos_edge_frac": float(self.edge_pos / self.fills) if self.fills else 0.0,
            "first_ts": self.first_ts.isoformat() if self.first_ts else None,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
            "duration_s": dur_s,
            "fills_per_min": fills_per_min,
        }


def _iter_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            yield row


def _collect_minute_rows_for_day(root: Path, day: str) -> List[Dict[str, str]]:
    """Load minute rows for a day from active + rotated files with dedupe/order."""
    minute_files = sorted(root.glob("minute.legacy_*.csv"))
    minute_main = root / "minute.csv"
    if minute_main.exists():
        minute_files.append(minute_main)

    rows: List[Dict[str, str]] = []
    for path in minute_files:
        rows.extend(_filter_day(_iter_csv_rows(path), day))

    # Deduplicate on timestamp while preferring later files (newer writes),
    # then return deterministic ts ordering.
    by_ts: Dict[str, Dict[str, str]] = {}
    for row in rows:
        ts = str(row.get("ts", "")).strip()
        if not ts:
            continue
        by_ts[ts] = row
    return [by_ts[k] for k in sorted(by_ts.keys(), key=lambda t: _parse_ts(t))]


def _filter_day(rows: Iterable[Dict[str, str]], day: str) -> List[Dict[str, str]]:
    start, end = _day_window_utc(day)
    out: List[Dict[str, str]] = []
    for row in rows:
        try:
            t = _parse_ts(row["ts"])
        except Exception:
            continue
        if start <= t < end:
            out.append(row)
    return out


def _read_json(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="UTC day, e.g. 2026-02-25")
    ap.add_argument("--root", default="hbot/data/bot1/logs/epp_v24/bot1_a", help="log root")
    ap.add_argument("--exchange", default=None, help="Filter fills by exchange/connector_name (fills.csv 'exchange' column)")
    ap.add_argument("--pair", default=None, help="Filter fills by trading_pair (fills.csv 'trading_pair' column)")
    ap.add_argument(
        "--since-ts",
        default=None,
        help="Optional ISO timestamp (UTC recommended). Filters fills/minute rows with ts >= since-ts.",
    )
    ap.add_argument(
        "--window",
        default="day",
        choices=["day", "minute_csv_range"],
        help="Which time window to aggregate fills over: full day or the min/max ts in minute.csv for that day",
    )
    args = ap.parse_args()

    root = Path(args.root)
    fills_path = root / "fills.csv"
    minute_path = root / "minute.csv"

    data_source_mode = "csv"
    data_source_fallback_reason: Optional[str] = None
    if _env_bool("OPS_DB_READ_PREFERRED", False):
        try:
            fills_day, minute_day = _load_day_rows_from_db(root, args.day)
            data_source_mode = "db"
        except Exception as exc:
            fills_day = _filter_day(_iter_csv_rows(fills_path), args.day) if fills_path.exists() else []
            minute_day = _collect_minute_rows_for_day(root, args.day)
            data_source_fallback_reason = f"db_unavailable:{exc}"
            data_source_mode = "csv"
    else:
        fills_day = _filter_day(_iter_csv_rows(fills_path), args.day) if fills_path.exists() else []
        minute_day = _collect_minute_rows_for_day(root, args.day)

    # Optional column filters (kept strict to avoid mixing runs)
    if args.exchange:
        fills_day = [r for r in fills_day if str(r.get("exchange", "")).strip() == str(args.exchange).strip()]
    if args.pair:
        fills_day = [r for r in fills_day if str(r.get("trading_pair", "")).strip() == str(args.pair).strip()]

    # Optional time filter (post-restart / post-variant analysis)
    if args.since_ts:
        t0 = _parse_ts(str(args.since_ts))
        fills_day = [r for r in fills_day if _parse_ts(r["ts"]) >= t0]
        minute_day = [r for r in minute_day if _parse_ts(r["ts"]) >= t0]

    # Optional time window narrowing
    if args.window == "minute_csv_range" and minute_day and fills_day:
        t0 = min(_parse_ts(r["ts"]) for r in minute_day if r.get("ts"))
        t1 = max(_parse_ts(r["ts"]) for r in minute_day if r.get("ts"))
        fills_day = [r for r in fills_day if t0 <= _parse_ts(r["ts"]) <= t1]

    agg = FillsAgg()
    for r in fills_day:
        agg.add_row(r)

    # Minute-derived quick stats
    minute_stats: Dict[str, object] = {
        "rows": len(minute_day),
    }
    if minute_day:
        # Use last row as end-of-day snapshot (controller writes monotonic day counters).
        last = minute_day[-1]
        for k in (
            "exchange",
            "trading_pair",
            "state",
            "regime",
            "mid",
            "equity_quote",
            "turnover_today_x",
            "fills_count_today",
            "fees_paid_today_quote",
            "realized_pnl_today_quote",
            "net_realized_pnl_today_quote",
            "funding_cost_today_quote",
            "position_base",
            "avg_entry_price",
            "drawdown_pct",
            "daily_loss_pct",
            "ws_reconnect_count",
            "order_book_stale",
            "risk_reasons",
            "maker_fee_pct",
            "taker_fee_pct",
            "fee_source",
            "cancel_per_min",
            "orders_active",
            "spread_competitiveness_cap_active",
            "spread_competitiveness_cap_side_pct",
        ):
            if k in last:
                minute_stats[k] = last[k]

        # Distribution of guard states
        states: Dict[str, int] = {}
        regimes: Dict[str, int] = {}
        for r in minute_day:
            states[r.get("state", "")] = states.get(r.get("state", ""), 0) + 1
            regimes[r.get("regime", "")] = regimes.get(r.get("regime", ""), 0) + 1
        minute_stats["state_counts"] = states
        minute_stats["regime_counts"] = regimes
        cap_active_rows = sum(1 for r in minute_day if _safe_bool(r.get("spread_competitiveness_cap_active", False)))
        cap_side_values = [abs(_d(r.get("spread_competitiveness_cap_side_pct", "0"))) for r in minute_day]
        cap_side_avg = (sum(cap_side_values, _ZERO) / Decimal(len(cap_side_values))) if cap_side_values else _ZERO
        minute_stats["spread_competitiveness_cap_active_rows"] = cap_active_rows
        minute_stats["spread_competitiveness_cap_observed_rows"] = len(minute_day)
        minute_stats["spread_competitiveness_cap_hit_ratio"] = (
            float(Decimal(cap_active_rows) / Decimal(len(minute_day))) if minute_day else 0.0
        )
        minute_stats["spread_competitiveness_cap_side_pct_avg"] = float(cap_side_avg)

    # Optional desk + daily_state snapshots for reconciliation hints
    daily_state_candidates = sorted(root.glob("daily_state_*.json"))
    daily_state = None
    for p in daily_state_candidates:
        obj = _read_json(p)
        if obj and obj.get("day_key") == args.day:
            daily_state = {"path": str(p), "data": obj}
            break

    desk_path = root / "paper_desk_v2.json"
    desk = _read_json(desk_path)

    out = {
        "day": args.day,
        "data_source_mode": data_source_mode,
        "paths": {
            "fills_csv": str(fills_path) if fills_path.exists() else None,
            "minute_csv": str(minute_path) if minute_path.exists() else None,
            "minute_legacy_csv": sorted(str(p) for p in root.glob("minute.legacy_*.csv")),
            "paper_desk_v2_json": str(desk_path) if desk_path.exists() else None,
        },
        "fills_agg": agg.to_dict(),
        "minute_snapshot": minute_stats,
        "daily_state": daily_state,
        "paper_desk_snapshot": desk,
    }
    if data_source_fallback_reason:
        out["data_source_fallback_reason"] = data_source_fallback_reason

    print(json.dumps(out, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

