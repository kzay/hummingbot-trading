from __future__ import annotations

from scripts.utils.event_store_count_check import STREAMS, _group_lag_from_xinfo_groups
from platform_lib.contracts.stream_names import MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM


def test_event_store_count_check_includes_high_volume_market_streams() -> None:
    assert MARKET_QUOTE_STREAM in STREAMS
    assert MARKET_DEPTH_STREAM in STREAMS


def test_group_lag_from_xinfo_groups_extracts_matching_group_lag() -> None:
    lag = _group_lag_from_xinfo_groups(
        [
            {"name": "other", "lag": 99},
            {"name": "hb_event_store_v1", "lag": 2},
        ],
        "hb_event_store_v1",
    )
    assert lag == 2
