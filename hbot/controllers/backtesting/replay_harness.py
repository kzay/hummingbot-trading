"""Replay harness for running real controllers on historical data."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

import yaml

from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.data_catalog import DataCatalog
from controllers.backtesting.data_store import (
    load_candles,
    load_candles_window,
    load_funding_rates,
    load_funding_window,
    load_trades,
    load_trades_window,
)
from controllers.backtesting.hb_stubs import install_hb_stubs
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.metrics import compute_all_metrics
from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.replay_connector import ReplayConnector
from controllers.backtesting.replay_injection import ReplayInjection
from controllers.backtesting.replay_market_data_provider import ReplayMarketDataProvider
from controllers.backtesting.replay_market_reader import ReplayMarketDataReader
from controllers.backtesting.report import print_summary, save_equity_curve_csv, save_json_report
from controllers.backtesting.types import (
    BacktestResult,
    CandleRow,
    EquitySnapshot,
    FillRecord,
    FundingRow,
    SynthesisConfig,
    TradeRow,
)
from simulation.desk import DeskConfig, PaperDesk
from simulation.bridge.hb_bridge import drive_desk_tick, install_paper_desk_bridge
from simulation.types import FundingApplied, InstrumentId, InstrumentSpec, OrderFilled
from controllers.price_buffer import MinuteBar

logger = logging.getLogger(__name__)
_ZERO = Decimal("0")


def _date_bounds_ms(start_date: str, end_date: str) -> tuple[int, int]:
    start_ms = int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end_date).replace(tzinfo=UTC).timestamp() * 1000) + 86_400_000
    return start_ms, end_ms


def _filter_rows_by_window(rows: list[Any], start_ms: int, end_ms: int) -> list[Any]:
    return [row for row in rows if start_ms <= int(row.timestamp_ms) <= end_ms]


def _default_connector_name(exchange: str, instrument_type: str) -> str:
    if instrument_type == "perp":
        return f"{exchange}_perpetual"
    return exchange


@dataclass
class ReplayDataConfig:
    exchange: str = "bitget"
    pair: str = "BTC-USDT"
    instrument_type: str = "perp"
    catalog_dir: str = "data/historical"
    candles_resolution: str = "1m"
    candles_path: str = ""
    trades_path: str = ""
    funding_path: str = ""


@dataclass
class ReplayConfig:
    mode: str = "replay"
    strategy_module: str = ""
    strategy_class: str = ""
    strategy_config: dict[str, Any] = field(default_factory=dict)
    data: ReplayDataConfig = field(default_factory=ReplayDataConfig)
    start_date: str = ""
    end_date: str = ""
    step_interval_s: int = 60
    warmup_bars: int = 60
    warmup_duration: str = ""
    initial_equity: Decimal = Decimal("500")
    seed: int = 42
    output_dir: str = "reports/replay"
    run_id: str = ""
    fill_model: str = "latency_aware"


@dataclass
class ReplayPreparedContext:
    config: ReplayConfig
    controller: Any
    controller_config: Any
    desk: PaperDesk
    data_feed: HistoricalDataFeed
    clock: ReplayClock
    trade_reader: ReplayMarketDataReader
    replay_connector: ReplayConnector
    market_data_provider: ReplayMarketDataProvider
    instrument_id: InstrumentId
    instrument_spec: InstrumentSpec
    candles: list[CandleRow]
    trades: list[TradeRow]
    funding_rates: list[FundingRow]
    replay_start_index: int
    replay_candles: list[CandleRow]


def load_replay_config(path: str | Path) -> ReplayConfig:
    raw = _load_yaml(path)
    if raw.get("mode", "adapter") != "replay":
        raise ValueError("Replay config must set mode: replay")
    if not raw.get("strategy_module"):
        raise ValueError("Replay config missing required field: strategy_module")
    if not raw.get("strategy_class"):
        raise ValueError("Replay config missing required field: strategy_class")
    if not raw.get("start_date") or not raw.get("end_date"):
        raise ValueError("Replay config must include start_date and end_date")

    strategy_config = dict(raw.get("strategy_config", {}))
    fee_mode = str(strategy_config.get("fee_mode", "auto"))
    if fee_mode not in {"manual", "project"}:
        raise ValueError("Replay requires strategy_config.fee_mode to be 'manual' or 'project'")

    data_raw = raw.get("data", {})
    return ReplayConfig(
        mode="replay",
        strategy_module=str(raw["strategy_module"]),
        strategy_class=str(raw["strategy_class"]),
        strategy_config=strategy_config,
        data=ReplayDataConfig(
            exchange=str(data_raw.get("exchange", "bitget")),
            pair=str(data_raw.get("pair", "BTC-USDT")),
            instrument_type=str(data_raw.get("instrument_type", "perp")),
            catalog_dir=str(data_raw.get("catalog_dir", "data/historical")),
            candles_resolution=str(data_raw.get("candles_resolution", "1m")),
            candles_path=str(data_raw.get("candles_path", "")),
            trades_path=str(data_raw.get("trades_path", "")),
            funding_path=str(data_raw.get("funding_path", "")),
        ),
        start_date=str(raw["start_date"]),
        end_date=str(raw["end_date"]),
        step_interval_s=int(raw.get("step_interval_s", 60)),
        warmup_bars=int(raw.get("warmup_bars", 60)),
        warmup_duration=str(raw.get("warmup_duration", "")),
        initial_equity=Decimal(str(raw.get("initial_equity", "500"))),
        seed=int(raw.get("seed", 42)),
        output_dir=str(raw.get("output_dir", "reports/replay")),
        run_id=str(raw.get("run_id", "")),
    )


def _load_yaml(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Replay config file not found: {file_path}")
    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Replay config must be a YAML mapping, got {type(data)}")
    return data


class ReplayHarness:
    def __init__(self, config: ReplayConfig):
        self._config = config

    @classmethod
    def from_path(cls, path: str | Path) -> ReplayHarness:
        return cls(load_replay_config(path))

    def prepare(self) -> ReplayPreparedContext:
        self._apply_replay_environment()
        prepare_restores = self._install_prepare_guards()
        try:
            candles, trades, funding_rates = self._load_market_data()
            controller_cls, config_cls = self._resolve_strategy_types()
            controller_config = self._build_controller_config(config_cls)
            controller = controller_cls(controller_config)
            controller.strategy = controller
            controller._strategy = controller

            start_ns = candles[0].timestamp_ns
            clock = ReplayClock(start_ns)
            instrument_id = InstrumentId(
                venue=self._config.data.exchange,
                trading_pair=self._config.data.pair,
                instrument_type=self._config.data.instrument_type,
            )
            instrument_spec = self._build_instrument_spec(instrument_id)
            step_interval_ns = self._config.step_interval_s * 1_000_000_000
            funding_map = {row.timestamp_ms: row.rate for row in funding_rates}
            data_feed = HistoricalDataFeed(
                candles=candles,
                instrument_id=instrument_id,
                synthesizer=CandleBookSynthesizer(SynthesisConfig(steps_per_bar=1, seed=self._config.seed)),
                step_interval_ns=step_interval_ns,
                funding_rates=funding_map,
                seed=self._config.seed,
            )
            data_feed.set_time(clock.now_ns)

            desk = self._create_desk(
                instrument_spec,
                data_feed,
                leverage=int(getattr(controller_config, "leverage", 1) or 1),
            )
            trade_reader = ReplayMarketDataReader(clock, trades)
            replay_connector = ReplayConnector(
                clock=clock,
                data_feed=data_feed,
                portfolio=desk.portfolio,
                instrument_spec=instrument_spec,
                connector_name=str(controller_config.connector_name),
            )
            candle_connector_name = str(getattr(controller_config, "candles_connector", "") or controller_config.connector_name)
            candle_pair = str(getattr(controller_config, "candles_trading_pair", "") or controller_config.trading_pair)
            market_data_provider = ReplayMarketDataProvider(
                clock=clock,
                connectors={str(controller_config.connector_name): replay_connector, candle_connector_name: replay_connector},
                candles_by_key={
                    (candle_connector_name, candle_pair, "1m"): candles,
                    (str(controller_config.connector_name), str(controller_config.trading_pair), "1m"): candles,
                },
            )

            primary_key = f"{str(controller_config.connector_name).strip().lower()}::{str(controller_config.trading_pair).strip().upper()}"

            def reader_factory(connector_name: str, trading_pair: str):
                key = f"{str(connector_name).strip().lower()}::{str(trading_pair).strip().upper()}"
                if key == primary_key:
                    return trade_reader
                raise NotImplementedError(
                    f"Replay v1 does not support auxiliary market reader for {connector_name}/{trading_pair}"
                )

            ReplayInjection.apply(
                controller,
                trade_reader=trade_reader,
                replay_connector=replay_connector,
                market_data_provider=market_data_provider,
                reader_factory=reader_factory,
            )

            install_paper_desk_bridge(
                controller,
                desk,
                str(controller_config.connector_name),
                instrument_id,
                str(controller_config.trading_pair),
                instrument_spec,
            )

            return ReplayPreparedContext(
                config=self._config,
                controller=controller,
                controller_config=controller_config,
                desk=desk,
                data_feed=data_feed,
                clock=clock,
                trade_reader=trade_reader,
                replay_connector=replay_connector,
                market_data_provider=market_data_provider,
                instrument_id=instrument_id,
                instrument_spec=instrument_spec,
                candles=candles,
                trades=trades,
                funding_rates=funding_rates,
                replay_start_index=self._resolve_warmup_bars(),
                replay_candles=candles[self._resolve_warmup_bars() :],
            )
        finally:
            for restore in reversed(prepare_restores):
                restore()

    def run(self, *, progress_every: int = 0, progress_dir: str = "") -> BacktestResult:
        import simulation.desk as _desk_mod
        prev_trace = _desk_mod._PAPER_DESK_TRACE_ENABLED
        _desk_mod._PAPER_DESK_TRACE_ENABLED = False
        try:
            return asyncio.run(self.run_async(progress_every=progress_every, progress_dir=progress_dir))
        finally:
            _desk_mod._PAPER_DESK_TRACE_ENABLED = prev_trace

    async def run_async(
        self,
        *,
        progress_every: int = 0,
        progress_dir: str = "",
        prepared: ReplayPreparedContext | None = None,
    ) -> BacktestResult:
        ctx = prepared or self.prepare()
        started = time.monotonic()
        restore_callbacks = self._install_replay_time_patches(ctx)
        event_buffer: list[Any] = []
        original_desk_tick = ctx.desk.tick
        original_buy = getattr(ctx.controller, "buy", None)
        original_sell = getattr(ctx.controller, "sell", None)
        ctx.controller._replay_submitted_order_count = 0

        def _capture_tick(now_ns: int | None = None):
            events = original_desk_tick(now_ns)
            event_buffer.clear()
            event_buffer.extend(events or [])
            return events

        def _counting_buy(self, *args, **kwargs):
            self._replay_submitted_order_count = int(getattr(self, "_replay_submitted_order_count", 0)) + 1
            return original_buy(*args, **kwargs)

        def _counting_sell(self, *args, **kwargs):
            self._replay_submitted_order_count = int(getattr(self, "_replay_submitted_order_count", 0)) + 1
            return original_sell(*args, **kwargs)

        ctx.desk.tick = _capture_tick  # type: ignore[assignment]
        if callable(original_buy):
            ctx.controller.buy = MethodType(_counting_buy, ctx.controller)
        if callable(original_sell):
            ctx.controller.sell = MethodType(_counting_sell, ctx.controller)
        self._patch_async_sampler(ctx.controller)
        self._seed_price_buffer(ctx.controller, ctx.candles[: ctx.replay_start_index])

        fills: list[FillRecord] = []
        fills_by_regime: dict[str, list[FillRecord]] = {}
        funding_paid = _ZERO
        funding_received = _ZERO
        position_series: list[float] = []
        equity_snapshots: list[EquitySnapshot] = []
        snapshot_regimes: list[str] = []
        peak_equity = ctx.config.initial_equity
        current_equity = ctx.config.initial_equity
        last_equity_day = -1
        prev_day_equity = ctx.config.initial_equity
        fill_cursor_for_day = 0
        regime_ticks_this_day: dict[str, int] = {}

        try:
            for tick_index, candle in enumerate(ctx.replay_candles, start=1):
                target_ns = candle.timestamp_ns
                if target_ns > ctx.clock.now_ns:
                    ctx.clock.advance(target_ns - ctx.clock.now_ns)
                ctx.trade_reader.advance(ctx.clock.now_ns)
                ctx.data_feed.set_time(ctx.clock.now_ns)

                drive_desk_tick(ctx.controller, ctx.desk, ctx.clock.now_ns)

                current_regime = self._controller_regime(ctx.controller)
                for event in event_buffer:
                    if isinstance(event, OrderFilled):
                        fill_rec = FillRecord(
                            timestamp_ns=ctx.clock.now_ns,
                            order_id=str(event.order_id),
                            side=str(event.side),
                            fill_price=event.fill_price,
                            fill_quantity=event.fill_quantity,
                            fee=event.fee,
                            is_maker=bool(event.is_maker),
                            slippage_bps=event.slippage_bps,
                            mid_slippage_bps=event.mid_slippage_bps,
                            source_bot=str(getattr(event, "source_bot", "") or "replay"),
                        )
                        fills.append(fill_rec)
                        fills_by_regime.setdefault(current_regime, []).append(fill_rec)
                    elif isinstance(event, FundingApplied):
                        if event.charge_quote > _ZERO:
                            funding_paid += event.charge_quote
                        else:
                            funding_received += abs(event.charge_quote)

                mark_price = ctx.replay_connector.get_mid_price(ctx.instrument_id.trading_pair)
                if mark_price <= _ZERO:
                    mark_price = candle.close
                self._feed_sync_price_sample(ctx.controller, ctx.clock.time(), mark_price, candle=candle)
                await self._await_controller_tick(ctx.controller)

                current_regime = self._controller_regime(ctx.controller)
                position = ctx.desk.portfolio.get_position(ctx.instrument_id)
                position_series.append(float(position.quantity))

                if mark_price > _ZERO:
                    current_equity = ctx.desk.portfolio.equity_quote({ctx.instrument_id.key: mark_price})
                peak_equity = max(peak_equity, current_equity)

                day = int(ctx.clock.time() // 86400)
                if day != last_equity_day:
                    if last_equity_day >= 0:
                        day_ts = datetime.fromtimestamp(ctx.clock.time(), tz=UTC)
                        dd_pct = float((peak_equity - current_equity) / peak_equity) if peak_equity > _ZERO else 0.0
                        ref_equity = prev_day_equity if prev_day_equity > _ZERO else ctx.config.initial_equity
                        daily_ret = float((current_equity - ref_equity) / ref_equity) if ref_equity > _ZERO else 0.0
                        cum_ret = (
                            float((current_equity - ctx.config.initial_equity) / ctx.config.initial_equity)
                            if ctx.config.initial_equity > _ZERO
                            else 0.0
                        )
                        day_fills = len(fills) - fill_cursor_for_day
                        fill_cursor_for_day = len(fills)
                        equity_snapshots.append(
                            EquitySnapshot(
                                date=day_ts.strftime("%Y-%m-%d"),
                                equity=current_equity,
                                drawdown_pct=Decimal(str(dd_pct)),
                                daily_return_pct=Decimal(str(daily_ret)),
                                cumulative_return_pct=Decimal(str(cum_ret)),
                                position_notional=abs(position.quantity) * mark_price if mark_price > _ZERO else _ZERO,
                                num_fills=day_fills,
                            )
                        )
                        dominant = (
                            max(regime_ticks_this_day, key=regime_ticks_this_day.get)
                            if regime_ticks_this_day
                            else current_regime
                        )
                        snapshot_regimes.append(dominant)
                    regime_ticks_this_day = {}
                    prev_day_equity = current_equity
                    last_equity_day = day
                regime_ticks_this_day[current_regime] = regime_ticks_this_day.get(current_regime, 0) + 1

                if progress_every > 0 and tick_index % progress_every == 0:
                    pct = round((tick_index / max(1, len(ctx.replay_candles))) * 100.0, 1)
                    logger.info(
                        "Replay progress: %s/%s ticks (%.1f%%)",
                        tick_index,
                        len(ctx.replay_candles),
                        pct,
                    )
                    self._write_progress(progress_dir, tick_index, len(ctx.replay_candles), pct)

            if ctx.replay_candles:
                final_ts = datetime.fromtimestamp(ctx.clock.time(), tz=UTC)
                final_mark = ctx.replay_candles[-1].close
                position = ctx.desk.portfolio.get_position(ctx.instrument_id)
                dd_pct = float((peak_equity - current_equity) / peak_equity) if peak_equity > _ZERO else 0.0
                ref_equity = prev_day_equity if prev_day_equity > _ZERO else ctx.config.initial_equity
                daily_ret = float((current_equity - ref_equity) / ref_equity) if ref_equity > _ZERO else 0.0
                cum_ret = (
                    float((current_equity - ctx.config.initial_equity) / ctx.config.initial_equity)
                    if ctx.config.initial_equity > _ZERO
                    else 0.0
                )
                equity_snapshots.append(
                    EquitySnapshot(
                        date=final_ts.strftime("%Y-%m-%d"),
                        equity=current_equity,
                        drawdown_pct=Decimal(str(dd_pct)),
                        daily_return_pct=Decimal(str(daily_ret)),
                        cumulative_return_pct=Decimal(str(cum_ret)),
                        position_notional=abs(position.quantity) * final_mark if final_mark > _ZERO else _ZERO,
                        num_fills=len(fills) - fill_cursor_for_day,
                    )
                )
                snapshot_regimes.append(
                    max(regime_ticks_this_day, key=regime_ticks_this_day.get)
                    if regime_ticks_this_day
                    else self._controller_regime(ctx.controller)
                )
        finally:
            ctx.desk.tick = original_desk_tick  # type: ignore[assignment]
            if callable(original_buy):
                ctx.controller.buy = original_buy
            if callable(original_sell):
                ctx.controller.sell = original_sell
            for restore in reversed(restore_callbacks):
                restore()

        self._write_progress(progress_dir, len(ctx.replay_candles), len(ctx.replay_candles), 100.0)

        returns_by_regime: dict[str, list[float]] = {}
        for snap, regime in zip(equity_snapshots, snapshot_regimes, strict=True):
            returns_by_regime.setdefault(regime, []).append(float(snap.daily_return_pct))

        result = compute_all_metrics(
            equity_curve=equity_snapshots,
            fills=fills,
            order_count=int(getattr(ctx.controller, "_replay_submitted_order_count", 0)),
            actual_pnl=current_equity - ctx.config.initial_equity,
            total_fees=sum((fill.fee for fill in fills), _ZERO),
            funding_paid=funding_paid,
            funding_received=funding_received,
            position_series=position_series,
            returns_by_regime=returns_by_regime if returns_by_regime else None,
            fills_by_regime=fills_by_regime if fills_by_regime else None,
        )
        result.config = {
            "mode": ctx.config.mode,
            "strategy_module": ctx.config.strategy_module,
            "strategy_class": ctx.config.strategy_class,
            "exchange": ctx.config.data.exchange,
            "pair": ctx.config.data.pair,
            "instrument_type": ctx.config.data.instrument_type,
            "step_interval_s": ctx.config.step_interval_s,
            "warmup_bars": ctx.replay_start_index,
        }
        result.data_start = ctx.config.start_date
        result.data_end = ctx.config.end_date
        result.strategy_name = ctx.config.strategy_class
        result.total_ticks = len(ctx.replay_candles)
        result.run_duration_s = time.monotonic() - started
        result.fill_disclaimer = (
            "Replay uses the real controller and PaperDesk fills, but quote/depth state is derived from replayed trades "
            "and candle-synthesized books rather than full native exchange L2."
        )
        result.warnings.append(
            "Replay mode patches runtime clock surfaces and suppresses the live price-sampler task."
        )
        return result

    def _apply_replay_environment(self) -> None:
        os.environ["REDIS_HOST"] = ""
        os.environ["PAPER_EXCHANGE_MODE"] = "disabled"
        os.environ["HB_HISTORY_PROVIDER_ENABLED"] = "false"
        os.environ["HB_HISTORY_SEED_ENABLED"] = "false"
        os.environ["HB_CANONICAL_MARKET_DATA_ENABLED"] = "false"

    def _resolve_strategy_types(self) -> tuple[type[Any], type[Any]]:
        install_hb_stubs()
        try:
            module = importlib.import_module(self._config.strategy_module)
        except ModuleNotFoundError as exc:
            raise ValueError(f"Cannot import replay strategy module {self._config.strategy_module!r}: {exc}") from exc
        controller_cls = getattr(module, self._config.strategy_class, None)
        if controller_cls is None:
            raise ValueError(
                f"Replay strategy class {self._config.strategy_class!r} not found in module {self._config.strategy_module!r}"
            )
        config_name = self._config.strategy_class.replace("Controller", "Config")
        config_cls = getattr(module, config_name, None)
        if config_cls is None:
            raise ValueError(f"Replay strategy config class {config_name!r} not found in module {self._config.strategy_module!r}")
        return controller_cls, config_cls

    def _build_controller_config(self, config_cls: type[Any]) -> Any:
        strategy_config = dict(self._config.strategy_config)
        strategy_config.setdefault("trading_pair", self._config.data.pair)
        strategy_config.setdefault(
            "connector_name",
            _default_connector_name(self._config.data.exchange, self._config.data.instrument_type),
        )
        strategy_config.setdefault("candles_trading_pair", self._config.data.pair)
        strategy_config.setdefault("candles_connector", strategy_config.get("connector_name"))
        strategy_config.setdefault("bot_mode", "paper")
        return config_cls(**strategy_config)

    def _load_market_data(self) -> tuple[list[CandleRow], list[TradeRow], list[FundingRow]]:
        start_ms, end_ms = _date_bounds_ms(self._config.start_date, self._config.end_date)

        # Candles need warmup bars *before* start_ms, so we load the full
        # file and slice in-memory (the warmup offset isn't known at the
        # parquet level).
        all_candles = self._load_candles()
        in_window_indexes = [idx for idx, row in enumerate(all_candles) if start_ms <= int(row.timestamp_ms) <= end_ms]
        if not in_window_indexes:
            raise ValueError("Replay requires candle data covering the requested window")
        warmup_bars = self._resolve_warmup_bars()
        first_idx = in_window_indexes[0]
        if first_idx < warmup_bars:
            raise ValueError(
                f"Replay requires {warmup_bars} warmup candles before start_date; only found {first_idx}"
            )
        candles = all_candles[first_idx - warmup_bars : in_window_indexes[-1] + 1]

        trades = self._load_trades(start_ms, end_ms)
        funding = self._load_funding(start_ms, end_ms)

        if len(candles) < max(2, warmup_bars + 1):
            raise ValueError(f"Replay requires enough candles for warmup; got {len(candles)}")
        if not trades:
            raise ValueError("Replay requires trade data covering the requested window")
        if self._config.data.instrument_type == "perp" and not funding:
            raise ValueError("Replay requires funding data for perp strategies")
        return candles, trades, funding

    def _load_candles(self) -> list[CandleRow]:
        if self._config.data.candles_path:
            return load_candles(Path(self._config.data.candles_path))
        entry = self._find_catalog_entry(self._config.data.candles_resolution)
        return load_candles(Path(entry["file_path"]))

    def _load_trades(self, start_ms: int | None = None, end_ms: int | None = None) -> list[TradeRow]:
        if self._config.data.trades_path:
            path = Path(self._config.data.trades_path)
            if start_ms is not None or end_ms is not None:
                return load_trades_window(path, start_ms=start_ms, end_ms=end_ms)
            return load_trades(path)
        entry = self._find_catalog_entry("trades", start_ms=start_ms, end_ms=end_ms)
        if start_ms is not None or end_ms is not None:
            return load_trades_window(Path(entry["file_path"]), start_ms=start_ms, end_ms=end_ms)
        return load_trades(Path(entry["file_path"]))

    def _load_funding(self, start_ms: int | None = None, end_ms: int | None = None) -> list[FundingRow]:
        if self._config.data.instrument_type != "perp":
            return []
        if self._config.data.funding_path:
            path = Path(self._config.data.funding_path)
            if start_ms is not None or end_ms is not None:
                return load_funding_window(path, start_ms=start_ms, end_ms=end_ms)
            return load_funding_rates(path)
        entry = self._find_catalog_entry("funding", start_ms=start_ms, end_ms=end_ms)
        if start_ms is not None or end_ms is not None:
            return load_funding_window(Path(entry["file_path"]), start_ms=start_ms, end_ms=end_ms)
        return load_funding_rates(Path(entry["file_path"]))

    def _find_catalog_entry(
        self,
        resolution: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, Any]:
        catalog = DataCatalog(Path(self._config.data.catalog_dir))
        entry = catalog.find(
            self._config.data.exchange, self._config.data.pair, resolution,
            start_ms=start_ms, end_ms=end_ms,
        )
        if entry is None:
            raise FileNotFoundError(
                f"No replay dataset found for {self._config.data.exchange}/{self._config.data.pair}/{resolution}"
            )
        return entry

    def _build_instrument_spec(self, instrument_id: InstrumentId) -> InstrumentSpec:
        if instrument_id.instrument_type == "perp":
            return InstrumentSpec.perp_usdt(instrument_id.venue, instrument_id.trading_pair)
        return InstrumentSpec.spot_usdt(instrument_id.venue, instrument_id.trading_pair)

    def _create_desk(self, instrument_spec: InstrumentSpec, data_feed: HistoricalDataFeed, leverage: int) -> PaperDesk:
        desk = PaperDesk(
            DeskConfig(
                initial_balances={instrument_spec.instrument_id.quote_asset: self._config.initial_equity},
                state_file_path=f"/tmp/replay_desk_{uuid.uuid4().hex[:8]}.json",
                redis_url=None,
                reset_state_on_startup=True,
                seed=self._config.seed,
                disable_persistence=True,
                default_fill_model=self._config.fill_model,
            )
        )
        desk.register_instrument(instrument_spec=instrument_spec, data_feed=data_feed, leverage=leverage)
        return desk

    def _resolve_warmup_bars(self) -> int:
        if self._config.warmup_duration:
            return max(0, self._parse_warmup_duration(self._config.warmup_duration))
        return max(0, int(self._config.warmup_bars))

    @staticmethod
    def _parse_warmup_duration(raw: str) -> int:
        text = str(raw or "").strip().lower()
        if not text:
            return 0
        match = re.fullmatch(r"(\d+)\s*([mhd])", text)
        if match is None:
            raise ValueError(f"Unsupported replay warmup_duration {raw!r}; expected e.g. 90m, 6h, 2d")
        value = int(match.group(1))
        unit = match.group(2)
        factor = {"m": 1, "h": 60, "d": 1440}[unit]
        return value * factor

    @staticmethod
    def _patch_async_sampler(controller: Any) -> None:
        def _noop_sampler(self) -> None:
            self._price_sampler_task = None

        controller._ensure_price_sampler_started = MethodType(_noop_sampler, controller)

    @staticmethod
    def _seed_price_buffer(controller: Any, candles: list[CandleRow]) -> None:
        price_buffer = getattr(controller, "_price_buffer", None)
        if price_buffer is None:
            return
        bars = [
            MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000),
                open=Decimal(candle.open),
                high=Decimal(candle.high),
                low=Decimal(candle.low),
                close=Decimal(candle.close),
            )
            for candle in candles
        ]
        price_buffer.seed_bars(bars, reset=True)
        controller._history_seed_attempted = True
        controller._history_seed_status = "replay_seeded"
        controller._history_seed_reason = ""
        controller._history_seed_source = "replay"
        controller._history_seed_bars = len(bars)

    @staticmethod
    def _feed_sync_price_sample(
        controller: Any,
        now_s: float,
        price: Decimal,
        candle: CandleRow | None = None,
    ) -> None:
        price_buffer = getattr(controller, "_price_buffer", None)
        if price_buffer is None or price <= _ZERO:
            return
        if candle is not None:
            bar = MinuteBar(
                ts_minute=int(candle.timestamp_ms // 1000 // 60) * 60,
                open=candle.open, high=candle.high,
                low=candle.low, close=candle.close,
            )
            price_buffer.append_bar(bar)
        else:
            price_buffer.add_sample(now_s, price)

    @staticmethod
    async def _await_controller_tick(controller: Any) -> None:
        update = getattr(controller, "update_processed_data", None)
        if not callable(update):
            raise TypeError("Replay strategy controller must define update_processed_data()")
        result = update()
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _controller_regime(controller: Any) -> str:
        processed = getattr(controller, "processed_data", None)
        if isinstance(processed, dict):
            regime = str(processed.get("regime", "") or "").strip()
            if regime:
                return regime
        return "unknown"

    @staticmethod
    def _write_progress(progress_dir: str, tick: int, total: int, pct: float) -> None:
        if not progress_dir:
            return
        try:
            d = Path(progress_dir)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "progress.tmp"
            tmp.write_text(json.dumps({
                "current_tick": tick,
                "total_ticks": total,
                "progress_pct": round(pct, 1),
            }))
            tmp.rename(d / "progress.json")
        except OSError:
            pass

    def _install_replay_time_patches(self, ctx: ReplayPreparedContext) -> list[Callable[[], None]]:
        restores: list[Callable[[], None]] = []
        shim = SimpleNamespace(time=ctx.clock.time, perf_counter=time.perf_counter)
        for module_name, attr_name in (
            ("controllers.connector_runtime_adapter", "time"),
            ("simulation.bridge.hb_event_fire", "time"),
            ("controllers.protective_stop", "time"),
            ("controllers.telemetry_mixin", "_time_mod"),
        ):
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            if not hasattr(module, attr_name):
                continue
            original = getattr(module, attr_name)
            setattr(module, attr_name, shim)
            restores.append(lambda m=module, a=attr_name, value=original: setattr(m, a, value))
        return restores

    @staticmethod
    def _install_prepare_guards() -> list[Callable[[], None]]:
        restores: list[Callable[[], None]] = []
        try:
            redis_client_module = importlib.import_module("services.hb_bridge.redis_client")
        except Exception:
            return restores
        client_cls = getattr(redis_client_module, "RedisStreamClient", None)
        if client_cls is None:
            return restores
        original_init = client_cls.__init__

        def _disabled_init(self, host, port, db, password=None, enabled=True, max_connections=4):
            return original_init(
                self,
                host="",
                port=port,
                db=db,
                password=password,
                enabled=False,
                max_connections=max_connections,
            )

        client_cls.__init__ = _disabled_init
        restores.append(lambda cls=client_cls, init=original_init: setattr(cls, "__init__", init))
        return restores


def _default_output_path(config: ReplayConfig, config_path: str | Path) -> Path:
    run_id = config.run_id or Path(config_path).stem
    return Path(config.output_dir) / f"{run_id}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a replay backtest with the real controller")
    parser.add_argument("--config", required=True, help="Path to replay YAML config")
    parser.add_argument("--output", default="", help="Path to write JSON report")
    parser.add_argument("--equity-csv", default="", help="Optional path for equity-curve CSV")
    parser.add_argument("--progress-dir", default="", help="Directory to write progress.json for dashboard tracking")
    parser.add_argument("--progress-every", type=int, default=0, help="Write progress every N replay ticks (default: every 10 when --progress-dir is set)")
    parser.add_argument("--no-summary", action="store_true", help="Skip stdout report summary")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        stream=sys.stdout,
    )

    progress_every = max(0, int(args.progress_every or 0))
    if args.progress_dir and progress_every == 0:
        progress_every = 10

    harness = ReplayHarness.from_path(args.config)
    result = harness.run(progress_every=progress_every, progress_dir=args.progress_dir)

    output_path = Path(args.output) if args.output else _default_output_path(harness._config, args.config)
    save_json_report(result, output_path)
    equity_path = Path(args.equity_csv) if args.equity_csv else output_path.with_suffix(".equity.csv")
    save_equity_curve_csv(result, equity_path)
    if not args.no_summary:
        print_summary(result)


__all__ = [
    "ReplayConfig",
    "ReplayDataConfig",
    "ReplayHarness",
    "ReplayPreparedContext",
    "load_replay_config",
]


if __name__ == "__main__":
    main()
