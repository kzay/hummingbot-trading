"""Backtest harness — core time-stepping loop that drives PaperDesk + strategy.

The harness owns the simulation clock.  Each step:

1. Advance clock by ``step_interval_ns``.
2. Set time on ``HistoricalDataFeed`` → synthesize book from candle.
3. Call ``desk.tick(now_ns)`` → match orders against synthetic book.
4. Call ``runtime_adapter.tick(...)`` → strategy computes plan, submits new orders.
5. Record equity, fills, regime for reporting.

The harness is intentionally stateless between runs; create a new instance for
each backtest (sweep workers, walk-forward windows).
"""
from __future__ import annotations

import importlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.data_store import load_candles, load_candles_window
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.types import (
    BacktestConfig,
    BacktestResult,
    CandleRow,
    EquitySnapshot,
    FillRecord,
    VisibleCandleRow,
)
from simulation.desk import DeskConfig, PaperDesk
from simulation.types import (
    _ZERO,
    FundingApplied,
    InstrumentId,
    InstrumentSpec,
    OrderFilled,
    disable_backtest_ids,
    enable_backtest_ids,
)

logger = logging.getLogger(__name__)

_ONE = Decimal("1")


# ---------------------------------------------------------------------------
# DeskFactory
# ---------------------------------------------------------------------------

class DeskFactory:
    """Creates isolated PaperDesk instances for backtest runs.

    Each call to ``create()`` returns a fresh desk with no persisted state,
    configured with the backtest's fill model and equity.
    """

    _FILL_PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "optimistic": {
            "fill_slippage_bps": Decimal("0.5"),
            "fill_adverse_selection_bps": Decimal("0.5"),
            "fill_prob_fill_on_limit": 0.6,
        },
        "balanced": {
            "fill_slippage_bps": Decimal("1.0"),
            "fill_adverse_selection_bps": Decimal("1.5"),
            "fill_prob_fill_on_limit": 0.4,
        },
        "conservative": {
            "fill_slippage_bps": Decimal("2.0"),
            "fill_adverse_selection_bps": Decimal("3.0"),
            "fill_prob_fill_on_limit": 0.25,
        },
        "pessimistic": {
            "fill_slippage_bps": Decimal("3.0"),
            "fill_adverse_selection_bps": Decimal("5.0"),
            "fill_prob_fill_on_limit": 0.15,
        },
    }

    @staticmethod
    def create(
        config: BacktestConfig,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        data_feed: HistoricalDataFeed,
    ) -> PaperDesk:
        """Create a fresh PaperDesk wired to the given data feed."""
        preset = DeskFactory._FILL_PRESETS.get(
            config.fill_model_preset,
            DeskFactory._FILL_PRESETS["balanced"],
        )
        desk_config = DeskConfig(
            initial_balances={instrument_id.quote_asset: config.initial_equity},
            default_fill_model=config.fill_model,
            fill_slippage_bps=preset["fill_slippage_bps"],
            fill_adverse_selection_bps=preset["fill_adverse_selection_bps"],
            fill_prob_fill_on_limit=preset["fill_prob_fill_on_limit"],
            insert_latency_ms=config.insert_latency_ms,
            cancel_latency_ms=config.cancel_latency_ms,
            default_latency_model=config.latency_model,
            state_file_path=f"/tmp/backtest_desk_{uuid.uuid4().hex[:8]}.json",
            redis_url=None,
            reset_state_on_startup=True,
            seed=config.seed,
            disable_persistence=True,
        )
        desk = PaperDesk(desk_config)
        desk.register_instrument(
            instrument_spec=instrument_spec,
            data_feed=data_feed,
            leverage=config.leverage,
        )
        return desk


# ---------------------------------------------------------------------------
# Default instrument spec
# ---------------------------------------------------------------------------

