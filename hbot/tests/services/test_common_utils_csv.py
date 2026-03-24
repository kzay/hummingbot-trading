from __future__ import annotations

from platform_lib.core.utils import read_last_csv_row


def test_read_last_csv_row_handles_quoted_commas_in_large_csv_tail(tmp_path) -> None:
    path = tmp_path / "minute.csv"
    path.write_text("ts,pnl_governor_activation_reason_counts,risk_reasons\n", encoding="utf-8")

    with path.open("a", encoding="utf-8", newline="") as f:
        for i in range(420):
            counts_json = f'"{{""active"": {i}, ""within_activation_buffer"": {i + 1}}}"'
            f.write(f"2026-03-05T00:{i % 60:02d}:00+00:00,{counts_json},base_pct_above_max|derisk_only\n")

    row = read_last_csv_row(path)
    assert row is not None
    assert row["ts"] == "2026-03-05T00:59:00+00:00"
    assert row["risk_reasons"] == "base_pct_above_max|derisk_only"
    assert row["pnl_governor_activation_reason_counts"] == '{"active": 419, "within_activation_buffer": 420}'
