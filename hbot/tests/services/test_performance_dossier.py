from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.analysis.performance_dossier import build_dossier


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_build_dossier_includes_checks_and_daily_rollups(tmp_path: Path) -> None:
    root = tmp_path / "hbot"
    bot = root / "data" / "bot1" / "logs" / "epp_v24" / "bot1_a"
    _write_csv(
        bot / "fills.csv",
        ["ts", "side", "price", "mid_ref", "notional_quote", "fee_quote", "realized_pnl_quote", "is_maker"],
        [
            {
                "ts": "2026-02-27T12:00:00+00:00",
                "side": "buy",
                "price": "100.1",
                "mid_ref": "100.0",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "realized_pnl_quote": "0.05",
                "is_maker": "true",
            },
            {
                "ts": "2026-02-27T12:01:00+00:00",
                "side": "sell",
                "price": "100.2",
                "mid_ref": "100.1",
                "notional_quote": "10",
                "fee_quote": "0.01",
                "realized_pnl_quote": "0.04",
                "is_maker": "false",
            },
        ],
    )
    _write_csv(
        bot / "minute.csv",
        ["ts", "drawdown_pct", "soft_pause_edge", "order_book_stale"],
        [
            {"ts": "2026-02-27T12:00:00+00:00", "drawdown_pct": "0.001", "soft_pause_edge": "False", "order_book_stale": "False"},
            {"ts": "2026-02-27T12:01:00+00:00", "drawdown_pct": "0.002", "soft_pause_edge": "True", "order_book_stale": "False"},
        ],
    )
    (root / "reports" / "reconciliation").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "portfolio_risk").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "promotion_gates").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "reconciliation" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "portfolio_risk" / "latest.json").write_text(
        json.dumps({"status": "ok", "critical_count": 0, "warning_count": 0}),
        encoding="utf-8",
    )
    (root / "reports" / "promotion_gates" / "strict_cycle_latest.json").write_text(
        json.dumps({"strict_gate_status": "PASS", "strict_gate_rc": 0}),
        encoding="utf-8",
    )

    out = build_dossier(root=root, bot_log_root=bot, lookback_days=3)

    assert out["status"] in {"pass", "warning"}
    assert out["summary"]["days_included"] == 1
    assert len(out["daily_breakdown"]) == 1
    assert len(out["checks"]) >= 5
