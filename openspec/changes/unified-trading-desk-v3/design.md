## Context

The platform runs 4 bots (bot1 MM, bot5 flow-biased, bot6 CVD divergence, bot7 pullback grid) on a shared `SharedRuntimeKernel` (~13K LOC, 7 mixins). Each bot inherits the kernel and overrides 5 hook methods. The kernel handles regime detection, quoting, risk, state persistence, and order lifecycle — but bots reach into its private attributes (`_ob_imbalance`, `_regime_ema_value`, etc.) creating brittle coupling. Risk logic is split between `SupervisoryMixin` (kernel) and per-bot `_evaluate_all_risk()` overrides. Telemetry is fragmented across `_extend_processed_data_before_log()` per bot. The backtesting framework already has a clean adapter registry and protocol (`BacktestTickAdapter`) that proves the pattern works.

The platform uses Redis Streams (13 named streams) for inter-service communication, a Paper Exchange Service for virtual trading, and Docker Compose for deployment. Existing contracts are defined in `platform_lib/contracts/` with Pydantic models.

## Goals / Non-Goals

**Goals:**
- Single `TradingDesk` abstraction that all bots integrate through — owns order lifecycle, position, P&L, risk, telemetry
- Strategy code is pure signal generation with zero framework imports — testable in isolation, reusable in backtest
- Typed `KernelDataSurface` API replaces all private attribute access from bot code
- Declarative strategy registration — new strategy = 1 signal module + 1 config entry
- Layered risk enforcement at desk level (portfolio → bot → signal) — removed from strategy code
- Backtest parity — same signal function runs in production and backtest, only desk swapped
- Incremental migration — bots migrate one at a time, old/new coexist via shim

**Non-Goals:**
- Rewriting the Hummingbot connector layer or exchange adapters
- Multi-asset / cross-pair portfolio optimization (future phase)
- Changing the Redis stream topology or event bus architecture
- Modifying the Docker deployment model or adding new containers
- Replacing PriceBuffer or the indicator computation engine
- Real-time strategy hot-swap (strategies are fixed per container lifecycle)

## Decisions

### D1: Composition over inheritance — TradingDesk owns the tick loop

**Decision:** Replace mixin inheritance with a composed `TradingDesk` that orchestrates the tick loop. Strategies are injected as collaborators, not base classes.

**Current:** `SharedRuntimeKernel` inherits from `MarketMakingControllerBase` + 7 mixins. Bots inherit from the kernel and override methods. This creates a diamond inheritance tree where method resolution is fragile.

**New:** `TradingDesk` is a concrete class that holds references to:
- `StrategySignalSource` — the bot's signal generator (injected)
- `ExecutionAdapter` — translates signals to orders (selected by strategy family)
- `DeskRiskGate` — layered risk enforcement
- `KernelDataSurface` — read-only market state
- `TelemetryEmitter` — unified telemetry output

The tick loop becomes:
```
snapshot = data_surface.snapshot()       # 1. Read market state
signal = strategy.evaluate(snapshot)     # 2. Generate signal (pure)
decision = risk_gate.evaluate(signal)    # 3. Risk check
if decision.approved:
    adapter.execute(decision, snapshot)  # 4. Place orders
telemetry.emit(snapshot, signal, decision)  # 5. Log everything
```

**Why not keep mixins:** Mixins work for adding orthogonal capabilities but break down when 7 mixins share state through `self._*` attributes. The audit found bots accessing 10+ private kernel attributes — this can't be fixed with better naming; it needs an explicit API boundary.

**Alternative considered:** Keep inheritance but add `@property` accessors for all private attributes. Rejected: this would be ~100 properties, still tightly couples bots to kernel evolution, and doesn't solve the "strategy should be pure" goal.

### D2: Strategy as a pure function protocol

**Decision:** Every strategy implements `StrategySignalSource` — a protocol with one primary method:

