from __future__ import annotations

from pathlib import Path

from scripts.ops.data_plane_rollback_drill import run_drill


def test_run_drill_dry_run_does_not_modify_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPS_DB_READ_PREFERRED=true\n", encoding="utf-8")
    report_dir = tmp_path / "reports" / "ops"

    payload = run_drill(
        env_file=env_file,
        report_dir=report_dir,
        from_mode="db_primary",
        to_mode="csv_compat",
        apply=False,
        max_rto_sec=300.0,
        rpo_lost_commands=0.0,
    )

    assert payload["status"] == "pass"
    assert payload["flags_after"]["OPS_DATA_PLANE_MODE"] == "csv_compat"
    assert payload["flags_after"]["OPS_DB_READ_PREFERRED"] == "false"
    assert payload["rpo_lost_commands"] == 0.0
    assert env_file.read_text(encoding="utf-8") == "OPS_DB_READ_PREFERRED=true\n"


def test_run_drill_apply_updates_env_and_creates_backup(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPS_DB_READ_PREFERRED=true\n", encoding="utf-8")
    report_dir = tmp_path / "reports" / "ops"

    payload = run_drill(
        env_file=env_file,
        report_dir=report_dir,
        from_mode="db_primary",
        to_mode="csv_compat",
        apply=True,
        max_rto_sec=300.0,
        rpo_lost_commands=0.0,
    )

    assert payload["status"] == "pass"
    assert payload["rpo_lost_commands"] == 0.0
    assert payload["env_backup"]
    assert Path(str(payload["env_backup"])).exists()
    text = env_file.read_text(encoding="utf-8")
    assert "OPS_DATA_PLANE_MODE=csv_compat" in text
    assert "PROMOTION_CHECK_CANONICAL_PLANE_GATES=false" in text
