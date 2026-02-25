# Paper Engine v2 — Technical Specification

**Status:** DRAFT v3 — FINAL (implementation-ready)
**Last Updated:** 2026-02-25
**Supersedes:** `controllers/paper_engine.py` (v1)
**Reference:** NautilusTrader v1.216 (`margin.pyx`, `margin_models.pyx`, `backtest/config.py`)

---

## 0. Quick Reference

| Item | Value |
|---|---|
| Target folder | `controllers/paper_engine_v2/` |
| Files | 12 (see Section 14) |
| Tests | ~97 pure-Python unit tests |
| HB imports | Isolated to `hb_bridge.py` only |
| Backward compat | `paper_engine.py` kept as thin wrapper |
| Edge gate bypass | `paper_edge_gate_bypass=True` (default) |
| Project entry point | `v2_with_controllers.py::_install_internal_paper_adapters()` |
| State persistence | Reuses `DailyStateStore` pattern (Redis + JSON) |

---

## 1. Problem Statement

The current engine (`controllers/paper_engine.py`, ~1340 lines) blocks semi-pro desk operation:

| Limitation | Root Cause | Impact |
|---|---|---|
| Zero fills | Edge gate cost model rejects quoting | Paper smoke always fails |
| 1 pair per adapter | `PaperLedger` is per-adapter, not shared | No cross-pair risk view |
| No position model | Only tracks order amounts | No avg entry, PnL, margin |
| No funding simulation | Perp positions never charged | Unrealistic perp P&L |
| 400-line monkey-patch | HB coupling is structural | Hard to maintain and test |
| Static fee model | Flat bps from config | Can't test tiered/profile fees |

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. Multi-instrument desk — N instruments across M exchanges, one shared portfolio
2. Multi-bot — all controllers share capital pool and consolidated risk
3. Exchange-agnostic — pluggable `MarketDataFeed` (HB connector, ccxt, replay)
4. Pluggable fill simulation — `FillModel` protocol with 3 built-ins
5. Pluggable fee computation — `FeeModel` protocol with 3 built-ins
6. Position tracking — avg entry, unrealized/realized PnL, funding charges
7. Margin model — spot vs perp balance accounting (leveraged margin formula)
8. Event-driven — all state changes produce typed events for audit and replay
9. Zero HB dependency in core — pure Python, testable without Docker
10. Backward compatible — existing `paper_engine.py` API preserved
11. Deterministic — same seed + same book sequence → identical fill sequence

### 2.2 Non-Goals

- Rust/C++ performance optimization (10s ticks, Python is sufficient)
- Full LOB queue simulation (L2/L3 order book priority tracking)
- Margin call / liquidation engine (warn, not liquidate)
- Historical data ingestion (handled by `scripts/backtest/` harness)

---

## 3. Architecture

### 3.1 Component Map

```
PaperDesk (desk.py)
├── PaperPortfolio (portfolio.py)
│   ├── MultiAssetLedger        balances per asset
│   ├── PositionTracker         per-instrument positions
│   ├── MarginModel             spot vs perp reserve accounting
│   └── RiskGuard               pre-trade checks
├── OrderMatchingEngine[*] (matching_engine.py)
│   ├── InstrumentSpec          exchange precision + rules
│   ├── FillModel               fill decision
│   ├── FeeModel                fee computation
│   ├── LatencyModel            inflight command queue
│   └── LiquidityTracker        optional consumption tracking
├── FundingSimulator (funding_simulator.py)
├── DeskStateStore (state_store.py)   Redis + JSON (reuses DailyStateStore)
└── MarketDataFeed[*] (data_feeds.py)  HB connector / ccxt / replay
```

### 3.2 Tick Data Flow

```
HB on_tick() → v2_with_controllers.py
    │
    ├── desk.tick(now_ns=int(time.time() * 1e9))
    │     │
    │     ├── for each engine:
    │     │     ├── feed.get_book() → OrderBookSnapshot
    │     │     ├── engine.update_book(snapshot)
    │     │     └── engine.tick(now_ns) → List[EngineEvent]
    │     │           ├── phase 1: process inflight commands
    │     │           └── phase 2: match open orders
    │     │
    │     ├── funding_simulator.tick(now_ns, portfolio, specs)
    │     ├── portfolio.mark_to_market(current_prices)
    │     └── state_store.save(snapshot, now_ts, force=False)  [throttled 30s]
    │
    └── hb_bridge: convert events → HB event types → fire on connector
```

### 3.3 Layer Map

| Layer | Files | HB Dep |
|---|---|---|
| Core domain | `types.py`, `matching_engine.py`, `portfolio.py`, `fill_models.py`, `fee_models.py`, `latency_model.py` | None |
| Simulation | `funding_simulator.py` | None |
| Orchestration | `desk.py`, `state_store.py` | None |
| Data | `data_feeds.py` | Adapter-specific |
| Bridge | `hb_bridge.py` | Yes (isolated) |

### 3.4 Concurrency Model

**Single-threaded tick-driven.** All `submit_order`, `cancel_order`, `tick` calls happen in the HB event loop thread. No locks needed.

**Exception — CCXTDataFeed:** Daemon thread with `queue.Queue(maxsize=1)` per instrument. `get_book()` does `queue.get_nowait()` (non-blocking, returns None on empty). Thread dies with the process.

---

## 4. Core Domain Types

File: `controllers/paper_engine_v2/types.py`

### 4.1 InstrumentId

```python
@dataclass(frozen=True)
class InstrumentId:
    venue: str            # "bitget" | "binance" | "bybit" | "okx"
    trading_pair: str     # "BTC-USDT"
    instrument_type: str  # "spot" | "perp" | "future"

    @property
    def base_asset(self) -> str:
        return self.trading_pair.split("-")[0]

    @property
    def quote_asset(self) -> str:
        parts = self.trading_pair.split("-")
        return parts[1] if len(parts) > 1 else "USDT"

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.trading_pair}:{self.instrument_type}"

    @property
    def is_perp(self) -> bool:
        return self.instrument_type == "perp"
```

### 4.2 InstrumentSpec

Mirrors Nautilus `Instrument` fields. Carries both exchange precision rules and
the margin init/maint ratios used by the LeveragedMarginModel.

