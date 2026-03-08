from __future__ import annotations

import json
from pathlib import Path

import services.realtime_ui_api.main as realtime_ui_main
from services.contracts.stream_names import BOT_TELEMETRY_STREAM, MARKET_DATA_STREAM, MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM
from services.realtime_ui_api.main import (
    DeskSnapshotFallback,
    OpsDbReadModel,
    RealtimeApiConfig,
    RealtimeState,
    _build_alerts,
    _build_gate_timeline,
    _build_instance_status_rows,
    _build_runtime_open_order_placeholders,
    _candles_from_points,
    _enrich_closed_trades_with_minute_context,
    _reconstruct_closed_trades,
    _summarize_daily_review,
    _summarize_fill_activity,
    _summarize_journal_review,
    _summarize_weekly_report,
    _to_epoch_ms,
)


def test_realtime_state_process_and_query() -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    quote = {
        "event_type": "market_quote",
        "connector_name": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "best_bid": 99.9,
        "best_ask": 100.1,
        "mid_price": 100.0,
    }
    market = {
        "event_type": "market_snapshot",
        "instance_name": "bot1",
        "controller_id": "ctrl",
        "connector_name": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "mid_price": 100.0,
    }
    depth = {
        "event_type": "market_depth_snapshot",
        "instance_name": "bot1",
        "controller_id": "ctrl",
        "connector_name": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "bids": [{"price": 99.9, "size": 1.0}],
        "asks": [{"price": 100.1, "size": 1.0}],
    }
    fill = {
        "event_type": "bot_fill",
        "instance_name": "bot1",
        "controller_id": "ctrl",
        "connector_name": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "price": 100.0,
        "amount_base": 0.1,
    }
    state.process(MARKET_QUOTE_STREAM, "999-0", quote)
    state.process(MARKET_DATA_STREAM, "1000-0", market)
    state.process(MARKET_DEPTH_STREAM, "1001-0", depth)
    state.process(BOT_TELEMETRY_STREAM, "1002-0", fill)

    result = state.get_state("bot1", "ctrl", "BTC-USDT")
    assert result["market"]["event_type"] == "market_quote"
    assert result["bot_market"]["event_type"] == "market_snapshot"
    assert result["depth"]["event_type"] == "market_depth_snapshot"
    assert len(result["fills"]) == 1
    assert state.newest_stream_age_ms() is not None


def test_realtime_state_lists_detected_instances() -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    state.process(
        MARKET_DATA_STREAM,
        "1000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot2",
            "controller_id": "ctrl-b",
            "connector_name": "bitget_perpetual",
            "trading_pair": "ETH-USDT",
            "mid_price": 2500.0,
        },
    )
    state.process(
        BOT_TELEMETRY_STREAM,
        "1001-0",
        {
            "event_type": "bot_fill",
            "instance_name": "bot1",
            "controller_id": "ctrl-a",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "price": 100.0,
            "amount_base": 0.1,
        },
    )
    assert state.instance_names() == ["bot1", "bot2"]


def test_build_instance_status_rows_merges_stream_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    snapshot_path = reports_root / "desk_snapshot" / "bot1" / "latest.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "source_ts": "2026-03-06T12:00:00+00:00",
                "minute": {
                    "ts": "2026-03-06T12:00:00+00:00",
                    "trading_pair": "BTC-USDT",
                    "state": "running",
                    "orders_active": "2",
                    "equity_quote": "1005.5",
                }
                ,
                "daily_state": {"equity_open": "1000.0", "equity_peak": "1008.0"},
            }
        ),
        encoding="utf-8",
    )
    (data_root / "bot3" / "conf").mkdir(parents=True, exist_ok=True)
    (data_root / "bot3" / "conf" / "instance_meta.json").write_text(
        json.dumps({"visible_in_supervision": True, "controller_id": "ctrl-c", "trading_pair": "SOL-USDT"}),
        encoding="utf-8",
    )
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    monkeypatch.setattr(realtime_ui_main, "_now_ms", lambda: 20_000)
    state.process(
        MARKET_DATA_STREAM,
        "19500-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot1",
            "controller_id": "ctrl-a",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "mid_price": 100.0,
            "timestamp_ms": 19_500,
        },
    )
    state.process(
        MARKET_DATA_STREAM,
        "10000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot2",
            "controller_id": "ctrl-b",
            "connector_name": "bitget_perpetual",
            "trading_pair": "ETH-USDT",
            "mid_price": 2500.0,
            "timestamp_ms": 10_000,
        },
    )
    fallback = DeskSnapshotFallback(reports_root, data_root)
    rows = _build_instance_status_rows(state, fallback, stream_stale_ms=2_000)
    assert [row["instance_name"] for row in rows] == ["bot1", "bot2", "bot3"]
    assert rows[0]["freshness"] == "live"
    assert rows[0]["source_label"] == "stream+artifacts"
    assert rows[0]["controller_id"] == "ctrl-a"
    assert rows[0]["trading_pair"] == "BTC-USDT"
    assert rows[0]["orders_active"] == 2
    assert rows[0]["equity_quote"] == 1005.5
    assert rows[0]["equity_open_quote"] == 1000.0
    assert rows[0]["equity_delta_open_quote"] == 5.5
    assert rows[1]["freshness"] == "stale"
    assert rows[1]["source_label"] == "stream"
    assert rows[2]["freshness"] == "artifact"
    assert rows[2]["controller_id"] == "ctrl-c"
    assert rows[2]["trading_pair"] == "SOL-USDT"


