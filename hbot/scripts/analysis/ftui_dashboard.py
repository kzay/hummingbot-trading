"""
FreqText-style terminal dashboard for the hbot EPP v2.4 trading desk.

Layout mirrors FreqTrade's ftui:
  ┌─────────────────────────────────────────────────────────┐
  │  Open │ Closed │  Daily │  Weekly │  Monthly             │
  ├─────────────────────────────────────────────────────────┤
  │  Bot performance table (one row per bot variant)         │
  ├─────────────────────────────────────────────────────────┤
  │  All Open Trades                                         │
  ├─────────────────────────────────────────────────────────┤
  │  All Closed Trades (recent fills)                        │
  ├─────────────────────────────────────────────────────────┤
  │  Cumulative Profit chart                                 │
  └─────────────────────────────────────────────────────────┘

Usage:
    PYTHONPATH=hbot python -m scripts.analysis.ftui_dashboard
    PYTHONPATH=hbot python -m scripts.analysis.ftui_dashboard --watch      # live refresh every 15s
    PYTHONPATH=hbot python -m scripts.analysis.ftui_dashboard --data-dir data/bot1/logs/epp_v24/bot1_a
"""

import argparse
import csv
import io
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Force UTF-8 output on Windows to support unicode box-drawing characters
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
CHART_WIDTH = 80
CHART_HEIGHT = 8


# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    """Read CSV file into list of dicts, return [] if missing."""
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_portfolio(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp, returns timezone.utc-aware datetime."""
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=UTC)


def _float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────────────────
# Aggregations
# ──────────────────────────────────────────────────────────────────────────────

class DashboardData:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.fills: list[dict] = []
        self.minutes: list[dict] = []
        self.portfolio: dict = {}
        self.now_utc = datetime.now(UTC)
        self.refresh()

    def refresh(self):
        self.fills = _read_csv(self.data_dir / "fills.csv")
        self.minutes = _read_csv(self.data_dir / "minute.csv")
        self.portfolio = _load_portfolio(self.data_dir / "paper_desk_v2.json")
        self.now_utc = datetime.now(UTC)

    # ── Header stats ──────────────────────────────────────────────────────────

    def open_pnl(self) -> float:
        """Unrealized PnL from current open position."""
        pos_data = self.portfolio.get("portfolio", {}).get("positions", {})
        total = 0.0
        for key, pos in pos_data.items():
            if isinstance(pos, str):
                # PowerShell returns @{...} strings; parse them
                pos = _parse_ps_object(pos)
            total += _float(pos.get("unrealized_pnl", 0))
        return total

    def closed_pnl(self) -> float:
        """Total realized PnL from fills (non-zero realized_pnl_quote rows)."""
        total = 0.0
        for f in self.fills:
            total += _float(f.get("realized_pnl_quote", 0))
        return total

    def _pnl_since(self, days: int) -> float:
        """Realized PnL for the last N days based on minute data."""
        if not self.minutes:
            return 0.0
        cutoff = self.now_utc - timedelta(days=days)
        pnl = 0.0
        # sum of realized_pnl_today_quote changes across day boundaries
        prev_date = None
        prev_pnl_today = 0.0
        for row in self.minutes:
            ts = _parse_ts(row.get("ts", ""))
            if ts < cutoff:
                continue
            day = ts.date()
            cur_pnl_today = _float(row.get("realized_pnl_today_quote", 0))
            if prev_date is not None and day != prev_date:
                pnl += prev_pnl_today  # previous day's full realized
            prev_date = day
            prev_pnl_today = cur_pnl_today
        pnl += prev_pnl_today  # current day so far
        return pnl

    def daily_pnl(self) -> float:
        if not self.minutes:
            return 0.0
        today = self.now_utc.date()
        for row in reversed(self.minutes):
            ts = _parse_ts(row.get("ts", ""))
            if ts.date() == today:
                return _float(row.get("realized_pnl_today_quote", 0))
        return 0.0

    def weekly_pnl(self) -> float:
        return self._pnl_since(7)

    def monthly_pnl(self) -> float:
        return self._pnl_since(30)

    # ── Bot table ─────────────────────────────────────────────────────────────

    def bot_stats(self) -> list[dict]:
        """Per-variant performance stats."""
        # Group fills by bot_variant
        variants: dict[str, list[dict]] = {}
        for f in self.fills:
            v = f.get("bot_variant", "?")
            variants.setdefault(v, []).append(f)

        rows = []
        for v, fills in sorted(variants.items()):
            pnl_list = [_float(f.get("realized_pnl_quote", 0)) for f in fills]
            nonzero_pnl = [p for p in pnl_list if p != 0.0]
            wins = [p for p in nonzero_pnl if p > 0]
            losses = [p for p in nonzero_pnl if p < 0]

            first_ts = _parse_ts(fills[0].get("ts", "")) if fills else None
            start_str = first_ts.strftime("%Y-%m-%d") if first_ts else "—"

            # open profit from portfolio
            open_pnl = 0.0
            pos_data = self.portfolio.get("portfolio", {}).get("positions", {})
            for key, pos in pos_data.items():
                if isinstance(pos, str):
                    pos = _parse_ps_object(pos)
                open_pnl += _float(pos.get("unrealized_pnl", 0))

            w = len(wins)
            l = len(losses)
            total = w + l
            winrate = (w / total * 100) if total > 0 else 0.0
            exp = sum(nonzero_pnl) / len(nonzero_pnl) if nonzero_pnl else 0.0
            # exp_rate = avg_win * winrate - avg_loss * (1-winrate)
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
            winrate_frac = winrate / 100
            exp_rate = avg_win * winrate_frac - avg_loss * (1 - winrate_frac) if total > 0 else 0.0
            med_w = _median(wins) if wins else 0.0
            med_l = _median(losses) if losses else 0.0

            rows.append({
                "bot": f"bot1-{v}",
                "start": start_str,
                "num_trades": len(fills),
                "open_profit": open_pnl,
                "w": w,
                "l": l,
                "winrate": winrate,
                "exp": exp,
                "exp_rate": exp_rate,
                "med_w": med_w,
                "med_l": med_l,
                "tot_profit": sum(pnl_list),
            })
        return rows

    # ── Open trades ───────────────────────────────────────────────────────────

    def open_trades(self) -> list[dict]:
        pos_data = self.portfolio.get("portfolio", {}).get("positions", {})
        trades = []
        for instrument_id, pos in pos_data.items():
            if isinstance(pos, str):
                pos = _parse_ps_object(pos)
            qty = _float(pos.get("quantity", 0))
            if qty == 0:
                continue
            avg_entry = _float(pos.get("avg_entry_price", 0))
            unr_pnl = _float(pos.get("unrealized_pnl", 0))
            fees = _float(pos.get("total_fees_paid", 0))
            # Determine current mid from latest minute row
            cur_mid = avg_entry
            if self.minutes:
                cur_mid = _float(self.minutes[-1].get("mid", avg_entry))
            # profit % vs entry
            notional = abs(qty) * avg_entry
            profit_pct = (unr_pnl / notional * 100) if notional > 0 else 0.0
            side = "S" if qty < 0 else "L"
            # Duration from opened_at_ns
            opened_ns = _float(pos.get("opened_at_ns", 0))
            if opened_ns > 0:
                opened_dt = datetime.fromtimestamp(opened_ns / 1e9, tz=UTC)
                dur = self.now_utc - opened_dt
                dur_str = _fmt_dur(dur)
            else:
                dur_str = "—"
            # Pair from instrument_id (e.g. bitget:BTC-USDT:perp → BTC-USDT)
            parts = instrument_id.split(":")
            pair = parts[1] if len(parts) >= 2 else instrument_id

            trades.append({
                "bot": "bot1-a",
                "id": instrument_id.split(":")[0][:8],
                "pair": pair,
                "stake": f"{notional:.2f}",
                "open_rate": f"{avg_entry:.2f}",
                "rate": f"{cur_mid:.2f}",
                "stop_pct": "—",
                "profit_pct": profit_pct,
                "profit": unr_pnl,
                "dur": dur_str,
                "sl": side,
                "tag": "epp_v2_4",
            })
        return trades

    # ── Closed trades (fills with realized PnL) ──────────────────────────────

    def closed_trades(self, n: int = 30) -> list[dict]:
        """Most recent N fills that have non-zero realized PnL (actual closed legs)."""
        # Collect fills with non-zero pnl first; fall back to all fills if none
        pnl_fills = [f for f in self.fills if _float(f.get("realized_pnl_quote", 0)) != 0.0]
        source = pnl_fills if pnl_fills else self.fills
        recent = list(reversed(source[-n:])) if len(source) > n else list(reversed(source))
        rows = []
        for f in recent[:n]:
            pnl = _float(f.get("realized_pnl_quote", 0))
            notional = _float(f.get("notional_quote", 0))
            profit_pct = (pnl / notional * 100) if notional > 0 and pnl != 0 else 0.0
            pair = f.get("trading_pair", "?")
            side = f.get("side", "?")
            ts = _parse_ts(f.get("ts", ""))
            order_id = f.get("order_id", "?")
            # Shorten paper_v2_XX style IDs
            short_id = order_id.split("_")[-1] if "_" in order_id else order_id[-10:]
            rows.append({
                "bot": f"bot1-{f.get('bot_variant', '?')}",
                "id": short_id,
                "pair": pair,
                "profit_pct": profit_pct,
                "profit": pnl,
                "open_date": ts.strftime("%Y-%m-%d %H:%M"),
                "dur": "—",
                "enter": side,
                "exit": f.get("state", "?"),
            })
        return rows

    # ── Chart data ────────────────────────────────────────────────────────────

    def equity_series(self) -> list[float]:
        """Cumulative realized PnL over time (equity minus starting equity)."""
        raw = [_float(r.get("equity_quote", 0)) for r in self.minutes if r.get("equity_quote")]
        if not raw:
            return []
        start = raw[0]
        return [v - start for v in raw]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_ps_object(s: str) -> dict:
    """Parse PowerShell @{key=val; key=val} string into dict (best-effort)."""
    result = {}
    s = s.strip()
    if s.startswith("@{") and s.endswith("}"):
        s = s[2:-1]
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def _median(lst: list[float]) -> float:
    if not lst:
        return 0.0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _fmt_dur(td: timedelta) -> str:
    total_s = int(td.total_seconds())
    if total_s < 0:
        return "—"
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h > 24:
        d = h // 24
        h %= 24
        return f"{d}d {h:02d}:{m:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def _color_pnl(val: float) -> str:
    if val > 0:
        return "green"
    elif val < 0:
        return "red"
    return "white"


def _fmt_pnl(val: float, decimals: int = 2) -> Text:
    s = f"{val:+.{decimals}f}"
    return Text(s, style=_color_pnl(val))


# ──────────────────────────────────────────────────────────────────────────────
# ASCII sparkline chart (no external deps beyond rich)
# ──────────────────────────────────────────────────────────────────────────────

BLOCK_CHARS = " .:-=+*#%@"  # ASCII-safe gradient chars


def _build_chart(series: list[float], width: int = CHART_WIDTH, height: int = CHART_HEIGHT) -> str:
    """Build an ASCII chart using text characters (terminal-safe)."""
    if not series:
        return "(no data)"
    # Downsample to fit width
    if len(series) > width:
        step = len(series) / width
        series = [series[int(i * step)] for i in range(width)]

    mn = min(series)
    mx = max(series)
    rng = mx - mn if mx != mn else 1.0

    # Build chart rows top-to-bottom
    rows = []
    for row_idx in range(height - 1, -1, -1):
        line = ""
        threshold_high = mn + rng * (row_idx + 1) / height
        threshold_low = mn + rng * row_idx / height
        for val in series:
            if val >= threshold_high:
                line += "#"
            elif val >= threshold_low:
                frac = (val - threshold_low) / (threshold_high - threshold_low)
                line += BLOCK_CHARS[max(1, int(frac * (len(BLOCK_CHARS) - 1)))]
            else:
                line += " "
        rows.append(line)

    # Y-axis labels
    labeled = []
    for i, row in enumerate(rows):
        rev_i = (height - 1) - i
        if rev_i == height - 1:
            lbl = f"{mx:>8.1f} |"
        elif rev_i == height // 2:
            mid_val = mn + rng / 2
            lbl = f"{mid_val:>8.1f} |"
        elif rev_i == 0:
            lbl = f"{mn:>8.1f} |"
        else:
            lbl = "         |"
        labeled.append(lbl + row)

    return "\n".join(labeled)


# ──────────────────────────────────────────────────────────────────────────────
# Rich panel builders
# ──────────────────────────────────────────────────────────────────────────────

def build_header(data: DashboardData) -> Panel:
    open_pnl = data.open_pnl()
    closed_pnl = data.closed_pnl()
    daily = data.daily_pnl()
    weekly = data.weekly_pnl()
    monthly = data.monthly_pnl()

    def metric(label: str, val: float) -> Text:
        t = Text()
        t.append(f"{label}\n", style="bold white")
        t.append(f"{val:+.2f}", style="bold " + _color_pnl(val))
        return t

    cols = Columns(
        [
            Panel(metric("Open", open_pnl), expand=True, border_style="grey35"),
            Panel(metric("Closed", closed_pnl), expand=True, border_style="grey35"),
            Panel(metric("Daily", daily), expand=True, border_style="grey35"),
            Panel(metric("Weekly", weekly), expand=True, border_style="grey35"),
            Panel(metric("Monthly", monthly), expand=True, border_style="grey35"),
        ],
        equal=True,
        expand=True,
    )
    return cols


def build_bot_table(data: DashboardData) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        expand=False,
        title="[bold]Bot Performance[/bold]",
        min_width=100,
    )
    t.add_column("Bot", style="cyan", no_wrap=True, min_width=8)
    t.add_column("Start", style="white", min_width=10)
    t.add_column("# Tr.", justify="right", min_width=6)
    t.add_column("Open PnL", justify="right", min_width=9)
    t.add_column("W/L", justify="right", min_width=7)
    t.add_column("Win%", justify="right", min_width=5)
    t.add_column("Exp.", justify="right", min_width=7)
    t.add_column("Exp.Rate", justify="right", min_width=8)
    t.add_column("Med.W", justify="right", min_width=7)
    t.add_column("Med.L", justify="right", min_width=7)
    t.add_column("Tot.Profit", justify="right", min_width=10)

    for row in data.bot_stats():
        t.add_row(
            row["bot"],
            row["start"],
            str(row["num_trades"]),
            _fmt_pnl(row["open_profit"]),
            f"{row['w']}/{row['l']}",
            f"{row['winrate']:.1f}",
            _fmt_pnl(row["exp"]),
            _fmt_pnl(row["exp_rate"]),
            Text(f"{row['med_w']:+.2f}", style="green"),
            Text(f"{row['med_l']:+.2f}", style="red"),
            _fmt_pnl(row["tot_profit"]),
        )
    return t


def build_open_trades(data: DashboardData) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        expand=False,
        title="[bold]All Open Trades[/bold]",
        min_width=110,
    )
    t.add_column("Bot", style="cyan", no_wrap=True, min_width=10)
    t.add_column("ID", min_width=8)
    t.add_column("Pair", style="white", min_width=10)
    t.add_column("Stake", justify="right", min_width=10)
    t.add_column("Open Rate", justify="right", min_width=10)
    t.add_column("Rate", justify="right", min_width=10)
    t.add_column("Stop %", justify="right", min_width=7)
    t.add_column("Profit %", justify="right", min_width=9)
    t.add_column("Profit", justify="right", min_width=9)
    t.add_column("Dur.", justify="right", min_width=10)
    t.add_column("S/L", justify="center", min_width=4)
    t.add_column("Tag", style="dim", min_width=12)

    for row in data.open_trades():
        t.add_row(
            row["bot"],
            row["id"],
            row["pair"],
            row["stake"],
            row["open_rate"],
            row["rate"],
            row["stop_pct"],
            _fmt_pnl(row["profit_pct"]),
            _fmt_pnl(row["profit"]),
            row["dur"],
            Text(row["sl"], style="green" if row["sl"] == "L" else "red"),
            row["tag"],
        )
    return t


def build_closed_trades(data: DashboardData) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        expand=False,
        title="[bold]All Closed Trades[/bold]",
        min_width=110,
    )
    t.add_column("Bot", style="cyan", no_wrap=True, min_width=8)
    t.add_column("ID", min_width=5)
    t.add_column("Pair", style="white", min_width=9)
    t.add_column("Profit %", justify="right", min_width=9)
    t.add_column("Profit", justify="right", min_width=8)
    t.add_column("Open Date", min_width=16, no_wrap=True)
    t.add_column("Dur.", min_width=6)
    t.add_column("Enter", min_width=5)
    t.add_column("Exit", style="dim", min_width=8)

    for row in data.closed_trades(n=25):
        t.add_row(
            row["bot"],
            row["id"],
            row["pair"],
            _fmt_pnl(row["profit_pct"]),
            _fmt_pnl(row["profit"]),
            row["open_date"],
            row["dur"],
            row["enter"],
            row["exit"],
        )
    return t


def build_chart_panel(data: DashboardData, console_width: int = 100) -> Panel:
    series = data.equity_series()
    chart_w = max(40, console_width - 16)  # 11 for y-axis label, 4 for panel border, 1 spare
    chart_txt = _build_chart(series, width=chart_w, height=CHART_HEIGHT)
    if series:
        cum_pnl = series[-1]
        sign = "+" if cum_pnl >= 0 else ""
        color = "green" if cum_pnl >= 0 else "red"
        subtitle = f"[{color}]{sign}{cum_pnl:.2f} USDT[/{color}]  ({len(series)} min snapshots)"
    else:
        subtitle = "(no data)"
    return Panel(
        chart_txt,
        title="[bold]Cumulative Profit (USDT)[/bold]",
        subtitle=subtitle,
        border_style="grey35",
    )


def build_timestamp(data: DashboardData) -> Text:
    ts_str = data.now_utc.strftime("%H:%M:%S timezone.utc")
    # Latest minute row state
    state = "—"
    regime = "—"
    if data.minutes:
        last = data.minutes[-1]
        state = last.get("state", "—")
        regime = last.get("regime", "—")
        ts_str = f"{ts_str}   last minute: {_parse_ts(last.get('ts','')).strftime('%Y-%m-%d %H:%M')} timezone.utc"
    color = {"running": "green", "soft_pause": "yellow", "hard_stop": "red"}.get(state, "white")
    t = Text()
    t.append(" FreqText ", style="bold white on blue")
    t.append(f"  {ts_str}   ", style="dim")
    t.append("State: ", style="bold")
    t.append(f"{state.upper()} ", style=f"bold {color}")
    t.append(f"  Regime: {regime}", style="dim")
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Main render
# ──────────────────────────────────────────────────────────────────────────────

def render(data: DashboardData, console: Console) -> None:
    console.clear()
    console.print(build_timestamp(data))
    console.print(build_header(data))
    console.print(build_bot_table(data))
    console.print(build_open_trades(data))
    console.print(build_closed_trades(data))
    console.print(build_chart_panel(data, console_width=console.width))


def main():
    parser = argparse.ArgumentParser(description="FreqText-style terminal dashboard for hbot")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Path to bot data directory (contains fills.csv, minute.csv, paper_desk_v2.json)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Refresh every 15 seconds (live mode)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Refresh interval in seconds (default 15)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    import shutil
    term_w = shutil.get_terminal_size((120, 24)).columns
    # Use terminal width but cap at 160 to avoid issues on very wide screens
    console_width = min(max(term_w, 100), 160)
    console = Console(width=console_width, highlight=False)
    data = DashboardData(data_dir)

    if args.watch:
        try:
            while True:
                render(data, console)
                time.sleep(args.interval)
                data.refresh()
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Stopped.[/bold yellow]")
    else:
        render(data, console)


if __name__ == "__main__":
    main()
