from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from controllers.backtesting.data_catalog import DataCatalog
from controllers.backtesting.data_store import save_candles, save_funding_rates, save_trades
from controllers.backtesting.replay_harness import ReplayHarness
from controllers.backtesting.types import CandleRow, FundingRow, TradeRow
from platform_lib.core.daily_state_store import DailyStateStore
from simulation.bridge import hb_bridge
from simulation.bridge.signal_consumer import _check_hard_stop_transitions, _consume_signals
from simulation.types import OrderSide


def _write_replay_datasets(base_dir: Path) -> None:
    base_ms = int(datetime(2023, 11, 13, 23, 58, tzinfo=UTC).timestamp() * 1000)
    candles = [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
        )
        for i in range(12)
    ]
    trades = [
        TradeRow(
            timestamp_ms=base_ms + i * 60_000,
            side="buy" if i % 2 == 0 else "sell",
            price=Decimal("100") + Decimal(str(i)),
            size=Decimal("1"),
            trade_id=f"t{i}",
        )
        for i in range(12)
    ]
    funding = [
        FundingRow(timestamp_ms=base_ms, rate=Decimal("0.0001")),
        FundingRow(timestamp_ms=base_ms + 180_000, rate=Decimal("-0.0002")),
    ]

    candles_path = base_dir / "bitget" / "BTC-USDT" / "1m" / "data.parquet"
    trades_path = base_dir / "bitget" / "BTC-USDT" / "trades" / "data.parquet"
    funding_path = base_dir / "bitget" / "BTC-USDT" / "funding" / "data.parquet"
    save_candles(candles, candles_path)
    save_trades(trades, trades_path)
    save_funding_rates(funding, funding_path)

    catalog = DataCatalog(base_dir)
    catalog.register("bitget", "BTC-USDT", "1m", candles[0].timestamp_ms, candles[-1].timestamp_ms, len(candles), str(candles_path), candles_path.stat().st_size)
    catalog.register("bitget", "BTC-USDT", "trades", trades[0].timestamp_ms, trades[-1].timestamp_ms, len(trades), str(trades_path), trades_path.stat().st_size)
    catalog.register("bitget", "BTC-USDT", "funding", funding[0].timestamp_ms, funding[-1].timestamp_ms, len(funding), str(funding_path), funding_path.stat().st_size)