def test_realtime_state_selected_stream_age_ignores_unrelated_keys(monkeypatch) -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    monkeypatch.setattr(realtime_ui_main, "_now_ms", lambda: 10_000)
    state.process(
        MARKET_DATA_STREAM,
        "1000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot1",
            "controller_id": "ctrl-a",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "mid_price": 100.0,
        },
    )
    state.process(
        MARKET_DATA_STREAM,
        "9000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot2",
            "controller_id": "ctrl-b",
            "connector_name": "bitget_perpetual",
            "trading_pair": "ETH-USDT",
            "mid_price": 200.0,
        },
    )
    assert state.newest_stream_age_ms() == 1000
    assert state.selected_stream_age_ms("bot1", "ctrl-a", "BTC-USDT") == 9000


def test_realtime_state_get_state_prefers_freshest_matching_key() -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    state.process(
        MARKET_DATA_STREAM,
        "9000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot1",
            "controller_id": "fresh-ctrl",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "mid_price": 101.0,
        },
    )
    state.process(
        MARKET_DATA_STREAM,
        "1000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot1",
            "controller_id": "stale-ctrl",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "mid_price": 99.0,
        },
    )
    result = state.get_state("bot1", "", "BTC-USDT")
    assert result["key"]["controller_id"] == "fresh-ctrl"
    assert result["bot_market"]["mid_price"] == 101.0


def test_realtime_state_candles_from_market_history() -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    for idx, price in enumerate([100.0, 101.0, 99.0, 102.0], start=1):
        state.process(
            MARKET_QUOTE_STREAM,
            f"{idx * 1000}-0",
            {
                "event_type": "market_quote",
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "mid_price": price,
                "best_bid": price - 0.1,
                "best_ask": price + 0.1,
            },
        )
    state.process(
        MARKET_DATA_STREAM,
        "9000-0",
        {
            "event_type": "market_snapshot",
            "instance_name": "bot1",
            "controller_id": "ctrl",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "mid_price": 102.0,
        },
    )
    candles = state.get_candles("bot1", "ctrl", "BTC-USDT", timeframe_s=2, limit=10)
    assert len(candles) >= 2
    assert set(candles[-1].keys()) == {"bucket_ms", "open", "high", "low", "close"}


def test_realtime_state_candles_include_depth_mid_history() -> None:
    cfg = RealtimeApiConfig()
    state = RealtimeState(cfg)
    for idx, (bid, ask) in enumerate([(99.9, 100.1), (100.9, 101.1), (98.9, 99.1), (101.9, 102.1)], start=1):
        state.process(
            MARKET_DEPTH_STREAM,
            f"{idx * 1000}-0",
            {
                "event_type": "market_depth_snapshot",
                "instance_name": "bot1",
                "controller_id": "ctrl",
                "trading_pair": "BTC-USDT",
                "bids": [{"price": bid, "size": 1.0}],
                "asks": [{"price": ask, "size": 1.0}],
            },
        )
    candles = state.get_candles("bot1", "ctrl", "BTC-USDT", timeframe_s=2, limit=10)
    assert len(candles) >= 2
    assert set(candles[-1].keys()) == {"bucket_ms", "open", "high", "low", "close"}


def test_to_epoch_ms_accepts_decimal_like_strings() -> None:
    ts_ms = _to_epoch_ms("1741200000000.0")
    assert ts_ms == 1741200000000


def test_candles_from_points_bridges_open_for_1m() -> None:
    points = [
        (1741200000000, 100.0),
        (1741200060000, 103.0),
        (1741200120000, 101.0),
    ]
    candles = _candles_from_points(points, timeframe_s=60, limit=10)
    assert len(candles) == 3
    assert candles[1]["open"] == 100.0
    assert candles[1]["close"] == 103.0
    assert candles[2]["open"] == 103.0
    assert candles[2]["close"] == 101.0


