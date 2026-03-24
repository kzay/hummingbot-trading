"""Replay-backed market-data reader compatible with runtime adapter calls."""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal
from typing import Any

from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.types import TradeRow
from platform_lib.market_data.market_data_plane import (
    DirectionalTradeFeatures,
    MarketTopOfBook,
    MarketTrade,
    TradeFlowFeatures,
)

_ZERO_D = Decimal("0")


class ReplayMarketDataReader:
    def __init__(self, clock: ReplayClock, trades: list[TradeRow]):
        self._clock = clock
        self._trades = sorted(trades, key=lambda trade: trade.timestamp_ms)
        self._timestamps_ms = [trade.timestamp_ms for trade in self._trades]
        self._visible_end = 0
        self.advance(clock.now_ns)

    @property
    def enabled(self) -> bool:
        return True

    def advance(self, now_ns: int) -> None:
        now_ms = int(now_ns) // 1_000_000
        self._visible_end = bisect_right(self._timestamps_ms, now_ms)

    def _visible_trades(self) -> list[TradeRow]:
        return self._trades[: self._visible_end]

    def latest_quote(self) -> dict[str, Any]:
        top = self.get_top_of_book()
        latest_ts_ms = self._latest_ts_ms()
        if top is None:
            return {}
        return {
            "best_bid": top.best_bid,
            "best_ask": top.best_ask,
            "best_bid_size": top.best_bid_size,
            "best_ask_size": top.best_ask_size,
            "exchange_ts_ms": latest_ts_ms,
            "ingest_ts_ms": latest_ts_ms,
        }

    def latest_depth(self) -> dict[str, Any]:
        top = self.get_top_of_book()
        latest_ts_ms = self._latest_ts_ms()
        if top is None:
            return {}
        return {
            "best_bid": top.best_bid,
            "best_ask": top.best_ask,
            "bids": [{"price": top.best_bid, "size": top.best_bid_size}] if top.best_bid > _ZERO_D else [],
            "asks": [{"price": top.best_ask, "size": top.best_ask_size}] if top.best_ask > _ZERO_D else [],
            "exchange_ts_ms": latest_ts_ms,
            "ingest_ts_ms": latest_ts_ms,
        }

    def latest_quote_state(self) -> None:
        return None

    def latest_depth_state(self) -> None:
        return None

    def get_market_state(self) -> None:
        return None

    def market_state_debug(self) -> dict[str, Any]:
        top = self.get_top_of_book()
        return {
            "available": top is not None,
            "stale": self.get_trade_flow_features().stale,
            "mid_price": float(self.get_mid_price()) if self.get_mid_price() > _ZERO_D else None,
            "best_bid": float(top.best_bid) if top and top.best_bid > _ZERO_D else None,
            "best_ask": float(top.best_ask) if top and top.best_ask > _ZERO_D else None,
            "exchange_ts_ms": self._latest_ts_ms() or None,
        }

    def get_mid_price(self) -> Decimal:
        top = self.get_top_of_book()
        if top is None or top.best_bid <= _ZERO_D or top.best_ask <= _ZERO_D:
            return _ZERO_D
        return (top.best_bid + top.best_ask) / Decimal("2")

    def get_top_of_book(self) -> MarketTopOfBook | None:
        trades = self.recent_trades(count=50)
        if not trades:
            return None

        sell_trades = [trade for trade in trades if trade.aggressor_side == "sell"]
        buy_trades = [trade for trade in trades if trade.aggressor_side == "buy"]
        if not sell_trades or not buy_trades:
            return None

        bid_trade = max(sell_trades, key=lambda trade: trade.price)
        ask_trade = min(buy_trades, key=lambda trade: trade.price)
        if ask_trade.price < bid_trade.price:
            return None

        mid = (bid_trade.price + ask_trade.price) / Decimal("2")
        spread_pct = ((ask_trade.price - bid_trade.price) / mid) if mid > _ZERO_D else _ZERO_D
        return MarketTopOfBook(
            best_bid=bid_trade.price,
            best_ask=ask_trade.price,
            spread_pct=spread_pct,
            best_bid_size=bid_trade.size,
            best_ask_size=ask_trade.size,
        )

    def get_depth_imbalance(self, depth: int = 5) -> Decimal:
        trades = self.recent_trades(count=max(1, int(depth)))
        if not trades:
            return _ZERO_D
        buy_volume = sum((trade.size for trade in trades if trade.delta > _ZERO_D), _ZERO_D)
        sell_volume = sum((trade.size for trade in trades if trade.delta < _ZERO_D), _ZERO_D)
        total = buy_volume + sell_volume
        if total <= _ZERO_D:
            return _ZERO_D
        return (buy_volume - sell_volume) / total

    def latest_payloads(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.latest_quote(), self.latest_depth()

    def recent_trade_payloads(self, count: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "trade_id": trade.trade_id,
                "side": trade.side,
                "price": trade.price,
                "size": trade.size,
                "exchange_ts_ms": trade.exchange_ts_ms,
                "ingest_ts_ms": trade.ingest_ts_ms,
                "market_sequence": trade.market_sequence,
                "extra": {"aggressor_side": trade.aggressor_side},
            }
            for trade in self.recent_trades(count=count)
        ]

    def recent_trades(self, count: int = 100) -> list[MarketTrade]:
        visible = self._visible_trades()
        if not visible:
            return []
        selected = visible[-max(1, int(count)) :]
        trades: list[MarketTrade] = []
        for index, trade in enumerate(selected, start=1):
            side = str(trade.side).strip().lower()
            delta = trade.size if side == "buy" else (-trade.size if side == "sell" else _ZERO_D)
            trades.append(
                MarketTrade(
                    trade_id=trade.trade_id,
                    side=side,
                    price=trade.price,
                    size=trade.size,
                    delta=delta,
                    exchange_ts_ms=trade.timestamp_ms,
                    ingest_ts_ms=trade.timestamp_ms,
                    market_sequence=index,
                    aggressor_side=side,
                )
            )
        return trades

    def _latest_ts_ms(self) -> int:
        visible = self._visible_trades()
        return visible[-1].timestamp_ms if visible else 0

    def _price_change_pct(self, trades: list[MarketTrade]) -> Decimal:
        if len(trades) < 2:
            return _ZERO_D
        first_price = trades[0].price
        last_price = trades[-1].price
        if first_price <= _ZERO_D or last_price <= _ZERO_D:
            return _ZERO_D
        return (last_price - first_price) / first_price

    def get_trade_flow_features(
        self,
        *,
        count: int = 120,
        stale_after_ms: int | None = None,
        imbalance_threshold: Decimal = Decimal("2.0"),
        delta_spike_min_baseline: int = 20,
    ) -> TradeFlowFeatures:
        trades = self.recent_trades(count=count)
        if not trades:
            return TradeFlowFeatures()

        buy_volume = _ZERO_D
        sell_volume = _ZERO_D
        cvd = _ZERO_D
        latest_ts_ms = 0
        last_price = _ZERO_D
        deltas: list[Decimal] = []
        stacked_buy_count = 0
        stacked_sell_count = 0
        current_buy_stack = 0
        current_sell_stack = 0

        for trade in trades:
            if trade.delta > _ZERO_D:
                buy_volume += trade.size
            elif trade.delta < _ZERO_D:
                sell_volume += trade.size
            cvd += trade.delta
            deltas.append(trade.delta)
            latest_ts_ms = max(latest_ts_ms, int(trade.exchange_ts_ms or trade.ingest_ts_ms or 0))
            last_price = trade.price

            buy_over_sell = trade.size / max(sell_volume if sell_volume > _ZERO_D else _ZERO_D, Decimal("1"))
            sell_over_buy = trade.size / max(buy_volume if buy_volume > _ZERO_D else _ZERO_D, Decimal("1"))
            if trade.delta > _ZERO_D and (sell_volume <= _ZERO_D or buy_over_sell >= imbalance_threshold):
                current_buy_stack += 1
                current_sell_stack = 0
            elif trade.delta < _ZERO_D and (buy_volume <= _ZERO_D or sell_over_buy >= imbalance_threshold):
                current_sell_stack += 1
                current_buy_stack = 0
            else:
                current_buy_stack = 0
                current_sell_stack = 0
            stacked_buy_count = max(stacked_buy_count, current_buy_stack)
            stacked_sell_count = max(stacked_sell_count, current_sell_stack)

        total_volume = buy_volume + sell_volume
        delta_volume = buy_volume - sell_volume
        imbalance_ratio = (delta_volume / total_volume) if total_volume > _ZERO_D else _ZERO_D

        spike_ratio = _ZERO_D
        minimum_baseline = max(5, delta_spike_min_baseline)
        if len(deltas) >= minimum_baseline + 1:
            baseline_start = -(minimum_baseline + 1)
            first_ts = trades[baseline_start].exchange_ts_ms or trades[baseline_start].ingest_ts_ms or 0
            last_ts = trades[-1].exchange_ts_ms or trades[-1].ingest_ts_ms or 0
            if last_ts - first_ts >= 30_000:
                last_delta_abs = abs(deltas[-1])
                history = deltas[baseline_start:-1]
                baseline = sum((abs(delta) for delta in history), _ZERO_D) / Decimal(str(len(history)))
                if baseline > _ZERO_D:
                    spike_ratio = last_delta_abs / baseline

        now_ms = self._clock.now_ms
        stale_limit = int(stale_after_ms or 15_000)
        is_stale = latest_ts_ms <= 0 or (now_ms - latest_ts_ms) > stale_limit
        return TradeFlowFeatures(
            trade_count=len(trades),
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            delta_volume=delta_volume,
            cvd=cvd,
            last_price=last_price,
            latest_ts_ms=latest_ts_ms,
            stale=is_stale,
            imbalance_ratio=imbalance_ratio,
            stacked_buy_count=stacked_buy_count,
            stacked_sell_count=stacked_sell_count,
            delta_spike_ratio=spike_ratio,
        )

    def get_directional_trade_features(
        self,
        *,
        spot_connector_name: str,
        spot_trading_pair: str,
        futures_count: int = 120,
        spot_count: int = 120,
        stale_after_ms: int | None = None,
        divergence_threshold_pct: Decimal = Decimal("0.15"),
        stacked_imbalance_min: int = 3,
        delta_spike_threshold: Decimal = Decimal("3.0"),
        delta_spike_min_baseline: int = 20,
        funding_rate: Decimal | None = None,
        long_funding_max: Decimal = Decimal("0.0005"),
        short_funding_min: Decimal = Decimal("-0.0003"),
    ) -> DirectionalTradeFeatures:
        futures_features = self.get_trade_flow_features(
            count=futures_count,
            stale_after_ms=stale_after_ms,
            delta_spike_min_baseline=delta_spike_min_baseline,
        )
        return DirectionalTradeFeatures(
            futures=futures_features,
            spot=TradeFlowFeatures(),
            funding_rate=funding_rate or _ZERO_D,
            funding_bias="neutral",
            stale=True,
        )


__all__ = ["ReplayMarketDataReader"]
