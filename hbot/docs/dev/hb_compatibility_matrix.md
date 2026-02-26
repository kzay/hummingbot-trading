> **Note (2026-02-26):** References to `paper_engine.py` below describe the v1 implementation. Current system uses `paper_engine_v2/` exclusively. The v1 patches listed here are no longer applied.

# Hummingbot Compatibility Matrix

## Target Version
- **Hummingbot**: `2.12.0` (`hummingbot/hummingbot:version-2.12.0`)
- **Python**: `3.11+`

## Active Workarounds / Patches

| # | Location | Patch Target | Purpose | HB Version Range | Risk on Upgrade |
|---|----------|-------------|---------|------------------|-----------------|
| 1 | `paper_engine.py` `enable_framework_paper_compat_fallbacks()` | `ExecutorBase.get_trading_rules` | Paper connector lacks `trading_rules` dict in the shape V2 executors expect | 2.12.0 | HIGH — executor API changes break this |
| 2 | `paper_engine.py` `enable_framework_paper_compat_fallbacks()` | `ExecutorBase.get_in_flight_order` | Paper connector `_order_tracker` lookup fails for custom `PaperExecutionAdapter` | 2.12.0 | MEDIUM — tracker interface may change |
| 3 | `paper_engine.py` `enable_framework_paper_compat_fallbacks()` | `MarketDataProvider._create_non_trading_connector` | `*_paper_trade` suffix not recognized as valid connector module | 2.12.0 | LOW — name resolution logic |
| 4 | `v2_with_controllers.py` `_install_trade_monitor_guard()` | `hb_interface_utils.start_trade_monitor` | Raises `ValueError("Connector ... not found")` for paper connectors | 2.12.0 | LOW — error handling only |
| 5 | `v2_with_controllers.py` `_install_connector_alias_guard()` | `ConnectorManager.update_connector_balances` | `binance_perpetual` alias not found; needs `binance_perpetual_testnet` fallback | 2.12.0 | LOW — connector naming only |

## Planned Removal Path

1. **Patches 1-3** should be replaced by making `PaperExecutionAdapter` directly expose the required interface (`trading_rules` property, `_order_tracker` attribute) without patching `ExecutorBase`. This requires testing against the full HB runtime.

2. **Patch 4** should become a call-site try/except in the strategy runner instead of a global function replacement.

3. **Patch 5** should be a connector alias map at strategy init time.

## Upgrade Preflight Checklist

Before upgrading HB version:

1. Run `scripts/release/check_hb_upgrade_readiness.py` (dry-run preflight)
2. Verify all 5 patches still apply cleanly (look for `AttributeError` in logs)
3. Run full paper smoke (bot3) + testnet smoke (bot4)
4. Run promotion gates in strict mode
5. If any patch fails, document the failure and adjust before promoting

## API Dependencies

| HB Internal | Used By | Access Pattern |
|------------|---------|----------------|
| `MarketMakingControllerBase` | `EppV24Controller` | Class extension |
| `MarketMakingControllerConfigBase` | `EppV24Config` | Class extension |
| `PositionExecutorConfig` | `get_executor_config()` | Data type import |
| `StrategyV2Base` | `v2_with_controllers.py` | Class extension |
| `ConnectorBase` | `v2_with_controllers.py` | Type annotation |
| `PriceType`, `TradeType` | Multiple files | Enum import |
| `OrderFilledEvent`, etc. | `paper_engine.py`, `epp_v2_4.py` | Event types |
| `build_trade_fee` | `paper_engine.py` | Fee estimation |
| `StopExecutorAction` | `epp_v2_4.py` | Executor lifecycle |
| `market_data_provider.time()` | `epp_v2_4.py` | Clock source |
| `connector.get_order_book()` | `epp_v2_4.py`, `paper_engine.py` | Market data |
| `connector.get_balance()` | `connector_runtime_adapter.py` | Balance reads |
| `connector.trading_rules` | Multiple | Exchange rules |
