"""Tests for paper_engine_v2 PaperDesk orchestrator.

Covers: multi-instrument, multi-bot routing, cancel_all,
event log, state persistence round-trip, determinism.
"""
import time
from decimal import Decimal

import pytest

from simulation.config import PaperEngineConfig
from simulation.data_feeds import StaticDataFeed
from simulation.desk import DeskConfig, PaperDesk
from simulation.risk_engine import LiquidationAction, MarginLevel
from simulation.types import (
    OrderAccepted,
    OrderFilled,
    OrderRejected,
    OrderSide,
    PaperOrderType,
)
from tests.controllers.test_paper_engine_v2.conftest import (
    BTC_PERP,
    BTC_SPOT,
    ETH_SPOT,
    make_book,
    make_spec,
)


def make_desk(tmp_path=None, usdt="10000", seed=7) -> PaperDesk:
    state_path = str(tmp_path / "desk.json") if tmp_path else "/tmp/test_desk.json"
    return PaperDesk(DeskConfig(
        initial_balances={"USDT": Decimal(usdt)},
        state_file_path=state_path,
        seed=seed,
        event_log_max_size=1000,
    ))


class TestDeskRegistration:
    def test_register_and_submit(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        book = make_book()
        feed = StaticDataFeed(book)
        desk.register_instrument(spec, feed)

        event = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
            Decimal("99.95"), Decimal("0.1"), source_bot="bot1",
        )
        assert isinstance(event, OrderAccepted)

    def test_submit_unregistered_rejects(self, tmp_path):
        desk = make_desk(tmp_path)
        event = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
            Decimal("99.95"), Decimal("0.1"),
        )
        assert isinstance(event, OrderRejected)
        assert "not_registered" in event.reason


class TestMultiInstrument:
    def test_two_instruments_ticked(self, tmp_path):
        """Both instruments registered and ticked. Orders accepted (even if no fill yet)."""
        desk = make_desk(tmp_path)
        spec_btc = make_spec(BTC_SPOT)
        spec_eth = make_spec(ETH_SPOT)
        desk.register_instrument(spec_btc, StaticDataFeed(make_book(iid=BTC_SPOT)))
        desk.register_instrument(spec_eth, StaticDataFeed(make_book("2000", "2001", iid=ETH_SPOT)))

        e1 = desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        e2 = desk.submit_order(ETH_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("1999"), Decimal("0.1"))

        # Both should be accepted
        assert isinstance(e1, OrderAccepted)
        assert isinstance(e2, OrderAccepted)
        # Tick drives both engines (even if no fills — orders are behind spread)
        events = desk.tick()
        # At minimum, the tick completes without error
        assert isinstance(events, list)


class TestMultiBotRouting:
    def test_orders_from_different_bots(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))

        e1 = desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                                Decimal("99.95"), Decimal("0.1"), source_bot="bot1")
        e2 = desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                                Decimal("99.90"), Decimal("0.1"), source_bot="bot2")
        assert isinstance(e1, OrderAccepted)
        assert isinstance(e2, OrderAccepted)


