from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import PriceType, TradeType
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderCancelledEvent, OrderFilledEvent
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig

from controllers.epp_logging import CsvSplitLogger
from controllers.ops_guard import GuardState, OpsGuard, OpsSnapshot
from controllers.price_buffer import MidPriceBuffer

# --- Patch: allow *_paper_trade connector names in V2 controller framework ---
_pt_log = logging.getLogger("epp_paper_trade_patch")
try:
    from hummingbot.data_feed.market_data_provider import MarketDataProvider as _MDP
    if not getattr(_MDP, "_paper_trade_patched", False):
        _orig_create = _MDP._create_non_trading_connector

        def _patched_create(self, connector_name):
            if connector_name.endswith("_paper_trade"):
                base_name = connector_name.replace("_paper_trade", "")
                _pt_log.info(f"Paper trade: creating non-trading connector as '{base_name}' (was '{connector_name}')")
                return _orig_create(self, base_name)
            return _orig_create(self, connector_name)

        _MDP._create_non_trading_connector = _patched_create
        _MDP._paper_trade_patched = True
        _pt_log.info("MarketDataProvider patched for paper trade connector support")
except Exception as e:
    _pt_log.warning(f"Paper trade patch failed: {e}")
# --- End patch ---


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _clip(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(high, max(low, value))


@dataclass
class RegimeSpec:
    spread_min: Decimal
    spread_max: Decimal
    levels_min: int
    levels_max: int
    refresh_s: int
    target_base_pct: Decimal
    quote_size_pct_min: Decimal
    quote_size_pct_max: Decimal
    one_sided: str  # "off" | "buy_only" | "sell_only"


class EppV24Config(MarketMakingControllerConfigBase):
    controller_name: str = "epp_v2_4"

    variant: str = Field(default="a", json_schema_extra={"prompt": "Variant a/b/c/d: ", "prompt_on_new": True})
    enabled: bool = Field(default=True, json_schema_extra={"prompt": "Enabled (true/false): ", "prompt_on_new": True})
    no_trade: bool = Field(default=False, json_schema_extra={"prompt": "No-trade mode: ", "prompt_on_new": True})
    instance_name: str = Field(default="bot1", json_schema_extra={"prompt": "Instance name: ", "prompt_on_new": True})
    log_dir: str = Field(default="/home/hummingbot/logs")
    candles_connector: Optional[str] = Field(default=None)
    candles_trading_pair: Optional[str] = Field(default=None)

    # Exchange profile (VIP0)
    spot_fee_pct: Decimal = Field(default=Decimal("0.0010"))
    slippage_est_pct: Decimal = Field(default=Decimal("0.0005"))
    turnover_cap_x: Decimal = Field(default=Decimal("3.0"))
    turnover_penalty_step: Decimal = Field(default=Decimal("0.0010"))

    # Regime detection
    high_vol_band_pct: Decimal = Field(default=Decimal("0.0080"))
    shock_drift_30s_pct: Decimal = Field(default=Decimal("0.0100"))
    trend_eps_pct: Decimal = Field(default=Decimal("0.0010"))

    # Runtime controls
    sample_interval_s: int = Field(default=10, ge=5, le=30)
    spread_floor_recalc_s: int = Field(default=300)
    daily_rollover_hour_utc: int = Field(default=0, ge=0, le=23)
    cancel_budget_per_min: int = Field(default=50)
    min_net_edge_bps: int = Field(default=2)
    cancel_pause_cooldown_s: int = Field(default=120)

    @field_validator("variant", mode="before")
    @classmethod
    def _validate_variant(cls, v: str) -> str:
        low = (v or "a").lower()
        if low not in {"a", "b", "c", "d"}:
            raise ValueError("variant must be one of a/b/c/d")
        return low

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("connector_name", ""))
        return str(v)

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("trading_pair", ""))
        return str(v)


