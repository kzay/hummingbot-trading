"""Tests for data catalog event publishing."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from controllers.backtesting.data_catalog_events import publish_catalog_update


class TestPublishCatalogUpdate:
    def test_publishes_valid_event(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "1234-0"

        result = publish_catalog_update(
            mock_redis,
            exchange="bitget",
            pair="BTC-USDT",
            resolution="1m",
            start_ms=1000,
            end_ms=2000,
            row_count=100,
            gaps_found=2,
            gaps_repaired=1,
        )

        assert result == "1234-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = json.loads(call_args[0][1]["data"])
        assert payload["event_type"] == "data_catalog_updated"
        assert payload["exchange"] == "bitget"
        assert payload["pair"] == "BTC-USDT"
        assert payload["resolution"] == "1m"
        assert payload["gaps_found"] == 2
        assert payload["gaps_repaired"] == 1
        assert "timestamp_ms" in payload

    def test_none_redis_returns_none(self) -> None:
        result = publish_catalog_update(
            None,
            exchange="bitget",
            pair="BTC-USDT",
            resolution="1m",
            start_ms=1000,
            end_ms=2000,
            row_count=100,
        )
        assert result is None

    def test_xadd_failure_returns_none(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = ConnectionError("Redis down")

        result = publish_catalog_update(
            mock_redis,
            exchange="bitget",
            pair="BTC-USDT",
            resolution="1m",
            start_ms=1000,
            end_ms=2000,
            row_count=100,
        )
        assert result is None
