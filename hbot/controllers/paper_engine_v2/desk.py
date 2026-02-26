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
    OrderStatus,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)


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
    default_fill_model: str = "queue_position"  # "queue_position"|"top_of_book"|"latency_aware"
    default_fee_source: str = "instrument_spec" # "instrument_spec"|"fee_profiles"
    default_fee_profile: str = "vip0"
    default_latency_model: str = "none"          # "none"|"fast"|"realistic"
    default_engine_config: EngineConfig = field(default_factory=EngineConfig)
    state_file_path: str = "/tmp/paper_desk_v2_state.json"
    redis_key: str = "paper_desk:v2:state"
    redis_url: Optional[str] = None
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

        fm = fill_model or make_fill_model(cfg.default_fill_model, seed=cfg.seed)
        fem = fee_model or make_fee_model(
            cfg.default_fee_source, instrument_spec,
            profile=cfg.default_fee_profile,
            profiles_path=cfg.fee_profiles_path,
        )
        lm = latency_model or make_latency_model(cfg.default_latency_model)
        ec = engine_config or cfg.default_engine_config

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
    ) -> EngineEvent:
        """Submit an order. Routes to the correct engine. Never raises."""
        key = instrument_id.key
        engine = self._engines.get(key)
        if engine is None:
            oid = self._next_order_id()
            return OrderRejected(
                event_id=_uuid(), timestamp_ns=self._now_ns(),
                instrument_id=instrument_id,
                order_id=oid, reason=f"instrument_not_registered:{key}",
                source_bot=source_bot,
            )

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
        )
        event = engine.submit_order(order, now_ns)
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
            if liq_actions:
                logger.warning(
                    "PaperDesk risk: %s level, %d liquidation actions required",
                    margin_level.value, len(liq_actions),
                )
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
            logger.info("PaperDesk: state restored from persistence")
        except Exception as exc:
            logger.warning("PaperDesk: state restore failed: %s", exc, exc_info=True)

    # -- Factory ------------------------------------------------------------

    @classmethod
    def from_epp_config(cls, cfg: Any) -> "PaperDesk":
        """Build PaperDesk from EppV24Config YAML fields (backward compat)."""
        redis_url = None
        rh = os.environ.get("REDIS_HOST", "")
        rp = os.environ.get("REDIS_PORT", "6379")
        if rh:
            redis_url = f"redis://{rh}:{rp}/0"

        initial_quote = Decimal(str(getattr(cfg, "paper_equity_quote", "500")))
        seed = int(getattr(cfg, "paper_seed", 7))
        latency_ms = int(getattr(cfg, "paper_latency_ms", 150))

        portfolio_config = PortfolioConfig()
        engine_config = EngineConfig(
            latency_ms=latency_ms,
            max_fills_per_order=int(getattr(cfg, "paper_max_fills_per_order", 8)),
        )

        instance_name = str(getattr(cfg, "instance_name", "bot1"))
        variant = str(getattr(cfg, "variant", "a"))
        log_dir = str(getattr(cfg, "log_dir", "/tmp"))

        return cls(DeskConfig(
            initial_balances={"USDT": initial_quote},
            portfolio_config=portfolio_config,
            default_fill_model="queue_position",
            default_fee_source="fee_profiles",
            default_fee_profile="vip0",
            fee_profiles_path="project_config/fee_profiles.json",
            default_latency_model="none",
            default_engine_config=engine_config,
            state_file_path=f"{log_dir}/epp_v24/{instance_name}_{variant}/paper_desk_v2.json",
            redis_key=f"paper_desk:v2:{instance_name}:{variant}",
            redis_url=redis_url,
            seed=seed,
        ))