def test_summarize_fill_activity_builds_15m_and_1h_windows() -> None:
    now_ms = 1741203600000
    fills = [
        {
            "timestamp_ms": now_ms - 2 * 60 * 1000,
            "side": "BUY",
            "price": 100.0,
            "amount_base": 0.5,
            "realized_pnl_quote": 0.0,
            "is_maker": True,
        },
        {
            "timestamp_ms": now_ms - 20 * 60 * 1000,
            "side": "SELL",
            "price": 101.0,
            "amount_base": 0.25,
            "realized_pnl_quote": 1.25,
            "is_maker": False,
        },
    ]
    summary = _summarize_fill_activity(fills, now_ms=now_ms, fills_total=12)
    assert summary["fills_total"] == 12
    assert summary["window_15m"]["fill_count"] == 1
    assert summary["window_15m"]["maker_count"] == 1
    assert summary["window_15m"]["volume_base"] == 0.5
    assert summary["window_1h"]["fill_count"] == 2
    assert summary["window_1h"]["sell_count"] == 1
    assert summary["window_1h"]["realized_pnl_quote"] == 1.25


def test_ops_db_read_model_fill_activity_uses_aggregate_row(monkeypatch) -> None:
    reader = OpsDbReadModel(RealtimeApiConfig())
    monkeypatch.setattr(reader, "available", lambda: True)
    monkeypatch.setattr(
        reader,
        "_query",
        lambda _sql, _params: [
            {
                "m15_fill_count": 3,
                "m15_buy_count": 2,
                "m15_sell_count": 1,
                "m15_maker_count": 1,
                "m15_volume_base": 0.75,
                "m15_notional_quote": 75.5,
                "m15_realized_pnl_quote": 1.5,
                "m15_avg_fill_size": 0.25,
                "m15_avg_fill_price": 100.1,
                "h1_fill_count": 5,
                "h1_buy_count": 3,
                "h1_sell_count": 2,
                "h1_maker_count": 2,
                "h1_volume_base": 1.25,
                "h1_notional_quote": 126.0,
                "h1_realized_pnl_quote": 2.0,
                "h1_avg_fill_size": 0.25,
                "h1_avg_fill_price": 100.3,
                "fills_total": 42,
                "latest_fill_ts_ms": 1741203600000,
            }
        ],
    )
    summary = reader.get_fill_activity("bot1", "BTC-USDT")
    assert summary["fills_total"] == 42
    assert summary["window_15m"]["fill_count"] == 3
    assert summary["window_15m"]["maker_ratio"] == 1 / 3
    assert summary["window_1h"]["fill_count"] == 5
    assert summary["latest_fill_ts_ms"] == 1741203600000


def test_build_alerts_reports_hard_stop_and_stale_dependencies() -> None:
    alerts = _build_alerts(
        {
            "controller_state": "hard_stop",
            "risk_reasons": "derisk_hard_stop_flatten",
            "order_book_stale": True,
            "pnl_governor_active": True,
            "pnl_governor_reason": "active",
        },
        {
            "stream_age_ms": 20000,
            "fallback_active": True,
            "redis_available": False,
            "db_available": False,
        },
    )
    titles = {alert["title"] for alert in alerts}
    assert "Hard stop active" in titles
    assert "Risk reasons active" in titles
    assert "Order book stale" in titles
    assert "PnL governor active" in titles
    assert "Stream stale" in titles
    assert "Fallback active" in titles
    assert "Redis unavailable" in titles
    assert "DB unavailable" in titles


def test_summarize_weekly_report_maps_multi_day_artifact() -> None:
    review = _summarize_weekly_report(
        "bot1",
        {
            "period": {"start": "2026-03-01", "end": "2026-03-07"},
            "n_days": 7,
            "days_with_data": 5,
            "total_net_pnl_usdt": 12.5,
            "mean_daily_pnl_usdt": 2.5,
            "mean_daily_net_pnl_bps": 18.2,
            "sharpe_annualized": 1.7,
            "win_rate": 0.6,
            "winning_days": 3,
            "losing_days": 2,
            "max_single_day_drawdown_pct": 0.012,
            "hard_stop_days": 0,
            "total_fills": 250,
            "warnings": ["window_short"],
            "regime_breakdown": {"neutral_low_vol": 10, "up": 25},
            "pnl_decomposition": {
                "dominant_source": "spread_capture",
                "spread_capture_dominant_source": True,
            },
            "road1_gate": {"pass": False, "failed_criteria": ["sharpe_gte_1_5"]},
            "daily_breakdown": [
                {
                    "date": "2026-03-01",
                    "net_pnl_usdt": 5.0,
                    "net_pnl_bps": 20.0,
                    "drawdown_pct": 0.01,
                    "daily_loss_pct": 0.0,
                    "fills": 100,
                    "turnover_x": 1.2,
                    "dominant_regime": "up",
                    "equity_quote": 1010.0,
                }
            ],
        },
    )
    assert review["summary"]["period_start"] == "2026-03-01"
    assert review["summary"]["total_net_pnl_quote"] == 12.5
    assert review["summary"]["dominant_regime"] == "up"
    assert review["summary"]["spread_capture_dominant_source"] is True
    assert review["summary"]["gate_pass"] is False
    assert len(review["days"]) == 1
    assert review["days"][0]["date"] == "2026-03-01"