```python
@runtime_checkable
class StrategySignalSource(Protocol):
    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal: ...
    def warmup_bars_required(self) -> int: ...
    def telemetry_schema(self) -> TelemetrySchema: ...
```

`MarketSnapshot` is a frozen dataclass containing everything a strategy needs:
- `mid`, `best_bid`, `best_ask`, `spread_pct` — L1 pricing
- `regime`, `regime_spec` — detected regime
- `indicators: IndicatorSnapshot` — EMA, ATR, RSI, ADX, BB, etc. from PriceBuffer
- `order_book: OrderBookSnapshot` — depth levels, imbalance
- `position: PositionSnapshot` — base/quote balances, net exposure
- `equity: EquitySnapshot` — equity quote, daily P&L, drawdown
- `funding_rate`, `mark_price` — perp-specific
- `trade_flow: TradeFlowSnapshot` — recent trades, CVD, absorption (for bot6/7)
- `ml_features: dict[str, Any] | None` — ML model outputs if available
- `timestamp_ms`, `config: FrozenDict` — timing and strategy config

`TradingSignal` is a typed union:
```python
@dataclass(frozen=True)
class TradingSignal:
    family: Literal["mm_grid", "directional", "hybrid", "no_trade"]
    direction: Literal["buy", "sell", "both", "off"]
    conviction: Decimal          # [0, 1]
    target_net_base_pct: Decimal # signed position target
    levels: list[SignalLevel]    # spread + size per level
    metadata: dict[str, Any]     # strategy-specific telemetry
    reason: str                  # human-readable explanation
```

**Why frozen dataclasses:** Immutability ensures strategies can't hold framework state. The snapshot is computed once per tick by `KernelDataSurface` and passed by value (cheap — Decimal fields are references).

**Why not just a function:** A protocol class allows `warmup_bars_required()` and `telemetry_schema()` — metadata the desk needs at registration time. The actual signal logic can still be a pure function called from `evaluate()`, following bot7's `pullback_signals.py` pattern.

### D3: KernelDataSurface as the single market state API

**Decision:** Create `KernelDataSurface` — a typed, read-only facade over the existing kernel state. The kernel still computes everything; the surface just provides typed access.

```python
class KernelDataSurface:
    def snapshot(self) -> MarketSnapshot: ...      # full tick snapshot
    def price_buffer(self) -> PriceBuffer: ...     # direct buffer access for warmup
    def connector_info(self) -> ConnectorInfo: ...  # exchange metadata
```

**Implementation:** Wraps `SharedRuntimeKernel` internally. Each `snapshot()` call reads current kernel state and assembles a `MarketSnapshot`. This is computed once per tick and cached.

**Why a facade, not a refactor:** The kernel works. Refactoring 13K LOC of mixins is high-risk. A facade provides the clean API boundary while the kernel can be incrementally simplified behind it.

### D4: ExecutionAdapter — family-specific signal-to-order translation

**Decision:** Three adapter implementations, selected by `TradingSignal.family`:

| Family | Adapter | Current Equivalent |
|--------|---------|-------------------|
| `mm_grid` | `MMGridExecutionAdapter` | `MarketMakingRuntimeAdapter` |
| `directional` | `DirectionalExecutionAdapter` | Per-bot `build_runtime_execution_plan()` |
| `hybrid` | `HybridExecutionAdapter` | Combo of MM + directional |

Each adapter implements:
```python
class ExecutionAdapter(Protocol):
    def translate(self, signal: TradingSignal, snapshot: MarketSnapshot) -> list[DeskOrder]: ...
    def manage_trailing(self, position: PositionSnapshot, signal: TradingSignal) -> list[DeskAction]: ...
```

`DeskOrder` is a typed instruction to the desk:
```python
@dataclass(frozen=True)
class DeskOrder:
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market"]
    price: Decimal
    amount_quote: Decimal
    level_id: str
    stop_loss: Decimal | None
    take_profit: Decimal | None
    time_limit_s: int | None
```