class TestCancelAll:
    def test_cancel_all_instruments(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.90"), Decimal("0.1"))
        events = desk.cancel_all()
        from simulation.types import OrderCanceled
        assert sum(1 for e in events if isinstance(e, OrderCanceled)) == 2

    def test_cancel_all_for_instrument(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        events = desk.cancel_all(instrument_id=BTC_SPOT)
        from simulation.types import OrderCanceled
        assert any(isinstance(e, OrderCanceled) for e in events)


class TestEventLog:
    def test_events_logged(self, tmp_path):
        desk = make_desk(tmp_path)
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1"))
        assert len(desk.event_log()) >= 1
        assert isinstance(desk.event_log()[0], OrderAccepted)


class TestStatePersistence:
    def test_persist_and_restore(self, tmp_path):
        desk = make_desk(tmp_path, usdt="5000")
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))
        # Force save
        desk._state_store.save(desk.snapshot(), now_ts=0.0, force=True)

        # New desk restores from file
        desk2 = make_desk(tmp_path, usdt="9999")
        assert desk2.portfolio.balance("USDT") == Decimal("5000")

    def test_order_counter_persists_across_restart(self, tmp_path):
        desk = make_desk(tmp_path, usdt="5000")
        spec = make_spec(BTC_SPOT)
        desk.register_instrument(spec, StaticDataFeed(make_book()))

        first = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.95"), Decimal("0.1")
        )
        second = desk.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.90"), Decimal("0.1")
        )
        assert isinstance(first, OrderAccepted)
        assert isinstance(second, OrderAccepted)
        pre_restart_counter = int(str(second.order_id).split("_")[-1])
        assert desk.snapshot()["order_counter"] == pre_restart_counter

        desk._state_store.save(desk.snapshot(), now_ts=0.0, force=True)

        restored = make_desk(tmp_path, usdt="9999")
        restored.register_instrument(spec, StaticDataFeed(make_book()))
        third = restored.submit_order(
            BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER, Decimal("99.85"), Decimal("0.1")
        )
        assert isinstance(third, OrderAccepted)
        post_restart_counter = int(str(third.order_id).split("_")[-1])
        assert post_restart_counter > pre_restart_counter


class TestDeterminism:
    def test_same_seed_same_events(self, tmp_path):
        """Same seed + same book → identical fill sequence."""
        def run_once():
            desk = make_desk(tmp_path, seed=7)
            spec = make_spec(BTC_SPOT)
            desk.register_instrument(spec, StaticDataFeed(make_book()))
            desk.submit_order(BTC_SPOT, OrderSide.BUY, PaperOrderType.LIMIT_MAKER,
                              Decimal("99.95"), Decimal("1.0"), source_bot="bot1")
            now = int(time.time() * 1e9)
            for i in range(5):
                desk.tick(now_ns=now + i * 200_000_000)
            return [(type(e).__name__, str(getattr(e, "fill_quantity", "")))
                    for e in desk.event_log()]

        r1 = run_once()
        r2 = run_once()
        assert r1 == r2


class TestRiskLiquidationExecution:
    def test_desk_executes_liquidation_actions(self, tmp_path):
        desk = make_desk(tmp_path, usdt="1000")
        spec = make_spec(BTC_PERP, size_inc="0.001", min_qty="0.001", min_notional="5")
        desk.register_instrument(spec, StaticDataFeed(make_book(iid=BTC_PERP, bid_size="5.0", ask_size="5.0")))
        desk.portfolio.settle_fill(
            instrument_id=BTC_PERP,
            side=OrderSide.BUY,
            quantity=Decimal("2.0"),
            price=Decimal("100"),
            fee=Decimal("0"),
            source_bot="test",
            now_ns=int(time.time() * 1e9),
            spec=spec,
            leverage=1,
        )

        def _forced_eval(_prices):
            return MarginLevel.LIQUIDATE, [
                LiquidationAction(
                    instrument_id=BTC_PERP,
                    side=OrderSide.SELL,
                    quantity=Decimal("1.0"),
                    reason="margin_liquidation_reduce",
                    level=MarginLevel.LIQUIDATE,
                )
            ]

        desk.portfolio.evaluate_risk = _forced_eval  # type: ignore[method-assign]
        events = desk.tick()
        forced_fills = [e for e in events if isinstance(e, OrderFilled) and str(e.order_id).startswith("liq_")]
        assert forced_fills
        assert desk.portfolio.get_position(BTC_PERP).abs_quantity <= Decimal("1.0")


