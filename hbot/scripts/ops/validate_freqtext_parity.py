"""
Parity check: compare values from ftui_dashboard.py DashboardData
against what bot_metrics_exporter.py would export for the same data_dir.

Run from workspace root:
    python hbot/scripts/ops/validate_freqtext_parity.py
"""
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path("hbot/data/bot1/logs/epp_v24/bot1_a")
PORTFOLIO_FILE = DATA_DIR / "paper_desk_v2.json"
FILLS_FILE = DATA_DIR / "fills.csv"
MINUTE_FILE = DATA_DIR / "minute.csv"

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
results = []


def _float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _median(lst):
    if not lst:
        return 0.0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def check(name, terminal_val, exporter_val, tol=0.01):
    delta = abs(terminal_val - exporter_val)
    rel = delta / max(abs(terminal_val), 1e-9)
    status = PASS if rel < tol else FAIL
    tag = f"[{status}]"
    results.append(status)
    print(f"{tag:6s}  {name:45s}  terminal={terminal_val:>12.4f}  exporter={exporter_val:>12.4f}  d={delta:.4f}")


# ──────────────────────────────────────────────────────────────────────────────
# Terminal values (DashboardData logic)
# ──────────────────────────────────────────────────────────────────────────────

def terminal_open_pnl():
    if not PORTFOLIO_FILE.exists():
        return 0.0
    data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    total = 0.0
    for pos in data.get("portfolio", {}).get("positions", {}).values():
        total += _float(pos.get("unrealized_pnl"))
    return total


def terminal_closed_pnl_and_stats():
    rows = []
    if FILLS_FILE.exists():
        with open(FILLS_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    total_pnl = sum(_float(r.get("realized_pnl_quote")) for r in rows)
    pnl_values = [_float(r.get("realized_pnl_quote")) for r in rows]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]
    nonzero = wins + losses
    denom = len(wins) + len(losses)
    winrate = len(wins) / denom if denom > 0 else 0.0
    expectancy = sum(nonzero) / len(nonzero) if nonzero else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    exp_rate = avg_win * winrate - avg_loss * (1 - winrate) if denom > 0 else 0.0
    med_w = _median(wins)
    med_l = _median(losses)

    # First fill timestamp
    first_ts = 0.0
    if rows:
        dt = _parse_ts(rows[0].get("ts", ""))
        first_ts = dt.timestamp() if dt != datetime.min.replace(tzinfo=timezone.utc) else 0.0

    return {
        "closed_pnl": total_pnl,
        "trades_total": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": winrate,
        "expectancy": expectancy,
        "exp_rate": exp_rate,
        "med_w": med_w,
        "med_l": med_l,
        "first_fill_ts": first_ts,
    }


