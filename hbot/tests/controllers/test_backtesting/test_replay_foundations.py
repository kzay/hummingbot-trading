from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from controllers.backtesting.hb_stubs import install_hb_stubs
from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.replay_injection import ReplayInjection


class TestReplayClock:
    def test_init_exposes_consistent_time_units(self):
        clock = ReplayClock(1_700_000_000_123_456_789)

        assert clock.now_ns == 1_700_000_000_123_456_789
        assert clock.now_ms == 1_700_000_000_123
        assert clock.time() == pytest.approx(1_700_000_000.1234567)

    def test_advance_updates_all_views(self):
        clock = ReplayClock(1_000)

        result = clock.advance(59_000_000_000)

        assert result == 59_000_001_000
        assert clock.now_ns == 59_000_001_000
        assert clock.now_ms == 59_000
        assert clock.time() == pytest.approx(59.000001)


class TestHbStubs:
    def test_pullback_controller_imports_with_stubs(self):
        install_hb_stubs()

        module = importlib.import_module("controllers.bots.bot7.pullback_v1")

        assert module.PullbackV1Controller.__name__ == "PullbackV1Controller"
        assert module.PullbackV1Config.__name__ == "PullbackV1Config"


class TestReplayInjection:
    def test_apply_replaces_primary_runtime_dependencies(self):
        runtime_adapter = SimpleNamespace(
            _canonical_market_reader="old-reader",
            _cached_connector=None,
            _aux_market_readers={"old": "reader"},
        )
        strategy = SimpleNamespace()
        controller = SimpleNamespace(
            config=SimpleNamespace(connector_name="bitget_perpetual"),
            _runtime_adapter=runtime_adapter,
            _trade_reader="live-reader",
            market_data_provider="live-mdp",
            connectors={},
            strategy=strategy,
            _strategy=None,
        )

        replay_reader = object()
        replay_connector = object()
        replay_mdp = object()

        ReplayInjection.apply(
            controller,
            trade_reader=replay_reader,
            replay_connector=replay_connector,
            market_data_provider=replay_mdp,
        )

        assert controller._trade_reader is replay_reader
        assert controller.market_data_provider is replay_mdp
        assert controller.connectors == {"bitget_perpetual": replay_connector}
        assert runtime_adapter._canonical_market_reader is replay_reader
        assert runtime_adapter._cached_connector is replay_connector
        assert runtime_adapter._aux_market_readers == {}
        assert strategy.connectors == {"bitget_perpetual": replay_connector}
        assert strategy.market_data_provider is replay_mdp

    def test_apply_can_patch_aux_reader_factory(self):
        runtime_adapter = SimpleNamespace(
            _canonical_market_reader=None,
            _cached_connector=None,
            _aux_market_readers={},
        )
        controller = SimpleNamespace(
            config=SimpleNamespace(connector_name="bitget_perpetual"),
            _runtime_adapter=runtime_adapter,
            _trade_reader=None,
            market_data_provider=None,
            connectors={},
            strategy=None,
            _strategy=None,
        )
        lookups: list[tuple[str, str]] = []

        def reader_factory(connector_name: str, trading_pair: str):
            lookups.append((connector_name, trading_pair))
            return f"{connector_name}:{trading_pair}"

        ReplayInjection.apply(
            controller,
            trade_reader=object(),
            replay_connector=object(),
            market_data_provider=object(),
            aux_readers={"cached": "value"},
            reader_factory=reader_factory,
        )

        assert runtime_adapter._aux_market_readers == {"cached": "value"}
        assert runtime_adapter._reader_for("spot", "BTC-USDT") == "spot:BTC-USDT"
        assert lookups == [("spot", "BTC-USDT")]
