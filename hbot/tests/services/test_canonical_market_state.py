from __future__ import annotations

from decimal import Decimal

from platform_lib.market_data.canonical_market_state import (
    canonical_market_state_age_ms,
    canonical_market_state_is_stale,
    parse_canonical_market_state,
)


def test_parse_canonical_market_state_accepts_depth_snapshot_and_derives_l1() -> None:
    state = parse_canonical_market_state(
        {
            "event_type": "market_depth_snapshot",
            "event_id": "depth-1",
            "instance_name": "bot1",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "timestamp_ms": 1_000,
            "exchange_ts_ms": 950,
            "ingest_ts_ms": 990,
            "market_sequence": 7,
            "bids": [{"price": 99.5, "size": 2.0}],
            "asks": [{"price": 100.5, "size": 1.5}],
        }
    )
    assert state is not None
    assert state.event_type == "market_depth_snapshot"
    assert state.best_bid == Decimal("99.5")
    assert state.best_ask == Decimal("100.5")
    assert state.best_bid_size == Decimal("2.0")
    assert state.best_ask_size == Decimal("1.5")
    assert state.mid_price == Decimal("100.0")
    assert state.has_top_of_book is True


def test_canonical_market_state_age_and_staleness_use_freshness_timestamp() -> None:
    state = parse_canonical_market_state(
        {
            "event_type": "market_quote",
            "event_id": "quote-1",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "timestamp_ms": 1_000,
            "exchange_ts_ms": 1_010,
            "ingest_ts_ms": 1_020,
            "best_bid": 99.0,
            "best_ask": 101.0,
        }
    )
    assert state is not None
    assert canonical_market_state_age_ms(state, now_ms=1_070) == 50
    assert canonical_market_state_is_stale(state, now_ms=1_070, stale_after_ms=60) is False
    assert canonical_market_state_is_stale(state, now_ms=1_090, stale_after_ms=60) is True
