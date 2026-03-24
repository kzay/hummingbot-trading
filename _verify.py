"""Re-verify the wider-spread baseline to ensure consistency after code changes."""
import sys, os, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.config_loader import load_backtest_config
from controllers.backtesting.harness import BacktestHarness

cfg = load_backtest_config("hbot/data/backtest_configs/bot7_mm_wider_3m.yml")
harness = BacktestHarness(cfg)
result = harness.run()

print(f"Return: {result.total_return_pct:.4f}%")
print(f"Fills: {result.fill_count}")
print(f"Closed trades: {result.closed_trade_count}")
print(f"Win rate: {result.win_rate:.4f}")
print(f"Profit factor: {result.profit_factor:.4f}")
print(f"Realized PnL: {result.realized_net_pnl_quote}")
print(f"Residual PnL: {result.residual_pnl_quote}")
print(f"Expectancy: {result.expectancy_quote}")
print(f"Avg win: {result.avg_win_quote}")
print(f"Avg loss: {result.avg_loss_quote}")
print(f"Max DD: {result.max_drawdown_pct:.4f}%")
print(f"Maker ratio: {result.maker_fill_ratio:.4f}")
print(f"Fees: {result.total_fees}")