```python
@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: InstrumentId
    # Precision
    price_precision: int          # decimal places (e.g. 2)
    size_precision: int           # decimal places (e.g. 4)
    price_increment: Decimal      # min tick (e.g. 0.01)
    size_increment: Decimal       # min lot (e.g. 0.0001)
    # Order limits
    min_quantity: Decimal
    min_notional: Decimal         # min order value in quote
    max_quantity: Decimal
    # Fees (defaults; overridden by FeeModel)
    maker_fee_rate: Decimal       # e.g. 0.0002
    taker_fee_rate: Decimal       # e.g. 0.0006
    # Margin (perps only; 0 for spot)
    margin_init: Decimal          # initial margin ratio (e.g. 0.10 for 10x)
    margin_maint: Decimal         # maintenance margin ratio (e.g. 0.05)
    leverage_max: int             # max leverage allowed (e.g. 20)
    # Funding (perps only; 0 for spot)
    funding_interval_s: int       # 28800 = 8h; 0 = no funding

    # --- Quantization ---

    def quantize_price(self, price: Decimal, side: str) -> Decimal:
        """Round price to valid tick. BUY rounds down, SELL rounds up."""
        if self.price_increment <= 0:
            return price
        rounding = ROUND_DOWN if side == "buy" else ROUND_UP
        steps = (price / self.price_increment).to_integral_value(rounding=rounding)
        return max(self.price_increment, steps * self.price_increment)

    def quantize_size(self, size: Decimal) -> Decimal:
        """Round size down to valid lot."""
        if self.size_increment <= 0:
            return size
        steps = (size / self.size_increment).to_integral_value(rounding=ROUND_DOWN)
        return max(self.min_quantity, steps * self.size_increment)

    def validate_order(self, price: Decimal, quantity: Decimal) -> Optional[str]:
        """Return rejection reason string or None if valid."""
        if quantity < self.min_quantity:
            return f"qty {quantity} < min {self.min_quantity}"
        if quantity > self.max_quantity:
            return f"qty {quantity} > max {self.max_quantity}"
        if price * quantity < self.min_notional:
            return f"notional {price * quantity} < min {self.min_notional}"
        return None

    # --- Margin (LeveragedMarginModel — Nautilus default) ---

    def compute_margin_init(self, quantity: Decimal, price: Decimal, leverage: int) -> Decimal:
        """Initial margin = (notional / leverage) * margin_init_ratio."""
        if not self.instrument_id.is_perp or leverage <= 0:
            return Decimal("0")
        notional = quantity * price
        return (notional / Decimal(leverage)) * self.margin_init

    def compute_margin_maint(self, quantity: Decimal, price: Decimal, leverage: int) -> Decimal:
        """Maintenance margin = (notional / leverage) * margin_maint_ratio."""
        if not self.instrument_id.is_perp or leverage <= 0:
            return Decimal("0")
        notional = quantity * price
        return (notional / Decimal(leverage)) * self.margin_maint

    # --- Factory methods ---

    @classmethod
    def from_hb_trading_rule(
        cls,
        instrument_id: InstrumentId,
        rule: Any,
        fee_profile: Optional[Dict[str, str]] = None,
    ) -> "InstrumentSpec":
        """Build from HB connector trading_rules dict entry."""
        def _d(attr, default="0") -> Decimal:
            return Decimal(str(getattr(rule, attr, default) or default))

        maker = Decimal(fee_profile["maker"]) if fee_profile else Decimal("0.0002")
        taker = Decimal(fee_profile["taker"]) if fee_profile else Decimal("0.0006")
        return cls(
            instrument_id=instrument_id,
            price_precision=int(getattr(rule, "price_precision", 2)),
            size_precision=int(getattr(rule, "quantity_precision", 4)),
            price_increment=_d("min_price_increment") or _d("min_price_tick_size") or Decimal("0.01"),
            size_increment=_d("min_base_amount_increment") or _d("min_order_size_increment") or Decimal("0.0001"),
            min_quantity=_d("min_order_size") or _d("min_base_amount"),
            min_notional=_d("min_notional_size") or _d("min_notional"),
            max_quantity=_d("max_order_size") or Decimal("1000000"),
            maker_fee_rate=maker,
            taker_fee_rate=taker,
            margin_init=Decimal("0.10"),   # default 10x max
            margin_maint=Decimal("0.05"),  # default 5%
            leverage_max=20,
            funding_interval_s=28800 if instrument_id.is_perp else 0,
        )

    @classmethod
    def spot_usdt(cls, venue: str, pair: str) -> "InstrumentSpec":
        """Convenience factory for a generic USDT spot instrument."""
        return cls(
            instrument_id=InstrumentId(venue=venue, trading_pair=pair, instrument_type="spot"),
            price_precision=2, size_precision=4,
            price_increment=Decimal("0.01"), size_increment=Decimal("0.0001"),
            min_quantity=Decimal("0.0001"), min_notional=Decimal("1"),
            max_quantity=Decimal("10000"),
            maker_fee_rate=Decimal("0.001"), taker_fee_rate=Decimal("0.001"),
            margin_init=Decimal("0"), margin_maint=Decimal("0"),
            leverage_max=1, funding_interval_s=0,
        )
```

### 4.3 Order Types

```python
class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class PaperOrderType(str, Enum):
    LIMIT = "limit"
    LIMIT_MAKER = "limit_maker"
    MARKET = "market"

class OrderStatus(str, Enum):
    PENDING_SUBMIT = "pending_submit"  # in latency queue
    OPEN = "open"
    PARTIALLY_FILLED = "partial"
    FILLED = "filled"                  # terminal
    CANCELED = "canceled"              # terminal
    REJECTED = "rejected"              # terminal

@dataclass
class PaperOrder:
    order_id: str
    instrument_id: InstrumentId
    side: OrderSide
    order_type: PaperOrderType
    price: Decimal                    # quantized at submit time
    quantity: Decimal                 # quantized at submit time
    status: OrderStatus
    created_at_ns: int
    updated_at_ns: int
    filled_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    filled_notional: Decimal = field(default_factory=lambda: Decimal("0"))
    cumulative_fee: Decimal = field(default_factory=lambda: Decimal("0"))
    fill_count: int = 0
    max_fills: int = 8
    crossed_at_creation: bool = False
    source_bot: str = ""
    reject_reason: str = ""

    @property
    def remaining_quantity(self) -> Decimal:
        return max(Decimal("0"), self.quantity - self.filled_quantity)

    @property
    def avg_fill_price(self) -> Decimal:
        if self.filled_quantity <= Decimal("0"):
            return self.price
        return self.filled_notional / self.filled_quantity

    @property
    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)
```

### 4.4 Position

PnL fields follow Nautilus convention: `realized_pnl` is **pure price PnL only**
(no fees). Fees are tracked separately in `total_fees_paid`. Net PnL is
`realized_pnl - total_fees_paid - funding_paid`.

