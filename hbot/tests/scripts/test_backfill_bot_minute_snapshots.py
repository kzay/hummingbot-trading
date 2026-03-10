from __future__ import annotations

import json
from pathlib import Path

from scripts.utils.backfill_bot_minute_snapshots_from_minute_csv import backfill


def test_backfill_minute_snapshots_appends_once_per_row(tmp_path: Path) -> None:
    root = tmp_path
    minute_dir = root / "data" / "bot5" / "logs" / "epp_v24" / "bot5_a"
    minute_dir.mkdir(parents=True, exist_ok=True)
    minute_dir.joinpath("minute.csv").write_text(
        "\n".join(
            [
                "ts,connector_name,trading_pair,state,equity_quote,base_pct,target_base_pct",
                "2026-03-09T12:00:00+00:00,bitget_perpetual,BTC-USDT,running,1000,0.1,0.0",
                "2026-03-09T12:01:00+00:00,bitget_perpetual,BTC-USDT,running,1001,0.1,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    total_rows, appended = backfill(root=root, bot="bot5", variant="a", day="20260309")

    assert total_rows == 2
    assert appended == 2

    out_path = root / "reports" / "event_store" / "events_20260309.jsonl"
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["event_type"] == "bot_minute_snapshot"
    assert payload["instance_name"] == "bot5"
    assert payload["payload"]["connector_name"] == "bitget_perpetual"

    total_rows_again, appended_again = backfill(root=root, bot="bot5", variant="a", day="20260309")
    assert total_rows_again == 2
    assert appended_again == 0
