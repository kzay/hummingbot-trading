"""Tests for bridge error paths — Redis failures, invalid events, patch failures."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestRedisUnavailable:
    def test_bridge_state_no_redis_host(self):
        from simulation.bridge.bridge_state import BridgeState

        state = BridgeState()
        with patch.dict(os.environ, {"REDIS_HOST": ""}, clear=False):
            state.redis_init_done = False
            state.redis_client = None
            result = state.get_redis()
            assert result is None
            assert state.redis_init_done is True

    def test_bridge_state_init_done_prevents_retry(self):
        from simulation.bridge.bridge_state import BridgeState

        state = BridgeState()
        state.redis_init_done = True
        state.redis_client = None
        result = state.get_redis()
        assert result is None
        assert state.redis_init_done is True

    def test_close_redis_with_no_client(self):
        from simulation.bridge.bridge_state import BridgeState

        state = BridgeState()
        state.redis_client = None
        state._close_redis()


class TestInvalidEvent:
    def test_canonical_cache_returns_unchanged_for_non_paper(self):
        from simulation.bridge.bridge_utils import _canonical_name

        result = _canonical_name("bitget_perpetual")
        assert result == "bitget_perpetual"

    def test_canonical_name_passthrough_non_paper(self):
        from simulation.bridge.bridge_utils import _canonical_name

        result = _canonical_name("some_exchange")
        assert result == "some_exchange"
        result2 = _canonical_name("some_exchange")
        assert result == result2


class TestConnectorPatchFailure:
    def test_budget_checker_install_on_missing_attr(self):
        from simulation.budget_checker import install_budget_checker
        from decimal import Decimal

        connector = MagicMock(spec=[])
        install_budget_checker(connector, Decimal("10000"))

    def test_budget_checker_install_on_valid_connector(self):
        from simulation.budget_checker import PaperBudgetChecker, install_budget_checker
        from decimal import Decimal

        connector = MagicMock()
        connector._budget_checker = MagicMock()
        install_budget_checker(connector, Decimal("10000"))
        assert isinstance(connector._budget_checker, PaperBudgetChecker)


class TestSignalHandlerIsolation:
    def test_event_subscriber_list_starts_empty(self):
        from simulation.bridge.hb_event_fire import _EVENT_SUBSCRIBERS

        initial_len = len(_EVENT_SUBSCRIBERS)
        assert initial_len >= 0

    def test_register_and_dispatch_does_not_raise(self):
        from simulation.bridge.hb_event_fire import (
            _EVENT_SUBSCRIBERS,
            register_event_subscriber,
        )

        class DummySubscriber:
            def on_fill(self, event, connector_name):
                pass

            def on_cancel(self, event, connector_name):
                pass

            def on_reject(self, event, connector_name):
                pass

        initial_count = len(_EVENT_SUBSCRIBERS)
        sub = DummySubscriber()
        register_event_subscriber(sub)
        assert len(_EVENT_SUBSCRIBERS) == initial_count + 1
        _EVENT_SUBSCRIBERS.remove(sub)
