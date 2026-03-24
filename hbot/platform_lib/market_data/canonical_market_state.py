from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_ZERO_D = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return _ZERO_D
        return Decimal(str(value))
    except Exception:
        return _ZERO_D


def _to_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except Exception:
        return 0


def _entry_id_ts_ms(entry_id: str) -> int:
    try:
        return int(str(entry_id or "").split("-", 1)[0])
    except Exception:
        return 0


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _normalize_connector(value: Any) -> str:
    return str(value or "").strip().lower()


def _depth_level(levels: Any) -> tuple[Decimal, Decimal]:
    if not isinstance(levels, list) or not levels:
        return _ZERO_D, _ZERO_D
    first = levels[0]
    if isinstance(first, dict):
        return _to_decimal(first.get("price")), _to_decimal(first.get("size"))
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        return _to_decimal(first[0]), _to_decimal(first[1])
    return _ZERO_D, _ZERO_D


def market_payload_freshness_ts_ms(payload: dict[str, Any], *, entry_id: str = "") -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("ingest_ts_ms", "exchange_ts_ms", "timestamp_ms"):
        value = _to_int(payload.get(key))
        if value > 0:
            return value
    return _entry_id_ts_ms(entry_id)


def market_payload_order_key(payload: dict[str, Any], *, entry_id: str = "") -> tuple[int, int, int]:
    if not isinstance(payload, dict):
        return 0, 0, 0
    exchange_ts_ms = _to_int(payload.get("exchange_ts_ms"))
    ingest_ts_ms = _to_int(payload.get("ingest_ts_ms"))
    timestamp_ms = _to_int(payload.get("timestamp_ms"))
    order_ts_ms = exchange_ts_ms or ingest_ts_ms or timestamp_ms or _entry_id_ts_ms(entry_id)
    market_sequence = _to_int(payload.get("market_sequence"))
    published_ts_ms = timestamp_ms or _entry_id_ts_ms(entry_id)
    return order_ts_ms, market_sequence, published_ts_ms


def market_payload_is_fresh(
    payload: dict[str, Any],
    *,
    now_ms: int,
    stale_after_ms: int,
    entry_id: str = "",
) -> bool:
    freshness_ts_ms = market_payload_freshness_ts_ms(payload, entry_id=entry_id)
    return freshness_ts_ms > 0 and max(0, int(now_ms) - freshness_ts_ms) <= max(1, int(stale_after_ms))


def canonical_market_state_age_ms(state: CanonicalMarketState, *, now_ms: int) -> int:
    freshness_ts_ms = int(getattr(state, "freshness_ts_ms", 0) or 0)
    timestamp_ms = int(getattr(state, "timestamp_ms", 0) or 0)
    reference_ts_ms = freshness_ts_ms or timestamp_ms
    if reference_ts_ms <= 0:
        return max(1, int(now_ms))
    return max(0, int(now_ms) - reference_ts_ms)


def canonical_market_state_is_stale(
    state: CanonicalMarketState,
    *,
    now_ms: int,
    stale_after_ms: int,
) -> bool:
    return canonical_market_state_age_ms(state, now_ms=now_ms) > max(1, int(stale_after_ms))


@dataclass(frozen=True)
class CanonicalMarketState:
    event_type: str
    event_id: str
    instance_name: str
    connector_name: str
    trading_pair: str
    timestamp_ms: int
    freshness_ts_ms: int
    exchange_ts_ms: int
    ingest_ts_ms: int
    market_sequence: int
    best_bid: Decimal
    best_ask: Decimal
    best_bid_size: Decimal
    best_ask_size: Decimal
    mid_price: Decimal
    last_trade_price: Decimal
    mark_price: Decimal
    funding_rate: Decimal
    entry_id: str = ""

    @property
    def has_top_of_book(self) -> bool:
        return self.best_bid > _ZERO_D and self.best_ask > _ZERO_D and self.best_ask >= self.best_bid

    @property
    def spread_pct(self) -> Decimal:
        if not self.has_top_of_book:
            return _ZERO_D
        mid = self.mid_price if self.mid_price > _ZERO_D else (self.best_bid + self.best_ask) / Decimal("2")
        if mid <= _ZERO_D:
            return _ZERO_D
        return (self.best_ask - self.best_bid) / mid

    @property
    def order_key(self) -> tuple[int, int, int]:
        return market_payload_order_key(
            {
                "exchange_ts_ms": self.exchange_ts_ms,
                "ingest_ts_ms": self.ingest_ts_ms,
                "timestamp_ms": self.timestamp_ms,
                "market_sequence": self.market_sequence,
            },
            entry_id=self.entry_id,
        )


def parse_canonical_market_state(payload: dict[str, Any], *, entry_id: str = "") -> CanonicalMarketState | None:
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("event_type", "")).strip().lower()
    if event_type not in {"market_quote", "market_snapshot", "market_depth_snapshot"}:
        return None

    connector_name = _normalize_connector(payload.get("connector_name"))
    trading_pair = _normalize_pair(payload.get("trading_pair"))
    if not connector_name or not trading_pair:
        return None

    best_bid = _to_decimal(payload.get("best_bid"))
    best_ask = _to_decimal(payload.get("best_ask"))
    if event_type == "market_depth_snapshot":
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        depth_bid, depth_bid_size = _depth_level(bids)
        depth_ask, depth_ask_size = _depth_level(asks)
        if best_bid <= _ZERO_D:
            best_bid = depth_bid
        if best_ask <= _ZERO_D:
            best_ask = depth_ask
    mid_price = _to_decimal(payload.get("mid_price"))
    if mid_price <= _ZERO_D and best_bid > _ZERO_D and best_ask > _ZERO_D and best_ask >= best_bid:
        mid_price = (best_bid + best_ask) / Decimal("2")

    best_bid_size = _to_decimal(payload.get("best_bid_size"))
    best_ask_size = _to_decimal(payload.get("best_ask_size"))
    if event_type == "market_depth_snapshot":
        if best_bid_size <= _ZERO_D:
            best_bid_size = depth_bid_size
        if best_ask_size <= _ZERO_D:
            best_ask_size = depth_ask_size

    return CanonicalMarketState(
        event_type=event_type,
        event_id=str(payload.get("event_id", "") or ""),
        instance_name=str(payload.get("instance_name", "") or ""),
        connector_name=connector_name,
        trading_pair=trading_pair,
        timestamp_ms=_to_int(payload.get("timestamp_ms")) or _entry_id_ts_ms(entry_id),
        freshness_ts_ms=market_payload_freshness_ts_ms(payload, entry_id=entry_id),
        exchange_ts_ms=_to_int(payload.get("exchange_ts_ms")),
        ingest_ts_ms=_to_int(payload.get("ingest_ts_ms")),
        market_sequence=_to_int(payload.get("market_sequence")),
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=best_bid_size,
        best_ask_size=best_ask_size,
        mid_price=mid_price,
        last_trade_price=_to_decimal(payload.get("last_trade_price")),
        mark_price=_to_decimal(payload.get("mark_price")),
        funding_rate=_to_decimal(payload.get("funding_rate")),
        entry_id=str(entry_id or ""),
    )
