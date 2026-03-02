"""Test that the exporter produces the new FreqText metrics from hbot/data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services"))

from services.bot_metrics_exporter import BotMetricsExporter  # noqa: E402

data_root = Path("hbot/data")
e = BotMetricsExporter(data_root=data_root)
snaps = e.collect()
print(f"Snapshots: {len(snaps)}")

out = e.render_prometheus()
lines = out.split("\n")

wanted = [
    "hbot_bot_open_pnl_quote",
    "hbot_bot_closed_pnl_quote_total",
    "hbot_bot_trades_total",
    "hbot_bot_trade_winrate",
    "hbot_bot_realized_pnl_week_quote",
    "hbot_bot_realized_pnl_month_quote",
    "hbot_bot_equity_start_quote",
    "hbot_bot_position_quantity_base",
    "hbot_bot_position_unrealized_pnl_quote",
]

print("\n-- New FreqText metrics --")
for prefix in wanted:
    hits = [l for l in lines if l.startswith(prefix + "{") or l.startswith(prefix + " ")]
    if hits:
        print(f"  OK  {hits[0]}")
    else:
        print(f"  MISSING: {prefix}")
