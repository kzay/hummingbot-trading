from pathlib import Path

from services.desk_snapshot_service import main as snapshot_service


def test_build_snapshot_clamps_future_minute_and_fill_ages(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    reports_root = tmp_path / "reports"
    log_dir = data_root / "bot1" / "logs" / "epp_v24" / "bot1_a"
    log_dir.mkdir(parents=True, exist_ok=True)
    (data_root / "bot1" / "logs" / "recovery").mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    (log_dir / "minute.csv").write_text(
        "\n".join(
            [
                "ts,state,regime,equity_quote,spread_pct,net_edge_pct,base_pct,daily_loss_pct,drawdown_pct,orders_active,realized_pnl_today_quote",
                "2026-03-06T21:00:05+00:00,running,up,1000,0.001,0.001,0,0,0,2,0.1",
            ]
        ),
        encoding="utf-8",
    )
    (log_dir / "fills.csv").write_text(
        "\n".join(
            [
                "ts,side,price,amount_base,fee_quote,realized_pnl_quote,is_maker",
                "2026-03-06T21:00:10+00:00,BUY,68000,0.001,0.01,0.02,True",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(snapshot_service, "_REPORTS_ROOT", reports_root)
    monkeypatch.setattr(snapshot_service, "_epoch_now", lambda: 1_772_830_800.0)  # 2026-03-06T21:00:00Z

    snapshot = snapshot_service.build_snapshot("bot1", data_root / "bot1")

    assert snapshot["minute_age_s"] == 0.0
    assert snapshot["fill_age_s"] == 0.0
