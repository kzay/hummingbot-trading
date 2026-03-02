from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ops import tradenote_sync


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_to_tradenote_execution_maps_template_fields() -> None:
    row = {
        "ts": "2026-02-27T12:34:56+00:00",
        "exchange": "bitget_paper_trade",
        "trading_pair": "BTC-USDT",
        "side": "buy",
        "price": "100.5",
        "amount_base": "0.1",
        "notional_quote": "10.05",
        "fee_quote": "0.01",
        "order_id": "paper-B-123",
        "is_maker": "false",
    }
    day_key, payload = tradenote_sync._to_tradenote_execution(
        row=row,
        account="hbot_bot1_a",
        security_type="0",
        settlement_days=0,
    )

    assert day_key == "2026-02-27"
    assert payload is not None
    assert payload["Account"] == "hbot_bot1_a"
    assert payload["Side"] == "B"
    assert payload["Currency"] == "USDT"
    assert payload["Type"] == "0"
    assert payload["Gross Proceeds"] == -10.05
    assert payload["Net Proceeds"] == -10.06
    assert payload["Exec Time"] == "12:34:56"
    assert payload["Liq"] == "T"


def test_collect_daily_payloads_groups_multi_bot_same_day(tmp_path: Path) -> None:
    today = datetime.now(timezone.utc).date()
    day_y = (today - timedelta(days=1)).isoformat()
    day_t = today.isoformat()

    headers = [
        "ts",
        "bot_variant",
        "exchange",
        "trading_pair",
        "side",
        "price",
        "amount_base",
        "notional_quote",
        "fee_quote",
        "order_id",
        "state",
        "mid_ref",
        "expected_spread_pct",
        "adverse_drift_30s",
        "fee_source",
        "is_maker",
        "realized_pnl_quote",
    ]
    base = tmp_path / "data"
    _write_csv(
        base / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv",
        headers,
        [
            {
                "ts": f"{day_y}T10:00:00+00:00",
                "exchange": "bitget_paper_trade",
                "trading_pair": "BTC-USDT",
                "side": "buy",
                "price": "100",
                "amount_base": "0.1",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "order_id": "b1-yday",
                "is_maker": "true",
            },
            {
                "ts": f"{day_t}T10:00:00+00:00",
                "exchange": "bitget_paper_trade",
                "trading_pair": "BTC-USDT",
                "side": "buy",
                "price": "101",
                "amount_base": "0.1",
                "notional_quote": "10.1",
                "fee_quote": "0.01",
                "order_id": "b1-today",
                "is_maker": "false",
            },
        ],
    )
    _write_csv(
        base / "bot3" / "logs" / "epp_v24" / "bot3_a" / "fills.csv",
        headers,
        [
            {
                "ts": f"{day_y}T12:00:00+00:00",
                "exchange": "bitget_paper_trade",
                "trading_pair": "ETH-USDT",
                "side": "sell",
                "price": "2500",
                "amount_base": "0.01",
                "notional_quote": "25",
                "fee_quote": "0.02",
                "order_id": "b3-yday",
                "is_maker": "false",
            }
        ],
    )

    discovered = tradenote_sync._discover_fill_files(base)
    rows_by_day, rows_by_source, skipped = tradenote_sync._collect_daily_payloads(
        fill_files=discovered,
        imported_days=set(),
        include_today=False,
        lookback_days=7,
        account_prefix="hbot",
        security_type="0",
        settlement_days=0,
    )

    assert day_y in rows_by_day
    assert day_t not in rows_by_day
    assert len(rows_by_day[day_y]) == 2
    assert rows_by_source["bot1:a"] == 1
    assert rows_by_source["bot3:a"] == 1
    accounts = {str(r["Account"]) for r in rows_by_day[day_y]}
    assert accounts == {"hbot_bot1_a", "hbot_bot3_a"}
    assert skipped == []


def test_collect_daily_payloads_skips_imported_days(tmp_path: Path) -> None:
    day_y = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    headers = ["ts", "exchange", "trading_pair", "side", "price", "amount_base", "notional_quote", "fee_quote", "order_id", "is_maker"]
    base = tmp_path / "data"
    _write_csv(
        base / "bot1" / "logs" / "epp_v24" / "bot1_a" / "fills.csv",
        headers,
        [
            {
                "ts": f"{day_y}T10:00:00+00:00",
                "exchange": "bitget_paper_trade",
                "trading_pair": "BTC-USDT",
                "side": "buy",
                "price": "100",
                "amount_base": "0.1",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "order_id": "b1-yday",
                "is_maker": "true",
            }
        ],
    )
    discovered = tradenote_sync._discover_fill_files(base)
    rows_by_day, _, skipped = tradenote_sync._collect_daily_payloads(
        fill_files=discovered,
        imported_days={day_y},
        include_today=False,
        lookback_days=7,
        account_prefix="hbot",
        security_type="0",
        settlement_days=0,
    )

    assert rows_by_day == {}
    assert skipped == [day_y]


def test_chunk_rows_splits_large_batches() -> None:
    rows = [{"i": i} for i in range(1201)]
    chunks = tradenote_sync._chunk_rows(rows, max_rows_per_post=500)
    sizes = [len(c) for c in chunks]
    assert sizes == [500, 500, 201]