class TestLatencyDefaultFromConfig:
    def test_paper_engine_config_requires_nested_block(self):
        class _Cfg:
            pass

        with pytest.raises(ValueError):
            PaperEngineConfig.from_controller_config(_Cfg())

    def test_paper_engine_config_from_nested_block(self):
        class _Cfg:
            paper_engine = {
                "paper_fill_model": "three_tier",
                "paper_latency_ms": 123,
                "instance_name": "botx",
                "variant": "a",
                "log_dir": "/tmp",
            }

        paper_cfg = PaperEngineConfig.from_controller_config(_Cfg())
        assert paper_cfg.paper_fill_model == "three_tier"
        assert paper_cfg.paper_latency_ms == 123

    def test_paper_engine_config_inherits_identity_from_controller_when_missing(self, tmp_path):
        class _Cfg:
            instance_name = "bot3"
            variant = "z"
            log_dir = str(tmp_path)
            paper_engine = {
                "paper_fill_model": "three_tier",
                "paper_latency_ms": 77,
            }

        paper_cfg = PaperEngineConfig.from_controller_config(_Cfg())
        assert paper_cfg.instance_name == "bot3"
        assert paper_cfg.variant == "z"
        assert paper_cfg.log_dir == str(tmp_path)

    def test_paper_engine_config_defaults_artifact_namespace_from_controller_name(self):
        class _RuntimeCfg:
            controller_name = "bot5_ift_jota_v1"
            paper_engine = {
                "paper_fill_model": "three_tier",
                "paper_latency_ms": 77,
            }

        class _LegacyCfg:
            controller_name = "epp_v2_4_bot5"
            paper_engine = {
                "paper_fill_model": "three_tier",
                "paper_latency_ms": 77,
            }

        runtime_cfg = PaperEngineConfig.from_controller_config(_RuntimeCfg())
        legacy_cfg = PaperEngineConfig.from_controller_config(_LegacyCfg())
        assert runtime_cfg.artifact_namespace == "runtime_v24"
        assert legacy_cfg.artifact_namespace == "epp_v24"

    def test_from_paper_config_uses_new_config_model(self, tmp_path):
        paper_cfg = PaperEngineConfig(
            paper_equity_quote=Decimal("700"),
            paper_reset_state_on_startup=True,
            paper_seed=11,
            paper_fill_model="three_tier",
            paper_latency_model="configured_latency_ms",
            paper_latency_ms=130,
            paper_insert_latency_ms=15,
            paper_cancel_latency_ms=60,
            paper_queue_position_enabled=True,
            paper_price_protection_points=5,
            paper_margin_model_type="standard",
            instance_name="botx",
            variant="a",
            log_dir=str(tmp_path),
            artifact_namespace="runtime_v24",
        )
        desk = PaperDesk.from_paper_config(paper_cfg)
        cfg = desk._config
        assert cfg.default_fill_model == "three_tier"
        assert cfg.default_engine_config.latency_ms == 130
        assert cfg.default_engine_config.price_protection_points == 5
        assert cfg.portfolio_config.margin_model_type == "standard"
        assert cfg.reset_state_on_startup is True
        assert "/runtime_v24/" in cfg.state_file_path.replace("\\", "/")

    def test_from_controller_config_uses_configured_latency_model(self, tmp_path):
        class _Cfg:
            paper_engine = {
                "paper_equity_quote": Decimal("500"),
                "paper_seed": 7,
                "paper_latency_ms": 150,
                "paper_max_fills_per_order": 8,
                "instance_name": "botx",
                "variant": "a",
                "log_dir": str(tmp_path),
            }

        desk = PaperDesk.from_controller_config(_Cfg())
        assert desk._config.default_latency_model == "configured_latency_ms"

    def test_from_controller_config_maps_fill_and_liquidity_knobs(self, tmp_path):
        class _Cfg:
            paper_engine = {
                "paper_equity_quote": Decimal("500"),
                "paper_seed": 7,
                "paper_fill_model": "two_tier",
                "paper_latency_model": "configured_latency_ms",
                "paper_latency_ms": 120,
                "paper_insert_latency_ms": 10,
                "paper_cancel_latency_ms": 80,
                "paper_queue_participation": Decimal("0.40"),
                "paper_slippage_bps": Decimal("0.8"),
                "paper_adverse_selection_bps": Decimal("1.2"),
                "paper_prob_fill_on_limit": 0.55,
                "paper_prob_slippage": 0.10,
                "paper_partial_fill_min_ratio": Decimal("0.2"),
                "paper_partial_fill_max_ratio": Decimal("0.9"),
                "paper_depth_levels": 5,
                "paper_depth_decay": Decimal("0.6"),
                "paper_liquidity_consumption": True,
                "paper_max_fills_per_order": 9,
                "fee_profile": "vip0",
                "instance_name": "botx",
                "variant": "a",
                "log_dir": str(tmp_path),
            }

        desk = PaperDesk.from_controller_config(_Cfg())
        cfg = desk._config
        assert cfg.default_fill_model == "two_tier"
        assert cfg.default_latency_model == "configured_latency_ms"
        assert cfg.insert_latency_ms == 10
        assert cfg.cancel_latency_ms == 80
        assert cfg.fill_depth_levels == 5
        assert cfg.fill_depth_decay == Decimal("0.6")
        assert cfg.fill_queue_position_enabled is False
        assert cfg.fill_prob_fill_on_limit == pytest.approx(0.55)
        assert cfg.fill_prob_slippage == pytest.approx(0.10)
        assert cfg.default_engine_config.liquidity_consumption is True
        assert cfg.default_engine_config.max_fills_per_order == 9

    def test_realism_profile_balanced_overrides_manual_knobs(self, tmp_path):
        class _Cfg:
            paper_engine = {
                "paper_realism_profile": "balanced",
                "paper_equity_quote": Decimal("500"),
                "paper_seed": 7,
                "paper_fill_model": "best_price",  # should be overridden
                "paper_latency_model": "none",     # should be overridden
                "paper_latency_ms": 999,           # should be overridden
                "paper_insert_latency_ms": 0,
                "paper_cancel_latency_ms": 0,
                "paper_queue_participation": Decimal("0.9"),
                "paper_slippage_bps": Decimal("9"),
                "paper_adverse_selection_bps": Decimal("9"),
                "paper_partial_fill_min_ratio": Decimal("0.9"),
                "paper_partial_fill_max_ratio": Decimal("0.9"),
                "paper_depth_levels": 1,
                "paper_depth_decay": Decimal("1"),
                "paper_liquidity_consumption": False,
                "paper_max_fills_per_order": 8,
                "fee_profile": "vip0",
                "instance_name": "botx",
                "variant": "a",
                "log_dir": str(tmp_path),
            }

        desk = PaperDesk.from_controller_config(_Cfg())
        cfg = desk._config
        assert cfg.default_fill_model == "latency_aware"
        assert cfg.default_latency_model == "configured_latency_ms"
        assert cfg.default_engine_config.latency_ms == 150
        assert cfg.insert_latency_ms == 20
        assert cfg.cancel_latency_ms == 80
        assert cfg.fill_depth_levels == 5
        assert cfg.fill_queue_position_enabled is True
        assert cfg.fill_prob_fill_on_limit == pytest.approx(0.40)
        assert cfg.fill_prob_slippage == pytest.approx(0.02)
        assert cfg.default_engine_config.price_protection_points == 8
        assert cfg.portfolio_config.margin_model_type == "leveraged"
        assert cfg.default_engine_config.liquidity_consumption is True

    def test_from_epp_config_aliases_controller_constructor(self, tmp_path):
        class _Cfg:
            paper_engine = {
                "paper_equity_quote": Decimal("500"),
                "paper_seed": 7,
                "paper_latency_ms": 150,
                "paper_max_fills_per_order": 8,
                "instance_name": "botx",
                "variant": "a",
                "log_dir": str(tmp_path),
            }

        desk = PaperDesk.from_epp_config(_Cfg())
        assert desk._config.default_latency_model == "configured_latency_ms"