**Why separate from strategy:** Strategies shouldn't know about order types, stop-loss mechanics, or executor lifecycle. Bot7's pullback signal says "enter buy at BB basis with 3 legs" — the adapter translates that into 3 `DeskOrder` objects with ATR-scaled barriers.

### D5: Layered DeskRiskGate

**Decision:** Three risk layers evaluated in sequence, each can veto or modify:

```
Layer 1: PortfolioRiskGate   — cross-bot (reads PORTFOLIO_RISK_STREAM)
Layer 2: BotRiskGate          — per-bot (daily loss, drawdown, turnover, margin)
Layer 3: SignalRiskGate        — per-signal (edge gate, adverse fill, selective quoting, cooldown)
```

Each layer implements:
```python
class RiskLayer(Protocol):
    def evaluate(self, signal: TradingSignal, snapshot: MarketSnapshot) -> RiskDecision: ...
```

`RiskDecision`:
```python
@dataclass
class RiskDecision:
    approved: bool
    modified_signal: TradingSignal | None  # Layer can reduce sizing, widen spreads
    reason: str
    layer: str
    metadata: dict[str, Any]
```

**Risk flows up:** If Layer 1 rejects, Layers 2-3 don't run. If Layer 2 approves but reduces size, Layer 3 sees the reduced signal.

**Migration from current:** `SupervisoryMixin._check_portfolio_risk_guard()` → `PortfolioRiskGate`. `StateMixin._risk_loss_metrics()` → `BotRiskGate`. Per-bot `_evaluate_all_risk()` → `SignalRiskGate` (with strategy-specific config).

### D6: StrategyRegistry — declarative production registration

**Decision:** Mirror the backtesting `adapter_registry.py` pattern:

```python
STRATEGY_REGISTRY: dict[str, StrategyEntry] = {
    "bot1_baseline": StrategyEntry(
        module_path="controllers.bots.bot1.baseline_signals",
        signal_class="BaselineSignalSource",
        config_class="BaselineConfig",
        execution_family="mm_grid",
        risk_profile="conservative",
    ),
    "bot7_pullback": StrategyEntry(
        module_path="controllers.bots.bot7.pullback_signals",
        signal_class="PullbackSignalSource",
        config_class="PullbackConfig",
        execution_family="directional",
        risk_profile="moderate",
    ),
}
```

**Adding a new strategy:**
1. Create `signals.py` with `StrategySignalSource` implementation
2. Add entry to `STRATEGY_REGISTRY`
3. Write YAML config
4. Done — desk handles everything else

**Why not auto-discovery:** Explicit registration is safer for production trading. No risk of accidentally loading a test strategy. The registry is the single source of truth.

### D7: Backtest parity via desk abstraction

**Decision:** Two desk implementations:
- `LiveTradingDesk` — wraps HB connectors (production) or Paper Exchange (paper mode)
- `BacktestTradingDesk` — wraps existing `BacktestPaperDesk` from backtesting framework

Both implement the same `TradingDesk` protocol. The strategy signal module is identical in both paths:

```
Production:  YAML config → StrategyRegistry → signal_source.evaluate(live_snapshot) → LiveTradingDesk
Backtest:    YAML config → StrategyRegistry → signal_source.evaluate(replay_snapshot) → BacktestTradingDesk
```

**Alignment with existing backtest adapters:** Current `BacktestTickAdapter` adapters contain both signal logic AND order management. Under the new model, backtest adapters only need the signal module — the `BacktestTradingDesk` handles order simulation. This eliminates the adapter duplication problem.

### D8: Incremental migration via StrategyMigrationShim

**Decision:** A shim wraps existing bot controllers to produce `TradingSignal` from their current hook outputs:

```python
class StrategyMigrationShim(StrategySignalSource):
    """Wraps a legacy bot controller as a signal source."""

    def __init__(self, legacy_controller):
        self._ctrl = legacy_controller

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        # Run legacy controller tick logic
        self._ctrl._update_signal_state(snapshot)
        # Extract signal from legacy state dict
        return self._extract_signal_from_legacy_state()
```