def test_reconstruct_closed_trades_builds_round_trip_journal() -> None:
    trades = _reconstruct_closed_trades(
        [
            {
                "timestamp_ms": 1000,
                "side": "BUY",
                "price": 100.0,
                "amount_base": 1.0,
                "fee_quote": 0.1,
                "realized_pnl_quote": 0.0,
                "is_maker": True,
            },
            {
                "timestamp_ms": 2000,
                "side": "BUY",
                "price": 110.0,
                "amount_base": 1.0,
                "fee_quote": 0.1,
                "realized_pnl_quote": 0.0,
                "is_maker": False,
            },
            {
                "timestamp_ms": 3000,
                "side": "SELL",
                "price": 120.0,
                "amount_base": 2.0,
                "fee_quote": 0.2,
                "realized_pnl_quote": 30.0,
                "is_maker": True,
            },
        ]
    )
    assert len(trades) == 1
    assert trades[0]["side"] == "long"
    assert trades[0]["quantity"] == 2.0
    assert trades[0]["avg_entry_price"] == 105.0
    assert trades[0]["avg_exit_price"] == 120.0
    assert trades[0]["realized_pnl_quote"] == 30.0
    assert trades[0]["fees_quote"] == 0.4
    assert len(trades[0]["fills"]) == 3
    assert trades[0]["fills"][0]["role"] == "entry"
    assert trades[0]["fills"][-1]["role"] == "exit"


def test_summarize_journal_review_aggregates_trade_stats() -> None:
    review = _summarize_journal_review(
        [
            {
                "entry_ts": "2026-03-01T00:00:00+00:00",
                "exit_ts": "2026-03-01T00:10:00+00:00",
                "realized_pnl_quote": 5.0,
                "fees_quote": 0.2,
                "hold_seconds": 600,
                "mfe_quote": 6.0,
                "mae_quote": -1.0,
                "entry_regime": "neutral_low_vol",
                "exit_reason_label": "profitable close",
            },
            {
                "entry_ts": "2026-03-01T01:00:00+00:00",
                "exit_ts": "2026-03-01T01:20:00+00:00",
                "realized_pnl_quote": -2.0,
                "fees_quote": 0.1,
                "hold_seconds": 1200,
                "mfe_quote": 1.0,
                "mae_quote": -3.0,
                "entry_regime": "trend_high_vol",
                "exit_reason_label": "risk / derisk",
            },
        ]
    )
    assert review["summary"]["trade_count"] == 2
    assert review["summary"]["winning_trades"] == 1
    assert review["summary"]["losing_trades"] == 1
    assert review["summary"]["win_rate"] == 0.5
    assert review["summary"]["realized_pnl_quote_total"] == 3.0
    assert review["summary"]["fees_quote_total"] == 0.30000000000000004
    assert review["summary"]["avg_mfe_quote"] == 3.5
    assert review["summary"]["avg_mae_quote"] == -2.0
    assert review["summary"]["entry_regime_breakdown"]["neutral_low_vol"] == 1
    assert review["summary"]["exit_reason_breakdown"]["risk / derisk"] == 1


def test_enrich_closed_trades_with_minute_context_adds_excursion_and_context() -> None:
    enriched = _enrich_closed_trades_with_minute_context(
        [
            {
                "trade_id": "trade-1",
                "entry_ts_ms": 1_000,
                "exit_ts_ms": 3_000,
                "entry_ts": "1970-01-01T00:00:01+00:00",
                "exit_ts": "1970-01-01T00:00:03+00:00",
                "side": "long",
                "quantity": 2.0,
                "avg_entry_price": 100.0,
                "avg_exit_price": 101.0,
                "realized_pnl_quote": 2.0,
                "fees_quote": 0.1,
                "hold_seconds": 2.0,
                "fill_count": 2,
                "maker_ratio": 0.5,
            }
        ],
        [
            {
                "timestamp_ms": 1_000,
                "mid": 100.0,
                "state": "running",
                "regime": "neutral_low_vol",
                "risk_reasons": "",
                "pnl_governor_active": False,
                "order_book_stale": False,
            },
            {
                "timestamp_ms": 2_000,
                "mid": 103.0,
                "state": "running",
                "regime": "neutral_low_vol",
                "risk_reasons": "base_pct_above_max",
                "pnl_governor_active": False,
                "order_book_stale": False,
            },
            {
                "timestamp_ms": 3_000,
                "mid": 99.0,
                "state": "soft_pause",
                "regime": "trend_high_vol",
                "risk_reasons": "base_pct_above_max|derisk_only",
                "pnl_governor_active": True,
                "order_book_stale": False,
            },
        ],
    )
    assert enriched[0]["entry_regime"] == "neutral_low_vol"
    assert enriched[0]["exit_regime"] == "trend_high_vol"
    assert enriched[0]["exit_state"] == "soft_pause"
    assert enriched[0]["mfe_quote"] == 6.0
    assert enriched[0]["mae_quote"] == -2.0
    assert enriched[0]["pnl_governor_seen"] is True
    assert enriched[0]["exit_reason_label"] == "risk / derisk"
    assert enriched[0]["path_summary"]["mid_high"] == 103.0
    assert enriched[0]["path_summary"]["point_count"] == 3
    assert len(enriched[0]["path_points"]) == 3
    assert len(enriched[0]["gate_timeline"]) >= 1


