from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from controllers.backtesting.data_catalog import DataCatalog
from controllers.backtesting.data_store import save_candles, save_funding_rates, save_trades
from controllers.backtesting.replay_harness import ReplayHarness, load_replay_config
from controllers.backtesting.types import CandleRow, FundingRow, TradeRow


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


def _write_config(path: Path, catalog_dir: Path, fee_mode: str = "manual", strategy_module: str = "controllers.bots.bot7.pullback_v1", strategy_class: str = "PullbackV1Controller") -> None:
    path.write_text(
        "\n".join(
            [
                "mode: replay",
                f"strategy_module: {strategy_module}",
                f"strategy_class: {strategy_class}",
                "strategy_config:",
                "  id: replay_bot7",
                "  controller_name: bot7_pullback_v1",
                "  connector_name: bitget_perpetual",
                "  trading_pair: BTC-USDT",
                "  candles_connector: bitget_perpetual",
                "  candles_trading_pair: BTC-USDT",
                "  fee_mode: " + fee_mode,
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
                "output_dir: reports/replay",
                "run_id: replay_test",
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestReplayHarnessConfig:
    def test_load_replay_config_rejects_auto_fee_mode(self, tmp_path: Path):
        config_path = tmp_path / "replay.yml"
        _write_config(config_path, tmp_path, fee_mode="auto")

        with pytest.raises(ValueError, match="fee_mode"):
            load_replay_config(config_path)

    def test_prepare_fails_fast_for_invalid_strategy_module(self, tmp_path: Path):
        _write_replay_datasets(tmp_path)
        config_path = tmp_path / "replay.yml"
        _write_config(config_path, tmp_path, strategy_module="controllers.missing.module")

        with pytest.raises(ValueError, match="Cannot import replay strategy module"):
            ReplayHarness.from_path(config_path).prepare()


class TestReplayHarnessPrepare:
    def test_prepare_bootstraps_real_controller_with_replay_dependencies(self, tmp_path: Path):
        _write_replay_datasets(tmp_path)
        config_path = tmp_path / "replay.yml"
        _write_config(config_path, tmp_path)

        ctx = ReplayHarness.from_path(config_path).prepare()

        assert ctx.controller.__class__.__name__ == "PullbackV1Controller"
        assert ctx.controller._trade_reader is ctx.trade_reader
        assert ctx.controller.market_data_provider is ctx.market_data_provider
        assert ctx.controller.connectors["bitget_perpetual"] is ctx.replay_connector
        assert ctx.instrument_id.key in ctx.desk._engines
        assert ctx.data_feed.has_data() is True
        assert len(ctx.candles) >= 3
        assert len(ctx.trades) >= 1
        assert ctx.replay_start_index == 2
        assert len(ctx.replay_candles) >= 1


class _ExplodingRedis:
    def __init__(self, *args, **kwargs):
        raise AssertionError("Redis client should not be constructed in replay mode")


class TestReplayHarnessRun:
    def test_run_completes_and_returns_structured_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_replay_datasets(tmp_path)
        config_path = tmp_path / "replay.yml"
        _write_config(config_path, tmp_path)
        monkeypatch.setitem(sys.modules, "redis", type("RedisModule", (), {"Redis": _ExplodingRedis})())

        result = ReplayHarness.from_path(config_path).run(progress_every=2)

        assert result.strategy_name == "PullbackV1Controller"
        assert result.total_ticks == 10
        assert isinstance(result.fill_count, int)
        assert isinstance(result.equity_curve, list)
        assert result.fill_disclaimer
        assert result.config["warmup_bars"] == 2
        assert any("Replay mode patches runtime clock surfaces" in warning for warning in result.warnings)