**Migration order:**
1. Phase 1: Build `TradingDesk`, `KernelDataSurface`, `ExecutionAdapter` — all bots use shim
2. Phase 2: Migrate Bot1 (simplest — MM only, ~128 lines)
3. Phase 3: Migrate Bot7 (already has pure signal module)
4. Phase 4: Extract Bot5 signals, migrate
5. Phase 5: Extract Bot6 signals, migrate
6. Phase 6: Remove shim, legacy code, unused mixins

Each phase is independently deployable. Rollback = revert to shim.

## Risks / Trade-offs

**[Risk] MarketSnapshot becomes a god object** → Mitigate by making it a composition of typed sub-snapshots (`IndicatorSnapshot`, `OrderBookSnapshot`, etc.). Strategies only access what they need. Unused fields are lazily computed.

**[Risk] Performance regression from snapshot assembly per tick** → Mitigate by caching the snapshot within a tick (computed once, read many). PriceBuffer indicators are already O(1) incremental. The snapshot is just copying references, not data.

**[Risk] Shim introduces subtle behavior differences during migration** → Mitigate by running shim and native side-by-side in shadow mode for each bot migration. Compare signals tick-by-tick before cutover.

**[Risk] Strategy purity is hard to enforce at runtime** → Mitigate by extending `test_strategy_isolation_contract.py` to lint imports in signal modules. CI blocks any signal file that imports from `controllers.runtime`, `hummingbot`, or `services`.

**[Risk] ExecutionAdapter abstraction may not cover all edge cases (trailing stops, partial exits, grid respacing)** → Mitigate by designing `DeskAction` as extensible (typed union with `submit_order`, `cancel_order`, `modify_order`, `close_position`, `partial_reduce`). Bot7's trailing stop becomes a `manage_trailing()` call on the adapter.

**[Trade-off] Facade over refactor:** KernelDataSurface wraps the existing kernel rather than rewriting it. This means the 13K LOC kernel remains — but it's now an implementation detail behind a stable API. Refactoring can happen incrementally without breaking the surface contract.

**[Trade-off] Two registries (strategy + backtest adapter):** They converge over time as backtest adapters are replaced by signal modules + `BacktestTradingDesk`. During transition, both exist.

## Migration Plan

| Phase | Scope | Deliverable | Rollback |
|-------|-------|-------------|----------|
| 1 | Foundation | `TradingDesk` protocol, `KernelDataSurface`, `MarketSnapshot`, `TradingSignal` types, `StrategyMigrationShim` | Delete new files |
| 2 | Bot1 | Extract `baseline_signals.py`, register, run via desk | Revert to shim |
| 3 | Bot7 | Wrap existing `pullback_signals.py` in `StrategySignalSource`, register | Revert to shim |
| 4 | Bot5 | Extract `flow_signals.py` from controller, register | Revert to shim |
| 5 | Bot6 | Extract `cvd_signals.py` from controller, register | Revert to shim |
| 6 | Cleanup | Remove shim, legacy controller overrides, unused mixins | N/A (feature-complete) |

Each phase is a separate PR. Shadow-mode validation before each cutover.

## Open Questions

1. **Should `MarketSnapshot` include raw candle data or only computed indicators?** Leaning toward indicators-only (strategies shouldn't recompute), but bot6 currently fetches multi-timeframe candles directly.
2. **How does the `TradingDesk` interact with the existing Paper Exchange Service?** Options: (a) desk wraps PES client directly, (b) desk publishes to Redis and PES remains separate. Leaning toward (a) for paper mode, keeping PES as an alternative for multi-process paper testing.
3. **Should risk profiles be config-driven or code-driven?** Leaning toward config-driven (YAML risk profile per strategy) with code escape hatches for complex logic.
