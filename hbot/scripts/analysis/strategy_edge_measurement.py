"""Unified per-strategy edge measurement.

Auto-discovers all bot log directories and computes comparative edge metrics:
  expectancy per fill, win rate (fills), avg win/loss, Sharpe, max drawdown,
  maker ratio, and fill rate proxy.

Outputs a unified JSON report for all strategies.

Usage::

    python scripts/analysis/strategy_edge_measurement.py
    python scripts/analysis/strategy_edge_measurement.py --bot bot1 --bot bot6
    python scripts/analysis/strategy_edge_measurement.py --save
    python scripts/analysis/strategy_edge_measurement.py --lookback-days 7
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from controllers.analytics.performance_metrics import max_drawdown


def _repo_root() -> Path:
    if Path("/.dockerenv").exists():
        return Path("/workspace/hbot")
    return Path(__file__).resolve().parents[2]


def _safe_float(v: object, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def _parse_ts(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _discover_bot_log_dirs(root: Path, filter_bots: list[str] | None = None) -> dict[str, Path]:
    data_dir = root / "data"
    if not data_dir.exists():
        return {}
    result: dict[str, Path] = {}
    for bot_dir in sorted(data_dir.iterdir()):
        if not bot_dir.is_dir():
            continue
        bot_name = bot_dir.name
        if filter_bots and bot_name not in filter_bots:
            continue
        log_root = bot_dir / "logs" / "epp_v24"
        if not log_root.exists():
            continue
        for variant_dir in sorted(log_root.iterdir()):
            if variant_dir.is_dir() and (variant_dir / "fills.csv").exists():
                result[bot_name] = variant_dir
                break
    return result


def _mean_ci95(values: list[float]) -> tuple[int, float, float, float]:
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


def _compute_strategy_edge(
    bot_name: str,
    log_dir: Path,
    lookback_days: int = 0,
) -> dict[str, object]:
    fills = _read_csv(log_dir / "fills.csv")
    minute = _read_csv(log_dir / "minute.csv")

    if lookback_days > 0:
        cutoff = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=lookback_days)
        fills = [f for f in fills if (_parse_ts(f.get("ts", "")) or cutoff) >= cutoff]
        minute = [m for m in minute if (_parse_ts(m.get("ts", "")) or cutoff) >= cutoff]

    if not fills:
        return {
            "bot": bot_name,
            "status": "no_fills",
            "fill_count": 0,
            "verdict": "INSUFFICIENT_DATA",
        }

    net_per_fill: list[float] = []
    maker_fills = 0
    taker_fills = 0
    win_fills = 0
    loss_fills = 0
    total_win_quote = 0.0
    total_loss_quote = 0.0
    total_fees = 0.0
    total_notional = 0.0
    daily_pnl: dict[str, float] = defaultdict(float)
    daily_equity: dict[str, float] = {}

    for r in fills:
        fee = _safe_float(r.get("fee_quote"))
        rpnl = _safe_float(r.get("realized_pnl_quote"))
        net = rpnl - fee
        net_per_fill.append(net)
        total_fees += fee
        total_notional += _safe_float(r.get("notional_quote"))

        is_maker = str(r.get("is_maker", "")).lower() == "true"
        if is_maker:
            maker_fills += 1
        else:
            taker_fills += 1

        if net > 0:
            win_fills += 1
            total_win_quote += net
        elif net < 0:
            loss_fills += 1
            total_loss_quote += abs(net)

        ts = _parse_ts(r.get("ts", ""))
        if ts:
            day = ts.date().isoformat()
            daily_pnl[day] += net

    for m in minute:
        ts = _parse_ts(m.get("ts", ""))
        eq = _safe_float(m.get("equity_quote"))
        if ts and eq > 0:
            day = ts.date().isoformat()
            daily_equity[day] = eq

    fill_count = len(net_per_fill)
    n, expectancy, ci_low, ci_high = _mean_ci95(net_per_fill)
    win_rate = win_fills / fill_count if fill_count > 0 else 0.0
    avg_win = total_win_quote / win_fills if win_fills > 0 else 0.0
    avg_loss = total_loss_quote / loss_fills if loss_fills > 0 else 0.0
    maker_ratio = maker_fills / fill_count if fill_count > 0 else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf") if avg_win > 0 else 0.0

    sorted_days = sorted(daily_pnl.keys())
    daily_returns: list[float] = []
    equity_series: list[float] = []
    ts_series: list[float] = []

    running_equity = daily_equity.get(sorted_days[0], 1000.0) if sorted_days else 1000.0
    for day in sorted_days:
        pnl = daily_pnl[day]
        eq_before = daily_equity.get(day, running_equity)
        if eq_before > 0:
            daily_returns.append(pnl / eq_before)
        running_equity = eq_before + pnl
        equity_series.append(running_equity)
        ts = datetime.fromisoformat(day).replace(tzinfo=UTC)
        ts_series.append(ts.timestamp())

    ann_sharpe = 0.0
    if len(daily_returns) >= 3:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1))
        ann_sharpe = (mean_r / std_r) * math.sqrt(365) if std_r > 0 else 0.0

    max_dd = 0.0
    if len(equity_series) >= 2:
        try:
            max_dd = max_drawdown(equity_series, ts_series, method="percent")
        except Exception:
            peak = equity_series[0]
            for eq in equity_series:
                peak = max(peak, eq)
                dd = (peak - eq) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

    total_net_pnl = sum(net_per_fill)

    cancel_minutes = sum(
        1
        for m in minute
        if _safe_float(m.get("cancel_per_min")) > 0 and _safe_float(m.get("fills_count_today")) == 0
    )
    total_minutes = len(minute)
    cancel_before_fill_rate = cancel_minutes / total_minutes if total_minutes > 0 else 0.0

    soft_pause_minutes = sum(1 for m in minute if str(m.get("state", "")).lower() == "soft_pause")
    hard_stop_minutes = sum(1 for m in minute if str(m.get("state", "")).lower() == "hard_stop")
    running_minutes = sum(1 for m in minute if str(m.get("state", "")).lower() == "running")

    uptime_pct = running_minutes / total_minutes if total_minutes > 0 else 0.0

    # Edge verdict
    if fill_count < 100:
        verdict = "INSUFFICIENT_DATA"
    elif expectancy > 0 and ci_low > 0:
        verdict = "EDGE_CONFIRMED"
    elif expectancy > 0 and ci_low <= 0:
        verdict = "EDGE_POSSIBLE"
    elif expectancy <= 0:
        verdict = "NO_EDGE"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "bot": bot_name,
        "status": "ok",
        "verdict": verdict,
        "fill_count": fill_count,
        "days_covered": len(sorted_days),
        "expectancy_per_fill_quote": round(expectancy, 6),
        "expectancy_ci95_low": round(ci_low, 6),
        "expectancy_ci95_high": round(ci_high, 6),
        "total_net_pnl_quote": round(total_net_pnl, 4),
        "total_notional_quote": round(total_notional, 2),
        "total_fees_quote": round(total_fees, 4),
        "win_rate": round(win_rate, 4),
        "win_fills": win_fills,
        "loss_fills": loss_fills,
        "avg_win_quote": round(avg_win, 6),
        "avg_loss_quote": round(avg_loss, 6),
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio != float("inf") else "inf",
        "maker_ratio": round(maker_ratio, 4),
        "annualized_sharpe": round(ann_sharpe, 4),
        "max_drawdown_pct": round(max_dd, 6),
        "cancel_before_fill_rate": round(cancel_before_fill_rate, 4),
        "uptime_pct": round(uptime_pct, 4),
        "soft_pause_minutes": soft_pause_minutes,
        "hard_stop_minutes": hard_stop_minutes,
        "running_minutes": running_minutes,
    }


def run(
    filter_bots: list[str] | None = None,
    lookback_days: int = 0,
    save: bool = False,
) -> dict[str, object]:
    root = _repo_root()
    bot_dirs = _discover_bot_log_dirs(root, filter_bots=filter_bots)

    strategies: dict[str, dict[str, object]] = {}
    for bot_name, log_dir in sorted(bot_dirs.items()):
        edge = _compute_strategy_edge(bot_name, log_dir, lookback_days=lookback_days)
        strategies[bot_name] = edge

    report = {
        "ts_utc": datetime.now(UTC).isoformat(),
        "lookback_days": lookback_days if lookback_days > 0 else "all",
        "strategies": strategies,
        "summary": _build_summary(strategies),
    }

    if save:
        reports_dir = root / "reports" / "strategy"
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = reports_dir / f"edge_measurement_{stamp}.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (reports_dir / "edge_measurement_latest.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    return report


def _build_summary(strategies: dict[str, dict[str, object]]) -> dict[str, object]:
    active = {k: v for k, v in strategies.items() if v.get("status") == "ok"}
    if not active:
        return {"status": "no_active_strategies"}

    best_expectancy_bot = max(active, key=lambda k: _safe_float(active[k].get("expectancy_per_fill_quote")))
    best_sharpe_bot = max(active, key=lambda k: _safe_float(active[k].get("annualized_sharpe")))

    total_net_pnl = sum(_safe_float(v.get("total_net_pnl_quote")) for v in active.values())
    total_fills = sum(int(v.get("fill_count", 0)) for v in active.values())

    verdicts = {k: str(v.get("verdict", "UNKNOWN")) for k, v in active.items()}
    edge_confirmed = [k for k, v in verdicts.items() if v == "EDGE_CONFIRMED"]
    no_edge = [k for k, v in verdicts.items() if v == "NO_EDGE"]
    insufficient = [k for k, v in verdicts.items() if v == "INSUFFICIENT_DATA"]

    recommendation = "CONTINUE_MONITORING"
    if edge_confirmed:
        recommendation = f"SCALE: {', '.join(edge_confirmed)} show confirmed edge"
    elif no_edge and not edge_confirmed:
        recommendation = f"REVIEW: {', '.join(no_edge)} show no edge — consider rethinking strategy"
    elif insufficient:
        recommendation = f"WAIT: {', '.join(insufficient)} need more data"

    return {
        "total_strategies": len(active),
        "total_fills": total_fills,
        "total_net_pnl_quote": round(total_net_pnl, 4),
        "best_expectancy_bot": best_expectancy_bot,
        "best_sharpe_bot": best_sharpe_bot,
        "verdicts": verdicts,
        "edge_confirmed": edge_confirmed,
        "no_edge": no_edge,
        "insufficient_data": insufficient,
        "recommendation": recommendation,
    }


def _print_table(report: dict[str, object]) -> None:
    strategies = report.get("strategies", {})
    if not strategies:
        print("No strategies found.")
        return

    header = (
        f"{'Bot':<8} {'Verdict':<18} {'Fills':>6} {'Days':>5} "
        f"{'Expect/Fill':>12} {'CI95 Low':>10} {'Win%':>6} "
        f"{'AvgWin':>10} {'AvgLoss':>10} {'Payoff':>8} "
        f"{'Maker%':>7} {'Sharpe':>8} {'MaxDD%':>8} {'NetPnL':>12}"
    )
    print(header)
    print("-" * len(header))

    for bot, data in sorted(strategies.items()):
        if data.get("status") != "ok":
            print(f"{bot:<8} {'NO_DATA':<18}")
            continue

        payoff = data.get("payoff_ratio", 0)
        payoff_str = f"{payoff:>8.2f}" if isinstance(payoff, (int, float)) else f"{'inf':>8}"

        print(
            f"{bot:<8} {data.get('verdict', '')!s:<18} "
            f"{data.get('fill_count', 0):>6} {data.get('days_covered', 0):>5} "
            f"{_safe_float(data.get('expectancy_per_fill_quote')):>12.6f} "
            f"{_safe_float(data.get('expectancy_ci95_low')):>10.6f} "
            f"{_safe_float(data.get('win_rate')) * 100:>5.1f}% "
            f"{_safe_float(data.get('avg_win_quote')):>10.6f} "
            f"{_safe_float(data.get('avg_loss_quote')):>10.6f} "
            f"{payoff_str} "
            f"{_safe_float(data.get('maker_ratio')) * 100:>6.1f}% "
            f"{_safe_float(data.get('annualized_sharpe')):>8.2f} "
            f"{_safe_float(data.get('max_drawdown_pct')) * 100:>7.2f}% "
            f"{_safe_float(data.get('total_net_pnl_quote')):>12.4f}"
        )

    summary = report.get("summary", {})
    if summary:
        print()
        print(f"Recommendation: {summary.get('recommendation', 'N/A')}")
        print(f"Total fills: {summary.get('total_fills', 0)} | Total net PnL: {_safe_float(summary.get('total_net_pnl_quote')):.4f} USDT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified per-strategy edge measurement")
    parser.add_argument("--bot", action="append", dest="bots", help="Filter to specific bots (repeatable)")
    parser.add_argument("--lookback-days", type=int, default=0, help="Limit to last N days (0=all)")
    parser.add_argument("--save", action="store_true", help="Save report JSON to reports/strategy/")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of table")
    args = parser.parse_args()

    result = run(filter_bots=args.bots, lookback_days=args.lookback_days, save=args.save)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_table(result)