```python
@dataclass
class PaperPosition:
    instrument_id: InstrumentId
    quantity: Decimal               # signed: >0 long, <0 short, 0 flat
    avg_entry_price: Decimal
    realized_pnl: Decimal           # pure price PnL — does NOT include fees
    unrealized_pnl: Decimal         # mark-to-market, updated on tick
    total_fees_paid: Decimal        # cumulative fees (tracked separately)
    funding_paid: Decimal           # cumulative funding (perps only)
    opened_at_ns: int
    last_fill_at_ns: int

    @property
    def side(self) -> str:
        if self.quantity > 0: return "long"
        if self.quantity < 0: return "short"
        return "flat"

    @property
    def abs_quantity(self) -> Decimal:
        return abs(self.quantity)

    @property
    def net_pnl(self) -> Decimal:
        """Total PnL: realized + unrealized - fees - funding."""
        return self.realized_pnl + self.unrealized_pnl - self.total_fees_paid - self.funding_paid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.key,
            "quantity": str(self.quantity),
            "avg_entry_price": str(self.avg_entry_price),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "total_fees_paid": str(self.total_fees_paid),
            "funding_paid": str(self.funding_paid),
            "opened_at_ns": self.opened_at_ns,
            "last_fill_at_ns": self.last_fill_at_ns,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], instrument_id: InstrumentId) -> "PaperPosition":
        return cls(
            instrument_id=instrument_id,
            quantity=Decimal(d["quantity"]),
            avg_entry_price=Decimal(d["avg_entry_price"]),
            realized_pnl=Decimal(d["realized_pnl"]),
            unrealized_pnl=Decimal(d["unrealized_pnl"]),
            total_fees_paid=Decimal(d["total_fees_paid"]),
            funding_paid=Decimal(d["funding_paid"]),
            opened_at_ns=int(d["opened_at_ns"]),
            last_fill_at_ns=int(d["last_fill_at_ns"]),
        )

    @classmethod
    def flat(cls, instrument_id: InstrumentId) -> "PaperPosition":
        z = Decimal("0")
        return cls(instrument_id=instrument_id, quantity=z, avg_entry_price=z,
                   realized_pnl=z, unrealized_pnl=z, total_fees_paid=z,
                   funding_paid=z, opened_at_ns=0, last_fill_at_ns=0)
```

### 4.5 OrderBookSnapshot

```python
@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal

@dataclass(frozen=True)
class OrderBookSnapshot:
    instrument_id: InstrumentId
    bids: Tuple[BookLevel, ...]    # best (highest price) first
    asks: Tuple[BookLevel, ...]    # best (lowest price) first
    timestamp_ns: int

    @property
    def best_bid(self) -> Optional[BookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[BookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        bb, ba = self.best_bid, self.best_ask
        return (bb.price + ba.price) / Decimal("2") if bb and ba else None

    @property
    def spread_pct(self) -> Optional[Decimal]:
        mid = self.mid_price
        bb, ba = self.best_bid, self.best_ask
        if mid and bb and ba and mid > 0:
            return (ba.price - bb.price) / mid
        return None
```

### 4.6 Events

All events are frozen dataclasses. `to_dict()` uses `dataclasses.asdict()` with
a custom encoder for Decimal and InstrumentId so they serialize to JSON for Redis.

```python
@dataclass(frozen=True)
class EngineEvent:
    event_id: str                  # UUID4 string
    timestamp_ns: int
    instrument_id: InstrumentId

    def to_dict(self) -> Dict[str, Any]:
        import dataclasses
        def _enc(v):
            if isinstance(v, Decimal): return str(v)
            if isinstance(v, InstrumentId): return v.key
            return v
        return {k: _enc(v) for k, v in dataclasses.asdict(self).items()}

@dataclass(frozen=True)
class OrderAccepted(EngineEvent):
    order_id: str
    side: str
    order_type: str
    price: Decimal
    quantity: Decimal
    source_bot: str

@dataclass(frozen=True)
class OrderRejected(EngineEvent):
    order_id: str
    reason: str
    source_bot: str

@dataclass(frozen=True)
class OrderFilled(EngineEvent):
    order_id: str
    fill_price: Decimal
    fill_quantity: Decimal
    fee: Decimal                   # fees tracked separately from PnL
    is_maker: bool
    remaining_quantity: Decimal
    source_bot: str

@dataclass(frozen=True)
class OrderCanceled(EngineEvent):
    order_id: str
    source_bot: str

@dataclass(frozen=True)
class PositionChanged(EngineEvent):
    position: PaperPosition
    trigger_order_id: str
    trigger_side: str
    fill_price: Decimal
    fill_quantity: Decimal
    realized_pnl: Decimal          # pure price PnL for this fill (no fees)

@dataclass(frozen=True)
class FundingApplied(EngineEvent):
    funding_rate: Decimal
    charge_quote: Decimal
    position_notional: Decimal

@dataclass(frozen=True)
class EngineError(EngineEvent):
    error_type: str
    message: str
```

---

## 5. OrderMatchingEngine

File: `controllers/paper_engine_v2/matching_engine.py`

### 5.1 Configuration

```python
@dataclass
class EngineConfig:
    latency_ms: int = 150              # min ms between consecutive fills on same order
    max_fills_per_order: int = 8
    max_open_orders: int = 50          # per-instrument
    reject_crossed_maker: bool = True  # reject LIMIT_MAKER crossing the spread
    prune_terminal_after_s: float = 60.0
    liquidity_consumption: bool = False  # track consumed depth per tick (Nautilus option)
```

### 5.2 Interface

```python
class OrderMatchingEngine:
    def __init__(
        self,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        portfolio: "PaperPortfolio",
        fill_model: "FillModel",
        fee_model: "FeeModel",
        latency_model: "LatencyModel",
        config: EngineConfig,
    ): ...

    # Never raises — returns typed event (including OrderRejected / EngineError)
    def submit_order(self, order: PaperOrder, now_ns: int) -> EngineEvent: ...
    def cancel_order(self, order_id: str, now_ns: int) -> Optional[EngineEvent]: ...
    def cancel_all(self, now_ns: int) -> List[EngineEvent]: ...
    def update_book(self, snapshot: OrderBookSnapshot) -> None: ...
    def tick(self, now_ns: int) -> List[EngineEvent]: ...
    def open_orders(self) -> List[PaperOrder]: ...
    def get_order(self, order_id: str) -> Optional[PaperOrder]: ...
```

### 5.3 `_compute_reserve(order)` — spot vs perp

**This is the critical split identified in the Nautilus source review:**

```python
def _compute_reserve(self, order: PaperOrder) -> Tuple[str, Decimal]:
    spec = self._spec
    iid = spec.instrument_id

    if iid.is_perp:
        # Perp: margin-based reserve = (notional / leverage) * margin_init_ratio
        # Following Nautilus LeveragedMarginModel: balance_impact = notional / leverage
        leverage = self._leverage  # set from DeskConfig or PortfolioConfig
        margin = spec.compute_margin_init(order.quantity, order.price, leverage)
        return (iid.quote_asset, margin)
    else:
        # Spot BUY: reserve full quote notional
        if order.side == OrderSide.BUY:
            return (iid.quote_asset, order.quantity * order.price)
        # Spot SELL: reserve base asset
        else:
            return (iid.base_asset, order.quantity)
```

