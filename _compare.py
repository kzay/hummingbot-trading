import json, sys
from pathlib import Path

names = sys.argv[1:] if len(sys.argv) > 1 else [
    'bot7_mom_filtered', 'bot7_mom_trend', 'bot7_mom_reversal',
    'bot7_mom_limit', 'bot7_mom_asym', 'bot7_mm_baseline',
]
for name in names:
    p = Path(f'hbot/reports/backtest/{name}.json')
    if not p.exists():
        print(f'=== {name} === NOT FOUND')
        continue
    d = json.loads(p.read_text())
    print(f'=== {name} ===')
    print(f'  return:       {d["total_return_pct"]:.2f}%')
    print(f'  fills:        {d["fill_count"]}')
    print(f'  closed_trades:{d["closed_trade_count"]}')
    print(f'  win_rate:     {d["win_rate"]:.1%}')
    print(f'  profit_factor:{d["profit_factor"]:.3f}')
    print(f'  realized_pnl: {d["realized_net_pnl_quote"]}')
    print(f'  residual_pnl: {d["residual_pnl_quote"]}')
    print(f'  total_fees:   {d["total_fees"]}')
    print(f'  expectancy:   {d["expectancy_quote"]}')
    print(f'  avg_win:      {d["avg_win_quote"]}')
    print(f'  avg_loss:     {d["avg_loss_quote"]}')
    print(f'  max_dd:       {d["max_drawdown_pct"]:.2f}%')
    print(f'  maker_ratio:  {d["maker_fill_ratio"]:.1%}')
    print(f'  terminal_pos: {d["terminal_position_base"]}')
    print()
