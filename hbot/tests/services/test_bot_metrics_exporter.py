from __future__ import annotations

import json
from datetime import UTC, datetime

from services.bot_metrics_exporter import BotMetricsExporter


def _write_minute_csv(path, include_net: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "ts",
        "bot_variant",
        "bot_mode",
        "accounting_source",
        "exchange",
        "trading_pair",
        "state",
        "regime",
        "equity_quote",
        "fills_count_today",
        "realized_pnl_today_quote",
        "funding_cost_today_quote",
        "history_seed_status",
        "history_seed_reason",
        "history_seed_source",
        "history_seed_bars",
        "history_seed_latency_ms",
        "ws_reconnect_count",
        "pnl_governor_target_effective_pct",
        "pnl_governor_size_mult_applied",
        "spread_competitiveness_cap_active",
        "spread_competitiveness_cap_side_pct",
        "pnl_governor_target_mode",
        "projected_total_quote",
        "edge_pause_threshold_pct",
        "edge_resume_threshold_pct",
        "min_base_pct",
        "max_base_pct",
        "max_total_notional_quote",
        "max_daily_turnover_x_hard",
        "max_daily_loss_pct_hard",
        "max_drawdown_pct_hard",
        "margin_ratio_soft_pause_pct",
        "margin_ratio_hard_stop_pct",
        "position_drift_soft_pause_pct",
        "margin_ratio",
        "position_drift_pct",
        "base_pct",
        "daily_loss_pct",
        "drawdown_pct",
        "turnover_today_x",
        "risk_reasons",
    ]
    if include_net:
        headers.append("net_realized_pnl_today_quote")
    values = {
        "ts": "2026-02-27T22:00:00+00:00",
        "bot_variant": "a",
        "bot_mode": "paper",
        "accounting_source": "paper_desk_v2",
        "exchange": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "state": "running",
        "regime": "neutral_low_vol",
        "equity_quote": "500",
        "fills_count_today": "4",
        "realized_pnl_today_quote": "12.5",
        "funding_cost_today_quote": "1.5",
        "history_seed_status": "fresh",
        "history_seed_reason": "",
        "history_seed_source": "db_v2",
        "history_seed_bars": "33",
        "history_seed_latency_ms": "87.5",
        "ws_reconnect_count": "0",
        "pnl_governor_target_effective_pct": "1.0",
        "pnl_governor_size_mult_applied": "1.15",
        "spread_competitiveness_cap_active": "true",
        "spread_competitiveness_cap_side_pct": "0.0012",
        "pnl_governor_target_mode": "pct_equity",
        "projected_total_quote": "120",
        "edge_pause_threshold_pct": "0.0004",
        "edge_resume_threshold_pct": "0.0006",
        "min_base_pct": "0.15",
        "max_base_pct": "0.90",
        "max_total_notional_quote": "1000",
        "max_daily_turnover_x_hard": "6",
        "max_daily_loss_pct_hard": "0.03",
        "max_drawdown_pct_hard": "0.05",
        "margin_ratio_soft_pause_pct": "0.20",
        "margin_ratio_hard_stop_pct": "0.10",
        "position_drift_soft_pause_pct": "0.05",
        "margin_ratio": "0.25",
        "position_drift_pct": "0.01",
        "base_pct": "0.50",
        "daily_loss_pct": "0.01",
        "drawdown_pct": "0.02",
        "turnover_today_x": "1.2",
        "risk_reasons": "edge_gate_blocked|margin_ratio_warning",
        "net_realized_pnl_today_quote": "11.0",
    }
    row = ",".join(values[h] for h in headers)
    path.write_text(",".join(headers) + "\n" + row + "\n", encoding="utf-8")


