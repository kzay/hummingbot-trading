---
description: Hummingbot V2 controller development patterns
globs: controllers/**/*.py
alwaysApply: false
---

# Hummingbot V2 Controller Patterns

When editing V2 controllers:

- Controllers extend `MarketMakingControllerBase` or `DirectionalTradingControllerBase`
- Config classes extend the matching `*ConfigBase` using Pydantic v2
- Override `update_processed_data()` to set `reference_price` (Decimal) and `spread_multiplier` (Decimal)
- Override `get_executor_config()` to return `PositionExecutorConfig`
- Use `pandas_ta` for indicators (available in Hummingbot image, no ta-lib needed)
- Get candle data via `self.market_data_provider.get_candles_df(connector, pair, interval, max_records)`
- Fields with `"is_updatable": True` in json_schema_extra are hot-reloadable from YAML
- Spread values in config are multiplied by `spread_multiplier` by the base class
- The base class handles order levels, executor refresh, triple barrier, and position rebalancing

Example structure (from pmm_dynamic.py):
```python
async def update_processed_data(self):
    candles = self.market_data_provider.get_candles_df(...)
    natr = ta.natr(candles["high"], candles["low"], candles["close"], length=14) / 100
    self.processed_data = {
        "reference_price": Decimal(str(candles["close"].iloc[-1])),
        "spread_multiplier": Decimal(str(natr.iloc[-1])),
    }
```

## Mandatory: Testing Config for Every New Strategy

When generating a new controller, ALWAYS create three config files:

1. **Controller config** — `conf/controllers/<name>.yml` (production params)
2. **Test controller config** — `conf/controllers/<name>_test.yml` (micro-live test)
3. **Script config** — `conf/scripts/v2_<name>_test.yml` (references the test controller)

The test config MUST use the **real connector with micro capital**, NOT paper_trade:

```yaml
# <name>_test.yml — MANDATORY for every new strategy
connector_name: bitget              # REAL connector, not paper_trade
trading_pair: BTC-USDT
total_amount_quote: 10              # $10 micro budget — real but negligible risk
leverage: 1
```

### Why not paper_trade?
`bitget_paper_trade` (and most `*_paper_trade` connectors) are broken in Hummingbot V2:
- `PaperTradeExchange` is missing `trading_rules` attribute → crashes `PositionExecutor`
- `PaperTradeExchange` is missing `_order_tracker` → crashes event processing
- Stale paper_trade executors persist in SQLite and poison subsequent sessions
- Cleaning requires deleting `data/botX/data/*.sqlite` + full container restart

### Testing workflow
1. Deploy controller + test config
2. `start --script v2_with_controllers.py --conf v2_<name>_test.yml`
3. Run for 1-2 hours, verify via `status`: orders placed, fills tracked, no errors in logs
4. Check `data/bot1/logs/logs_*.log` for any ERROR lines
5. If clean → switch to production config with real capital
