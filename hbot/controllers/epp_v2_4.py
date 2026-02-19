from __future__ import annotations

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

    # Phase & bot role
    variant: str = Field(default="a", json_schema_extra={"prompt": "Variant a/b/c/d: ", "prompt_on_new": True})
    enabled: bool = Field(default=True, json_schema_extra={"prompt": "Enabled (true/false): ", "prompt_on_new": True})
    no_trade: bool = Field(default=False, json_schema_extra={"prompt": "No-trade mode: ", "prompt_on_new": True})
    instance_name: str = Field(default="bot1", json_schema_extra={"prompt": "Instance name: ", "prompt_on_new": True})
    log_dir: str = Field(default="/home/hummingbot/logs")
    paper_mode: bool = Field(default=True)
    paper_start_quote: Decimal = Field(default=Decimal("10000"))
    paper_start_base: Decimal = Field(default=Decimal("0"))
    candles_connector: Optional[str] = Field(default=None)
    candles_trading_pair: Optional[str] = Field(default=None)

    # Exchange profile (VIP0)
    spot_fee_pct: Decimal = Field(default=Decimal("0.0010"))  # 0.10%
    slippage_est_pct: Decimal = Field(default=Decimal("0.0005"))
    turnover_cap_x: Decimal = Field(default=Decimal("3.0"))
    turnover_penalty_step: Decimal = Field(default=Decimal("0.0005"))

    # Regime detection
    high_vol_band_pct: Decimal = Field(default=Decimal("0.0080"))
    shock_drift_30s_pct: Decimal = Field(default=Decimal("0.0100"))
    trend_eps_pct: Decimal = Field(default=Decimal("0.0010"))
    z1_normal: Decimal = Field(default=Decimal("1.0"))
    z1_high_vol: Decimal = Field(default=Decimal("1.5"))

    # Runtime controls
    sample_interval_s: int = Field(default=10, ge=5, le=30)
    spread_floor_recalc_s: int = Field(default=300)
    daily_rollover_hour_utc: int = Field(default=0, ge=0, le=23)
    cancel_budget_per_min: int = Field(default=50)
    max_age_neutral_s: int = Field(default=90)
    max_age_trend_s: int = Field(default=60)
    max_age_high_vol_s: int = Field(default=40)

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
            return str(info.data.get("connector_name", "bitget"))
        return str(v)

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v: Optional[str], info: ValidationInfo) -> str:
        if v in (None, ""):
            return str(info.data.get("trading_pair", "BTC-USDT"))
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
        self._paper_quote_balance: Decimal = config.paper_start_quote
        self._paper_base_balance: Decimal = config.paper_start_base
        self._paper_last_fill_minute_key: Optional[int] = None

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

        inv_error = base_pct - target_base_pct
        skew = _clip(inv_error * Decimal("0.5"), Decimal("-0.002"), Decimal("0.002"))
        adverse_drift = self._price_buffer.adverse_drift_30s(now)
        turnover_x = self._traded_notional_today / equity_quote if equity_quote > 0 else Decimal("0")
        turnover_penalty = max(Decimal("0"), turnover_x - self.config.turnover_cap_x) * self.config.turnover_penalty_step

        if now - self._last_floor_recalc_ts >= self.config.spread_floor_recalc_s:
            self._spread_floor_pct = (
                Decimal("2") * self.config.spot_fee_pct
                + self.config.slippage_est_pct
                + max(Decimal("0"), adverse_drift)
                + turnover_penalty
            )
            self._last_floor_recalc_ts = now

        spread_pct = self._pick_spread_pct(regime_spec, turnover_x)
        spread_pct = max(spread_pct, self._spread_floor_pct)
        net_edge = Decimal("0.5") * spread_pct - self.config.spot_fee_pct - self.config.slippage_est_pct - max(
            Decimal("0"), adverse_drift
        )
        self._soft_pause_edge = net_edge <= 0

        connector_ready = self._connector_ready()
        balance_ok = self._balances_consistent()
        state = self._ops_guard.update(
            OpsSnapshot(
                connector_ready=connector_ready,
                balances_consistent=balance_ok,
                cancel_fail_streak=self._cancel_fail_streak,
                edge_gate_blocked=self._soft_pause_edge,
            )
        )

        if not self.config.enabled or self.config.variant in {"b", "c"}:
            state = self._ops_guard.force_hard_stop("phase0_stub_disabled")
        if self.config.no_trade or self.config.variant == "d":
            state = GuardState.SOFT_PAUSE

        levels = self._pick_levels(regime_spec, turnover_x)
        if self._cancel_per_min(now) > self.config.cancel_budget_per_min:
            levels = max(1, levels - 1)
            self.config.executor_refresh_time = int(regime_spec.refresh_s + 10)
        else:
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

        self.processed_data = {
            "reference_price": mid,
            "spread_multiplier": Decimal("1"),
            "regime": regime_name,
            "target_base_pct": target_base_pct,
            "base_pct": base_pct,
            "state": state.value,
            "spread_pct": spread_pct,
            "net_edge_pct": net_edge,
            "turnover_x": turnover_x,
            "skew": skew,
            "adverse_drift_30s": adverse_drift,
        }

        if state != GuardState.RUNNING:
            self.config.buy_spreads = ""
            self.config.sell_spreads = ""
            self.config.total_amount_quote = Decimal("0")
        elif self.config.paper_mode:
            self._paper_trade_tick(
                now_ts=now,
                mid=mid,
                equity_quote=equity_quote,
                base_pct=base_pct,
                target_base_pct=target_base_pct,
                quote_size_pct=(regime_spec.quote_size_pct_min + regime_spec.quote_size_pct_max) / Decimal("2"),
                state=state,
            )

        self._log_minute(now, mid, equity_quote, base_pct, target_base_pct, spread_pct, net_edge, turnover_x, state)

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
            }
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
        return int(regime_spec.levels_max - int(round(float(ratio) * span)))

    def _build_side_spreads(
        self, spread_pct: Decimal, skew: Decimal, levels: int, one_sided: str
    ) -> Tuple[List[Decimal], List[Decimal]]:
        # Spread is percent, and order placement around mid is based on half spread.
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
        if self.config.paper_mode:
            # Internal paper simulator handles virtual fills; avoid real order placement.
            self.config.buy_spreads = ""
            self.config.sell_spreads = ""
            self.config.total_amount_quote = Decimal("0")
            return
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
        return self.market_data_provider.get_connector(self.config.connector_name)

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
        if self.config.paper_mode:
            return self._paper_base_balance, self._paper_quote_balance
        connector = self._connector()
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
        if self.config.paper_mode:
            return self._get_mid_price() > 0
        connector = self._connector()
        return bool(getattr(connector, "ready", False))

    def _balances_consistent(self) -> bool:
        if self.config.paper_mode:
            return self._paper_base_balance >= 0 and self._paper_quote_balance >= 0
        connector = self._connector()
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

    def _maybe_roll_day(self, now_ts: float) -> None:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        day_key = dt.strftime("%Y-%m-%d")
        if self._daily_key is None:
            self._daily_key = day_key
            return
        if day_key != self._daily_key and dt.hour >= self.config.daily_rollover_hour_utc:
            mid = self._get_mid_price()
            equity_now, _ = self._compute_equity_and_base_pct(mid)
            equity_open = self._daily_equity_open or equity_now
            pnl = equity_now - equity_open
            pnl_pct = (pnl / equity_open) if equity_open > 0 else Decimal("0")
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
                }
            )
            self._daily_key = day_key
            self._daily_equity_open = equity_now
            self._traded_notional_today = Decimal("0")
            self._fills_count_today = 0
            self._cancel_events_ts = []

    def _log_minute(
        self,
        now_ts: float,
        mid: Decimal,
        equity_quote: Decimal,
        base_pct: Decimal,
        target_base_pct: Decimal,
        spread_pct: Decimal,
        net_edge: Decimal,
        turnover_x: Decimal,
        state: GuardState,
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
                "mid": str(mid),
                "equity_quote": str(equity_quote),
                "base_pct": str(base_pct),
                "target_base_pct": str(target_base_pct),
                "spread_pct": str(spread_pct),
                "net_edge_pct": str(net_edge),
                "turnover_today_x": str(turnover_x),
                "cancel_per_min": self._cancel_per_min(now_ts),
                "orders_active": len(self.executors_info),
            }
        )

    def _paper_trade_tick(
        self,
        now_ts: float,
        mid: Decimal,
        equity_quote: Decimal,
        base_pct: Decimal,
        target_base_pct: Decimal,
        quote_size_pct: Decimal,
        state: GuardState,
    ) -> None:
        if self.config.variant != "a" or self.config.no_trade or state != GuardState.RUNNING:
            return
        minute_key = int(now_ts // 60)
        if self._paper_last_fill_minute_key == minute_key:
            return

        threshold = Decimal("0.02")
        notional = max(Decimal("5"), equity_quote * quote_size_pct)
        side: Optional[str] = None
        amount_base = Decimal("0")
        if base_pct < target_base_pct - threshold and self._paper_quote_balance > Decimal("1"):
            side = "buy"
            notional = min(notional, self._paper_quote_balance)
            amount_base = notional / mid
            self._paper_quote_balance -= notional
            self._paper_base_balance += amount_base
        elif base_pct > target_base_pct + threshold and self._paper_base_balance > Decimal("0"):
            side = "sell"
            amount_base = min(self._paper_base_balance, notional / mid)
            notional = amount_base * mid
            self._paper_base_balance -= amount_base
            self._paper_quote_balance += notional

        if side is not None and amount_base > 0:
            fee_quote = notional * self.config.spot_fee_pct
            if side == "buy":
                self._paper_quote_balance = max(Decimal("0"), self._paper_quote_balance - fee_quote)
            else:
                self._paper_quote_balance = max(Decimal("0"), self._paper_quote_balance - fee_quote)
            self._traded_notional_today += notional
            self._fills_count_today += 1
            self._paper_last_fill_minute_key = minute_key
            self._csv.log_fill(
                {
                    "bot_variant": self.config.variant,
                    "exchange": f"{self.config.connector_name}_paper_sim",
                    "trading_pair": self.config.trading_pair,
                    "side": side,
                    "price": str(mid),
                    "amount_base": str(amount_base),
                    "notional_quote": str(notional),
                    "fee_quote": str(fee_quote),
                    "order_id": f"paper-{minute_key}-{side}",
                    "state": self._ops_guard.state.value,
                }
            )