### 5.4 `submit_order` pseudocode

```python
def submit_order(self, order: PaperOrder, now_ns: int) -> EngineEvent:
    try:
        # 1. Quantize
        order.price = self._spec.quantize_price(order.price, order.side.value)
        order.quantity = self._spec.quantize_size(order.quantity)

        # 2. Spec validation
        reject = self._spec.validate_order(order.price, order.quantity)
        if reject:
            return self._reject(order, reject)

        # 3. LIMIT_MAKER cross check
        if order.order_type == PaperOrderType.LIMIT_MAKER and self._book:
            if self._would_cross(order):
                if self._config.reject_crossed_maker:
                    return self._reject(order, "limit_maker_would_cross")
                order.crossed_at_creation = True

        # 4. Reserve check
        asset, amount = self._compute_reserve(order)
        if not self._portfolio.can_reserve(asset, amount):
            return self._reject(order, "insufficient_balance")

        # 5. Risk guard
        reason = self._portfolio.risk_guard.check_order(
            order, self._spec, self._book.mid_price if self._book else order.price
        )
        if reason:
            return self._reject(order, reason)

        # 6. Accept
        self._portfolio.reserve(asset, amount)
        order._reserved_asset = asset
        order._reserved_amount = amount

        if self._latency_model.total_insert_ns > 0:
            order.status = OrderStatus.PENDING_SUBMIT
            self._inflight.append((now_ns + self._latency_model.total_insert_ns, "accept", order))
        else:
            order.status = OrderStatus.OPEN
            self._orders[order.order_id] = order

        return OrderAccepted(event_id=uuid4_str(), timestamp_ns=now_ns,
                             instrument_id=self._spec.instrument_id,
                             order_id=order.order_id, side=order.side.value,
                             order_type=order.order_type.value,
                             price=order.price, quantity=order.quantity,
                             source_bot=order.source_bot)
    except Exception as exc:
        logger.error("submit_order failed: %s", exc, exc_info=True)
        return EngineError(event_id=uuid4_str(), timestamp_ns=now_ns,
                           instrument_id=self._spec.instrument_id,
                           error_type=type(exc).__name__, message=str(exc))
```

### 5.5 `tick` pseudocode

```python
def tick(self, now_ns: int) -> List[EngineEvent]:
    events: List[EngineEvent] = []
    try:
        # Phase 1: inflight commands due now
        still_inflight = []
        for (due_ns, action, order) in self._inflight:
            if due_ns <= now_ns:
                if action == "accept":
                    order.status = OrderStatus.OPEN
                    self._orders[order.order_id] = order
                    events.append(OrderAccepted(...))
            else:
                still_inflight.append((due_ns, action, order))
        self._inflight = still_inflight

        # Phase 2: match open orders
        if self._book is None:
            return events

        if self._config.liquidity_consumption:
            self._consumed.clear()

        for order in list(self._orders.values()):
            if order.is_terminal:
                continue
            if order.fill_count >= self._config.max_fills_per_order:
                continue
            last_fill_ns = self._last_fill_ns.get(order.order_id, 0)
            if last_fill_ns > 0 and (now_ns - last_fill_ns) < self._config.latency_ms * 1_000_000:
                continue

            decision = self._fill_model.evaluate(order, self._book, now_ns)
            if decision.fill_quantity <= 0:
                continue

            # Track consumed liquidity (Nautilus liquidity_consumption option)
            if self._config.liquidity_consumption:
                level_price = decision.fill_price
                self._consumed[level_price] = self._consumed.get(level_price, Decimal("0")) + decision.fill_quantity

            fill_notional = decision.fill_quantity * decision.fill_price
            fee = self._fee_model.compute(fill_notional, decision.is_maker)

            pos_event = self._portfolio.settle_fill(
                instrument_id=self._spec.instrument_id,
                side=order.side, quantity=decision.fill_quantity,
                price=decision.fill_price, fee=fee,
                source_bot=order.source_bot, now_ns=now_ns,
                spec=self._spec, leverage=self._leverage,
            )

            order.filled_quantity += decision.fill_quantity
            order.filled_notional += fill_notional
            order.cumulative_fee += fee
            order.fill_count += 1
            order.updated_at_ns = now_ns
            self._last_fill_ns[order.order_id] = now_ns

            if order.remaining_quantity <= self._spec.size_increment:
                order.status = OrderStatus.FILLED
                self._portfolio.release(order._reserved_asset, order._reserved_amount)
                del self._orders[order.order_id]
            else:
                order.status = OrderStatus.PARTIALLY_FILLED

            events.append(OrderFilled(
                event_id=uuid4_str(), timestamp_ns=now_ns,
                instrument_id=self._spec.instrument_id,
                order_id=order.order_id,
                fill_price=decision.fill_price,
                fill_quantity=decision.fill_quantity,
                fee=fee, is_maker=decision.is_maker,
                remaining_quantity=order.remaining_quantity,
                source_bot=order.source_bot,
            ))
            events.append(pos_event)

        # Phase 3: prune done orders
        self._prune_terminal(now_ns)
    except Exception as exc:
        logger.error("engine.tick failed: %s", exc, exc_info=True)
        events.append(EngineError(event_id=uuid4_str(), timestamp_ns=now_ns,
                                  instrument_id=self._spec.instrument_id,
                                  error_type=type(exc).__name__, message=str(exc)))
    return events
```

---

## 6. FillModel

File: `controllers/paper_engine_v2/fill_models.py`

### 6.1 Protocol + FillDecision

```python
@dataclass(frozen=True)
class FillDecision:
    fill_quantity: Decimal
    fill_price: Decimal
    is_maker: bool
    queue_delay_ms: int

class FillModel(Protocol):
    def evaluate(self, order: PaperOrder, book: OrderBookSnapshot, now_ns: int) -> FillDecision: ...
```

### 6.2 QueuePositionFillModel (default)

Config:
```python
@dataclass
class QueuePositionConfig:
    queue_participation: Decimal = Decimal("0.35")
    min_partial_fill_ratio: Decimal = Decimal("0.15")
    max_partial_fill_ratio: Decimal = Decimal("0.85")
    slippage_bps: Decimal = Decimal("1.0")
    adverse_selection_bps: Decimal = Decimal("1.5")
    prob_fill_on_limit: float = 1.0    # Nautilus: probability of fill at touched limit
    prob_slippage: float = 0.0         # Nautilus: probability of 1-tick additional slippage
    queue_jitter_pct: float = 0.20
    seed: int = 7
```

Behavior (full algorithm):

