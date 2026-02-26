"""Quick test: verify bot_metrics_exporter renders metrics from current data."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services"))
from pathlib import Path
from bot_metrics_exporter import BotMetricsExporter
e = BotMetricsExporter(Path(os.environ.get("HB_DATA_ROOT", "/workspace/hbot/data")))
try:
    out = e.render_prometheus()
    print(f"OK: {len(out.splitlines())} metrics lines")
    for line in out.splitlines():
        if any(k in line for k in ("position_base", "equity_quote", "fills_buy", "realized_pnl", "daily_pnl")):
            print(line)
except Exception as ex:
    print(f"ERROR: {ex}")
    import traceback; traceback.print_exc()