def test_enrich_closed_trades_with_minute_context_falls_back_to_fill_path() -> None:
    enriched = _enrich_closed_trades_with_minute_context(
        [
            {
                "trade_id": "trade-1",
                "entry_ts_ms": 1_000,
                "exit_ts_ms": 3_000,
                "entry_ts": "1970-01-01T00:00:01+00:00",
                "exit_ts": "1970-01-01T00:00:03+00:00",
                "side": "long",
                "quantity": 1.0,
                "avg_entry_price": 100.0,
                "avg_exit_price": 102.0,
                "realized_pnl_quote": 2.0,
                "fees_quote": 0.1,
                "hold_seconds": 2.0,
                "fill_count": 2,
                "maker_ratio": 1.0,
                "fills": [
                    {"ts": "1970-01-01T00:00:01+00:00", "timestamp_ms": 1_000, "price": 100.0, "role": "entry"},
                    {"ts": "1970-01-01T00:00:03+00:00", "timestamp_ms": 3_000, "price": 102.0, "role": "exit"},
                ],
            }
        ],
        [],
    )
    assert enriched[0]["path_summary"]["point_count"] == 2
    assert enriched[0]["path_summary"]["mid_open"] == 100.0
    assert enriched[0]["path_summary"]["mid_close"] == 102.0
    assert len(enriched[0]["path_points"]) == 2
    assert enriched[0]["path_points"][0]["state"] == "entry"


def test_build_gate_timeline_collapses_stable_segments() -> None:
    timeline = _build_gate_timeline(
        [
            {"timestamp_ms": 1_000, "state": "running", "regime": "neutral_low_vol", "risk_reasons": "", "pnl_governor_active": False, "order_book_stale": False, "soft_pause_edge": False, "net_edge_pct": 0.0003, "net_edge_gate_pct": 0.0002, "adaptive_effective_min_edge_pct": 0.0002, "spread_pct": 0.0020, "spread_floor_pct": 0.0015, "spread_competitiveness_cap_active": False, "orders_active": 2, "pnl_governor_activation_reason": ""},
            {"timestamp_ms": 2_000, "state": "running", "regime": "neutral_low_vol", "risk_reasons": "", "pnl_governor_active": False, "order_book_stale": False, "soft_pause_edge": False, "net_edge_pct": 0.00031, "net_edge_gate_pct": 0.0002, "adaptive_effective_min_edge_pct": 0.0002, "spread_pct": 0.0020, "spread_floor_pct": 0.0015, "spread_competitiveness_cap_active": False, "orders_active": 2, "pnl_governor_activation_reason": ""},
            {"timestamp_ms": 3_000, "state": "soft_pause", "regime": "neutral_low_vol", "risk_reasons": "soft_pause_edge", "pnl_governor_active": False, "order_book_stale": False, "soft_pause_edge": True, "net_edge_pct": 0.0001, "net_edge_gate_pct": 0.0002, "adaptive_effective_min_edge_pct": 0.0002, "spread_pct": 0.0010, "spread_floor_pct": 0.0015, "spread_competitiveness_cap_active": False, "orders_active": 0, "pnl_governor_activation_reason": ""},
        ]
    )
    assert len(timeline) == 2
    assert timeline[0]["quoting_status"] == "quoting"
    assert timeline[1]["quoting_status"] == "waiting"


def test_build_runtime_open_order_placeholders_marks_runtime_source() -> None:
    orders = _build_runtime_open_order_placeholders(
        orders_active=2,
        best_bid=99.5,
        best_ask=100.5,
        mid_price=100.0,
        quantity=0.4,
        trading_pair="BTC-USDT",
        timestamp_ms=1_234,
        source_label="runtime",
    )
    assert len(orders) == 2
    assert orders[0]["order_id"] == "runtime-BTC-USDT-buy-1"
    assert orders[0]["side"] == "buy"
    assert orders[0]["price"] == 99.5
    assert orders[0]["estimate_source"] == "runtime"
    assert orders[0]["price_hint_source"] == "book"
    assert orders[0]["trading_pair"] == "BTC-USDT"
    assert orders[1]["order_id"] == "runtime-BTC-USDT-sell-1"
    assert orders[1]["side"] == "sell"
    assert orders[1]["price"] == 100.5