1. If book is empty or `remaining_quantity <= 0`: return `qty=0`.

2. Determine touchability:
   - BUY is touchable: `best_ask.price <= order.price`
   - SELL is touchable: `best_bid.price >= order.price`

3. **LIMIT_MAKER (passive, not crossed at creation):**
   - If NOT touchable: partial passive fill
     - `qf = queue_participation * rng.uniform(1 - jitter, 1 + jitter)`
     - `pr = rng.uniform(min_ratio, max_ratio)`
     - `qty = min(remaining, best_bid.size * qf, remaining * pr)`
     - `price = order.price`, `is_maker = True`, `delay = latency_ms * 1.5`
   - If touchable: apply `prob_fill_on_limit` miss check
     - If `rng.random() > prob_fill_on_limit`: return `qty=0` (queue miss)
     - Else: same partial fill logic, `price = order.price`, `is_maker = True`

4. **Resting LIMIT (not crossed at creation):**
   - If NOT touchable: return `qty=0`
   - If touchable: apply `prob_fill_on_limit`, then partial fill same as above

5. **Taker (crossed at creation or MARKET):**
   - `qty = min(remaining, best_ask/bid.size * qf)` (use ask for BUY, bid for SELL)
   - `slippage = (slippage_bps + adverse_selection_bps) / 10000`
   - BUY: `price = best_ask.price * (1 + slippage)`
   - SELL: `price = best_bid.price * (1 - slippage)`
   - If `rng.random() < prob_slippage`: add 1 more tick of slippage
   - `is_maker = False`, `delay = latency_ms`

6. Return `FillDecision(fill_quantity=max(0, qty), fill_price=price, ...)`

### 6.3 TopOfBookFillModel (smoke tests only)

Fills entire remaining quantity instantly at best ask (buy) or best bid (sell). `is_maker=False`. Only valid for structural validation — not PnL benchmarking.

### 6.4 LatencyAwareFillModel (most realistic)

Extends QueuePositionFillModel with:
- `depth_participation_pct`: cap `fill_qty` at `depth_at_level * pct`
- Post-fill drift metric stored in event metadata (not applied to fill price)

### 6.5 Test Vectors

Fixed parameters: `seed=7`, `queue_participation=0.35`, `jitter=0.20`,
`min_ratio=0.15`, `max_ratio=0.85`, `slippage_bps=1.0`, `adverse_selection_bps=1.5`.

```
V1 — Passive maker not touched (LIMIT_MAKER @ 99.95, asks=[100.05], bids=[100.00,5.0])
  Expected: partial fill, fill_price=99.95, is_maker=True
  Concrete with seed=7: rng gives jitter=0.12, pr=0.48
    qf = 0.35 * 1.12 = 0.392; qty = min(2.0, 5.0*0.392, 2.0*0.48) = min(2.0, 1.96, 0.96) = 0.96

V2 — Resting limit touched (BUY LIMIT @ 99.95, asks=[99.90,3.0], crossed_at_creation=False)
  Expected: fill_price=99.95, is_maker=True, prob_fill_on_limit=1.0 → always fills

V3 — Taker cross (BUY LIMIT @ 100.10, asks=[100.05,3.0], crossed_at_creation=True)
  Expected: fill_price = 100.05 * (1 + 0.00025) = 100.0750125, is_maker=False

V4 — No fill (BUY LIMIT @ 99.50, asks=[100.05], bids=[100.00])
  Expected: fill_qty=0 (order price not reached)

V5 — TopOfBook (BUY MARKET, asks=[100.05,5.0])
  Expected: fill_qty=remaining, fill_price=100.05, is_maker=False

V6 — Position flip (test_portfolio.py)
  open long 1.0 @ 100, then sell 2.0 @ 105 (close 1.0 long + open 1.0 short)
  Expected: realized_pnl = (105 - 100) * 1.0 = 5.0 (NO fee subtracted)
           position.quantity = -1.0, avg_entry_price = 105.0
```

---

## 7. FeeModel

File: `controllers/paper_engine_v2/fee_models.py`

```python
class FeeModel(Protocol):
    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        """Return fee in quote asset. Does NOT affect PnL directly."""
        ...
```

**MakerTakerFeeModel** — from `InstrumentSpec` rates (default).
**TieredFeeModel** — reads from `config/fee_profiles.json`, resolves by `(venue, profile)`.
**FixedFeeModel** — flat commission regardless of notional.

```python
class TieredFeeModel:
    def __init__(self, venue: str, profile: str = "vip0",
                 profiles_path: str = "config/fee_profiles.json"):
        import json, pathlib
        data = json.loads(pathlib.Path(profiles_path).read_text())
        rates = data["profiles"][profile][venue]
        self._maker = Decimal(rates["maker"])
        self._taker = Decimal(rates["taker"])

    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        return notional * (self._maker if is_maker else self._taker)
```

---

## 8. LatencyModel

File: `controllers/paper_engine_v2/latency_model.py`

Following Nautilus `LatencyModelConfig` (nanosecond-precision, per-command-type):

```python
@dataclass(frozen=True)
class LatencyModel:
    base_latency_ns: int = 0
    insert_latency_ns: int = 0
    cancel_latency_ns: int = 0

    @property
    def total_insert_ns(self) -> int:
        return self.base_latency_ns + self.insert_latency_ns

    @property
    def total_cancel_ns(self) -> int:
        return self.base_latency_ns + self.cancel_latency_ns

NO_LATENCY = LatencyModel()
FAST_LATENCY = LatencyModel(base_latency_ns=50_000_000)        # 50ms
REALISTIC_LATENCY = LatencyModel(
    base_latency_ns=100_000_000,
    insert_latency_ns=50_000_000,
    cancel_latency_ns=30_000_000,
)
```

---

## 9. PaperPortfolio

File: `controllers/paper_engine_v2/portfolio.py`

### 9.1 Configuration

```python
@dataclass
class PortfolioConfig:
    max_position_notional_per_instrument: Decimal = Decimal("10000")
    max_net_exposure_quote: Decimal = Decimal("50000")
    max_drawdown_pct_hard: Decimal = Decimal("0.10")
    default_leverage: int = 1
    leverage_max: int = 20
    margin_ratio_warn_pct: Decimal = Decimal("0.20")
    margin_ratio_critical_pct: Decimal = Decimal("0.10")
```

### 9.2 `settle_fill` — Corrected Accounting (Nautilus-aligned)

**Key fix from Nautilus source review:** Realized PnL is pure price PnL only.
Fee is deducted from the ledger separately. Position.realized_pnl never includes fee.

