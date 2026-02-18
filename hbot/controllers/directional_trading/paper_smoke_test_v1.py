"""
Paper Smoke Test V1
===================

Purpose:
  A deterministic controller to verify paper-trade lifecycle end-to-end:
  signal -> open position -> close via TP/SL/time-limit.

Design:
  - Alternates long/short signal every `flip_interval_seconds`.
  - Uses small risk settings so positions close quickly.
  - Intended for paper mode validation only.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerBase,
    DirectionalTradingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig


class PaperSmokeTestV1Config(DirectionalTradingControllerConfigBase):
    controller_name: str = "paper_smoke_test_v1"

    candles_connector: Optional[str] = Field(default=None, json_schema_extra={"is_updatable": True})
    candles_trading_pair: Optional[str] = Field(default=None, json_schema_extra={"is_updatable": True})
    interval: str = Field(default="1m", json_schema_extra={"is_updatable": True})
    flip_interval_seconds: int = Field(default=300, json_schema_extra={"is_updatable": True})
    long_signal_strength: float = Field(default=0.8, json_schema_extra={"is_updatable": True})
    short_signal_strength: float = Field(default=0.8, json_schema_extra={"is_updatable": True})
    enable_shorts: bool = Field(default=True, json_schema_extra={"is_updatable": True})

    @field_validator("candles_connector", mode="before")
    @classmethod
    def _set_candles_connector(cls, v, info: ValidationInfo):
        return info.data.get("connector_name") if not v else v

    @field_validator("candles_trading_pair", mode="before")
    @classmethod
    def _set_candles_pair(cls, v, info: ValidationInfo):
        return info.data.get("trading_pair") if not v else v


class PaperSmokeTestV1Controller(DirectionalTradingControllerBase):
    def __init__(self, config: PaperSmokeTestV1Config, *args, **kwargs):
        self.config = config
        if len(self.config.candles_config) == 0:
            self.config.candles_config = [CandlesConfig(
                connector=config.candles_connector,
                trading_pair=config.candles_trading_pair,
                interval=config.interval,
                max_records=80,
            )]
        super().__init__(config, *args, **kwargs)

    async def update_processed_data(self):
        now = int(self.market_data_provider.time())
        epoch = max(1, self.config.flip_interval_seconds)
        cycle = (now // epoch) % 2

        price = self.market_data_provider.get_price_by_type(
            self.config.connector_name, self.config.trading_pair
        )

        if cycle == 0:
            signal = float(self.config.long_signal_strength)
            signal_type = "smoke_long"
        else:
            signal = -float(self.config.short_signal_strength) if self.config.enable_shorts else 0.0
            signal_type = "smoke_short" if self.config.enable_shorts else "smoke_flat"

        self.processed_data = {
            "signal": signal,
            "signal_type": signal_type,
            "current_price": float(price),
            "meta": f"flip_cycle={cycle} interval={epoch}s",
            "next_flip_utc": datetime.datetime.utcfromtimestamp(((now // epoch) + 1) * epoch).isoformat(),
        }

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        signal = float(self.processed_data.get("signal", 0.0))
        side = TradeType.BUY if signal >= 0 else TradeType.SELL
        return PositionExecutorConfig(
            timestamp=self.market_data_provider.time(),
            level_id=level_id,
            connector_name=self.config.connector_name,
            trading_pair=self.config.trading_pair,
            entry_price=price,
            amount=amount,
            triple_barrier_config=self.config.triple_barrier_config,
            leverage=self.config.leverage,
            side=side,
        )

    def to_format_status(self) -> List[str]:
        d = self.processed_data
        return [
            "Paper Smoke Test V1",
            f"Signal: {d.get('signal', 0):+.2f} ({d.get('signal_type', 'n/a')})",
            f"Price: {d.get('current_price', 0):.4f}",
            f"Meta: {d.get('meta', '')}",
            f"Next flip UTC: {d.get('next_flip_utc', '')}",
        ]

    def get_custom_info(self) -> dict:
        return {
            "signal": self.processed_data.get("signal"),
            "signal_type": self.processed_data.get("signal_type"),
            "next_flip_utc": self.processed_data.get("next_flip_utc"),
        }