class EppV24Controller(MarketMakingControllerBase):
    PHASE0_SPECS: Dict[str, RegimeSpec] = {
        "neutral_low_vol": RegimeSpec(
            spread_min=Decimal("0.0025"),
            spread_max=Decimal("0.0045"),
            levels_min=2,
            levels_max=4,
            refresh_s=90,
            target_base_pct=Decimal("0.50"),
            quote_size_pct_min=Decimal("0.0008"),
            quote_size_pct_max=Decimal("0.0012"),
            one_sided="off",
        ),
        "up": RegimeSpec(
            spread_min=Decimal("0.0030"),
            spread_max=Decimal("0.0055"),
            levels_min=2,
            levels_max=3,
            refresh_s=70,
            target_base_pct=Decimal("0.65"),
            quote_size_pct_min=Decimal("0.0006"),
            quote_size_pct_max=Decimal("0.0010"),
            one_sided="buy_only",
        ),
        "down": RegimeSpec(
            spread_min=Decimal("0.0035"),
            spread_max=Decimal("0.0080"),
            levels_min=2,
            levels_max=3,
            refresh_s=60,
            target_base_pct=Decimal("0.25"),
            quote_size_pct_min=Decimal("0.0005"),
            quote_size_pct_max=Decimal("0.0008"),
            one_sided="sell_only",
        ),
        "high_vol_shock": RegimeSpec(
            spread_min=Decimal("0.0080"),
            spread_max=Decimal("0.0200"),
            levels_min=1,
            levels_max=2,
            refresh_s=120,
            target_base_pct=Decimal("0.40"),
            quote_size_pct_min=Decimal("0.0003"),
            quote_size_pct_max=Decimal("0.0005"),
            one_sided="sell_only",
        ),
    }

    def __init__(self, config: EppV24Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self._price_buffer = MidPriceBuffer(sample_interval_sec=config.sample_interval_s)
        self._ops_guard = OpsGuard()
        self._csv = CsvSplitLogger(config.log_dir, config.instance_name, config.variant)
        self._last_floor_recalc_ts: float = 0
        self._spread_floor_pct: Decimal = Decimal("0.0025")
        self._traded_notional_today: Decimal = Decimal("0")
        self._fills_count_today: int = 0
        self._daily_equity_open: Optional[Decimal] = None
        self._daily_key: Optional[str] = None
        self._cancel_events_ts: List[float] = []
        self._cancel_fail_streak: int = 0
        self._soft_pause_edge: bool = False
        self._last_minute_key: Optional[int] = None
        self._external_soft_pause: bool = False
        self._external_pause_reason: str = ""
        self._external_target_base_pct_override: Optional[Decimal] = None
        self._last_external_model_version: str = ""
        self._last_external_intent_reason: str = ""
        self._cancel_pause_until: float = 0

    async def update_processed_data(self):
        now = float(self.market_data_provider.time())
        mid = self._get_mid_price()
        if mid <= 0:
            return
        self._price_buffer.add_sample(now, mid)

        self._maybe_roll_day(now)
        equity_quote, base_pct = self._compute_equity_and_base_pct(mid)
        if self._daily_equity_open is None and equity_quote > 0:
            self._daily_equity_open = equity_quote

        regime_name, regime_spec = self._detect_regime(mid)
        target_base_pct = regime_spec.target_base_pct
        if self._external_target_base_pct_override is not None:
            target_base_pct = _clip(self._external_target_base_pct_override, Decimal("0"), Decimal("1"))

        # ext6: stronger skew in trend regimes
        skew_factor = Decimal("0.8") if regime_name in {"up", "down"} else Decimal("0.5")
        inv_error = base_pct - target_base_pct
        skew = _clip(inv_error * skew_factor, Decimal("-0.002"), Decimal("0.002"))

        adverse_drift = self._price_buffer.adverse_drift_30s(now)
        turnover_x = self._traded_notional_today / equity_quote if equity_quote > 0 else Decimal("0")
        turnover_penalty = max(Decimal("0"), turnover_x - self.config.turnover_cap_x) * self.config.turnover_penalty_step

        # ext5: add ATR volatility term to spread floor
        vol_penalty = (self._price_buffer.band_pct(14) or Decimal("0")) * Decimal("0.5")
        if now - self._last_floor_recalc_ts >= self.config.spread_floor_recalc_s:
            self._spread_floor_pct = (
                Decimal("2") * self.config.spot_fee_pct
                + self.config.slippage_est_pct
                + max(Decimal("0"), adverse_drift)
                + turnover_penalty
                + vol_penalty
            )
            self._last_floor_recalc_ts = now

        spread_pct = self._pick_spread_pct(regime_spec, turnover_x)
        spread_pct = max(spread_pct, self._spread_floor_pct)
        min_edge_threshold = Decimal(self.config.min_net_edge_bps) / Decimal("10000")
        # ext4: realistic fill rate (0.4 instead of 0.5)
        net_edge = (
            Decimal("0.4") * spread_pct
            - self.config.spot_fee_pct
            - self.config.slippage_est_pct
            - max(Decimal("0"), adverse_drift)
            - turnover_penalty
        )
        self._soft_pause_edge = net_edge <= min_edge_threshold

        # ext9: detect high_vol and spread collapse for OpsGuard
        band_pct = self._price_buffer.band_pct(14) or Decimal("0")
        is_high_vol = band_pct >= self.config.high_vol_band_pct

        connector_ready = self._connector_ready()
        balance_ok = self._balances_consistent()
        state = self._ops_guard.update(
            OpsSnapshot(
                connector_ready=connector_ready,
                balances_consistent=balance_ok,
                cancel_fail_streak=self._cancel_fail_streak,
                edge_gate_blocked=self._soft_pause_edge,
                high_vol=is_high_vol,
            )
        )

        if not self.config.enabled or self.config.variant in {"b", "c"}:
            state = self._ops_guard.force_hard_stop("phase0_stub_disabled")
        if self.config.no_trade or self.config.variant == "d":
            state = GuardState.SOFT_PAUSE
        if self._external_soft_pause:
            state = GuardState.SOFT_PAUSE

        # ext7: cancel budget breach triggers SOFT_PAUSE for cooldown period
        cancel_rate = self._cancel_per_min(now)
        if cancel_rate > self.config.cancel_budget_per_min:
            self._cancel_pause_until = now + self.config.cancel_pause_cooldown_s
        if now < self._cancel_pause_until:
            state = GuardState.SOFT_PAUSE

        levels = self._pick_levels(regime_spec, turnover_x)
        self.config.executor_refresh_time = int(regime_spec.refresh_s)

        buy_spreads, sell_spreads = self._build_side_spreads(spread_pct, skew, levels, regime_spec.one_sided)
        self._apply_runtime_spreads_and_sizing(
            buy_spreads=buy_spreads,
            sell_spreads=sell_spreads,
            levels=levels,
            equity_quote=equity_quote,
            mid=mid,
            quote_size_pct=(regime_spec.quote_size_pct_min + regime_spec.quote_size_pct_max) / Decimal("2"),
        )

        base_bal, quote_bal = self._get_balances()
        self.processed_data = {
            "reference_price": mid,
            "spread_multiplier": Decimal("1"),
            "regime": regime_name,
            "target_base_pct": target_base_pct,
            "base_pct": base_pct,
            "state": state.value,
            "spread_pct": spread_pct,
            "spread_floor_pct": self._spread_floor_pct,
            "net_edge_pct": net_edge,
            "turnover_x": turnover_x,
            "skew": skew,
            "adverse_drift_30s": adverse_drift,
            "equity_quote": equity_quote,
            "mid": mid,
            "base_balance": base_bal,
            "quote_balance": quote_bal,
            "soft_pause_edge": self._soft_pause_edge,
            "external_soft_pause": self._external_soft_pause,
            "external_pause_reason": self._external_pause_reason,
            "external_model_version": self._last_external_model_version,
            "external_intent_reason": self._last_external_intent_reason,
        }

        if state != GuardState.RUNNING:
            self.config.buy_spreads = ""
            self.config.sell_spreads = ""
            self.config.total_amount_quote = Decimal("0")

        # ext1: pass event timestamp, not log time
        event_ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        self._log_minute(now, event_ts, mid, equity_quote, base_pct, base_bal, quote_bal,
                         target_base_pct, spread_pct, net_edge, turnover_x, state,
                         regime_name, adverse_drift, skew)

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=self.get_trade_type_from_level_id(level_id),
        )

    def did_fill_order(self, event: OrderFilledEvent):
        notional = _d(event.amount) * _d(event.price)
        self._traded_notional_today += notional
        self._fills_count_today += 1
        fee_quote = Decimal("0")
        quote_asset = self.config.trading_pair.split("-")[1]
        try:
            fee_quote = _d(event.trade_fee.fee_amount_in_token(quote_asset, event.price, event.amount))
        except Exception:
            pass
        event_ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
        self._csv.log_fill(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "side": event.trade_type.name.lower(),
                "price": str(event.price),
                "amount_base": str(event.amount),
                "notional_quote": str(notional),
                "fee_quote": str(fee_quote),
                "order_id": event.order_id,
                "state": self._ops_guard.state.value,
            },
            ts=event_ts,
        )

    def did_cancel_order(self, cancelled_event: OrderCancelledEvent):
        self._cancel_events_ts.append(float(self.market_data_provider.time()))
        self._cancel_fail_streak = 0

    def did_fail_order(self, order_failed_event: MarketOrderFailureEvent):
        msg = (order_failed_event.error_message or "").lower()
        if "cancel" in msg:
            self._cancel_fail_streak += 1
        else:
            self._cancel_fail_streak = 0

    def to_format_status(self) -> List[str]:
        return [
            "EPP v2.4 - VIP0 Survival Yield Engine",
            f"variant={self.config.variant} state={self._ops_guard.state.value}",
            f"regime={self.processed_data.get('regime', 'n/a')}",
            f"spread={self.processed_data.get('spread_pct', Decimal('0')) * Decimal('100'):.3f}%",
            f"net_edge={self.processed_data.get('net_edge_pct', Decimal('0')) * Decimal('100'):.4f}%",
            f"base_pct={self.processed_data.get('base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"target_base={self.processed_data.get('target_base_pct', Decimal('0')) * Decimal('100'):.2f}%",
            f"turnover_today={self.processed_data.get('turnover_x', Decimal('0')):.3f}x",
            f"guard_reasons={','.join(self._ops_guard.reasons) if self._ops_guard.reasons else 'none'}",
        ]

    def get_custom_info(self) -> dict:
        return dict(self.processed_data)

    def set_external_soft_pause(self, active: bool, reason: str) -> None:
        self._external_soft_pause = bool(active)
        self._external_pause_reason = reason

    def apply_execution_intent(self, intent: Dict[str, object]) -> Tuple[bool, str]:
        action = str(intent.get("action", "")).strip()
        metadata = intent.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        self._last_external_model_version = str(metadata.get("model_version", ""))
        self._last_external_intent_reason = str(metadata.get("reason", ""))
        if action == "soft_pause":
            reason = str(metadata.get("reason", "external_intent"))
            self.set_external_soft_pause(True, reason)
            return True, "ok"
        if action == "resume":
            self.set_external_soft_pause(False, "resume")
            return True, "ok"
        if action == "kill_switch":
            self._ops_guard.force_hard_stop("external_kill_switch")
            return True, "ok"
        if action == "set_target_base_pct":
            value = intent.get("target_base_pct")
            if value is None:
                return False, "missing_target_base_pct"
            try:
                candidate = _d(value)
                if candidate < Decimal("0") or candidate > Decimal("1"):
                    return False, "target_base_pct_out_of_range"
                self._external_target_base_pct_override = _clip(candidate, Decimal("0"), Decimal("1"))
                return True, "ok"
            except Exception:
                return False, "invalid_target_base_pct"
        return False, "unsupported_action"

    def _detect_regime(self, mid: Decimal) -> Tuple[str, RegimeSpec]:
        ema50 = self._price_buffer.ema(50)
        band_pct = self._price_buffer.band_pct(14) or Decimal("0")
        drift = self._price_buffer.adverse_drift_30s(float(self.market_data_provider.time()))
        if band_pct >= self.config.high_vol_band_pct or drift >= self.config.shock_drift_30s_pct:
            return "high_vol_shock", self.PHASE0_SPECS["high_vol_shock"]
        if ema50 is None:
            return "neutral_low_vol", self.PHASE0_SPECS["neutral_low_vol"]
        if mid > ema50 * (Decimal("1") + self.config.trend_eps_pct):
            return "up", self.PHASE0_SPECS["up"]
        if mid < ema50 * (Decimal("1") - self.config.trend_eps_pct):
            return "down", self.PHASE0_SPECS["down"]
        return "neutral_low_vol", self.PHASE0_SPECS["neutral_low_vol"]

    def _pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        ratio = _clip(turnover_x / max(self.config.turnover_cap_x, Decimal("0.0001")), Decimal("0"), Decimal("1"))
        return regime_spec.spread_min + (regime_spec.spread_max - regime_spec.spread_min) * ratio

    def _pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        if regime_spec.levels_min == regime_spec.levels_max:
            return regime_spec.levels_min
        ratio = _clip(turnover_x / max(self.config.turnover_cap_x, Decimal("0.0001")), Decimal("0"), Decimal("1"))
        span = regime_spec.levels_max - regime_spec.levels_min
        return max(regime_spec.levels_min, int(regime_spec.levels_max - int(round(float(ratio) * span))))

    def _build_side_spreads(
        self, spread_pct: Decimal, skew: Decimal, levels: int, one_sided: str
    ) -> Tuple[List[Decimal], List[Decimal]]:
        half = spread_pct / Decimal("2")
        step = half * Decimal("0.4")
        buy: List[Decimal] = []
        sell: List[Decimal] = []
        for i in range(levels):
            level_offset = half + step * Decimal(i)
            buy_spread = max(Decimal("0.0001"), level_offset - skew)
            sell_spread = max(Decimal("0.0001"), level_offset + skew)
            buy.append(buy_spread)
            sell.append(sell_spread)
        if one_sided == "buy_only":
            sell = []
        elif one_sided == "sell_only":
            buy = []
        return buy, sell

    def _apply_runtime_spreads_and_sizing(
        self,
        buy_spreads: List[Decimal],
        sell_spreads: List[Decimal],
        levels: int,
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
    ) -> None:
        if self.config.no_trade or self.config.variant == "d":
            self.config.buy_spreads = ""
            self.config.sell_spreads = ""
            self.config.total_amount_quote = Decimal("0")
            return
        if self.config.variant in {"b", "c"} or not self.config.enabled:
            self.config.buy_spreads = ""
            self.config.sell_spreads = ""
            self.config.total_amount_quote = Decimal("0")
            return

        self.config.buy_spreads = ",".join(str(x) for x in buy_spreads)
        self.config.sell_spreads = ",".join(str(x) for x in sell_spreads)

        per_order_quote = max(self._min_notional_quote(), equity_quote * quote_size_pct)
        side_levels = max(1, len(buy_spreads) + len(sell_spreads))
        self.config.total_amount_quote = per_order_quote * Decimal(side_levels)

        min_base = self._min_base_amount(mid)
        if min_base > 0 and self.config.total_amount_quote > 0:
            base_for_total = self.config.total_amount_quote / mid
            if base_for_total < min_base:
                self.config.total_amount_quote = min_base * mid

        self.config.executor_refresh_time = max(30, int(self.config.executor_refresh_time))
        self.config.cooldown_time = max(5, int(self.config.cooldown_time))

    def _connector(self):
        try:
            return self.market_data_provider.get_connector(self.config.connector_name)
        except Exception:
            return None

    def _get_mid_price(self) -> Decimal:
        try:
            return _d(
                self.market_data_provider.get_price_by_type(
                    self.config.connector_name,
                    self.config.trading_pair,
                    PriceType.MidPrice,
                )
            )
        except Exception:
            return Decimal("0")

    def _get_balances(self) -> Tuple[Decimal, Decimal]:
        connector = self._connector()
        if connector is None:
            return Decimal("0"), Decimal("0")
        base_asset, quote_asset = self.config.trading_pair.split("-")
        base = Decimal("0")
        quote = Decimal("0")
        try:
            base = _d(connector.get_balance(base_asset))
            quote = _d(connector.get_balance(quote_asset))
        except Exception:
            pass
        return base, quote

    def _compute_equity_and_base_pct(self, mid: Decimal) -> Tuple[Decimal, Decimal]:
        base_bal, quote_bal = self._get_balances()
        equity = quote_bal + base_bal * mid
        if equity <= 0:
            return Decimal("0"), Decimal("0")
        base_pct = (base_bal * mid) / equity
        return equity, base_pct

    def _connector_ready(self) -> bool:
        connector = self._connector()
        if connector is None:
            return False
        return bool(getattr(connector, "ready", False))

    def _balances_consistent(self) -> bool:
        connector = self._connector()
        if connector is None:
            return False
        base_asset, quote_asset = self.config.trading_pair.split("-")
        try:
            base_total = _d(connector.get_balance(base_asset))
            base_free = _d(connector.get_available_balance(base_asset))
            quote_total = _d(connector.get_balance(quote_asset))
            quote_free = _d(connector.get_available_balance(quote_asset))
        except Exception:
            return False
        if base_total < 0 or quote_total < 0:
            return False
        if base_free > base_total + Decimal("1e-8"):
            return False
        if quote_free > quote_total + Decimal("1e-8"):
            return False
        return True

    def _cancel_per_min(self, now: float) -> int:
        self._cancel_events_ts = [ts for ts in self._cancel_events_ts if now - ts <= 60.0]
        return len(self._cancel_events_ts)

    def _min_notional_quote(self) -> Decimal:
        connector = self._connector()
        if connector is None:
            return Decimal("0")
        rule = None
        try:
            trading_rules = getattr(connector, "trading_rules", {})
            rule = trading_rules.get(self.config.trading_pair)
        except Exception:
            rule = None
        if rule is None:
            return Decimal("0")
        for attr in ("min_notional_size", "min_notional", "min_order_value"):
            value = getattr(rule, attr, None)
            if value is not None:
                return _d(value)
        return Decimal("0")

    def _min_base_amount(self, ref_price: Decimal) -> Decimal:
        quote_min = self._min_notional_quote()
        if quote_min <= 0 or ref_price <= 0:
            return Decimal("0")
        return quote_min / ref_price

    # ext10: roll on day change only, remove hour condition
    def _maybe_roll_day(self, now_ts: float) -> None:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        if self._daily_key is None:
            self._daily_key = day_key
            return
        if day_key != self._daily_key:
            mid = self._get_mid_price()
            equity_now, _ = self._compute_equity_and_base_pct(mid)
            equity_open = self._daily_equity_open or equity_now
            pnl = equity_now - equity_open
            pnl_pct = (pnl / equity_open) if equity_open > 0 else Decimal("0")
            event_ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
            self._csv.log_daily(
                {
                    "bot_variant": self.config.variant,
                    "exchange": self.config.connector_name,
                    "trading_pair": self.config.trading_pair,
                    "state": self._ops_guard.state.value,
                    "equity_open_quote": str(equity_open),
                    "equity_now_quote": str(equity_now),
                    "pnl_quote": str(pnl),
                    "pnl_pct": str(pnl_pct),
                    "turnover_x": str(self._traded_notional_today / equity_now) if equity_now > 0 else "0",
                    "fills_count": self._fills_count_today,
                    "ops_events": "|".join(self._ops_guard.reasons),
                },
                ts=event_ts,
            )
            self._daily_key = day_key
            self._daily_equity_open = equity_now
            self._traded_notional_today = Decimal("0")
            self._fills_count_today = 0
            self._cancel_events_ts = []

    # ext2: enriched minute.csv with all debug signals
    def _log_minute(
        self,
        now_ts: float,
        event_ts: str,
        mid: Decimal,
        equity_quote: Decimal,
        base_pct: Decimal,
        base_balance: Decimal,
        quote_balance: Decimal,
        target_base_pct: Decimal,
        spread_pct: Decimal,
        net_edge: Decimal,
        turnover_x: Decimal,
        state: GuardState,
        regime: str,
        adverse_drift: Decimal,
        skew: Decimal,
    ) -> None:
        minute_key = int(now_ts // 60)
        if self._last_minute_key == minute_key:
            return
        self._last_minute_key = minute_key
        self._csv.log_minute(
            {
                "bot_variant": self.config.variant,
                "exchange": self.config.connector_name,
                "trading_pair": self.config.trading_pair,
                "state": state.value,
                "regime": regime,
                "mid": str(mid),
                "equity_quote": str(equity_quote),
                "base_pct": str(base_pct),
                "target_base_pct": str(target_base_pct),
                "spread_pct": str(spread_pct),
                "spread_floor_pct": str(self._spread_floor_pct),
                "net_edge_pct": str(net_edge),
                "skew": str(skew),
                "adverse_drift_30s": str(adverse_drift),
                "soft_pause_edge": str(self._soft_pause_edge),
                "base_balance": str(base_balance),
                "quote_balance": str(quote_balance),
                "turnover_today_x": str(turnover_x),
                "cancel_per_min": self._cancel_per_min(now_ts),
                "orders_active": len(self.executors_info),
            },
            ts=event_ts,
        )