def test_desk_snapshot_fallback_extracts_position_and_orders(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    path = reports_root / "desk_snapshot" / "bot1" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_ts": "2026-03-05T12:00:00+00:00",
        "minute": {"mid": "100"},
        "open_orders": [{"order_id": "1", "trading_pair": "BTC-USDT"}],
        "portfolio": {
            "portfolio": {
                "positions": {
                    "bitget:BTC-USDT:perp": {"quantity": "0.5"},
                }
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    fallback = DeskSnapshotFallback(reports_root)
    state = fallback.state_from_snapshot("bot1", "BTC-USDT")
    assert state["snapshot_ts"] == "2026-03-05T12:00:00+00:00"
    assert len(state["open_orders"]) == 1
    assert state["position"]["quantity"] == "0.5"

    # Pair matching should be robust to separators/casing differences.
    state_slash_pair = fallback.state_from_snapshot("bot1", "btc/usdt")
    assert state_slash_pair["position"]["quantity"] == "0.5"


def test_desk_snapshot_fallback_lists_available_instances(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    (reports_root / "desk_snapshot" / "bot2").mkdir(parents=True, exist_ok=True)
    (reports_root / "desk_snapshot" / "bot2" / "latest.json").write_text("{}", encoding="utf-8")
    (data_root / "bot1" / "logs").mkdir(parents=True, exist_ok=True)
    (data_root / "bot3" / "conf").mkdir(parents=True, exist_ok=True)
    (data_root / "bot4").mkdir(parents=True, exist_ok=True)
    (data_root / "bot4" / ".supervision_enabled").write_text("", encoding="utf-8")
    (data_root / "bot5" / "conf").mkdir(parents=True, exist_ok=True)
    (data_root / "bot5" / "conf" / "instance_meta.json").write_text(
        json.dumps({"visible_in_supervision": True, "controller_id": "ctrl-5", "trading_pair": "SOL-USDT"}),
        encoding="utf-8",
    )
    fallback = DeskSnapshotFallback(reports_root, data_root)
    assert fallback.available_instances() == ["bot1", "bot2", "bot3", "bot4", "bot5"]


def test_desk_snapshot_fallback_does_not_leak_other_pair_position_or_orders(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    path = reports_root / "desk_snapshot" / "bot1" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_ts": "2026-03-05T12:00:00+00:00",
        "minute": {"mid": "100", "orders_active": "2", "best_bid_price": "99.5", "best_ask_price": "100.5"},
        "open_orders": [{"order_id": "eth-1", "trading_pair": "ETH-USDT", "side": "buy"}],
        "portfolio": {
            "portfolio": {
                "positions": {
                    "bitget:ETH-USDT:perp": {"quantity": "1.25"},
                }
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    fallback = DeskSnapshotFallback(reports_root)
    state = fallback.state_from_snapshot("bot1", "BTC-USDT")
    assert state["open_orders"] == []
    assert state["position"] == {}


def test_desk_snapshot_fallback_builds_runtime_order_placeholders_for_matching_minute_pair(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    path = reports_root / "desk_snapshot" / "bot1" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_ts": "2026-03-05T12:00:00+00:00",
        "minute": {
            "ts": "2026-03-05T12:00:00+00:00",
            "trading_pair": "BTC-USDT",
            "orders_active": "2",
            "best_bid_price": "99.5",
            "best_ask_price": "100.5",
        },
        "open_orders": [],
        "portfolio": {"portfolio": {"positions": {}}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    fallback = DeskSnapshotFallback(reports_root)
    state = fallback.state_from_snapshot("bot1", "BTC-USDT")
    assert len(state["open_orders"]) == 2
    assert state["open_orders"][0]["estimate_source"] == "runtime"
    assert state["open_orders"][0]["price_hint_source"] == "book"
    assert state["open_orders"][0]["trading_pair"] == "BTC-USDT"
    assert state["open_orders"][0]["state"] == "runtime"
    assert state["open_orders"][1]["state"] == "runtime"


def test_build_runtime_open_order_placeholders_falls_back_to_mid_price() -> None:
    orders = _build_runtime_open_order_placeholders(
        orders_active=1,
        best_bid=None,
        best_ask=None,
        mid_price=100.25,
        quantity=None,
        trading_pair="BTC-USDT",
        timestamp_ms=1_234,
        source_label="runtime",
    )
    assert len(orders) == 1
    assert orders[0]["order_id"] == "runtime-BTC-USDT-open-1"
    assert orders[0]["price"] == 100.25
    assert orders[0]["amount"] is None
    assert orders[0]["price_hint_source"] == "mid"


def test_desk_snapshot_fallback_account_summary_reads_minute_equity(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    path = reports_root / "desk_snapshot" / "bot1" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_ts": "2026-03-06T12:00:00+00:00",
        "minute": {
            "ts": "2026-03-06T12:00:00+00:00",
            "equity_quote": "1000.5",
            "quote_balance": "998.25",
            "state": "running",
            "regime": "neutral_low_vol",
            "pnl_governor_active": "True",
            "pnl_governor_activation_reason": "active",
            "risk_reasons": "soft_pause_edge",
            "daily_loss_pct": "0.0125",
            "max_daily_loss_pct_hard": "0.03",
            "drawdown_pct": "0.02",
            "max_drawdown_pct_hard": "0.05",
            "order_book_stale": "False",
            "soft_pause_edge": "True",
            "net_edge_pct": "0.00015",
            "net_edge_gate_pct": "0.00020",
            "adaptive_effective_min_edge_pct": "0.00018",
            "spread_pct": "0.0019",
            "spread_floor_pct": "0.0016",
            "spread_competitiveness_cap_active": "True",
            "orders_active": "2",
        },
        "daily_state": {
            "equity_open": "995.0",
            "equity_peak": "1002.75",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    fallback = DeskSnapshotFallback(reports_root)
    summary = fallback.account_summary("bot1")
    assert summary["equity_quote"] == 1000.5
    assert summary["quote_balance"] == 998.25
    assert summary["equity_open_quote"] == 995.0
    assert summary["equity_peak_quote"] == 1002.75
    assert summary["controller_state"] == "running"
    assert summary["regime"] == "neutral_low_vol"
    assert summary["pnl_governor_active"] is True
    assert summary["pnl_governor_reason"] == "active"
    assert summary["risk_reasons"] == "soft_pause_edge"
    assert summary["daily_loss_pct"] == 0.0125
    assert summary["max_daily_loss_pct_hard"] == 0.03
    assert summary["drawdown_pct"] == 0.02
    assert summary["max_drawdown_pct_hard"] == 0.05
    assert summary["order_book_stale"] is False
    assert summary["quoting_status"] == "waiting"
    assert "Soft pause edge gate active" in summary["quoting_reason"]
    assert summary["orders_active"] == 2
    assert len(summary["quote_gates"]) >= 6
    edge_gate = next(gate for gate in summary["quote_gates"] if gate["key"] == "edge")
    assert edge_gate["status"] == "fail"
    assert summary["snapshot_ts"] == "2026-03-06T12:00:00+00:00"


def test_desk_snapshot_fallback_loads_candles_from_minute_log(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    minute_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_path.parent.mkdir(parents=True, exist_ok=True)
    minute_path.write_text(
        "\n".join(
            [
                "ts,trading_pair,mid",
                "2026-03-05T12:00:00+00:00,BTC-USDT,100",
                "2026-03-05T12:00:30+00:00,BTC-USDT,101",
                "2026-03-05T12:01:00+00:00,BTC-USDT,99",
                "2026-03-05T12:01:30+00:00,ETH-USDT,2000",
                "2026-03-05T12:02:00+00:00,BTC-USDT,102",
            ]
        ),
        encoding="utf-8",
    )

    fallback = DeskSnapshotFallback(reports_root, data_root)
    candles = fallback.candles_from_minute_log("bot1", "BTC-USDT", timeframe_s=60, limit=10)

    assert len(candles) == 3
    assert candles[0]["open"] == 100.0
    assert candles[0]["close"] == 101.0
    assert candles[-1]["close"] == 102.0


def test_desk_snapshot_fallback_minute_log_bridges_open_on_1m(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    minute_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_path.parent.mkdir(parents=True, exist_ok=True)
    minute_path.write_text(
        "\n".join(
            [
                "ts,trading_pair,mid",
                "2026-03-05T12:00:00+00:00,BTC-USDT,100",
                "2026-03-05T12:01:00+00:00,BTC-USDT,103",
                "2026-03-05T12:02:00+00:00,BTC-USDT,101",
            ]
        ),
        encoding="utf-8",
    )
    fallback = DeskSnapshotFallback(reports_root, data_root)
    candles = fallback.candles_from_minute_log("bot1", "BTC-USDT", timeframe_s=60, limit=10)
    assert len(candles) == 3
    assert candles[1]["open"] == 100.0
    assert candles[1]["close"] == 103.0


def test_desk_snapshot_fallback_loads_fills_from_csv(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    fills_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv"
    fills_path.parent.mkdir(parents=True, exist_ok=True)
    fills_path.write_text(
        "\n".join(
            [
                "ts,trading_pair,side,price,amount_base,realized_pnl_quote,order_id,is_maker",
                "2026-03-05T12:00:00+00:00,BTC-USDT,buy,100,0.1,0,o1,false",
                "2026-03-05T12:00:30+00:00,BTC-USDT,sell,101,0.1,0.2,o2,true",
                "2026-03-05T12:00:40+00:00,ETH-USDT,buy,2000,1,0,o3,false",
            ]
        ),
        encoding="utf-8",
    )

    fallback = DeskSnapshotFallback(reports_root, data_root)
    fills = fallback.fills_from_csv("bot1", "BTC-USDT", limit=20)

    assert len(fills) == 2
    assert fills[-1]["order_id"] == "o2"
    assert fills[-1]["is_maker"] is True


def test_desk_snapshot_fallback_loads_day_scoped_review_rows(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    minute_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    fills_path = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv"
    minute_path.parent.mkdir(parents=True, exist_ok=True)
    fills_path.parent.mkdir(parents=True, exist_ok=True)
    minute_path.write_text(
        "\n".join(
            [
                "ts,trading_pair,mid,equity_quote,quote_balance,realized_pnl_today_quote,state,regime,risk_reasons,pnl_governor_active,order_book_stale",
                "2026-03-05T09:00:00+00:00,BTC-USDT,100,1000,999,1.5,running,up,,True,False",
                "2026-03-05T10:00:00+00:00,BTC-USDT,101,1002,999,2.0,running,up,,True,False",
                "2026-03-06T10:00:00+00:00,BTC-USDT,102,1003,999,3.0,hard_stop,down,risk,False,True",
            ]
        ),
        encoding="utf-8",
    )
    fills_path.write_text(
        "\n".join(
            [
                "ts,trading_pair,side,price,amount_base,notional_quote,fee_quote,realized_pnl_quote,order_id,is_maker",
                "2026-03-05T09:10:00+00:00,BTC-USDT,buy,100,0.1,10,0.01,0.0,o1,false",
                "2026-03-05T10:15:00+00:00,BTC-USDT,sell,102,0.1,10.2,0.01,0.5,o2,true",
                "2026-03-06T11:00:00+00:00,BTC-USDT,sell,103,0.1,10.3,0.01,0.7,o3,true",
            ]
        ),
        encoding="utf-8",
    )
    fallback = DeskSnapshotFallback(reports_root, data_root)
    minute_rows = fallback.minute_rows_from_csv("bot1", "BTC-USDT", "2026-03-05")
    fills = fallback.fills_from_csv_for_day("bot1", "BTC-USDT", "2026-03-05")
    review = _summarize_daily_review(
        "2026-03-05",
        minute_rows,
        fills,
        {"equity_open_quote": 1000.0, "equity_quote": 1002.0, "quote_balance": 999.0},
    )
    assert len(minute_rows) == 2
    assert len(fills) == 2
    assert review["summary"]["equity_open_quote"] == 1000.0
    assert review["summary"]["equity_close_quote"] == 1002.0
    assert review["summary"]["fill_count"] == 2
    assert review["summary"]["maker_ratio"] == 0.5
    assert len(review["hourly"]) == 2
    assert len(review["gate_timeline"]) == 1
    assert review["gate_timeline"][0]["quoting_status"] == "waiting"


def test_desk_snapshot_fallback_open_orders_from_state_snapshot(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    data_root = tmp_path / "data"
    state_snapshot_path = reports_root / "verification" / "paper_exchange_state_snapshot_latest.json"
    state_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    state_snapshot_path.write_text(
        json.dumps(
            {
                "orders": {
                    "o1": {
                        "order_id": "o1",
                        "instance_name": "bot1",
                        "trading_pair": "BTC-USDT",
                        "side": "buy",
                        "price": 99.5,
                        "amount_base": 0.4,
                        "state": "open",
                        "created_ts_ms": 1000,
                        "updated_ts_ms": 1001,
                    },
                    "o2": {
                        "order_id": "o2",
                        "instance_name": "bot1",
                        "trading_pair": "BTC-USDT",
                        "side": "sell",
                        "price": 101.5,
                        "amount_base": 0.3,
                        "state": "filled",
                        "created_ts_ms": 1002,
                        "updated_ts_ms": 1003,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    fallback = DeskSnapshotFallback(reports_root, data_root)
    orders = fallback.open_orders_from_state_snapshot("bot1", "BTC-USDT", limit=20)
    assert len(orders) == 1
    assert orders[0]["order_id"] == "o1"
    assert orders[0]["state"] == "open"


def test_ops_db_read_model_rest_backfill_candles(monkeypatch) -> None:
    class _FakeExchange:
        def __init__(self, _opts):
            self.sandbox = False

        def set_sandbox_mode(self, enabled: bool) -> None:
            self.sandbox = enabled

        def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int):
            assert symbol == "BTC/USDT"
            assert timeframe == "1m"
            assert limit == 5
            return [
                [1741200000000, 100.0, 101.0, 99.5, 100.5, 12.0],
                [1741200060000, 100.5, 102.0, 100.0, 101.5, 8.0],
            ]

    monkeypatch.setattr(realtime_ui_main, "ccxt", type("FakeCcxt", (), {"bitget": _FakeExchange}))
    reader = OpsDbReadModel(RealtimeApiConfig())
    candles = reader.get_rest_backfill_candles("bitget_perpetual", "BTC-USDT", 60, 5)
    assert len(candles) == 2
    assert candles[0]["open"] == 100.0
    assert candles[-1]["close"] == 101.5