def terminal_daily_pnl(now_utc):
    if not MINUTE_FILE.exists():
        return 0.0
    today = now_utc.date()
    with open(MINUTE_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in reversed(rows):
        ts = _parse_ts(row.get("ts", ""))
        if ts.date() == today:
            return _float(row.get("realized_pnl_today_quote"))
    return 0.0


def terminal_pnl_since(rows, days, now_utc):
    cutoff = now_utc - timedelta(days=days)
    pnl = 0.0
    prev_date = None
    prev_pnl_today = 0.0
    for row in rows:
        ts = _parse_ts(row.get("ts", ""))
        if ts < cutoff:
            continue
        day = ts.date()
        cur = _float(row.get("realized_pnl_today_quote"))
        if prev_date is not None and day != prev_date:
            pnl += prev_pnl_today
        prev_date = day
        prev_pnl_today = cur
    pnl += prev_pnl_today
    return pnl


def terminal_equity_series(rows):
    raw = [_float(r.get("equity_quote")) for r in rows if r.get("equity_quote")]
    if not raw:
        return 0.0, 0.0
    return raw[0], raw[-1] - raw[0]


# ──────────────────────────────────────────────────────────────────────────────
# Exporter values (bot_metrics_exporter logic)
# ──────────────────────────────────────────────────────────────────────────────

# We import and call the actual exporter to get the real rendered metrics.
# Since bot_metrics_exporter reads from the same DATA_DIR files, values must match.

sys.path.insert(0, "hbot")
try:
    from services.bot_metrics_exporter import BotMetricsExporter
    exporter_available = True
except Exception as e:
    print(f"[WARN] Could not import BotMetricsExporter: {e}")
    exporter_available = False

# ──────────────────────────────────────────────────────────────────────────────
# Run parity checks
# ──────────────────────────────────────────────────────────────────────────────

now_utc = datetime.now(timezone.utc)

print("=" * 90)
print("FreqText -> Grafana parity check")
print(f"data_dir: {DATA_DIR.resolve()}")
print(f"now_utc:  {now_utc.isoformat()}")
print("=" * 90)

# ── Terminal computation ──────────────────────────────────────────────────────
t_open = terminal_open_pnl()
t_stats = terminal_closed_pnl_and_stats()
t_daily = terminal_daily_pnl(now_utc)

minute_rows = []
if MINUTE_FILE.exists():
    with open(MINUTE_FILE, newline="", encoding="utf-8") as f:
        minute_rows = list(csv.DictReader(f))

t_weekly = terminal_pnl_since(minute_rows, 7, now_utc)
t_monthly = terminal_pnl_since(minute_rows, 30, now_utc)
t_equity_start, t_cum_profit = terminal_equity_series(minute_rows)

if not exporter_available:
    print("\n[WARN] Exporter not importable — printing terminal-only values.\n")
    print(f"  Open:         {t_open:+.4f}")
    print(f"  Closed:       {t_stats['closed_pnl']:+.4f}")
    print(f"  Daily:        {t_daily:+.4f}")
    print(f"  Weekly:       {t_weekly:+.4f}")
    print(f"  Monthly:      {t_monthly:+.4f}")
    print(f"  # Trades:     {t_stats['trades_total']}")
    print(f"  Wins/Losses:  {t_stats['wins']}/{t_stats['losses']}")
    print(f"  Winrate:      {t_stats['winrate']:.4f}")
    print(f"  Expectancy:   {t_stats['expectancy']:+.4f}")
    print(f"  Exp.Rate:     {t_stats['exp_rate']:+.4f}")
    print(f"  Med.W:        {t_stats['med_w']:+.4f}")
    print(f"  Med.L:        {t_stats['med_l']:+.4f}")
    print(f"  EquityStart:  {t_equity_start:.4f}")
    print(f"  CumProfit:    {t_cum_profit:+.4f}")
    sys.exit(0)

# ── Exporter computation ──────────────────────────────────────────────────────
exporter = BotMetricsExporter(data_root=DATA_DIR.parent.parent.parent.parent)
snapshots = exporter.collect()

if not snapshots:
    print("[WARN] No snapshots collected — check data_dir path or file availability.")
    sys.exit(1)

snap = snapshots[0]
fs = snap.fill_stats
pf = snap.portfolio
mh = snap.minute_history

print("\n--- Header stats ---")
check("Open PnL",          t_open,                    pf.open_pnl_quote if pf else 0.0)
check("Closed PnL total",  t_stats["closed_pnl"],     fs.closed_pnl_total if fs else 0.0)
check("Daily PnL",         t_daily,                   snap.realized_pnl_today_quote)
check("Weekly PnL",        t_weekly,                  mh.realized_pnl_week_quote if mh else 0.0)
check("Monthly PnL",       t_monthly,                 mh.realized_pnl_month_quote if mh else 0.0)

print("\n--- Bot performance table ---")
check("# Trades",          float(t_stats["trades_total"]), float(fs.trades_total if fs else 0))
check("Wins",              float(t_stats["wins"]),         float(fs.trade_wins_total if fs else 0))
check("Losses",            float(t_stats["losses"]),       float(fs.trade_losses_total if fs else 0))
check("Winrate",           t_stats["winrate"],             fs.trade_winrate if fs else 0.0)
check("Expectancy",        t_stats["expectancy"],          fs.trade_expectancy_quote if fs else 0.0)
check("Expectancy Rate",   t_stats["exp_rate"],            fs.trade_expectancy_rate_quote if fs else 0.0)
check("Median Win",        t_stats["med_w"],               fs.trade_median_win_quote if fs else 0.0)
check("Median Loss",       t_stats["med_l"],               fs.trade_median_loss_quote if fs else 0.0)
check("First fill epoch",  t_stats["first_fill_ts"],       fs.first_fill_timestamp_seconds if fs else 0.0, tol=0.001)

print("\n--- Cumulative profit chart ---")
check("Equity start",      t_equity_start,                 mh.equity_start_quote if mh else 0.0)

print("\n--- Open position (paper_desk_v2.json) ---")
if pf and pf.positions:
    for pos in pf.positions:
        print(f"  instrument_id={pos.instrument_id}  qty={pos.quantity_base:.6f}  unr_pnl={pos.unrealized_pnl_quote:.4f}")
else:
    print("  (no open positions or portfolio not read)")

print()
n_pass = results.count(PASS)
n_fail = results.count(FAIL)
print(f"Result: {n_pass}/{len(results)} PASS  {n_fail} FAIL")
if n_fail:
    sys.exit(1)