```python
def settle_fill(
    self,
    instrument_id: InstrumentId,
    side: OrderSide,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
    source_bot: str,
    now_ns: int,
    spec: InstrumentSpec,
    leverage: int,
) -> PositionChanged:
    pos = self._positions.get(instrument_id.key) or PaperPosition.flat(instrument_id)

    fill_signed = +quantity if side == OrderSide.BUY else -quantity
    old_qty = pos.quantity
    new_qty = old_qty + fill_signed
    realized_pnl = Decimal("0")

    is_closing = (old_qty > 0 and fill_signed < 0) or (old_qty < 0 and fill_signed > 0)

    if is_closing and old_qty != 0:
        # close_qty = min of fill and existing position (Nautilus: avoid double-counting on flip)
        close_qty = min(abs(fill_signed), abs(old_qty))
        direction = Decimal("1") if old_qty > 0 else Decimal("-1")
        # PURE price PnL — no fee deduction (Nautilus convention)
        realized_pnl = (price - pos.avg_entry_price) * close_qty * direction

        if new_qty != 0 and (new_qty > 0) != (old_qty > 0):
            # Position flip: new side opens at fill price
            remaining_open = abs(new_qty)
            pos.avg_entry_price = price
        # else: partial close, avg_entry unchanged
    else:
        # Opening or adding
        if abs(old_qty) > 0:
            old_cost = abs(old_qty) * pos.avg_entry_price
            new_cost = quantity * price
            pos.avg_entry_price = (old_cost + new_cost) / abs(new_qty)
        else:
            pos.avg_entry_price = price

    pos.quantity = new_qty
    pos.realized_pnl += realized_pnl
    pos.total_fees_paid += fee            # fees tracked separately
    pos.last_fill_at_ns = now_ns
    if pos.opened_at_ns == 0:
        pos.opened_at_ns = now_ns

    # --- Ledger settlement ---
    quote = instrument_id.quote_asset
    base = instrument_id.base_asset

    if instrument_id.is_perp:
        # Perp: debit margin deposit for open, credit margin return for close
        # Fee always debited from quote
        self._ledger.debit(quote, fee)   # fee always comes out
        if is_closing:
            # Return realized PnL to balance (can be negative)
            if realized_pnl > 0:
                self._ledger.credit(quote, realized_pnl)
            else:
                self._ledger.debit(quote, abs(realized_pnl))
    else:
        # Spot: full notional exchange
        if side == OrderSide.BUY:
            self._ledger.debit(quote, quantity * price + fee)
            self._ledger.credit(base, quantity)
        else:
            self._ledger.debit(base, quantity)
            self._ledger.credit(quote, quantity * price - fee)

    self._positions[instrument_id.key] = pos
    return PositionChanged(
        event_id=uuid4_str(), timestamp_ns=now_ns,
        instrument_id=instrument_id,
        position=pos,
        trigger_order_id="",
        trigger_side=side.value,
        fill_price=price,
        fill_quantity=quantity,
        realized_pnl=realized_pnl,
    )
```

### 9.3 MultiAssetLedger

```python
class MultiAssetLedger:
    def __init__(self, initial_balances: Dict[str, Decimal]):
        self._balances: Dict[str, Decimal] = dict(initial_balances)
        self._reserved: Dict[str, Decimal] = {}

    def total(self, asset: str) -> Decimal:
        return self._balances.get(asset, Decimal("0"))

    def available(self, asset: str) -> Decimal:
        # Clamp to zero (Nautilus: never negative available, graceful degradation)
        raw = self.total(asset) - self._reserved.get(asset, Decimal("0"))
        return max(Decimal("0"), raw)

    def can_reserve(self, asset: str, amount: Decimal) -> bool:
        return self.available(asset) >= amount - Decimal("1e-10")

    def reserve(self, asset: str, amount: Decimal) -> None:
        self._reserved[asset] = self._reserved.get(asset, Decimal("0")) + amount

    def release(self, asset: str, amount: Decimal) -> None:
        curr = self._reserved.get(asset, Decimal("0"))
        self._reserved[asset] = max(Decimal("0"), curr - amount)

    def credit(self, asset: str, amount: Decimal) -> None:
        self._balances[asset] = self.total(asset) + max(Decimal("0"), amount)

    def debit(self, asset: str, amount: Decimal) -> None:
        self._balances[asset] = self.total(asset) - max(Decimal("0"), amount)

    def to_dict(self) -> Dict[str, str]:
        return {k: str(v) for k, v in self._balances.items()}
```

### 9.4 RiskGuard

```python
class RiskGuard:
    def __init__(self, config: PortfolioConfig, portfolio: "PaperPortfolio"): ...

    def check_order(self, order: PaperOrder, spec: InstrumentSpec, mid_price: Decimal) -> Optional[str]:
        pos = self._portfolio.get_position(spec.instrument_id)
        new_notional = (abs(pos.quantity) + order.quantity) * mid_price
        if new_notional > self._config.max_position_notional_per_instrument:
            return f"position_notional_cap: {new_notional} > {self._config.max_position_notional_per_instrument}"
        if self._portfolio.drawdown_pct() > self._config.max_drawdown_pct_hard:
            return "drawdown_hard_stop"
        return None
```

---

## 10. FundingSimulator

File: `controllers/paper_engine_v2/funding_simulator.py`

Following Nautilus `SimulationModule` / `FXRolloverInterestConfig` pattern:

```python
class FundingSimulator:
    """Applies periodic funding to open perp positions."""

    def __init__(self):
        self._last_funding_ns: Dict[str, int] = {}

    def tick(
        self,
        now_ns: int,
        portfolio: "PaperPortfolio",
        instruments: Dict[str, Tuple[InstrumentSpec, Decimal]],  # key → (spec, funding_rate)
    ) -> List[FundingApplied]:
        events = []
        for key, (spec, funding_rate) in instruments.items():
            if not spec.instrument_id.is_perp or spec.funding_interval_s <= 0:
                continue
            interval_ns = spec.funding_interval_s * 1_000_000_000
            last_ns = self._last_funding_ns.get(key, 0)
            if last_ns > 0 and (now_ns - last_ns) < interval_ns:
                continue
            self._last_funding_ns[key] = now_ns
            pos = portfolio.get_position(spec.instrument_id)
            if pos.abs_quantity <= 0:
                continue
            notional = pos.abs_quantity * pos.avg_entry_price
            charge = abs(funding_rate) * notional  # long pays positive rate, short receives
            event = portfolio.apply_funding(spec.instrument_id, charge, now_ns)
            events.append(event)
        return events
```

---

## 11. MarketDataFeed

File: `controllers/paper_engine_v2/data_feeds.py`

```python
class MarketDataFeed(Protocol):
    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]: ...
    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]: ...
    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal: ...
```

**HummingbotDataFeed** — reads from HB connector's `get_order_book()` and `get_price_by_type()`. Converts HB OrderBookEntry → BookLevel. Used inside HB paper mode. Funding rate from `connector.funding_rates` dict.

