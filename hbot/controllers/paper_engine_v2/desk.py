"""PaperDesk orchestrator for Paper Engine v2.

Single desk per compose host — manages all instruments, bots, and portfolio.
Drives all engines on each tick, applies funding, persists state.

Thread safety: tick() must be called from a single thread (HB event loop).
"""
from __future__ import annotations

import logging
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional

from controllers.paper_engine_v2.fee_models import FeeModel, make_fee_model
from controllers.paper_engine_v2.fill_models import FillModel, make_fill_model
from controllers.paper_engine_v2.funding_simulator import FundingSimulator
from controllers.paper_engine_v2.latency_model import LatencyModel, make_latency_model
from controllers.paper_engine_v2.matching_engine import EngineConfig, OrderMatchingEngine
from controllers.paper_engine_v2.config import PaperEngineConfig
from controllers.paper_engine_v2.portfolio import PaperPortfolio, PortfolioConfig
from controllers.paper_engine_v2.state_store import DeskStateStore
from controllers.paper_engine_v2.types import (
    EngineEvent,
    InstrumentId,
    InstrumentSpec,
    OrderFilled,
    OrderRejected,
    OrderSide,
    PaperOrder,
    PaperOrderType,
    PositionAction,
    OrderStatus,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)
_PAPER_DESK_TRACE_ENABLED: bool = os.getenv("HB_PAPER_DESK_TRACE_ENABLED", "true").lower() in {"1", "true", "yes"}
_PAPER_DESK_TRACE_COOLDOWN_S: float = max(0.5, float(os.getenv("HB_PAPER_DESK_TRACE_COOLDOWN_S", "1.0")))
_LAST_PAPER_DESK_TRACE_TS: float = 0.0


def _trace_paper_desk(message: str, *args: Any, force: bool = False) -> None:
    global _LAST_PAPER_DESK_TRACE_TS
    if not _PAPER_DESK_TRACE_ENABLED:
        return
    now = time.time()
    if not force and (now - _LAST_PAPER_DESK_TRACE_TS) < _PAPER_DESK_TRACE_COOLDOWN_S:
        return
    _LAST_PAPER_DESK_TRACE_TS = now
    logger.warning("PAPER_DESK_TRACE " + message, *args)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DeskConfig:
    """Configuration for PaperDesk.

    YAML config fields map to these parameters (see Section 15.2 of spec).
    """
    initial_balances: Dict[str, Decimal]       # {"USDT": Decimal("10000")}
    portfolio_config: PortfolioConfig = field(default_factory=PortfolioConfig)
    default_fill_model: str = "queue_position"  # "queue_position"|"latency_aware"|"top_of_book"|"best_price"|"one_tick_slippage"|"two_tier"
    default_fee_source: str = "instrument_spec" # "instrument_spec"|"fee_profiles"
    default_fee_profile: str = "vip0"
    default_latency_model: str = "none"          # "configured_latency_ms"|"none"|"fast"|"realistic"
    fill_queue_participation: Decimal = Decimal("0.35")
    fill_slippage_bps: Decimal = Decimal("1.0")
    fill_adverse_selection_bps: Decimal = Decimal("1.5")
    fill_prob_fill_on_limit: float = 0.4
    fill_prob_slippage: float = 0.0
    fill_partial_min_ratio: Decimal = Decimal("0.15")
    fill_partial_max_ratio: Decimal = Decimal("0.85")
    fill_depth_levels: int = 3
    fill_depth_decay: Decimal = Decimal("0.70")
    fill_queue_position_enabled: bool = False
    fill_queue_ahead_ratio: Decimal = Decimal("0.50")
    fill_queue_trade_through_ratio: Decimal = Decimal("0.35")
    insert_latency_ms: int = 0
    cancel_latency_ms: int = 0
    default_engine_config: EngineConfig = field(default_factory=EngineConfig)
    state_file_path: str = "/tmp/paper_desk_v2_state.json"
    redis_key: str = "paper_desk:v2:state"
    redis_url: Optional[str] = None
    reset_state_on_startup: bool = False
    event_log_max_size: int = 100_000
    seed: int = 7
    fee_profiles_path: str = "config/fee_profiles.json"


# ---------------------------------------------------------------------------
# PaperDesk
# ---------------------------------------------------------------------------

