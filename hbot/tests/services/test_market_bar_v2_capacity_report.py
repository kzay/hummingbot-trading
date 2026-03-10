from __future__ import annotations

from scripts.ops.report_market_bar_v2_capacity import _summarize_capacity


def test_summarize_capacity_passes_for_healthy_usage() -> None:
    summary = _summarize_capacity(
        [
            {
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "bar_source": "quote_mid",
                "bar_interval_s": 60,
                "row_count": 50_000,
                "oldest_bucket_utc": "2026-01-01T00:00:00+00:00",
                "newest_bucket_utc": "2026-02-04T00:00:00+00:00",
                "span_days": 34.0,
            }
        ],
        retention_max_bars=100_000,
        max_distinct_keys=50,
        storage_budget_mb=512.0,
        total_table_bytes=10 * 1024 * 1024,
        total_index_bytes=5 * 1024 * 1024,
    )

    assert summary["status"] == "pass"
    assert summary["distinct_keys"] == 1
    assert summary["projected_capacity_rows"] == 100_000
    assert summary["total_storage_mb"] == 15.0
    assert summary["bytes_per_row"] == round((15 * 1024 * 1024) / 50_000, 3)


def test_summarize_capacity_warns_when_near_cap() -> None:
    summary = _summarize_capacity(
        [
            {
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "bar_source": "quote_mid",
                "bar_interval_s": 60,
                "row_count": 85_000,
                "oldest_bucket_utc": "2026-01-01T00:00:00+00:00",
                "newest_bucket_utc": "2026-02-20T00:00:00+00:00",
                "span_days": 50.0,
            }
        ],
        retention_max_bars=100_000,
        max_distinct_keys=50,
        storage_budget_mb=512.0,
        total_table_bytes=20 * 1024 * 1024,
        total_index_bytes=10 * 1024 * 1024,
    )

    assert summary["status"] == "warn"
    assert summary["reason"] == "retention_near_cap"
    assert len(summary["near_cap_keys"]) == 1


def test_summarize_capacity_fails_when_key_count_or_cap_exceeded() -> None:
    rows = []
    for idx in range(3):
        rows.append(
            {
                "connector_name": "bitget_perpetual",
                "trading_pair": f"PAIR-{idx}",
                "bar_source": "quote_mid",
                "bar_interval_s": 60,
                "row_count": 120_000 if idx == 0 else 10_000,
                "oldest_bucket_utc": "2026-01-01T00:00:00+00:00",
                "newest_bucket_utc": "2026-02-20T00:00:00+00:00",
                "span_days": 50.0,
            }
        )

    summary = _summarize_capacity(
        rows,
        retention_max_bars=100_000,
        max_distinct_keys=2,
        storage_budget_mb=512.0,
        total_table_bytes=30 * 1024 * 1024,
        total_index_bytes=15 * 1024 * 1024,
    )

    assert summary["status"] == "fail"
    assert "distinct_keys_above_budget" in summary["reason"]
    assert "retention_cap_exceeded" in summary["reason"]


def test_summarize_capacity_uses_heap_plus_index_bytes_once() -> None:
    summary = _summarize_capacity(
        [
            {
                "connector_name": "bitget_perpetual",
                "trading_pair": "BTC-USDT",
                "bar_source": "quote_mid",
                "bar_interval_s": 60,
                "row_count": 10,
                "oldest_bucket_utc": "2026-01-01T00:00:00+00:00",
                "newest_bucket_utc": "2026-01-01T00:10:00+00:00",
                "span_days": 1.0,
            }
        ],
        retention_max_bars=100_000,
        max_distinct_keys=50,
        storage_budget_mb=512.0,
        total_table_bytes=100,
        total_index_bytes=50,
    )

    assert summary["total_storage_mb"] == round(150 / (1024 * 1024), 3)
    assert summary["bytes_per_row"] == 15.0