**CCXTDataFeed** — ccxt.pro websocket in daemon thread, `queue.Queue(maxsize=1)` per instrument.

**ReplayDataFeed** — reads `market_snapshot` events from JSONL event store. Deterministic regression testing.

---

## 12. PaperDesk

File: `controllers/paper_engine_v2/desk.py`

### 12.1 Config

```python
@dataclass
class DeskConfig:
    initial_balances: Dict[str, Decimal]   # {"USDT": Decimal("10000")}
    portfolio_config: PortfolioConfig = field(default_factory=PortfolioConfig)
    default_fill_model: str = "queue_position"  # "queue_position"|"top_of_book"|"latency_aware"
    default_fee_source: str = "instrument_spec"  # "instrument_spec"|"fee_profiles"
    default_fee_profile: str = "vip0"
    default_latency_model: str = "none"          # "none"|"fast"|"realistic"
    default_engine_config: EngineConfig = field(default_factory=EngineConfig)
    state_file_path: str = "/tmp/paper_desk_state.json"
    redis_key: str = "paper_desk:v2:state"
    redis_url: Optional[str] = None
    event_log_max_size: int = 100_000
    seed: int = 7
```

### 12.2 Interface

```python
class PaperDesk:
    def __init__(self, config: DeskConfig): ...
    def register_instrument(self, spec: InstrumentSpec, feed: MarketDataFeed,
                            fill_model=None, fee_model=None,
                            latency_model=None, engine_config=None) -> None: ...
    def submit_order(self, instrument_id: InstrumentId, side: OrderSide,
                     order_type: PaperOrderType, price: Decimal,
                     quantity: Decimal, source_bot: str = "") -> EngineEvent: ...
    def cancel_order(self, instrument_id: InstrumentId, order_id: str) -> Optional[EngineEvent]: ...
    def cancel_all(self, instrument_id: Optional[InstrumentId] = None) -> List[EngineEvent]: ...
    def tick(self, now_ns: int) -> List[EngineEvent]: ...
    @property
    def portfolio(self) -> PaperPortfolio: ...
    def snapshot(self) -> Dict[str, Any]: ...
    def event_log(self) -> List[EngineEvent]: ...
```

---

## 13. State Persistence

File: `controllers/paper_engine_v2/state_store.py`

Directly reuses `DailyStateStore` from `controllers/daily_state_store.py`:

```python
from controllers.daily_state_store import DailyStateStore

class DeskStateStore:
    """Thin wrapper around DailyStateStore for PaperDesk snapshots."""

    def __init__(self, config: DeskConfig):
        self._store = DailyStateStore(
            file_path=config.state_file_path,
            redis_key=config.redis_key,
            redis_url=config.redis_url,
            save_throttle_s=30.0,
        )

    def save(self, snapshot: Dict[str, Any], now_ts: float, force: bool = False) -> None:
        self._store.save(snapshot, now_ts, force=force)

    def load(self) -> Optional[Dict[str, Any]]:
        return self._store.load()
```

Persisted: all balances, all positions (`to_dict()`), peak equity, funding timestamps.
**Not persisted:** order book, open orders (transient — recreated on restart).

---

## 14. HummingbotBridge

File: `controllers/paper_engine_v2/hb_bridge.py`

Only file that imports HB types. Replaces the 400-line monkey-patch in `paper_engine.py`.

### 14.1 Installation

Called from `v2_with_controllers.py::_install_internal_paper_adapters()`:

```python
def install_paper_desk_bridge(
    strategy: Any,
    desk: PaperDesk,
    connector_name: str,
    instrument_id: InstrumentId,
    trading_pair: str,
) -> bool:
    """Patch HB connector to route orders through PaperDesk. Returns True on success."""
```

### 14.2 HB → v2 Parameter Mapping

| HB call | v2 call |
|---|---|
| `connector.buy(pair, qty, LIMIT_MAKER, price)` | `desk.submit_order(id, BUY, LIMIT_MAKER, price, qty, source_bot)` |
| `connector.sell(pair, qty, LIMIT, price)` | `desk.submit_order(id, SELL, LIMIT, price, qty, source_bot)` |
| `connector.cancel(pair, oid)` | `desk.cancel_order(id, oid)` |
| HB `on_tick()` | `desk.tick(int(time.time()*1e9))` |

### 14.3 v2 → HB Event Conversion

| v2 event | HB event |
|---|---|
| `OrderFilled` | `OrderFilledEvent(order_id, ..., fee=TradeFee(flat_fee=fill.fee))` |
| `OrderCanceled` | `OrderCancelledEvent(order_id=...)` |
| `OrderRejected` | `MarketOrderFailureEvent(order_id=..., error_message=reason)` |

### 14.4 Edge Gate Paper Bypass

Add to `EppV24Config` in `controllers/epp_v2_4.py`:

```python
paper_edge_gate_bypass: bool = Field(
    default=True,
    description=(
        "When True and is_paper=True, skip the edge gate so paper fills occur. "
        "Paper mode validates structural behavior, not edge profitability."
    )
)
```

In `EppV24Controller._update_edge_gate_ewma()`:

```python
if self.config.is_paper and self.config.paper_edge_gate_bypass:
    self._soft_pause_edge = False
    self._edge_gate_blocked = False
    return
```

---

## 15. Project Integration Points

### 15.1 `v2_with_controllers.py` — `_install_internal_paper_adapters()`

Existing method (lines 265-366) builds `PaperEngineConfig` and calls `install_paper_adapter()`.

**Change:** After building `paper_cfg`, also build and register with `PaperDesk` if a shared desk exists:

```python
# In V2WithControllers.__init__()
self._paper_desk: Optional[PaperDesk] = None
if bot_mode == "paper":
    from controllers.paper_engine_v2.desk import PaperDesk, DeskConfig
    desk_config = DeskConfig(
        initial_balances={"USDT": Decimal(str(getattr(cfg, "paper_equity_quote", "500")))},
        seed=int(getattr(cfg, "paper_seed", 7)),
        redis_url=...,  # from env
    )
    self._paper_desk = PaperDesk(desk_config)

# In _install_internal_paper_adapters() for each controller:
if self._paper_desk is not None:
    spec = InstrumentSpec.from_hb_trading_rule(instrument_id, rule, fee_profile)
    self._paper_desk.register_instrument(spec, HummingbotDataFeed(connector))
    install_paper_desk_bridge(self, self._paper_desk, connector_name, instrument_id, trading_pair)
```

### 15.2 Existing YAML Config Fields — Unchanged