def _write_config(path: Path, catalog_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "mode: replay",
                "strategy_module: controllers.bots.bot7.pullback_v1",
                "strategy_class: PullbackV1Controller",
                "strategy_config:",
                "  id: replay_bot7",
                "  controller_name: bot7_pullback_v1",
                "  connector_name: bitget_perpetual",
                "  trading_pair: BTC-USDT",
                "  candles_connector: bitget_perpetual",
                "  candles_trading_pair: BTC-USDT",
                "  fee_mode: manual",
                "  bot_mode: paper",
                "  log_dir: /tmp",
                "data:",
                "  exchange: bitget",
                "  pair: BTC-USDT",
                "  instrument_type: perp",
                f"  catalog_dir: {catalog_dir.as_posix()}",
                "  candles_resolution: 1m",
                "start_date: '2023-11-14'",
                "end_date: '2023-11-14'",
                "step_interval_s: 60",
                "warmup_bars: 2",
                "initial_equity: 500",
                "seed: 7",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _prepare_context(tmp_path: Path):
    _write_replay_datasets(tmp_path)
    config_path = tmp_path / "replay.yml"
    _write_config(config_path, tmp_path)
    return ReplayHarness.from_path(config_path).prepare()


def _strategy_with_controller() -> SimpleNamespace:
    controller = SimpleNamespace(
        config=SimpleNamespace(instance_name="bot1", connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        id="ctrl-1",
    )
    return SimpleNamespace(controllers={"ctrl-1": controller}, _paper_desk_v2_bridges={})


class TestReplayEnvironmentVerification:
    def test_redis_host_empty_uses_safe_no_redis_fallbacks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_HOST", "")
        bridge_state = hb_bridge.BridgeState()
        assert bridge_state.get_redis() is None

        store = DailyStateStore(
            file_path=str(tmp_path / "daily_state.json"),
            redis_key="replay:test",
            redis_url=None,
            save_throttle_s=0.0,
        )
        store.save({"position_base": "0.1"}, now_ts=1_700_000_000.0, force=True)
        assert store.load()["position_base"] == "0.1"

        strategy = _strategy_with_controller()
        _consume_signals(strategy, bridge_state)
        _check_hard_stop_transitions(strategy, bridge_state)

        previous_client = hb_bridge._bridge_state.redis_client
        previous_init_done = hb_bridge._bridge_state.redis_init_done
        hb_bridge._bridge_state.redis_client = None
        hb_bridge._bridge_state.redis_init_done = True
        try:
            hb_bridge._consume_paper_exchange_events(strategy)
        finally:
            hb_bridge._bridge_state.redis_client = previous_client
            hb_bridge._bridge_state.redis_init_done = previous_init_done

    def test_replay_controller_portfolio_guard_noops_without_telemetry_redis(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("REDIS_HOST", "")
        ctx = _prepare_context(tmp_path)

        ctx.controller.config.portfolio_risk_guard_enabled = True
        ctx.controller.config.portfolio_risk_guard_check_s = 0
        ctx.controller._last_portfolio_risk_check_ts = 0.0
        ctx.controller._portfolio_risk_hard_stop_latched = False

        ctx.controller._check_portfolio_risk_guard(ctx.clock.time())

        assert ctx.controller._portfolio_risk_hard_stop_latched is False

    def test_paper_exchange_disabled_skips_command_publish_and_sync(self, monkeypatch) -> None:
        monkeypatch.setenv("PAPER_EXCHANGE_MODE", "disabled")
        strategy = _strategy_with_controller()

        monkeypatch.setattr(
            hb_bridge,
            "_get_signal_redis",
            lambda: (_ for _ in ()).throw(AssertionError("disabled mode should not request Redis")),
        )
        hb_bridge._bridge_state.sync_state_published_keys.clear()

        result = hb_bridge._publish_paper_exchange_command(
            strategy,
            connector_name="bitget_perpetual",
            trading_pair="BTC-USDT",
            command="submit_order",
        )
        hb_bridge._ensure_sync_state_command(strategy, "bitget_perpetual", "BTC-USDT")

        assert result is None
        assert hb_bridge._bridge_state.sync_state_published_keys == set()

    def test_executor_margin_and_startup_sync_paths_work_with_replay_surfaces(self, tmp_path: Path) -> None:
        ctx = _prepare_context(tmp_path)
        controller = ctx.controller

        controller.executors_info = [SimpleNamespace(id="ex-1", is_active=True)]
        pending_before = len(controller._pending_stale_cancel_actions)
        controller._enqueue_force_derisk_executor_cancels()
        assert len(controller._pending_stale_cancel_actions) == pending_before + 1

        close_actions_before = len(controller._pb_pending_actions)
        controller._emit_close_action(Decimal("0.01"), "buy", "pb_test_close", order_type="MARKET")
        assert len(controller._pb_pending_actions) == close_actions_before

        controller.config.leverage = 5
        controller._margin_ratio = Decimal("0")
        controller._refresh_margin_ratio(Decimal("50000"), Decimal("0.5"), Decimal("5000"))
        assert abs(controller._margin_ratio - Decimal("1")) < Decimal("0.000001")

        ctx.desk.portfolio.settle_fill(
            instrument_id=ctx.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("0.25"),
            price=Decimal("42000"),
            fee=Decimal("0"),
            source_bot="replay-test",
            now_ns=ctx.clock.now_ns,
            spec=ctx.instrument_spec,
            leverage=1,
        )
        assert ctx.replay_connector.get_position("BTC-USDT").amount == Decimal("0.25")
        assert ctx.replay_connector.account_positions()["BTC-USDT"]["amount"] == Decimal("0.25")

        controller._position_base = Decimal("0")
        controller._avg_entry_price = Decimal("0")
        controller._startup_position_sync_done = False
        controller._startup_sync_first_ts = 0.0
        controller._startup_sync_retries = 0
        controller._startup_recon_next_retry_ts = 0.0
        controller._startup_recon_soft_pause = False

        controller._run_startup_position_sync()

        assert controller._startup_position_sync_done is True
        assert controller._position_base == Decimal("0.25")
        assert controller._avg_entry_price == Decimal("42000")
