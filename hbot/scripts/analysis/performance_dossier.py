#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight environments.
    psycopg = None  # type: ignore[assignment]


def _parse_ts(value: str) -> Optional[datetime]:
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _safe_float(v: object, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def _iter_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _infer_bot_variant(bot_log_root: Path) -> Tuple[Optional[str], Optional[str]]:
    # Expected layout: data/<bot>/logs/epp_v24/<variant_folder>
    try:
        return str(bot_log_root.parts[-5]).lower(), str(bot_log_root.parts[-1]).lower()
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


def _fetch_rows_from_db(bot_log_root: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    bot, variant = _infer_bot_variant(bot_log_root)
    if not bot or not variant:
        raise RuntimeError("cannot_infer_bot_variant_from_path")

    conn = _connect_ops_db()
    try:
        fills_rows: List[Dict[str, str]] = []
        minute_rows: List[Dict[str, str]] = []
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts_utc, side, price, mid_ref, notional_quote, fee_quote, realized_pnl_quote, is_maker
                FROM fills
                WHERE bot = %s AND variant = %s
                ORDER BY ts_utc
                """,
                (bot, variant),
            )
            fill_cols = [str(desc[0]) for desc in (cur.description or [])]
            for rec in cur.fetchall() or []:
                row = dict(zip(fill_cols, rec))
                ts_utc = row.get("ts_utc")
                fills_rows.append(
                    {
                        "ts": ts_utc.astimezone(timezone.utc).isoformat() if hasattr(ts_utc, "astimezone") else str(ts_utc or ""),
                        "side": str(row.get("side") or ""),
                        "price": str(row.get("price") or ""),
                        "mid_ref": str(row.get("mid_ref") or ""),
                        "notional_quote": str(row.get("notional_quote") or ""),
                        "fee_quote": str(row.get("fee_quote") or ""),
                        "realized_pnl_quote": str(row.get("realized_pnl_quote") or ""),
                        "is_maker": str(row.get("is_maker") or ""),
                    }
                )

            cur.execute(
                """
                SELECT ts_utc, state, drawdown_pct, soft_pause_edge, order_book_stale
                FROM bot_snapshot_minute
                WHERE bot = %s AND variant = %s
                ORDER BY ts_utc
                """,
                (bot, variant),
            )
            minute_cols = [str(desc[0]) for desc in (cur.description or [])]
            for rec in cur.fetchall() or []:
                row = dict(zip(minute_cols, rec))
                ts_utc = row.get("ts_utc")
                minute_rows.append(
                    {
                        "ts": ts_utc.astimezone(timezone.utc).isoformat() if hasattr(ts_utc, "astimezone") else str(ts_utc or ""),
                        "state": str(row.get("state") or ""),
                        "drawdown_pct": str(row.get("drawdown_pct") or ""),
                        "soft_pause_edge": str(row.get("soft_pause_edge") or ""),
                        "order_book_stale": str(row.get("order_book_stale") or ""),
                    }
                )
        return fills_rows, minute_rows
    finally:
        conn.close()


def _load_rows_with_fallback(bot_log_root: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], str, Optional[str]]:
    if _env_bool("OPS_DB_READ_PREFERRED", False):
        try:
            fills, minute = _fetch_rows_from_db(bot_log_root)
            return fills, minute, "db", None
        except Exception as exc:
            fills = _iter_csv(bot_log_root / "fills.csv")
            minute = _iter_csv(bot_log_root / "minute.csv")
            return fills, minute, "csv", f"db_unavailable:{exc}"

    fills = _iter_csv(bot_log_root / "fills.csv")
    minute = _iter_csv(bot_log_root / "minute.csv")
    return fills, minute, "csv", None


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _slippage_bps(side: str, px: float, mid: float) -> float:
    if mid <= 0:
        return 0.0
    side_l = (side or "").lower()
    if side_l == "buy":
        return ((px - mid) / mid) * 10000.0
    if side_l == "sell":
        return ((mid - px) / mid) * 10000.0
    return 0.0


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(max(0, min(len(sorted_vals) - 1, (len(sorted_vals) - 1) * p)))
    return sorted_vals[idx]


def _mean_ci95(values: List[float]) -> Tuple[int, float, float, float]:
    n = len(values)
    if n <= 0:
        return 0, 0.0, 0.0, 0.0
    mean = sum(values) / float(n)
    if n == 1:
        return 1, mean, mean, mean
    variance = sum((v - mean) ** 2 for v in values) / float(n - 1)
    std = math.sqrt(max(0.0, variance))
    half_width = 1.96 * std / math.sqrt(float(n))
    return n, mean, mean - half_width, mean + half_width


def _rolling_values(values: List[float], window: int) -> List[float]:
    if window <= 0:
        return list(values)
    if len(values) <= window:
        return list(values)
    return values[-window:]


def _cancel_before_fill_rate(rows: List[Dict[str, str]]) -> Tuple[int, float]:
    count = sum(
        1
        for r in rows
        if _safe_float(r.get("cancel_per_min")) > 0.0 and _safe_float(r.get("fills_count_today")) == 0.0
    )
    rate = (count / len(rows)) if rows else 0.0
    return count, rate


def _expectancy_buckets(values_by_key: Dict[str, List[float]]) -> Dict[str, Dict[str, float]]:
    buckets: Dict[str, Dict[str, float]] = {}
    for raw_key, values in values_by_key.items():
        key = str(raw_key or "unknown").strip() or "unknown"
        n, mean, ci_low, ci_high = _mean_ci95(values)
        buckets[key] = {
            "fills": float(n),
            "expectancy_per_fill_quote": mean,
            "ci95_low_quote": ci_low,
            "ci95_high_quote": ci_high,
        }
    return buckets


def build_dossier(root: Path, bot_log_root: Path, lookback_days: int = 5) -> Dict[str, object]:
    fills, minute, data_source_mode, data_source_fallback_reason = _load_rows_with_fallback(bot_log_root)
    rolling_window_fills = max(1, int(os.getenv("PERF_DOSSIER_EXPECTANCY_ROLLING_WINDOW_FILLS", "300")))
    expectancy_gate_min_fills = max(
        1,
        int(os.getenv("PERF_DOSSIER_EXPECTANCY_GATE_MIN_FILLS", str(rolling_window_fills))),
    )

    # Per-day rollups from fills (execution truth source).
    by_day: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    slippage_by_day: Dict[str, List[float]] = defaultdict(list)
    maker_count_by_day: Dict[str, int] = defaultdict(int)
    fills_count_by_day: Dict[str, int] = defaultdict(int)
    net_per_fill_values: List[float] = []
    maker_net_per_fill_values: List[float] = []
    taker_net_per_fill_values: List[float] = []
    alpha_policy_net_per_fill: Dict[str, List[float]] = defaultdict(list)
    regime_net_per_fill: Dict[str, List[float]] = defaultdict(list)

    for r in fills:
        ts = _parse_ts(r.get("ts", ""))
        if ts is None:
            continue
        day = ts.date().isoformat()
        notional_quote = _safe_float(r.get("notional_quote"))
        fee_quote = _safe_float(r.get("fee_quote"))
        realized_pnl_quote = _safe_float(r.get("realized_pnl_quote"))
        by_day[day]["notional"] += notional_quote
        by_day[day]["fees"] += fee_quote
        by_day[day]["realized"] += realized_pnl_quote
        fills_count_by_day[day] += 1
        is_maker = str(r.get("is_maker", "")).lower() == "true"
        if is_maker:
            maker_count_by_day[day] += 1
        net_per_fill = realized_pnl_quote - fee_quote
        net_per_fill_values.append(net_per_fill)
        alpha_policy_net_per_fill[str(r.get("alpha_policy_state", "unknown") or "unknown")].append(net_per_fill)
        regime_net_per_fill[str(r.get("regime", "unknown") or "unknown")].append(net_per_fill)
        if is_maker:
            maker_net_per_fill_values.append(net_per_fill)
        else:
            taker_net_per_fill_values.append(net_per_fill)
        slip = _slippage_bps(
            side=str(r.get("side", "")),
            px=_safe_float(r.get("price")),
            mid=_safe_float(r.get("mid_ref")),
        )
        slippage_by_day[day].append(slip)

    days = sorted(by_day.keys())[-lookback_days:]
    day_rows: List[Dict[str, object]] = []
    for day in days:
        notional = by_day[day]["notional"]
        fees = by_day[day]["fees"]
        realized = by_day[day]["realized"]
        net = realized - fees
        maker_ratio = (maker_count_by_day[day] / fills_count_by_day[day]) if fills_count_by_day[day] > 0 else 0.0
        slips = sorted(slippage_by_day[day])
        day_rows.append(
            {
                "day": day,
                "fills": int(fills_count_by_day[day]),
                "realized_pnl_quote": realized,
                "fees_quote": fees,
                "net_pnl_quote": net,
                "fee_bps": ((fees / notional) * 10000.0) if notional > 0 else 0.0,
                "maker_ratio": maker_ratio,
                "slippage_median_bps": _percentile(slips, 0.50),
                "slippage_p95_bps": _percentile(slips, 0.95),
            }
        )

    # Minute-level runtime health (latest file content only).
    # Keep both edge-gate pause and controller state pause metrics explicit:
    # they capture different failure modes and can diverge materially.
    soft_pause_edge_rows = sum(1 for r in minute if str(r.get("soft_pause_edge", "")).lower() == "true")
    soft_pause_state_rows = sum(1 for r in minute if str(r.get("state", "")).strip().lower() == "soft_pause")
    selective_quote_block_rows = sum(
        1 for r in minute if str(r.get("selective_quote_state", "")).strip().lower() == "blocked"
    )
    selective_quote_reduce_rows = sum(
        1 for r in minute if str(r.get("selective_quote_state", "")).strip().lower() == "reduced"
    )
    alpha_no_trade_rows = sum(
        1 for r in minute if str(r.get("alpha_policy_state", "")).strip().lower() == "no_trade"
    )
    alpha_aggressive_rows = sum(
        1 for r in minute if str(r.get("alpha_policy_state", "")).strip().lower().startswith("aggressive_")
    )
    stale_rows = sum(1 for r in minute if str(r.get("order_book_stale", "")).lower() == "true")
    cancel_before_fill_rows, cancel_before_fill_rate = _cancel_before_fill_rate(minute)
    max_drawdown = max((_safe_float(r.get("drawdown_pct")) for r in minute), default=0.0)

    # External service health snapshots.
    recon = _read_json(root / "reports" / "reconciliation" / "latest.json")
    portfolio = _read_json(root / "reports" / "portfolio_risk" / "latest.json")
    strict_cycle = _read_json(root / "reports" / "promotion_gates" / "strict_cycle_latest.json")

    # Simple gate checks for operator quick-read.
    total_net = sum(_safe_float(d["net_pnl_quote"]) for d in day_rows)
    mean_fee_bps = (sum(_safe_float(d["fee_bps"]) for d in day_rows) / len(day_rows)) if day_rows else 0.0
    mean_maker_ratio = (sum(_safe_float(d["maker_ratio"]) for d in day_rows) / len(day_rows)) if day_rows else 0.0
    total_fills = sum(fills_count_by_day.get(day, 0) for day in days)
    total_maker_fills = sum(maker_count_by_day.get(day, 0) for day in days)
    maker_ratio_weighted = (total_maker_fills / total_fills) if total_fills > 0 else 0.0
    max_slippage_p95 = max((_safe_float(d["slippage_p95_bps"]) for d in day_rows), default=0.0)
    soft_pause_edge_ratio = (soft_pause_edge_rows / len(minute)) if minute else 0.0
    soft_pause_state_ratio = (soft_pause_state_rows / len(minute)) if minute else 0.0
    selective_quote_block_ratio = (selective_quote_block_rows / len(minute)) if minute else 0.0
    selective_quote_reduce_ratio = (selective_quote_reduce_rows / len(minute)) if minute else 0.0
    alpha_no_trade_ratio = (alpha_no_trade_rows / len(minute)) if minute else 0.0
    alpha_aggressive_ratio = (alpha_aggressive_rows / len(minute)) if minute else 0.0
    # Backward-compatible alias now reflects the state-based quoting pause signal.
    soft_pause_ratio = soft_pause_state_ratio
    expectancy_n, expectancy_mean, expectancy_ci95_low, expectancy_ci95_high = _mean_ci95(net_per_fill_values)
    rolling_expectancy_values = _rolling_values(net_per_fill_values, rolling_window_fills)
    (
        rolling_expectancy_n,
        rolling_expectancy_mean,
        rolling_expectancy_ci95_low,
        rolling_expectancy_ci95_high,
    ) = _mean_ci95(rolling_expectancy_values)
    maker_expectancy_n, maker_expectancy_mean, maker_expectancy_ci95_low, maker_expectancy_ci95_high = _mean_ci95(
        maker_net_per_fill_values
    )
    taker_expectancy_n, taker_expectancy_mean, taker_expectancy_ci95_low, taker_expectancy_ci95_high = _mean_ci95(
        taker_net_per_fill_values
    )
    maker_rolling_values = _rolling_values(maker_net_per_fill_values, rolling_window_fills)
    taker_rolling_values = _rolling_values(taker_net_per_fill_values, rolling_window_fills)
    (
        maker_rolling_n,
        maker_rolling_mean,
        maker_rolling_ci95_low,
        maker_rolling_ci95_high,
    ) = _mean_ci95(maker_rolling_values)
    (
        taker_rolling_n,
        taker_rolling_mean,
        taker_rolling_ci95_low,
        taker_rolling_ci95_high,
    ) = _mean_ci95(taker_rolling_values)
    alpha_policy_expectancy = _expectancy_buckets(alpha_policy_net_per_fill)
    regime_expectancy = _expectancy_buckets(regime_net_per_fill)
    rolling_expectancy_gate_ready = rolling_expectancy_n >= expectancy_gate_min_fills
    rolling_expectancy_gate_fail = (
        rolling_expectancy_gate_ready and rolling_expectancy_ci95_high < 0.0
    )
    rolling_expectancy_gate_pass = rolling_expectancy_gate_ready and not rolling_expectancy_gate_fail

    checks = [
        {
            "name": "net_pnl_non_negative",
            "pass": total_net >= 0.0,
            "value": total_net,
            "threshold": 0.0,
        },
        {
            "name": "mean_fee_bps_within_0_to_12",
            "pass": 0.0 <= mean_fee_bps <= 12.0,
            "value": mean_fee_bps,
            "threshold": [0.0, 12.0],
        },
        {
            "name": "maker_ratio_at_least_45pct",
            "pass": maker_ratio_weighted >= 0.45,
            "value": maker_ratio_weighted,
            "threshold": 0.45,
            "note": "weighted_by_fills",
        },
        {
            "name": "slippage_p95_below_25bps",
            "pass": max_slippage_p95 < 25.0,
            "value": max_slippage_p95,
            "threshold": 25.0,
        },
        {
            "name": "drawdown_below_2pct",
            "pass": max_drawdown < 0.02,
            "value": max_drawdown,
            "threshold": 0.02,
        },
        {
            "name": "soft_pause_state_ratio_below_30pct",
            "pass": soft_pause_ratio < 0.30,
            "value": soft_pause_ratio,
            "threshold": 0.30,
        },
        {
            "name": "reconciliation_not_critical",
            "pass": _safe_float(recon.get("critical_count"), 0.0) == 0.0,
            "value": _safe_float(recon.get("critical_count"), 0.0),
            "threshold": 0.0,
        },
        {
            "name": "portfolio_risk_not_critical",
            "pass": _safe_float(portfolio.get("critical_count"), 0.0) == 0.0,
            "value": _safe_float(portfolio.get("critical_count"), 0.0),
            "threshold": 0.0,
        },
        {
            "name": "rolling_expectancy_ci95_upper_non_negative",
            "pass": rolling_expectancy_gate_pass,
            "value": rolling_expectancy_ci95_high,
            "threshold": 0.0,
            "note": (
                f"window_fills={rolling_window_fills}; sample={rolling_expectancy_n}; "
                f"gate_min_fills={expectancy_gate_min_fills}; "
                f"gate_ready={rolling_expectancy_gate_ready}"
            ),
        },
    ]
    status = "pass" if all(bool(c["pass"]) for c in checks) else "warning"

    payload: Dict[str, object] = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "bot_log_root": str(bot_log_root),
        "lookback_days": lookback_days,
        "data_source_mode": data_source_mode,
        "summary": {
            "days_included": len(day_rows),
            "total_net_pnl_quote": total_net,
            "mean_fee_bps": mean_fee_bps,
            "mean_maker_ratio": mean_maker_ratio,
            "maker_ratio_mean_daily": mean_maker_ratio,
            "maker_ratio_weighted": maker_ratio_weighted,
            "max_slippage_p95_bps": max_slippage_p95,
            "max_drawdown_pct": max_drawdown,
            "soft_pause_ratio": soft_pause_ratio,
            "soft_pause_state_ratio": soft_pause_state_ratio,
            "soft_pause_edge_ratio": soft_pause_edge_ratio,
            "soft_pause_state_rows": soft_pause_state_rows,
            "soft_pause_edge_rows": soft_pause_edge_rows,
            "selective_quote_block_rows": selective_quote_block_rows,
            "selective_quote_block_ratio": selective_quote_block_ratio,
            "selective_quote_reduce_rows": selective_quote_reduce_rows,
            "selective_quote_reduce_ratio": selective_quote_reduce_ratio,
            "alpha_no_trade_rows": alpha_no_trade_rows,
            "alpha_no_trade_ratio": alpha_no_trade_ratio,
            "alpha_aggressive_rows": alpha_aggressive_rows,
            "alpha_aggressive_ratio": alpha_aggressive_ratio,
            "order_book_stale_rows": stale_rows,
            "cancel_before_fill_rows": cancel_before_fill_rows,
            "cancel_before_fill_rate": cancel_before_fill_rate,
            "expectancy_sample_count": expectancy_n,
            "expectancy_per_fill_quote": expectancy_mean,
            "expectancy_ci95_low_quote": expectancy_ci95_low,
            "expectancy_ci95_high_quote": expectancy_ci95_high,
            "rolling_expectancy_window_fills": rolling_window_fills,
            "rolling_expectancy_sample_count": rolling_expectancy_n,
            "rolling_expectancy_per_fill_quote": rolling_expectancy_mean,
            "rolling_expectancy_ci95_low_quote": rolling_expectancy_ci95_low,
            "rolling_expectancy_ci95_high_quote": rolling_expectancy_ci95_high,
            "rolling_expectancy_gate_min_fills": expectancy_gate_min_fills,
            "rolling_expectancy_gate_ready": rolling_expectancy_gate_ready,
            "rolling_expectancy_gate_fail": rolling_expectancy_gate_fail,
            "maker_expectancy_sample_count": maker_expectancy_n,
            "maker_expectancy_per_fill_quote": maker_expectancy_mean,
            "maker_expectancy_ci95_low_quote": maker_expectancy_ci95_low,
            "maker_expectancy_ci95_high_quote": maker_expectancy_ci95_high,
            "maker_rolling_expectancy_sample_count": maker_rolling_n,
            "maker_rolling_expectancy_per_fill_quote": maker_rolling_mean,
            "maker_rolling_expectancy_ci95_low_quote": maker_rolling_ci95_low,
            "maker_rolling_expectancy_ci95_high_quote": maker_rolling_ci95_high,
            "taker_expectancy_sample_count": taker_expectancy_n,
            "taker_expectancy_per_fill_quote": taker_expectancy_mean,
            "taker_expectancy_ci95_low_quote": taker_expectancy_ci95_low,
            "taker_expectancy_ci95_high_quote": taker_expectancy_ci95_high,
            "taker_rolling_expectancy_sample_count": taker_rolling_n,
            "taker_rolling_expectancy_per_fill_quote": taker_rolling_mean,
            "taker_rolling_expectancy_ci95_low_quote": taker_rolling_ci95_low,
            "taker_rolling_expectancy_ci95_high_quote": taker_rolling_ci95_high,
            "alpha_policy_expectancy": alpha_policy_expectancy,
            "regime_expectancy": regime_expectancy,
        },
        "checks": checks,
        "daily_breakdown": day_rows,
        "external": {
            "reconciliation": {
                "status": recon.get("status"),
                "critical_count": recon.get("critical_count"),
                "warning_count": recon.get("warning_count"),
            },
            "portfolio_risk": {
                "status": portfolio.get("status"),
                "critical_count": portfolio.get("critical_count"),
                "warning_count": portfolio.get("warning_count"),
            },
            "strict_cycle": {
                "status": strict_cycle.get("strict_gate_status"),
                "rc": strict_cycle.get("strict_gate_rc"),
            },
        },
    }
    if data_source_fallback_reason:
        payload["data_source_fallback_reason"] = data_source_fallback_reason
    return payload


def _to_markdown(dossier: Dict[str, object]) -> str:
    summary = dossier.get("summary", {})
    checks = dossier.get("checks", [])
    rows = dossier.get("daily_breakdown", [])
    md = [
        "# Performance Dossier",
        "",
        f"- Generated: `{dossier.get('ts_utc', '')}`",
        f"- Status: **{dossier.get('status', 'unknown').upper()}**",
        f"- Data source: `{dossier.get('data_source_mode', 'csv')}`",
        f"- Days included: `{summary.get('days_included', 0)}`",
        f"- Total net PnL: `{summary.get('total_net_pnl_quote', 0):.4f}`",
        f"- Mean fee bps: `{summary.get('mean_fee_bps', 0):.2f}`",
        f"- Maker ratio (weighted): `{summary.get('maker_ratio_weighted', summary.get('mean_maker_ratio', 0)):.2%}`",
        f"- Maker ratio (mean daily): `{summary.get('maker_ratio_mean_daily', summary.get('mean_maker_ratio', 0)):.2%}`",
        f"- Max p95 slippage: `{summary.get('max_slippage_p95_bps', 0):.2f}` bps",
        f"- Max drawdown: `{summary.get('max_drawdown_pct', 0):.2%}`",
        f"- Soft-pause (state): `{summary.get('soft_pause_state_ratio', summary.get('soft_pause_ratio', 0)):.2%}`",
        f"- Soft-pause (edge): `{summary.get('soft_pause_edge_ratio', 0):.2%}`",
        f"- Selective quote block: `{summary.get('selective_quote_block_ratio', 0):.2%}`",
        f"- Selective quote reduced: `{summary.get('selective_quote_reduce_ratio', 0):.2%}`",
        f"- Alpha no-trade: `{summary.get('alpha_no_trade_ratio', 0):.2%}`",
        f"- Alpha aggressive: `{summary.get('alpha_aggressive_ratio', 0):.2%}`",
        f"- Cancel-before-fill: `{summary.get('cancel_before_fill_rate', 0):.2%}`",
        (
            f"- Rolling expectancy/fill ({int(summary.get('rolling_expectancy_sample_count', 0))} rows): "
            f"`{summary.get('rolling_expectancy_per_fill_quote', 0):.6f}` "
            f"(95% CI: `{summary.get('rolling_expectancy_ci95_low_quote', 0):.6f}` .. "
            f"`{summary.get('rolling_expectancy_ci95_high_quote', 0):.6f}`)"
        ),
        (
            f"- Rolling maker expectancy/fill: "
            f"`{summary.get('maker_rolling_expectancy_per_fill_quote', 0):.6f}` "
            f"(95% CI: `{summary.get('maker_rolling_expectancy_ci95_low_quote', 0):.6f}` .. "
            f"`{summary.get('maker_rolling_expectancy_ci95_high_quote', 0):.6f}`)"
        ),
        (
            f"- Rolling taker expectancy/fill: "
            f"`{summary.get('taker_rolling_expectancy_per_fill_quote', 0):.6f}` "
            f"(95% CI: `{summary.get('taker_rolling_expectancy_ci95_low_quote', 0):.6f}` .. "
            f"`{summary.get('taker_rolling_expectancy_ci95_high_quote', 0):.6f}`)"
        ),
        "",
        "## Expectancy Buckets",
        f"- Alpha policy: `{json.dumps(summary.get('alpha_policy_expectancy', {}), sort_keys=True)}`",
        f"- Regime: `{json.dumps(summary.get('regime_expectancy', {}), sort_keys=True)}`",
        "",
        "## Checks",
    ]
    for c in checks:
        status = "PASS" if c.get("pass") else "FAIL"
        md.append(f"- [{status}] `{c.get('name')}` value=`{c.get('value')}` threshold=`{c.get('threshold')}`")
    md.append("")
    md.append("## Daily Breakdown")
    md.append("| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(
            f"| {r.get('day')} | {r.get('fills')} | {float(r.get('net_pnl_quote', 0)):.4f} | "
            f"{float(r.get('fee_bps', 0)):.2f} | {float(r.get('maker_ratio', 0)):.2%} | "
            f"{float(r.get('slippage_p95_bps', 0)):.2f} |"
        )
    return "\n".join(md) + "\n"


def _resolve_output_paths(repo_root: Path, output_dir: str, output_stem: str) -> Tuple[Path, Path]:
    safe_stem = str(output_stem or "performance_dossier_latest").strip() or "performance_dossier_latest"
    out_dir = Path(output_dir) if str(output_dir).strip() else (repo_root / "reports" / "analysis")
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    return out_dir / f"{safe_stem}.json", out_dir / f"{safe_stem}.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate performance dossier for bot logs.")
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser.add_argument("--root", default=str(root))
    parser.add_argument("--bot-log-root", default=str(root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"))
    parser.add_argument("--lookback-days", type=int, default=5)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--output-dir", default="reports/analysis")
    parser.add_argument("--output-stem", default="performance_dossier_latest")
    args = parser.parse_args()

    repo_root = Path(args.root)
    bot_root = Path(args.bot_log_root)
    dossier = build_dossier(repo_root, bot_root, lookback_days=max(1, args.lookback_days))
    print(json.dumps(dossier, indent=2))

    if args.save:
        json_path, md_path = _resolve_output_paths(repo_root, args.output_dir, args.output_stem)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        md_path.write_text(_to_markdown(dossier), encoding="utf-8")
        print(f"[performance-dossier] saved_json={json_path}")
        print(f"[performance-dossier] saved_md={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