The v2 engine reads the same `EppV24Config` paper fields:
- `paper_equity_quote` → `DeskConfig.initial_balances["USDT"]`
- `paper_seed` → `DeskConfig.seed`
- `paper_latency_ms` → `EngineConfig.latency_ms` + `LatencyModel.base_latency_ns`
- `paper_queue_participation` → `QueuePositionConfig.queue_participation`
- `paper_slippage_bps` → `QueuePositionConfig.slippage_bps`
- `paper_adverse_selection_bps` → `QueuePositionConfig.adverse_selection_bps`
- `paper_partial_fill_min/max_ratio` → `QueuePositionConfig.min/max_partial_fill_ratio`
- `paper_max_fills_per_order` → `EngineConfig.max_fills_per_order`

### 15.3 Fee Profile Integration

`TieredFeeModel` loads from `config/fee_profiles.json` (already present):

```json
{"profiles": {"vip0": {"bitget_perpetual": {"maker": "0.0002", "taker": "0.0006"}}}}
```

The venue key in `InstrumentId.venue` maps to the fee profile key directly.

---

## 16. File Structure

```
controllers/paper_engine_v2/
    __init__.py           # exports: PaperDesk, InstrumentId, InstrumentSpec
    types.py              # InstrumentId, InstrumentSpec, PaperOrder, PaperPosition,
                          # OrderBookSnapshot, BookLevel, all EngineEvent subclasses
    matching_engine.py    # OrderMatchingEngine, EngineConfig
    fill_models.py        # FillModel protocol, FillDecision,
                          # QueuePositionFillModel, TopOfBookFillModel, LatencyAwareFillModel
    fee_models.py         # FeeModel protocol, MakerTakerFeeModel, TieredFeeModel, FixedFeeModel
    latency_model.py      # LatencyModel, NO/FAST/REALISTIC_LATENCY presets
    portfolio.py          # PaperPortfolio, MultiAssetLedger, PortfolioConfig, RiskGuard
    funding_simulator.py  # FundingSimulator
    desk.py               # PaperDesk, DeskConfig
    state_store.py        # DeskStateStore (wrapper around DailyStateStore)
    data_feeds.py         # MarketDataFeed protocol, HummingbotDataFeed, CCXTDataFeed, ReplayDataFeed
    hb_bridge.py          # install_paper_desk_bridge (ONLY HB import)

controllers/paper_engine.py   # KEPT — thin backward-compat wrapper

tests/controllers/test_paper_engine_v2/
    __init__.py
    conftest.py           # fixtures: sample_book(), sample_order(), sample_spec()
    test_types.py         # quantization, validation, to_dict/from_dict
    test_matching_engine.py   # full order lifecycle
    test_fill_models.py   # all 5+ test vectors + seeded reproducibility
    test_fee_models.py    # all 3 models
    test_portfolio.py     # settle_fill scenarios incl. flip + perp accounting
    test_funding_simulator.py
    test_desk.py          # multi-instrument, multi-bot, persistence round-trip
    test_state_store.py
```

---

## 17. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Singleton desk | One PaperDesk per host | Nautilus: one Portfolio per TradingNode for consolidated risk |
| Position persistence | Redis (primary) + JSON (fallback) | Reuses existing `DailyStateStore`; crash-only recovery pattern |
| CCXT threading | Daemon thread + queue.Queue | ccxt.pro is async; HB loop is sync |
| Funding simulation | YES, every 8h | Nautilus SimulationModule pattern; critical for perp P&L realism |
| Edge gate paper bypass | YES (default True) | Paper validates structure, not profitability |
| Realized PnL | Pure price PnL, no fees | Nautilus `calculate_pnls` convention; fees tracked separately |
| Margin model | LeveragedMarginModel | Nautilus default: `margin = notional / leverage * margin_init_ratio` |
| Reserve model | Spot: full notional; Perp: margin only | Nautilus `balance_impact` formula |
| Available balance | Clamped to zero | Nautilus: graceful degradation on transient over-margin |

---

## 18. Testing Strategy

### 18.1 Unit Tests — 97 minimum, zero HB/Docker

| File | Key scenarios | Min |
|---|---|---|
| `test_types.py` | quantize round-trip, validate_order, to_dict/from_dict, factory methods | 10 |
| `test_matching_engine.py` | accept, reject (balance/spec/risk), LIMIT_MAKER cross, time gate, max fills, latency queue, cancel, cancel_all, prune | 20 |
| `test_fill_models.py` | V1-V6 test vectors, seeded determinism (run twice same output), prob_fill_on_limit=0 → never fill, TopOfBook instant | 15 |
| `test_fee_models.py` | maker/taker rates, tiered lookup, fixed flat | 8 |
| `test_portfolio.py` | spot open/close, perp open/close, flip (V6), realized_pnl no fee, margin reserve, available clamped to 0, drawdown, mark_to_market, snapshot/restore | 20 |
| `test_funding_simulator.py` | apply at interval, skip flat, skip spot, accumulate | 6 |
| `test_desk.py` | multi-instrument tick, multi-bot routing, cancel_all, event log, persist+restore | 12 |
| `test_state_store.py` | save/load, throttle, force, Redis fallback to file | 6 |
| **Total** | | **97** |

### 18.2 Determinism test (in conftest.py)

```python
def test_identical_fill_sequence(sample_book, sample_spec):
    def run_once():
        desk = PaperDesk(DeskConfig(initial_balances={"USDT": Decimal("1000")}, seed=7))
        # ... register, submit, tick 10 times
        return [e.to_dict() for e in desk.event_log()]
    assert run_once() == run_once()
```

---

## 19. Migration Plan

| Phase | Scope | Files | Days | Risk |
|---|---|---|---|---|
| 1 | Core domain + all tests | All except `hb_bridge.py`, `data_feeds.py` | 3 | None |
| 2 | HB bridge + HB data feed + `v2_with_controllers.py` wiring + edge gate bypass | `hb_bridge.py`, `data_feeds.py` (HB), `epp_v2_4.py`, `v2_with_controllers.py` | 2 | Medium |
| 3 | State persistence (DailyStateStore reuse) | `state_store.py` | 0.5 | Low |
| 4 | CCXT data feed | `data_feeds.py` (CCXT) | 1 | Low |
| 5 | Replay data feed | `data_feeds.py` (Replay) | 0.5 | Low |
| 6 | Deprecate v1 wrapper | `paper_engine.py` | 0.5 | Low |

### Backward Compatibility Checklist

- [ ] `paper_engine.py` importable with same public API
- [ ] `PaperEngineConfig` dataclass unchanged
- [ ] `install_paper_adapter()` function preserved
- [ ] `install_paper_adapter_on_connector()` preserved
- [ ] `paper_stats` dict returns same keys (`paper_fill_count`, `paper_reject_count`, `paper_avg_queue_delay_ms`)
- [ ] All YAML config fields (`paper_equity_quote`, `paper_latency_ms`, etc.) read unchanged