def test_net_realized_metric_uses_minute_field_when_present(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot_net_realized_pnl_today_quote" in text
    assert " 11.0" in text


def test_net_realized_metric_falls_back_to_realized_minus_funding(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=False)

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    # fallback: 12.5 - 1.5 = 11.0
    assert "hbot_bot_net_realized_pnl_today_quote" in text
    assert " 11.0" in text


def test_governor_and_competitiveness_metrics_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot_pnl_governor_target_effective_pct" in text
    assert "hbot_bot_pnl_governor_size_mult_applied" in text
    assert "hbot_bot_spread_competitiveness_cap_active" in text
    assert "hbot_bot_spread_competitiveness_cap_side_pct" in text
    assert 'hbot_bot_pnl_governor_target_mode_info' in text
    assert 'target_mode="pct_equity"' in text


def test_history_seed_metrics_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_history_seed_status" in text
    assert 'status="fresh"' in text
    assert "hbot_history_seed_bars_count" in text
    assert " 33.0" in text or " 33\n" in text
    assert "hbot_history_seed_latency_ms" in text
    assert " 87.5" in text
    assert "hbot_history_seed_info" in text
    assert 'source="db_v2"' in text


def test_gate_diagnostics_metrics_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot_gate_active_total" in text
    assert "hbot_bot_gate_active_hard_total" in text
    assert "hbot_bot_gate_active_soft_total" in text
    assert "hbot_bot_gate_reason_active" in text
    assert 'reason="edge_gate_blocked"' in text
    assert "hbot_bot_gate_headroom_ratio" in text
    assert 'gate="daily_loss"' in text
    assert 'gate="edge_pause"' in text
    assert "hbot_bot_gate_threshold_value" in text
    assert "hbot_bot_gate_current_value" in text


def test_bot6_directional_metrics_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot6" / "logs" / "epp_v24" / "bot6_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "ts",
        "bot_variant",
        "bot_mode",
        "accounting_source",
        "exchange",
        "trading_pair",
        "state",
        "regime",
        "equity_quote",
        "fills_count_today",
        "realized_pnl_today_quote",
        "funding_cost_today_quote",
        "bot6_signal_score_active",
        "bot6_cvd_divergence_ratio",
        "bot6_delta_spike_ratio",
    ]
    values = {
        "ts": "2026-02-27T22:00:00+00:00",
        "bot_variant": "a",
        "bot_mode": "paper",
        "accounting_source": "paper_desk_v2",
        "exchange": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "state": "running",
        "regime": "up",
        "equity_quote": "500",
        "fills_count_today": "4",
        "realized_pnl_today_quote": "12.5",
        "funding_cost_today_quote": "1.5",
        "bot6_signal_score_active": "8",
        "bot6_cvd_divergence_ratio": "0.21",
        "bot6_delta_spike_ratio": "3.6",
    }
    minute_file.write_text(
        ",".join(headers) + "\n" + ",".join(values[h] for h in headers) + "\n",
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot6_signal_score_active" in text
    assert "hbot_bot6_cvd_divergence_ratio" in text
    assert "hbot_bot6_delta_spike_ratio" in text


def test_standardized_dedicated_bot_signal_scores_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot7" / "logs" / "epp_v24" / "bot7_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "ts",
        "bot_variant",
        "bot_mode",
        "accounting_source",
        "exchange",
        "trading_pair",
        "state",
        "regime",
        "equity_quote",
        "bot1_signal_score",
        "bot5_signal_score",
        "bot6_signal_score",
        "bot7_signal_score",
    ]
    values = {
        "ts": "2026-02-27T22:00:00+00:00",
        "bot_variant": "a",
        "bot_mode": "paper",
        "accounting_source": "paper_desk_v2",
        "exchange": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "state": "running",
        "regime": "neutral_low_vol",
        "equity_quote": "500",
        "bot1_signal_score": "0.42",
        "bot5_signal_score": "0.75",
        "bot6_signal_score": "8",
        "bot7_signal_score": "0.66",
    }
    minute_file.write_text(
        ",".join(headers) + "\n" + ",".join(values[h] for h in headers) + "\n",
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot1_signal_score" in text
    assert "hbot_bot5_signal_score" in text
    assert "hbot_bot6_signal_score" in text
    assert "hbot_bot7_signal_score" in text


def test_open_and_closed_trade_table_metrics_are_exported(tmp_path) -> None:
    base_dir = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a"
    minute_file = base_dir / "minute.csv"
    fills_file = base_dir / "fills.csv"
    desk_file = base_dir / "paper_desk_v2.json"
    _write_minute_csv(minute_file, include_net=True)
    fills_file.write_text(
        "ts,side,price,amount_base,notional_quote,fee_quote,order_id,state,expected_spread_pct,realized_pnl_quote\n"
        "2026-02-27T22:00:00+00:00,buy,100,1,100,0.1,t1,running,0.001,2.5\n",
        encoding="utf-8",
    )
    desk_file.write_text(
        json.dumps(
            {
                "portfolio": {
                    "positions": {
                        "bitget:BTC-USDT:perp": {
                            "quantity": 1.0,
                            "avg_entry_price": 100.0,
                            "unrealized_pnl": 5.0,
                            "opened_at_ns": 1709070000000000000,
                            "total_fees_paid": 0.2,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert "hbot_bot_position_unrealized_pnl_pct" in text
    assert "hbot_bot_position_duration_seconds" in text
    assert "hbot_bot_position_stop_pct" in text
    assert 'hbot_bot_position_side_info' in text
    assert 'side="long"' in text
    assert "hbot_bot_closed_trade_profit_quote" in text
    assert "hbot_bot_closed_trade_profit_pct" in text
    assert "hbot_bot_closed_trade_info" in text


def test_data_plane_consistency_fails_when_minute_age_is_stale(tmp_path) -> None:
    data_root = tmp_path / "data"
    (data_root / "bot1" / "logs" / "epp_v24" / "bot1_a").mkdir(parents=True, exist_ok=True)
    snap_path = tmp_path / "reports" / "desk_snapshot" / "bot1" / "latest.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(
        json.dumps(
            {
                "generated_ts": datetime.now(UTC).isoformat(),
                "completeness": 1.0,
                "minute_age_s": 181.0,
                "fill_age_s": 10.0,
            }
        ),
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=data_root)
    text = exporter.render_prometheus()

    assert "hbot_data_plane_consistency 0.0" in text


def test_derisk_stall_watchdog_metrics_exported_for_soft_pause_derisk(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    minute_file.parent.mkdir(parents=True, exist_ok=True)
    minute_file.write_text(
        "\n".join(
            [
                "ts,bot_variant,bot_mode,accounting_source,exchange,trading_pair,state,regime,equity_quote,fills_count_today,realized_pnl_today_quote,funding_cost_today_quote,position_base,risk_reasons",
                "2026-02-27T22:00:00+00:00,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,soft_pause,neutral_low_vol,500,4,12.5,1.5,0.020,base_pct_above_max|eod_close_pending",
                "2026-02-27T22:10:00+00:00,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,soft_pause,neutral_low_vol,500,4,12.5,1.5,0.020,base_pct_above_max|eod_close_pending",
                "2026-02-27T22:20:00+00:00,a,paper,paper_desk_v2,bitget_perpetual,BTC-USDT,soft_pause,neutral_low_vol,500,4,12.5,1.5,0.020,base_pct_above_max|eod_close_pending",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    stall_seconds_lines = [line for line in text.splitlines() if line.startswith("hbot_bot_derisk_stall_seconds{")]
    stall_active_lines = [line for line in text.splitlines() if line.startswith("hbot_bot_derisk_stall_active{")]
    assert stall_seconds_lines
    assert stall_active_lines
    assert any(line.endswith(" 1200.0") for line in stall_seconds_lines)
    assert any(line.endswith(" 1.0") for line in stall_active_lines)


def test_render_uses_cache_until_ttl_expires(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    class _CountingExporter(BotMetricsExporter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.render_calls = 0

        def _render_prometheus_impl(self) -> str:
            self.render_calls += 1
            return super()._render_prometheus_impl()

    exporter = _CountingExporter(data_root=tmp_path, cache_ttl_seconds=60)
    first = exporter.render_prometheus()
    second = exporter.render_prometheus()

    assert first
    assert second
    assert exporter.render_calls == 1
    assert "hbot_exporter_render_requests_total 2.0" in second
    assert "hbot_exporter_render_cache_hits_total 1.0" in second
    assert "hbot_exporter_render_cache_hit_ratio 0.500000" in second


def test_render_falls_back_to_stale_cache_after_refresh_failure(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)

    class _FlakyExporter(BotMetricsExporter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.render_calls = 0

        def _render_prometheus_impl(self) -> str:
            self.render_calls += 1
            if self.render_calls == 1:
                return super()._render_prometheus_impl()
            raise RuntimeError("forced exporter render failure")

    exporter = _FlakyExporter(data_root=tmp_path, cache_ttl_seconds=1)
    first = exporter.render_prometheus()
    exporter._last_render_monotonic -= 10.0
    second = exporter.render_prometheus()

    assert "hbot_bot_fills_total" in first
    assert "hbot_bot_fills_total" in second
    assert exporter.render_calls == 2
    assert "hbot_exporter_stale_cache_fallback_total 1.0" in second
    assert "hbot_exporter_render_failures_total 1.0" in second


def test_source_read_failures_are_exported(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    _write_minute_csv(minute_file, include_net=True)
    minute_file.parent.joinpath("paper_desk_v2.json").write_text("{invalid", encoding="utf-8")

    exporter = BotMetricsExporter(data_root=tmp_path)
    text = exporter.render_prometheus()

    assert 'hbot_exporter_source_read_failures_total{source="portfolio"} 1.0' in text


def test_fill_stats_and_minute_history_use_file_cache(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    fills_file = minute_file.parent / "fills.csv"
    _write_minute_csv(minute_file, include_net=True)
    fills_file.write_text(
        "\n".join(
            [
                "ts,side,notional_quote,fee_quote,price,amount_base,realized_pnl_quote,is_maker,mid_ref,expected_spread_pct,adverse_drift_30s",
                "2026-02-27T22:00:00+00:00,buy,100,0.1,100,1,1.0,true,100,0.001,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exporter = BotMetricsExporter(data_root=tmp_path)
    fill_stats_first = exporter._cached_fill_stats(fills_file)
    fill_stats_second = exporter._cached_fill_stats(fills_file)
    history_first = exporter._cached_minute_history(minute_file)
    history_second = exporter._cached_minute_history(minute_file)

    assert fill_stats_first is fill_stats_second
    assert history_first is history_second


def test_default_fills_summary_is_reused_across_snapshot_reads(tmp_path) -> None:
    minute_file = tmp_path / "bot1" / "logs" / "epp_v24" / "bot1_a" / "minute.csv"
    fills_file = minute_file.parent / "fills.csv"
    _write_minute_csv(minute_file, include_net=True)
    fills_file.write_text(
        "\n".join(
            [
                "ts,side,notional_quote,fee_quote,price,amount_base,realized_pnl_quote,is_maker,mid_ref,expected_spread_pct,adverse_drift_30s,order_id,state",
                "2026-02-27T22:00:00+00:00,buy,100,0.1,100,1,1.0,true,100,0.001,0.0,o1,running",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _CountingExporter(BotMetricsExporter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fills_scan_calls = 0
            self.minute_scan_calls = 0

        def _scan_fills_file(self, fills_path, recent_limit: int = 50):
            self.fills_scan_calls += 1
            return super()._scan_fills_file(fills_path, recent_limit=recent_limit)

        def _scan_minute_file(self, minute_path):
            self.minute_scan_calls += 1
            return super()._scan_minute_file(minute_path)

    exporter = _CountingExporter(data_root=tmp_path)
    snapshot = exporter.collect()[0]

    assert snapshot.fills_total == 1.0
    assert snapshot.minute_rows_total == 1.0
    assert exporter.fills_scan_calls == 1
    assert exporter.minute_scan_calls == 1
