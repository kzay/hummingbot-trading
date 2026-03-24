#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.ops.data_plane_rollback_drill import run_drill as run_data_plane_rollback_drill
from scripts.ops.ops_db_restore_drill import run_restore_drill
from scripts.ops.pg_backup import run_backup


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_report(report_dir: Path, stem: str, payload: dict[str, object]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ts_path = report_dir / f"{stem}_{stamp}.json"
    latest_path = report_dir / f"{stem}_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_path.write_text(raw, encoding="utf-8")
    latest_path.write_text(raw, encoding="utf-8")


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run ops DB backup/restore/rollback drills with evidence.")
    parser.add_argument("--backup-dir", default=os.getenv("OPS_DB_BACKUP_DIR", str(root / "backups" / "postgres")))
    parser.add_argument("--report-dir", default=os.getenv("OPS_DB_BACKUP_REPORT_DIR", str(root / "reports" / "ops")))
    parser.add_argument("--parity-latest-path", default=str(root / "reports" / "parity" / "latest.json"))
    parser.add_argument("--env-file", default=str(root / "env" / ".env.template"))
    parser.add_argument("--retention-count", type=int, default=int(os.getenv("OPS_DB_BACKUP_RETENTION_COUNT", "7")))
    parser.add_argument("--backup-timeout-sec", type=int, default=int(os.getenv("OPS_DB_BACKUP_TIMEOUT_SEC", "300")))
    parser.add_argument("--restore-timeout-sec", type=int, default=int(os.getenv("OPS_DB_RESTORE_DRILL_TIMEOUT_SEC", "600")))
    parser.add_argument("--rollback-max-rto-sec", type=float, default=300.0)
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--skip-restore", action="store_true")
    parser.add_argument("--skip-rollback-drill", action="store_true")
    parser.add_argument("--rollback-apply", action="store_true", help="Persist rollback mode changes to --env-file.")
    args = parser.parse_args()

    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
    user = os.getenv("OPS_DB_USER", "kzay_capital")
    password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")
    admin_db = os.getenv("OPS_DB_ADMIN_DB", "postgres")

    backup_payload: dict[str, object] = {"status": "skipped"}
    restore_payload: dict[str, object] = {"status": "skipped"}
    rollback_payload: dict[str, object] = {"status": "skipped"}

    backup_dir = Path(args.backup_dir)
    report_dir = Path(args.report_dir)
    parity_latest = Path(args.parity_latest_path)
    env_file = Path(args.env_file)

    if not args.skip_backup:
        backup_payload = run_backup(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            backup_dir=backup_dir,
            retention_count=int(args.retention_count),
            report_dir=report_dir,
            parity_latest_path=parity_latest,
            timeout_sec=int(args.backup_timeout_sec),
        )

    if not args.skip_restore:
        restore_payload = run_restore_drill(
            backup_dir=backup_dir,
            report_dir=report_dir,
            host=host,
            port=port,
            source_db=dbname,
            admin_db=admin_db,
            user=user,
            password=password,
            restore_db_prefix="kzay_capital_ops_restore_drill",
            timeout_sec=int(args.restore_timeout_sec),
            keep_restored_db=False,
            require_parity_sidecar=True,
        )

    if not args.skip_rollback_drill:
        rollback_payload = run_data_plane_rollback_drill(
            env_file=env_file,
            report_dir=report_dir,
            from_mode="db_primary",
            to_mode="csv_compat",
            apply=bool(args.rollback_apply),
            max_rto_sec=float(args.rollback_max_rto_sec),
        )

    restore_acceptance = str(restore_payload.get("status", "fail")) == "pass"
    rollback_duration_sec = float(rollback_payload.get("duration_sec", 1e9) or 1e9)
    rollback_acceptance = (
        str(rollback_payload.get("status", "fail")) == "pass" and rollback_duration_sec <= float(args.rollback_max_rto_sec)
    )
    overall_pass = restore_acceptance and rollback_acceptance

    summary = {
        "ts_utc": _utc_now(),
        "status": "pass" if overall_pass else "fail",
        "acceptance": {
            "restore_recovers_canonical_tables_and_parity_state": restore_acceptance,
            "rollback_performed_under_target_seconds": rollback_acceptance,
            "rollback_target_seconds": float(args.rollback_max_rto_sec),
        },
        "metrics": {
            "backup_freshness_hours": float(backup_payload.get("backup_freshness_hours", 1e9) or 1e9),
            "restore_duration_sec": float(restore_payload.get("duration_sec", 0.0) or 0.0),
            "rollback_duration_sec": rollback_duration_sec,
        },
        "steps": {
            "backup": backup_payload,
            "restore_drill": restore_payload,
            "rollback_drill": rollback_payload,
        },
    }
    _write_report(report_dir, "ops_db_drills", summary)
    print(f"[ops-db-drills] status={summary['status']}")
    print(f"[ops-db-drills] evidence={report_dir / 'ops_db_drills_latest.json'}")
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