class PaperDesk:
    """Multi-instrument, multi-bot paper trading desk.

    Single instance shared across all bots in the process.
    All public methods are safe to call from the HB event loop thread.
    """

    def __init__(self, config: DeskConfig):
        self._config = config
        self._portfolio = PaperPortfolio(config.initial_balances, config.portfolio_config)
        self._engines: Dict[str, OrderMatchingEngine] = {}
        self._feeds: Dict[str, Any] = {}   # MarketDataFeed per instrument key
        self._specs: Dict[str, InstrumentSpec] = {}
        self._funding_rates: Dict[str, Decimal] = {}
        self._funding_sim = FundingSimulator()
        self._state_store = DeskStateStore(
            file_path=config.state_file_path,
            redis_key=config.redis_key,
            redis_url=config.redis_url,
        )
        self._event_log: Deque[EngineEvent] = deque(maxlen=config.event_log_max_size)
        self._rng = random.Random(config.seed)
        self._order_counter: int = 0
        self._risk_margin_call_events_total: int = 0
        self._risk_liquidation_events_total: int = 0
        self._risk_liquidation_actions_total: int = 0
        self._risk_last_margin_level: str = "unknown"
        if config.reset_state_on_startup:
            logger.warning(
                "PaperDesk: clearing persisted state on startup for %s",
                config.redis_key,
            )
            self._state_store.clear()
        self._restore_state()

    # -- Registration -------------------------------------------------------

    def register_instrument(
        self,
        instrument_spec: InstrumentSpec,
        data_feed: Any,
        fill_model: Optional[FillModel] = None,
        fee_model: Optional[FeeModel] = None,
        latency_model: Optional[LatencyModel] = None,
        engine_config: Optional[EngineConfig] = None,
        leverage: int = 1,
    ) -> None:
        """Register an instrument with its data feed and simulation models."""
        key = instrument_spec.instrument_id.key
        cfg = self._config

        fm = fill_model or make_fill_model(
            cfg.default_fill_model,
            seed=cfg.seed,
            queue_participation=cfg.fill_queue_participation,
            slippage_bps=cfg.fill_slippage_bps,
            adverse_selection_bps=cfg.fill_adverse_selection_bps,
            prob_fill_on_limit=cfg.fill_prob_fill_on_limit,
            prob_slippage=cfg.fill_prob_slippage,
            partial_fill_min_ratio=cfg.fill_partial_min_ratio,
            partial_fill_max_ratio=cfg.fill_partial_max_ratio,
            depth_levels=cfg.fill_depth_levels,
            depth_decay=cfg.fill_depth_decay,
            queue_position_enabled=cfg.fill_queue_position_enabled,
            queue_ahead_ratio=cfg.fill_queue_ahead_ratio,
            queue_trade_through_ratio=cfg.fill_queue_trade_through_ratio,
        )
        fem = fee_model or make_fee_model(
            cfg.default_fee_source, instrument_spec,
            profile=cfg.default_fee_profile,
            profiles_path=cfg.fee_profiles_path,
        )
        ec = engine_config or cfg.default_engine_config
        lm = latency_model or make_latency_model(
            cfg.default_latency_model,
            latency_ms=ec.latency_ms,
            insert_latency_ms=cfg.insert_latency_ms,
            cancel_latency_ms=cfg.cancel_latency_ms,
        )

        engine = OrderMatchingEngine(
            instrument_id=instrument_spec.instrument_id,
            instrument_spec=instrument_spec,
            portfolio=self._portfolio,
            fill_model=fm,
            fee_model=fem,
            latency_model=lm,
            config=ec,
            leverage=leverage,
        )
        self._engines[key] = engine
        self._feeds[key] = data_feed
        self._specs[key] = instrument_spec
        self._funding_rates[key] = _ZERO
        logger.info("PaperDesk: registered instrument %s", key)

    # -- Order management ---------------------------------------------------

    def submit_order(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        order_type: PaperOrderType,
        price: Decimal,
        quantity: Decimal,
        source_bot: str = "",
        position_action: PositionAction = PositionAction.AUTO,
        position_mode: str = "ONEWAY",
    ) -> EngineEvent:
        """Submit an order. Routes to the correct engine. Never raises."""
        key = instrument_id.key
        force_trace = order_type == PaperOrderType.MARKET
        _trace_paper_desk(
            "stage=submit_enter instrument=%s side=%s order_type=%s price=%s quantity=%s source_bot=%s",
            key,
            side.value,
            order_type.value,
            str(price),
            str(quantity),
            source_bot,
            force=force_trace,
        )
        if force_trace:
            logger.warning(
                "PAPER_DESK_PROBE stage=submit_enter instrument=%s side=%s order_type=%s price=%s quantity=%s source_bot=%s",
                key,
                side.value,
                order_type.value,
                str(price),
                str(quantity),
                source_bot,
            )
        engine = self._engines.get(key)
        if engine is None:
            oid = self._next_order_id()
            event = OrderRejected(
                event_id=_uuid(), timestamp_ns=self._now_ns(),
                instrument_id=instrument_id,
                order_id=oid, reason=f"instrument_not_registered:{key}",
                source_bot=source_bot,
            )
            _trace_paper_desk(
                "stage=submit_rejected instrument=%s order_id=%s reason=%s",
                key,
                oid,
                str(getattr(event, "reason", "") or ""),
                force=True,
            )
            return event

        now_ns = self._now_ns()
        oid = self._next_order_id()
        order = PaperOrder(
            order_id=oid,
            instrument_id=instrument_id,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            status=OrderStatus.PENDING_SUBMIT,
            created_at_ns=now_ns,
            updated_at_ns=now_ns,
            source_bot=source_bot,
            position_action=position_action,
            position_mode=str(position_mode or "ONEWAY").upper(),
        )
        event = engine.submit_order(order, now_ns)
        _trace_paper_desk(
            "stage=submit_result instrument=%s order_id=%s event=%s reason=%s",
            key,
            str(getattr(event, "order_id", "") or oid),
            type(event).__name__,
            str(getattr(event, "reason", "") or ""),
            force=force_trace or type(event).__name__ != "OrderAccepted",
        )
        if force_trace:
            open_orders = len(engine.open_orders()) if hasattr(engine, "open_orders") else -1
            inflight = len(getattr(engine, "_inflight", []) or [])
            logger.warning(
                "PAPER_DESK_PROBE stage=submit_result instrument=%s order_id=%s event=%s reason=%s open_orders=%d inflight=%d",
                key,
                str(getattr(event, "order_id", "") or oid),
                type(event).__name__,
                str(getattr(event, "reason", "") or ""),
                open_orders,
                inflight,
            )
        self._event_log.append(event)
        return event

    def cancel_order(
        self, instrument_id: InstrumentId, order_id: str
    ) -> Optional[EngineEvent]:
        key = instrument_id.key
        engine = self._engines.get(key)
        if engine is None:
            return None
        event = engine.cancel_order(order_id, self._now_ns())
        if event is not None:
            self._event_log.append(event)
        return event

    def cancel_all(self, instrument_id: Optional[InstrumentId] = None) -> List[EngineEvent]:
        """Cancel all orders. If instrument_id given, cancel only for that instrument."""
        events: List[EngineEvent] = []
        now_ns = self._now_ns()
        if instrument_id is not None:
            engine = self._engines.get(instrument_id.key)
            if engine:
                ev = engine.cancel_all(now_ns)
                events.extend(ev)
        else:
            for engine in self._engines.values():
                ev = engine.cancel_all(now_ns)
                events.extend(ev)
        self._event_log.extend(events)
        return events

    # -- Tick ---------------------------------------------------------------

    def tick(self, now_ns: Optional[int] = None) -> List[EngineEvent]:
        """Drive all engines for one tick cycle. Never raises."""
        if now_ns is None:
            now_ns = self._now_ns()

        all_events: List[EngineEvent] = []
        current_prices: Dict[str, Decimal] = {}

        for key, engine in self._engines.items():
            feed = self._feeds.get(key)
            spec = self._specs.get(key)
            if feed is None or spec is None:
                continue

            # Update book from data feed
            try:
                book = feed.get_book(spec.instrument_id)
                if book is not None:
                    engine.update_book(book)
                    mid = book.mid_price
                    if mid:
                        current_prices[key] = mid
                # Update funding rate
                try:
                    self._funding_rates[key] = feed.get_funding_rate(spec.instrument_id)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("Data feed error for %s: %s", key, exc, exc_info=True)

            # Tick engine
            events = engine.tick(now_ns)
            all_events.extend(events)
            market_open_orders = [
                o for o in engine.open_orders()
                if getattr(o, "order_type", None) == PaperOrderType.MARKET
            ]
            if market_open_orders:
                best_bid = getattr(getattr(engine, "_book", None), "best_bid", None)
                best_ask = getattr(getattr(engine, "_book", None), "best_ask", None)
                logger.warning(
                    "PAPER_DESK_PROBE stage=tick_market_open instrument=%s market_open_orders=%d best_bid=%s best_ask=%s",
                    key,
                    len(market_open_orders),
                    str(getattr(best_bid, "price", "")),
                    str(getattr(best_ask, "price", "")),
                )
            for ev in events:
                order_id = str(getattr(ev, "order_id", "") or "")
                if order_id.startswith("paper_v2_") and type(ev).__name__ in {"OrderAccepted", "OrderRejected", "OrderFilled", "OrderCanceled"}:
                    logger.warning(
                        "PAPER_DESK_PROBE stage=tick_event instrument=%s event=%s order_id=%s reason=%s",
                        key,
                        type(ev).__name__,
                        order_id,
                        str(getattr(ev, "reason", "") or ""),
                    )

        # Apply funding charges
        instruments_with_rates = {
            key: (spec, self._funding_rates.get(key, _ZERO))
            for key, spec in self._specs.items()
        }
        funding_events = self._funding_sim.tick(now_ns, self._portfolio, instruments_with_rates)
        all_events.extend(funding_events)

        # Mark to market
        if current_prices:
            self._portfolio.mark_to_market(current_prices)

        # Post-trade risk evaluation (advisory liquidation actions)
        try:
            margin_level, liq_actions = self._portfolio.evaluate_risk(current_prices)
            current_margin_level = str(getattr(margin_level, "value", margin_level)).strip().lower() or "unknown"
            if current_margin_level in {"critical", "liquidate", "bankrupt"} and self._risk_last_margin_level in {
                "safe",
                "warn",
                "unknown",
            }:
                self._risk_margin_call_events_total += 1
            self._risk_last_margin_level = current_margin_level
            if liq_actions:
                self._risk_liquidation_events_total += 1
                self._risk_liquidation_actions_total += len(liq_actions)
                logger.warning(
                    "PaperDesk risk: %s level, %d liquidation actions required",
                    margin_level.value, len(liq_actions),
                )
                for action in liq_actions:
                    engine = self._engines.get(action.instrument_id.key)
                    if engine is None:
                        continue
                    all_events.extend(
                        engine.force_reduce(
                            side=action.side,
                            quantity=action.quantity,
                            now_ns=now_ns,
                            source_bot="risk_engine",
                        )
                    )
                if current_prices:
                    self._portfolio.mark_to_market(current_prices)
        except Exception:
            pass

        # Persist state (throttled)
        now_ts = now_ns / 1e9
        snap = self.snapshot()
        self._state_store.save(snap, now_ts, force=False)

        # Journal fill events for replay/postmortem
        try:
            for ev in all_events:
                if isinstance(ev, OrderFilled):
                    self._state_store.journal_event("order_filled", {
                        "instrument_id": ev.instrument_id.key,
                        "order_id": ev.order_id,
                        "fill_price": str(ev.fill_price),
                        "fill_quantity": str(ev.fill_quantity),
                        "fee": str(ev.fee),
                        "is_maker": ev.is_maker,
                    })
        except Exception:
            pass

        # Log events
        self._event_log.extend(all_events)
        return all_events

    # -- Accessors ----------------------------------------------------------

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio

    def snapshot(self) -> Dict[str, Any]:
        return {
            "portfolio": self._portfolio.snapshot(),
            "funding_timestamps": dict(self._funding_sim._last_funding_ns),
            "order_counter": int(self._order_counter),
            "risk_counters": {
                "margin_call_events_total": int(self._risk_margin_call_events_total),
                "liquidation_events_total": int(self._risk_liquidation_events_total),
                "liquidation_actions_total": int(self._risk_liquidation_actions_total),
                "last_margin_level": str(self._risk_last_margin_level),
            },
        }

    def event_log(self) -> List[EngineEvent]:
        return list(self._event_log)

    def paper_stats(self, instrument_id: Optional[InstrumentId] = None) -> Dict[str, Any]:
        """Return paper_stats dict compatible with existing paper_engine.py API."""
        fill_count = 0
        reject_count = 0
        for ev in self._event_log:
            if isinstance(ev, OrderFilled):
                if instrument_id is None or ev.instrument_id == instrument_id:
                    fill_count += 1
            elif isinstance(ev, OrderRejected):
                if instrument_id is None or ev.instrument_id == instrument_id:
                    reject_count += 1
        return {
            "paper_fill_count": Decimal(str(fill_count)),
            "paper_reject_count": Decimal(str(reject_count)),
            "paper_avg_queue_delay_ms": _ZERO,
            "paper_dropped_relay_count": Decimal("0"),
        }

    # -- Internal ----------------------------------------------------------

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"paper_v2_{self._order_counter}"

    @staticmethod
    def _now_ns() -> int:
        return int(time.time() * 1_000_000_000)

    def _restore_state(self) -> None:
        data = self._state_store.load()
        if data is None:
            return
        try:
            if "portfolio" in data:
                self._portfolio.restore_from_snapshot(data["portfolio"])
            if "funding_timestamps" in data:
                self._funding_sim._last_funding_ns.update(
                    {k: int(v) for k, v in data["funding_timestamps"].items()}
                )
            try:
                restored_order_counter = int(data.get("order_counter", 0) or 0)
            except Exception:
                restored_order_counter = 0
            self._order_counter = max(0, restored_order_counter)
            risk_counters = data.get("risk_counters", {}) if isinstance(data.get("risk_counters"), dict) else {}
            self._risk_margin_call_events_total = int(risk_counters.get("margin_call_events_total", 0) or 0)
            self._risk_liquidation_events_total = int(risk_counters.get("liquidation_events_total", 0) or 0)
            self._risk_liquidation_actions_total = int(risk_counters.get("liquidation_actions_total", 0) or 0)
            self._risk_last_margin_level = (
                str(risk_counters.get("last_margin_level", self._risk_last_margin_level)).strip().lower() or "unknown"
            )
            logger.info("PaperDesk: state restored from persistence")
        except Exception as exc:
            logger.warning("PaperDesk: state restore failed: %s", exc, exc_info=True)

    # -- Factory ------------------------------------------------------------

    @classmethod
    def from_paper_config(cls, cfg: PaperEngineConfig, redis_url: Optional[str] = None) -> "PaperDesk":
        """Build PaperDesk from PaperEngineConfig."""
        if redis_url is None:
            redis_url = PaperEngineConfig.resolve_redis_url_from_env()
        portfolio_config = PortfolioConfig(
            margin_model_type=cfg.paper_margin_model_type,
        )
        engine_config = EngineConfig(
            latency_ms=cfg.paper_latency_ms,
            max_fills_per_order=cfg.paper_max_fills_per_order,
            liquidity_consumption=cfg.paper_liquidity_consumption,
            price_protection_points=cfg.paper_price_protection_points,
            margin_model_type=cfg.paper_margin_model_type,
        )
        return cls(DeskConfig(
            initial_balances={"USDT": cfg.paper_equity_quote},
            portfolio_config=portfolio_config,
            default_fill_model=cfg.paper_fill_model,
            default_fee_source="fee_profiles",
            default_fee_profile=cfg.fee_profile,
            fee_profiles_path="project_config/fee_profiles.json",
            default_latency_model=cfg.paper_latency_model,
            fill_queue_participation=cfg.paper_queue_participation,
            fill_slippage_bps=cfg.paper_slippage_bps,
            fill_adverse_selection_bps=cfg.paper_adverse_selection_bps,
            fill_prob_fill_on_limit=cfg.paper_prob_fill_on_limit,
            fill_prob_slippage=cfg.paper_prob_slippage,
            fill_partial_min_ratio=cfg.paper_partial_fill_min_ratio,
            fill_partial_max_ratio=cfg.paper_partial_fill_max_ratio,
            fill_depth_levels=cfg.paper_depth_levels,
            fill_depth_decay=cfg.paper_depth_decay,
            fill_queue_position_enabled=cfg.paper_queue_position_enabled,
            fill_queue_ahead_ratio=cfg.paper_queue_ahead_ratio,
            fill_queue_trade_through_ratio=cfg.paper_queue_trade_through_ratio,
            insert_latency_ms=cfg.paper_insert_latency_ms,
            cancel_latency_ms=cfg.paper_cancel_latency_ms,
            default_engine_config=engine_config,
            state_file_path=(
                f"{cfg.log_dir}/{cfg.artifact_namespace}/{cfg.instance_name}_{cfg.variant}/paper_desk_v2.json"
            ),
            redis_key=f"paper_desk:v2:{cfg.instance_name}:{cfg.variant}",
            redis_url=redis_url,
            reset_state_on_startup=cfg.paper_reset_state_on_startup,
            seed=cfg.paper_seed,
        ))

    @classmethod
    def from_controller_config(cls, cfg: Any) -> "PaperDesk":
        """Adapter from a controller config object with nested `paper_engine` block."""
        return cls.from_paper_config(PaperEngineConfig.from_controller_config(cfg))

    @classmethod
    def from_epp_config(cls, cfg: Any) -> "PaperDesk":
        """Backward-compatible alias for legacy EPP integrations."""
        return cls.from_controller_config(cfg)
