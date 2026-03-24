## ADDED Requirements

### Requirement: ATR-scaled stop-loss at executor creation
The controller SHALL compute a dynamic stop-loss percentage as `pb_sl_atr_mult * ATR / mid` each tick and inject it into the `triple_barrier_config` before executor creation. The value SHALL be clamped to `[pb_sl_floor_pct, pb_sl_cap_pct]`.

#### Scenario: Normal ATR available
- **WHEN** ATR is 50 USDT, mid is 100000 USDT, `pb_sl_atr_mult` is 1.5, `pb_sl_floor_pct` is 0.003, `pb_sl_cap_pct` is 0.01
- **THEN** SL = clamp(1.5 * 50 / 100000, 0.003, 0.01) = clamp(0.00075, 0.003, 0.01) = 0.003 (floor applied)

#### Scenario: High volatility capping
- **WHEN** ATR is 2000 USDT, mid is 100000 USDT, `pb_sl_atr_mult` is 1.5
- **THEN** SL = clamp(1.5 * 2000 / 100000, 0.003, 0.01) = clamp(0.03, 0.003, 0.01) = 0.01 (cap applied)

#### Scenario: ATR unavailable during warmup
- **WHEN** PriceBuffer has fewer bars than `atr_period` and ATR returns None
- **THEN** the controller SHALL fall back to the static `config.stop_loss` value (0.0045)

### Requirement: ATR-scaled take-profit at executor creation
The controller SHALL compute a dynamic take-profit percentage as `pb_tp_atr_mult * ATR / mid` each tick, clamped to `[pb_tp_floor_pct, pb_tp_cap_pct]`, and inject it into `triple_barrier_config`.

#### Scenario: Normal ATR produces valid TP
- **WHEN** ATR is 200 USDT, mid is 100000 USDT, `pb_tp_atr_mult` is 3.0, `pb_tp_floor_pct` is 0.006, `pb_tp_cap_pct` is 0.02
- **THEN** TP = clamp(3.0 * 200 / 100000, 0.006, 0.02) = clamp(0.006, 0.006, 0.02) = 0.006

#### Scenario: TP always greater than or equal to SL
- **WHEN** ATR-scaled TP after clamping is less than ATR-scaled SL after clamping
- **THEN** TP SHALL be set to max(TP, SL * 1.5) to maintain minimum 1.5:1 reward-to-risk ratio

### Requirement: Dynamic TBC injection via config property
The controller SHALL store the dynamic `TriplBarrierConfig` on the config object such that `controller.config.triple_barrier_config` returns the ATR-adjusted version. The adapter's `get_executor_config()` at `market_making_core.py:107` SHALL pick up the dynamic values without adapter modification.

#### Scenario: Executor created with dynamic barriers
- **WHEN** a signal fires and an executor is created via the adapter
- **THEN** the executor's `triple_barrier_config.stop_loss` and `triple_barrier_config.take_profit` SHALL reflect the ATR-scaled values computed on the current tick, not the static YAML values

#### Scenario: Dynamic TBC cached per tick
- **WHEN** multiple executors are created on the same tick (multiple grid legs)
- **THEN** all executors on that tick SHALL use the same ATR-scaled SL/TP values

### Requirement: Config parameters for ATR-scaled barriers
The following config fields SHALL be added to `PullbackV1Config` with the specified defaults:

| Param | Type | Default | Description |
|---|---|---|---|
| `pb_sl_atr_mult` | Decimal | 1.5 | ATR multiplier for stop-loss |
| `pb_tp_atr_mult` | Decimal | 3.0 | ATR multiplier for take-profit |
| `pb_sl_floor_pct` | Decimal | 0.003 | Minimum stop-loss (30bps) |
| `pb_sl_cap_pct` | Decimal | 0.01 | Maximum stop-loss (100bps) |
| `pb_tp_floor_pct` | Decimal | 0.006 | Minimum take-profit (60bps) |
| `pb_tp_cap_pct` | Decimal | 0.02 | Maximum take-profit (200bps) |
| `pb_dynamic_barriers_enabled` | bool | True | Enable/disable dynamic ATR barriers |

#### Scenario: Dynamic barriers disabled
- **WHEN** `pb_dynamic_barriers_enabled` is False
- **THEN** the controller SHALL use the static `stop_loss` and `take_profit` from config (current behavior)
