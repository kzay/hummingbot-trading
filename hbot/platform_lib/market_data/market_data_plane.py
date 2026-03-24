from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from services.common.canonical_market_state import (
    CanonicalMarketState,
    canonical_market_state_age_ms,
    canonical_market_state_is_stale,
    market_payload_freshness_ts_ms,
    market_payload_is_fresh,
    parse_canonical_market_state,
)
from services.contracts.stream_names import MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM, MARKET_TRADE_STREAM
from services.hb_bridge.redis_client import RedisStreamClient

_ZERO_D = Decimal("0")


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _normalize_connector(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return _ZERO_D
        return Decimal(str(value))
    except Exception:
        return _ZERO_D


@dataclass(frozen=True)
class MarketTopOfBook:
    best_bid: Decimal = _ZERO_D
    best_ask: Decimal = _ZERO_D
    spread_pct: Decimal = _ZERO_D
    best_bid_size: Decimal = _ZERO_D
    best_ask_size: Decimal = _ZERO_D


@dataclass(frozen=True)
class MarketTrade:
    trade_id: str = ""
    side: str = ""
    price: Decimal = _ZERO_D
    size: Decimal = _ZERO_D
    delta: Decimal = _ZERO_D
    exchange_ts_ms: int = 0
    ingest_ts_ms: int = 0
    market_sequence: int = 0
    aggressor_side: str = ""


@dataclass(frozen=True)
class TradeFlowFeatures:
    trade_count: int = 0
    buy_volume: Decimal = _ZERO_D
    sell_volume: Decimal = _ZERO_D
    delta_volume: Decimal = _ZERO_D
    cvd: Decimal = _ZERO_D
    last_price: Decimal = _ZERO_D
    latest_ts_ms: int = 0
    stale: bool = True
    imbalance_ratio: Decimal = _ZERO_D
    stacked_buy_count: int = 0
    stacked_sell_count: int = 0
    delta_spike_ratio: Decimal = _ZERO_D


@dataclass(frozen=True)
class DirectionalTradeFeatures:
    futures: TradeFlowFeatures = TradeFlowFeatures()
    spot: TradeFlowFeatures = TradeFlowFeatures()
    futures_price_change_pct: Decimal = _ZERO_D
    spot_price_change_pct: Decimal = _ZERO_D
    cvd_divergence_ratio: Decimal = _ZERO_D
    bullish_divergence: bool = False
    bearish_divergence: bool = False
    funding_rate: Decimal = _ZERO_D
    funding_bias: str = "neutral"
    funding_aligned_long: bool = False
    funding_aligned_short: bool = False
    long_score: int = 0
    short_score: int = 0
    stale: bool = True


class CanonicalMarketDataReader:
    """Read the latest canonical quote/depth for one connector/pair from Redis."""

    def __init__(
        self,
        connector_name: str,
        trading_pair: str,
        *,
        enabled: Optional[bool] = None,
        stream_scan_count: Optional[int] = None,
        stale_after_ms: Optional[int] = None,
    ) -> None:
        self._connector_name = _normalize_connector(connector_name)
        self._trading_pair = _normalize_pair(trading_pair)
        self._enabled = (
            enabled
            if enabled is not None
            else os.getenv("HB_CANONICAL_MARKET_DATA_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
        )
        self._stream_scan_count = max(
            1,
            int(stream_scan_count or os.getenv("HB_CANONICAL_MARKET_STREAM_SCAN_COUNT", "50")),
        )
        self._stale_after_ms = max(
            250,
            int(stale_after_ms or os.getenv("HB_CANONICAL_MARKET_STALE_AFTER_MS", "15000")),
        )
        self._client = RedisStreamClient(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", "") or None,
            enabled=self._enabled,
        )
        self._last_quote_payload: Dict[str, Any] = {}
        self._last_depth_payload: Dict[str, Any] = {}
        self._last_quote_freshness_ts_ms: int = 0
        self._last_depth_freshness_ts_ms: int = 0
        self._last_trade_payloads: List[Dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._client.enabled)

    def _matches(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        return (
            _normalize_connector(payload.get("connector_name")) == self._connector_name
            and _normalize_pair(payload.get("trading_pair")) == self._trading_pair
        )

    def _fresh(self, payload: Dict[str, Any], entry_id: str) -> bool:
        return market_payload_is_fresh(
            payload,
            now_ms=int(time.time() * 1000),
            stale_after_ms=self._stale_after_ms,
            entry_id=entry_id,
        )

    def _read_matching(self, stream: str) -> Tuple[Optional[str], Dict[str, Any]]:
        if not self.enabled:
            return None, {}
        records = self._client.read_recent(stream, count=self._stream_scan_count)
        for entry_id, payload in records:
            if self._matches(payload) and self._fresh(payload, entry_id):
                return entry_id, payload
        return None, {}

    def _cached_payload_if_fresh(self, payload: Dict[str, Any], freshness_ts_ms: int) -> Dict[str, Any]:
        if not payload or freshness_ts_ms <= 0:
            return {}
        now_ms = int(time.time() * 1000)
        if max(0, now_ms - int(freshness_ts_ms)) > self._stale_after_ms:
            return {}
        return dict(payload)

    def latest_quote(self) -> Dict[str, Any]:
        entry_id, payload = self._read_matching(MARKET_QUOTE_STREAM)
        if payload:
            self._last_quote_payload = payload
            self._last_quote_freshness_ts_ms = market_payload_freshness_ts_ms(payload, entry_id=str(entry_id or ""))
        return self._cached_payload_if_fresh(self._last_quote_payload, self._last_quote_freshness_ts_ms)

    def latest_depth(self) -> Dict[str, Any]:
        entry_id, payload = self._read_matching(MARKET_DEPTH_STREAM)
        if payload:
            self._last_depth_payload = payload
            self._last_depth_freshness_ts_ms = market_payload_freshness_ts_ms(payload, entry_id=str(entry_id or ""))
        return self._cached_payload_if_fresh(self._last_depth_payload, self._last_depth_freshness_ts_ms)

    def latest_quote_state(self) -> Optional[CanonicalMarketState]:
        payload = self.latest_quote()
        return parse_canonical_market_state(payload) if payload else None

    def latest_depth_state(self) -> Optional[CanonicalMarketState]:
        payload = self.latest_depth()
        return parse_canonical_market_state(payload) if payload else None

    def get_market_state(self) -> Optional[CanonicalMarketState]:
        depth_state = self.latest_depth_state()
        if depth_state is not None and depth_state.has_top_of_book:
            return depth_state
        quote_state = self.latest_quote_state()
        if quote_state is not None and (quote_state.has_top_of_book or quote_state.mid_price > _ZERO_D):
            return quote_state
        return depth_state or quote_state

    def market_state_debug(self) -> Dict[str, Any]:
        now_ms = int(time.time() * 1000)
        state = self.get_market_state()
        if state is None:
            return {
                "connector_name": self._connector_name,
                "trading_pair": self._trading_pair,
                "available": False,
                "source_event_type": "",
                "stale": True,
                "age_ms": None,
                "mid_price": None,
                "best_bid": None,
                "best_ask": None,
                "best_bid_size": None,
                "best_ask_size": None,
                "market_sequence": None,
                "exchange_ts_ms": None,
                "ingest_ts_ms": None,
                "timestamp_ms": None,
            }
        return {
            "connector_name": state.connector_name,
            "trading_pair": state.trading_pair,
            "available": True,
            "source_event_type": state.event_type,
            "stale": canonical_market_state_is_stale(state, now_ms=now_ms, stale_after_ms=self._stale_after_ms),
            "age_ms": canonical_market_state_age_ms(state, now_ms=now_ms),
            "mid_price": float(state.mid_price) if state.mid_price > _ZERO_D else None,
            "best_bid": float(state.best_bid) if state.best_bid > _ZERO_D else None,
            "best_ask": float(state.best_ask) if state.best_ask > _ZERO_D else None,
            "best_bid_size": float(state.best_bid_size) if state.best_bid_size > _ZERO_D else None,
            "best_ask_size": float(state.best_ask_size) if state.best_ask_size > _ZERO_D else None,
            "market_sequence": int(state.market_sequence or 0) or None,
            "exchange_ts_ms": int(state.exchange_ts_ms or 0) or None,
            "ingest_ts_ms": int(state.ingest_ts_ms or 0) or None,
            "timestamp_ms": int(state.timestamp_ms or 0) or None,
        }

    def get_mid_price(self) -> Decimal:
        state = self.get_market_state()
        if state is not None and state.mid_price > _ZERO_D:
            return state.mid_price
        quote = self.latest_quote()
        bid = _to_decimal(quote.get("best_bid"))
        ask = _to_decimal(quote.get("best_ask"))
        if bid > _ZERO_D and ask > _ZERO_D and ask >= bid:
            return (bid + ask) / Decimal("2")
        return _ZERO_D

    def get_top_of_book(self) -> Optional[MarketTopOfBook]:
        state = self.get_market_state()
        if state is not None and state.has_top_of_book:
            return MarketTopOfBook(
                best_bid=state.best_bid,
                best_ask=state.best_ask,
                spread_pct=state.spread_pct,
                best_bid_size=state.best_bid_size,
                best_ask_size=state.best_ask_size,
            )
        depth = self.latest_depth()
        bids = depth.get("bids", []) if isinstance(depth.get("bids"), list) else []
        asks = depth.get("asks", []) if isinstance(depth.get("asks"), list) else []
        bid_price = _to_decimal(depth.get("best_bid"))
        ask_price = _to_decimal(depth.get("best_ask"))
        bid_size = _ZERO_D
        ask_size = _ZERO_D
        if bids:
            first_bid = bids[0] if isinstance(bids[0], dict) else {}
            bid_price = _to_decimal(first_bid.get("price")) if bid_price <= _ZERO_D else bid_price
            bid_size = _to_decimal(first_bid.get("size"))
        if asks:
            first_ask = asks[0] if isinstance(asks[0], dict) else {}
            ask_price = _to_decimal(first_ask.get("price")) if ask_price <= _ZERO_D else ask_price
            ask_size = _to_decimal(first_ask.get("size"))
        if bid_price <= _ZERO_D or ask_price <= _ZERO_D or ask_price < bid_price:
            quote = self.latest_quote()
            bid_price = _to_decimal(quote.get("best_bid")) if bid_price <= _ZERO_D else bid_price
            ask_price = _to_decimal(quote.get("best_ask")) if ask_price <= _ZERO_D else ask_price
            bid_size = _to_decimal(quote.get("best_bid_size")) if bid_size <= _ZERO_D else bid_size
            ask_size = _to_decimal(quote.get("best_ask_size")) if ask_size <= _ZERO_D else ask_size
        if bid_price <= _ZERO_D or ask_price <= _ZERO_D or ask_price < bid_price:
            return None
        mid = (bid_price + ask_price) / Decimal("2")
        spread_pct = ((ask_price - bid_price) / mid) if mid > _ZERO_D else _ZERO_D
        return MarketTopOfBook(
            best_bid=bid_price,
            best_ask=ask_price,
            spread_pct=spread_pct,
            best_bid_size=bid_size,
            best_ask_size=ask_size,
        )

    def get_depth_imbalance(self, depth: int = 5) -> Decimal:
        snapshot = self.latest_depth()
        bids = snapshot.get("bids", []) if isinstance(snapshot.get("bids"), list) else []
        asks = snapshot.get("asks", []) if isinstance(snapshot.get("asks"), list) else []
        bid_depth = sum(_to_decimal((row or {}).get("size")) for row in bids[: max(1, int(depth))] if isinstance(row, dict))
        ask_depth = sum(_to_decimal((row or {}).get("size")) for row in asks[: max(1, int(depth))] if isinstance(row, dict))
        total = bid_depth + ask_depth
        if total <= _ZERO_D:
            return _ZERO_D
        return (bid_depth - ask_depth) / total

    def latest_payloads(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return self.latest_quote(), self.latest_depth()

    def recent_trade_payloads(self, count: int = 100) -> List[Dict[str, Any]]:
        if not self.enabled:
            return list(self._last_trade_payloads)
        records = self._client.read_recent(MARKET_TRADE_STREAM, count=max(1, int(count)))
        matched: List[Dict[str, Any]] = []
        for entry_id, payload in records:
            if not self._matches(payload) or not self._fresh(payload, entry_id):
                continue
            matched.append(dict(payload))
        if matched:
            # read_recent returns newest first; keep oldest->newest for feature math.
            self._last_trade_payloads = list(reversed(matched))
        return list(self._last_trade_payloads)

    def recent_trades(self, count: int = 100) -> List[MarketTrade]:
        trades: List[MarketTrade] = []
        for payload in self.recent_trade_payloads(count=count):
            price = _to_decimal(payload.get("price"))
            size = _to_decimal(payload.get("size"))
            if price <= _ZERO_D or size <= _ZERO_D:
                continue
            side = str(payload.get("side", "")).strip().lower()
            aggressor_side = str((payload.get("extra") or {}).get("aggressor_side", side)).strip().lower() if isinstance(payload.get("extra"), dict) else side
            if aggressor_side not in {"buy", "sell"}:
                aggressor_side = side if side in {"buy", "sell"} else ""
            delta = size if aggressor_side == "buy" else (-size if aggressor_side == "sell" else _ZERO_D)
            trades.append(
                MarketTrade(
                    trade_id=str(payload.get("trade_id", "") or ""),
                    side=side,
                    price=price,
                    size=size,
                    delta=delta,
                    exchange_ts_ms=int(payload.get("exchange_ts_ms") or 0),
                    ingest_ts_ms=int(payload.get("ingest_ts_ms") or 0),
                    market_sequence=int(payload.get("market_sequence") or 0),
                    aggressor_side=aggressor_side,
                )
            )
        return trades

    def _price_change_pct(self, trades: List[MarketTrade]) -> Decimal:
        if len(trades) < 2:
            return _ZERO_D
        first_price = _to_decimal(trades[0].price)
        last_price = _to_decimal(trades[-1].price)
        if first_price <= _ZERO_D or last_price <= _ZERO_D:
            return _ZERO_D
        return (last_price - first_price) / first_price

    def get_trade_flow_features(
        self,
        *,
        count: int = 120,
        stale_after_ms: Optional[int] = None,
        imbalance_threshold: Decimal = Decimal("2.0"),
    ) -> TradeFlowFeatures:
        trades = self.recent_trades(count=count)
        if not trades:
            return TradeFlowFeatures()

        buy_volume = _ZERO_D
        sell_volume = _ZERO_D
        cvd = _ZERO_D
        latest_ts_ms = 0
        last_price = _ZERO_D
        deltas: List[Decimal] = []
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
        if len(deltas) >= 2:
            last_delta_abs = abs(deltas[-1])
            history = deltas[-6:-1]
            baseline = sum((abs(delta) for delta in history), _ZERO_D) / Decimal(str(len(history)))
            if baseline > _ZERO_D:
                spike_ratio = last_delta_abs / baseline

        now_ms = int(time.time() * 1000)
        stale_limit = int(stale_after_ms or self._stale_after_ms)
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
        stale_after_ms: Optional[int] = None,
        divergence_threshold_pct: Decimal = Decimal("0.15"),
        stacked_imbalance_min: int = 3,
        delta_spike_threshold: Decimal = Decimal("3.0"),
        funding_rate: Optional[Decimal] = None,
        long_funding_max: Decimal = Decimal("0.0005"),
        short_funding_min: Decimal = Decimal("-0.0003"),
    ) -> DirectionalTradeFeatures:
        futures_features = self.get_trade_flow_features(count=futures_count, stale_after_ms=stale_after_ms)
        spot_reader = CanonicalMarketDataReader(
            connector_name=spot_connector_name,
            trading_pair=spot_trading_pair,
            enabled=self._enabled,
            stream_scan_count=self._stream_scan_count,
            stale_after_ms=self._stale_after_ms,
        )
        spot_features = spot_reader.get_trade_flow_features(count=spot_count, stale_after_ms=stale_after_ms)
        futures_trades = self.recent_trades(count=futures_count)
        spot_trades = spot_reader.recent_trades(count=spot_count)
        futures_price_change_pct = self._price_change_pct(futures_trades)
        spot_price_change_pct = spot_reader._price_change_pct(spot_trades)
        divergence_denominator = max(
            abs(futures_features.cvd),
            abs(spot_features.cvd),
            futures_features.buy_volume + futures_features.sell_volume,
            spot_features.buy_volume + spot_features.sell_volume,
            Decimal("1"),
        )
        cvd_divergence_ratio = (spot_features.cvd - futures_features.cvd) / divergence_denominator
        bullish_divergence = (
            (futures_price_change_pct < _ZERO_D and futures_features.cvd > _ZERO_D)
            or cvd_divergence_ratio >= abs(divergence_threshold_pct)
        )
        bearish_divergence = (
            (futures_price_change_pct > _ZERO_D and futures_features.cvd < _ZERO_D)
            or cvd_divergence_ratio <= -abs(divergence_threshold_pct)
        )
        resolved_funding_rate = (
            _to_decimal(funding_rate)
            if funding_rate is not None
            else _to_decimal(self.latest_quote().get("funding_rate"))
        )
        funding_aligned_long = resolved_funding_rate <= long_funding_max
        funding_aligned_short = resolved_funding_rate <= short_funding_min
        funding_bias = "neutral"
        if funding_aligned_short:
            funding_bias = "short"
        elif funding_aligned_long:
            funding_bias = "long"

        long_score = 0
        short_score = 0
        if bullish_divergence:
            long_score += 3
        if bearish_divergence:
            short_score += 3
        if futures_features.stacked_buy_count >= stacked_imbalance_min:
            long_score += 3
        if futures_features.stacked_sell_count >= stacked_imbalance_min:
            short_score += 3
        if funding_aligned_long:
            long_score += 2
        if funding_aligned_short:
            short_score += 2
        if futures_features.delta_spike_ratio >= delta_spike_threshold:
            if futures_features.delta_volume >= _ZERO_D:
                long_score += 1
            else:
                short_score += 1

        return DirectionalTradeFeatures(
            futures=futures_features,
            spot=spot_features,
            futures_price_change_pct=futures_price_change_pct,
            spot_price_change_pct=spot_price_change_pct,
            cvd_divergence_ratio=cvd_divergence_ratio,
            bullish_divergence=bullish_divergence,
            bearish_divergence=bearish_divergence,
            funding_rate=resolved_funding_rate,
            funding_bias=funding_bias,
            funding_aligned_long=funding_aligned_long,
            funding_aligned_short=funding_aligned_short,
            long_score=long_score,
            short_score=short_score,
            stale=bool(futures_features.stale or spot_features.stale),
        )