def _default_instrument_spec(instrument_id: InstrumentId) -> InstrumentSpec:
    """Create a reasonable default InstrumentSpec for BTC-like perp instruments."""
    return InstrumentSpec(
        instrument_id=instrument_id,
        price_precision=2,
        size_precision=4,
        price_increment=Decimal("0.01"),
        size_increment=Decimal("0.0001"),
        min_quantity=Decimal("0.0001"),
        min_notional=Decimal("5"),
        max_quantity=Decimal("1000"),
        maker_fee_rate=Decimal("0.0002"),
        taker_fee_rate=Decimal("0.0006"),
        margin_init=Decimal("0.10"),
        margin_maint=Decimal("0.05"),
        leverage_max=10,
        funding_interval_s=28800,
    )


# ---------------------------------------------------------------------------
# Strategy loader
# ---------------------------------------------------------------------------

def _load_strategy(class_path: str, config: dict[str, Any]) -> Any:
    """Dynamically import and instantiate a strategy class.

    ``class_path`` is a dotted module path with a class name at the end,
    e.g. ``controllers.backtesting.runtime_adapter.DefaultMMBacktestStrategy``.

    Special values:
      - ``""`` or ``"default_mm"`` → use ``DefaultMMBacktestStrategy``
    """
    from controllers.backtesting.runtime_adapter import DefaultMMBacktestStrategy

    if not class_path or class_path == "default_mm":
        return DefaultMMBacktestStrategy()

    parts = class_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid strategy class path: {class_path!r}")
    module_path, class_name = parts
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ValueError(
            f"Cannot import strategy module {module_path!r}: {e}"
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(
            f"Class {class_name!r} not found in module {module_path!r}. "
            f"Available: {[n for n in dir(module) if not n.startswith('_')]}"
        )
    return cls(**config) if config else cls()


# ---------------------------------------------------------------------------
# BacktestHarness
# ---------------------------------------------------------------------------

class BacktestHarness:
    """Core time-stepping backtest engine.

    Usage::

        harness = BacktestHarness(config)
        result = harness.run()
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config
        self._run_id = config.run_id or uuid.uuid4().hex[:12]

    def run(self) -> BacktestResult:
        """Execute the full backtest and return results."""
        import simulation.desk as _desk_mod
        prev_trace = _desk_mod._PAPER_DESK_TRACE_ENABLED
        _desk_mod._PAPER_DESK_TRACE_ENABLED = False
        enable_backtest_ids()
        try:
            return self._run_impl()
        finally:
            disable_backtest_ids()
            _desk_mod._PAPER_DESK_TRACE_ENABLED = prev_trace

    def _run_impl(self) -> BacktestResult:
        t0 = time.monotonic()
        config = self._config

        # --- Load and validate data ---
        candles = self._load_candles()
        if len(candles) < config.warmup_bars + 10:
            raise ValueError(
                f"Insufficient candles: {len(candles)} < warmup({config.warmup_bars}) + 10"
            )

        from controllers.backtesting.data_store import validate_candles
        data_warnings = validate_candles(candles)
        if data_warnings:
            for w in data_warnings:
                logger.warning("Data quality: %s", w)

        # --- Build instrument ---
        ds = config.data_source
        instrument_id = InstrumentId(
            venue=ds.exchange,
            trading_pair=ds.pair,
            instrument_type=ds.instrument_type,
        )
        instrument_spec = _default_instrument_spec(instrument_id)

        # --- Build synthesizer and data feed ---
        synthesis = config.synthesis
        synthesizer = CandleBookSynthesizer(synthesis)

        step_interval_ns = config.step_interval_s * 1_000_000_000
        feed = HistoricalDataFeed(
            candles=candles,
            instrument_id=instrument_id,
            synthesizer=synthesizer,
            step_interval_ns=step_interval_ns,
            seed=config.seed,
        )

        # --- Create PaperDesk ---
        desk = DeskFactory.create(config, instrument_id, instrument_spec, feed)

        # --- Build adapter ---
        adapter = self._build_adapter(config, desk, instrument_id, instrument_spec)

        # --- Pre-compute features for ML adapters (if supported) ---
        if callable(getattr(adapter, "set_all_candles", None)):
            adapter.set_all_candles(candles)

        # --- Warmup: feed candles to PriceBuffer ---
        warmup_candles = candles[:config.warmup_bars]
        adapter.warmup(warmup_candles)

        # --- Time-stepping loop ---
        backtest_candles = candles[config.warmup_bars:]
        fills: list[FillRecord] = []
        equity_snapshots: list[EquitySnapshot] = []
        regime_ticks: dict[str, int] = {}
        position_series: list[float] = []
        fills_by_regime: dict[str, list[FillRecord]] = {}
        order_count = 0
        total_ticks = 0
        last_equity_day = -1
        prev_day_equity = Decimal("0")
        fill_cursor_for_day = 0
        funding_paid = Decimal("0")
        funding_received = Decimal("0")
        regime_ticks_this_day: dict[str, int] = {}
        snapshot_regimes: list[str] = []

        initial_equity = config.initial_equity
        current_equity = initial_equity
        peak_equity = initial_equity
        position_base = Decimal("0")

        start_ns = backtest_candles[0].timestamp_ns
        end_ns = backtest_candles[-1].timestamp_ns
        expected_total_ticks = max(1, (end_ns - start_ns) // step_interval_ns + 1)

        progress_dir = Path(config.progress_dir) if config.progress_dir else None
        progress_interval = 1000
        if progress_dir:
            progress_dir.mkdir(parents=True, exist_ok=True)

        now_ns = start_ns

        # Initial equity snapshot — anchors day-0 return correctly
        init_ts = datetime.fromtimestamp(start_ns / 1_000_000_000, tz=UTC)
        equity_snapshots.append(EquitySnapshot(
            date=init_ts.strftime("%Y-%m-%d"),
            equity=initial_equity,
            drawdown_pct=Decimal("0"),
            daily_return_pct=Decimal("0"),
            cumulative_return_pct=Decimal("0"),
            position_notional=_ZERO,
            num_fills=0,
        ))
        snapshot_regimes.append("initial")

        while now_ns <= end_ns:
            total_ticks += 1
            now_s = now_ns / 1_000_000_000

            # 1. Set feed time
            feed.set_time(now_ns)

            # 2. Desk tick: match orders against current book
            events = desk.tick(now_ns)

            # 3. Process fill and funding events
            regime = adapter.regime_name
            for event in events:
                if isinstance(event, OrderFilled):
                    fill_qty = event.fill_quantity
                    fill_price = event.fill_price
                    fee = event.fee
                    is_buy = event.side == "buy"

                    if is_buy:
                        position_base += fill_qty
                    else:
                        position_base -= fill_qty

                    fill_notional = fill_price * fill_qty
                    adapter.record_fill_notional(fill_notional)

                    mid = feed.get_mid_price(instrument_id) or fill_price
                    slippage_bps = _ZERO
                    if mid > _ZERO:
                        slippage_bps = abs(fill_price - mid) / mid * Decimal("10000")

                    fill_rec = FillRecord(
                        timestamp_ns=now_ns,
                        order_id=event.order_id,
                        side="buy" if is_buy else "sell",
                        fill_price=fill_price,
                        fill_quantity=fill_qty,
                        fee=fee,
                        is_maker=event.is_maker,
                        slippage_bps=slippage_bps,
                        mid_slippage_bps=slippage_bps,
                        source_bot="backtest",
                    )
                    fills.append(fill_rec)
                    fills_by_regime.setdefault(regime, []).append(fill_rec)

                elif isinstance(event, FundingApplied):
                    if event.charge_quote > _ZERO:
                        funding_paid += event.charge_quote
                    else:
                        funding_received += abs(event.charge_quote)

            # 4. Get book once (cached by feed after desk.tick synthesis)
            book = feed.get_book(instrument_id)
            mid_price = book.mid_price if book is not None else Decimal("0")
            if mid_price > _ZERO:
                current_equity = desk.portfolio.equity_quote(
                    mark_prices={instrument_id.key: mid_price},
                )
            peak_equity = max(peak_equity, current_equity)

            # 4b. Record position for inventory half-life
            position_series.append(float(position_base))

            # 5. Runtime adapter tick
            raw_candle = feed.get_current_candle()
            if raw_candle is not None and not config.allow_full_candle:
                candle_for_adapter: CandleRow | VisibleCandleRow = VisibleCandleRow(
                    raw_candle,
                    step_index=feed.current_step_index,
                    max_step=feed.steps_per_bar - 1,
                )
            else:
                candle_for_adapter = raw_candle  # type: ignore[assignment]
            plan = adapter.tick(
                now_s=now_s,
                mid=mid_price,
                book=book,
                equity_quote=current_equity,
                position_base=position_base,
                candle=candle_for_adapter,
            )
            if plan is not None:
                order_count += adapter.last_submitted_count

            # 6. Track regime
            regime_ticks[regime] = regime_ticks.get(regime, 0) + 1
            regime_ticks_this_day[regime] = regime_ticks_this_day.get(regime, 0) + 1

            # 7. Daily equity snapshot
            day = int(now_s // 86400)
            if day != last_equity_day:
                if last_equity_day >= 0:
                    day_ts = datetime.fromtimestamp(now_s, tz=UTC)
                    dd_pct = float((peak_equity - current_equity) / peak_equity) if peak_equity > _ZERO else 0.0
                    ref_equity = prev_day_equity if prev_day_equity > _ZERO else initial_equity
                    daily_ret = float((current_equity - ref_equity) / ref_equity) if ref_equity > _ZERO else 0.0
                    cum_ret = float((current_equity - initial_equity) / initial_equity) if initial_equity > _ZERO else 0.0
                    day_fills = len(fills) - fill_cursor_for_day
                    fill_cursor_for_day = len(fills)
                    equity_snapshots.append(EquitySnapshot(
                        date=day_ts.strftime("%Y-%m-%d"),
                        equity=current_equity,
                        drawdown_pct=Decimal(str(dd_pct)),
                        daily_return_pct=Decimal(str(daily_ret)),
                        cumulative_return_pct=Decimal(str(cum_ret)),
                        position_notional=position_base * mid_price if mid_price > _ZERO else _ZERO,
                        num_fills=day_fills,
                    ))
                    dominant = max(regime_ticks_this_day, key=regime_ticks_this_day.get) if regime_ticks_this_day else regime
                    snapshot_regimes.append(dominant)
                regime_ticks_this_day = {}
                prev_day_equity = current_equity
                last_equity_day = day

            # 8. Progress emission
            if progress_dir and total_ticks % progress_interval == 0:
                pct = min(100.0, total_ticks / expected_total_ticks * 100)
                try:
                    tmp = progress_dir / "progress.tmp"
                    tmp.write_text(json.dumps({
                        "current_tick": total_ticks,
                        "total_ticks": expected_total_ticks,
                        "progress_pct": round(pct, 1),
                    }))
                    tmp.rename(progress_dir / "progress.json")
                except OSError:
                    pass

            # 9. Advance clock
            now_ns += step_interval_ns

        # --- Final equity snapshot ---
        if backtest_candles:
            final_ts = datetime.fromtimestamp(end_ns / 1_000_000_000, tz=UTC)
            dd_pct = float((peak_equity - current_equity) / peak_equity) if peak_equity > _ZERO else 0.0
            ref_equity = prev_day_equity if prev_day_equity > _ZERO else initial_equity
            daily_ret = float((current_equity - ref_equity) / ref_equity) if ref_equity > _ZERO else 0.0
            cum_ret = float((current_equity - initial_equity) / initial_equity) if initial_equity > _ZERO else 0.0
            equity_snapshots.append(EquitySnapshot(
                date=final_ts.strftime("%Y-%m-%d"),
                equity=current_equity,
                drawdown_pct=Decimal(str(dd_pct)),
                daily_return_pct=Decimal(str(daily_ret)),
                cumulative_return_pct=Decimal(str(cum_ret)),
                position_notional=position_base * mid_price if mid_price > _ZERO else _ZERO,
                num_fills=len(fills) - fill_cursor_for_day,
            ))
            dominant = max(regime_ticks_this_day, key=regime_ticks_this_day.get) if regime_ticks_this_day else (adapter.regime_name or "unknown")
            snapshot_regimes.append(dominant)

        # --- Build regime return series from per-day dominant regime ---
        # Skip the initial anchor snapshot (regime="initial", return=0) so it
        # doesn't create a phantom regime or dilute real regime statistics.
        returns_by_regime: dict[str, list[float]] = {}
        for snap, rname in zip(equity_snapshots, snapshot_regimes, strict=True):
            if rname == "initial":
                continue
            returns_by_regime.setdefault(rname, []).append(float(snap.daily_return_pct))

        # --- Final progress: 100% ---
        if progress_dir:
            try:
                (progress_dir / "progress.json").write_text(json.dumps({
                    "current_tick": total_ticks,
                    "total_ticks": total_ticks,
                    "progress_pct": 100.0,
                }))
            except OSError:
                pass

        # --- Compute metrics ---
        from controllers.backtesting.metrics import compute_all_metrics

        run_duration = time.monotonic() - t0
        total_fees = sum((f.fee for f in fills), Decimal("0"))
        actual_pnl = current_equity - initial_equity
        result = compute_all_metrics(
            equity_curve=equity_snapshots,
            fills=fills,
            order_count=order_count,
            actual_pnl=actual_pnl,
            total_fees=total_fees,
            funding_paid=funding_paid,
            funding_received=funding_received,
            position_series=position_series,
            returns_by_regime=returns_by_regime if returns_by_regime else None,
            fills_by_regime=fills_by_regime if fills_by_regime else None,
        )
        from controllers.backtesting.metrics import compute_round_trips

        rt = compute_round_trips(fills)
        result.closed_trade_count = rt.total_count
        result.winning_trade_count = rt.win_count
        result.losing_trade_count = rt.loss_count
        result.gross_profit_quote = rt.gross_profit
        result.gross_loss_quote = rt.gross_loss
        result.avg_win_quote = rt.avg_win
        result.avg_loss_quote = rt.avg_loss
        result.expectancy_quote = rt.expectancy
        result.realized_net_pnl_quote = rt.realized_net
        result.residual_pnl_quote = actual_pnl - rt.realized_net
        result.terminal_position_base = position_base
        result.terminal_mark_price = mid_price if mid_price > _ZERO else _ZERO
        result.terminal_position_notional = (
            position_base * result.terminal_mark_price
            if result.terminal_mark_price > _ZERO else _ZERO
        )
        result.config = {
            "strategy_class": config.strategy_class,
            "exchange": config.data_source.exchange,
            "pair": config.data_source.pair,
            "resolution": config.data_source.resolution,
            "initial_equity": str(config.initial_equity),
            "fill_model": config.fill_model,
            "step_interval_s": config.step_interval_s,
            "warmup_bars": config.warmup_bars,
            "seed": config.seed,
        }
        result.run_duration_s = run_duration
        result.order_count = order_count
        result.total_ticks = total_ticks
        result.strategy_name = config.strategy_class.rsplit(".", 1)[-1] if config.strategy_class else ""
        if backtest_candles:
            result.data_start = datetime.fromtimestamp(
                backtest_candles[0].timestamp_ms / 1000, tz=UTC,
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            result.data_end = datetime.fromtimestamp(
                backtest_candles[-1].timestamp_ms / 1000, tz=UTC,
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            result.data_start = ""
            result.data_end = ""
        result.equity_curve = equity_snapshots
        result.fills = fills
        result.fill_disclaimer = (
            "Fills are approximate: synthetic order books from OHLCV candles. "
            "Use LatencyAwareFillModel for conservative estimates."
        )

        logger.info(
            "Backtest complete: %d ticks, %d fills, Sharpe=%.2f, return=%.2f%% in %.1fs",
            total_ticks, len(fills), result.sharpe_ratio,
            result.total_return_pct, run_duration,
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_candles(self) -> list[CandleRow]:
        """Load candles from data catalog or explicit path, filtered by date range.

        Uses filtered parquet loading with predicate pushdown when a date
        range is configured, avoiding a full-file scan + Python filtering.
        """
        ds = self._config.data_source
        start_ms, end_ms = self._date_range_to_ms(ds.start_date, ds.end_date)

        if ds.data_path:
            if start_ms or end_ms:
                candles = load_candles_window(Path(ds.data_path), start_ms=start_ms, end_ms=end_ms)
            else:
                candles = load_candles(Path(ds.data_path))
        else:
            from controllers.backtesting.data_catalog import DataCatalog
            catalog = DataCatalog(base_dir=Path(ds.catalog_dir))
            pair_key = ds.pair.replace("/", "-").replace(":", "-")
            entry = catalog.find(
                ds.exchange, pair_key, ds.resolution,
                start_ms=start_ms, end_ms=end_ms,
            )
            if entry is None:
                raise FileNotFoundError(
                    f"No dataset found for {ds.exchange}/{pair_key}/{ds.resolution} "
                    f"(catalog_dir={ds.catalog_dir!r}). "
                    f"Download (Bitget perp often needs BTC/USDT:USDT): "
                    f"python -m scripts.backtest.download_data "
                    f"--exchange {ds.exchange} --pair BTC/USDT:USDT --resolution {ds.resolution} "
                    f"--start {ds.start_date} --end {ds.end_date} "
                    f"(set --output to match catalog_dir, or BACKTEST_CATALOG_DIR in Docker)."
                )
            if start_ms or end_ms:
                candles = load_candles_window(Path(entry["file_path"]), start_ms=start_ms, end_ms=end_ms)
            else:
                candles = load_candles(Path(entry["file_path"]))

        return candles

    @staticmethod
    def _date_range_to_ms(
        start_date: str,
        end_date: str,
    ) -> tuple[int | None, int | None]:
        """Convert ISO date strings to ``(start_ms, end_ms)`` for parquet filters."""
        start_ms: int | None = None
        end_ms: int | None = None
        if start_date:
            dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
            start_ms = int(dt.timestamp() * 1000)
        if end_date:
            dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
            end_ms = int(dt.timestamp() * 1000) + 86_400_000  # inclusive end
        return start_ms, end_ms

    @staticmethod
    def _filter_by_date_range(
        candles: list[CandleRow],
        start_date: str,
        end_date: str,
    ) -> list[CandleRow]:
        """Clip candles to the [start_date, end_date] range if specified.

        Retained for walk-forward in-memory re-slicing where the candles
        are already loaded.
        """
        if not start_date and not end_date:
            return candles
        start_ms = 0
        end_ms = int(9e15)
        if start_date:
            dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
            start_ms = int(dt.timestamp() * 1000)
        if end_date:
            dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
            end_ms = int(dt.timestamp() * 1000) + 86_400_000  # inclusive end
        return [c for c in candles if start_ms <= c.timestamp_ms <= end_ms]

    @staticmethod
    def _build_adapter(
        config: BacktestConfig,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
    ) -> Any:
        """Build the tick adapter for this backtest.

        Delegates to the declarative adapter registry.  See
        ``adapter_registry.py`` for the full mapping and hydration logic.
        """
        from controllers.backtesting.adapter_registry import build_adapter

        return build_adapter(
            config,
            desk,
            instrument_id,
            instrument_spec,
            load_strategy_fn=_load_strategy,
        )
