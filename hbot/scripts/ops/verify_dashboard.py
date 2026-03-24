from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _age_seconds(path: Path) -> float:
    try:
        return max(0.0, datetime.now(UTC).timestamp() - path.stat().st_mtime)
    except Exception:
        return float("inf")


def _parse_required_sources(raw: str) -> list[str]:
    items = [chunk.strip() for chunk in str(raw or "").split(",")]
    return [item for item in items if item]


def _source_key(bot_dir: str, variant_dir: str) -> str:
    variant = variant_dir.split("_")[-1] if "_" in variant_dir else variant_dir
    return f"{bot_dir}:{variant}"


def _discover_sources(paths: list[Path]) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for path in paths:
        try:
            bot_dir = path.parents[3].name  # .../data/<bot>/logs/epp_v24/<bot_variant>/minute.csv
            variant_dir = path.parent.name
            key = _source_key(bot_dir, variant_dir)
            existing = discovered.get(key)
            if existing is None or path.stat().st_mtime > existing.stat().st_mtime:
                discovered[key] = path
        except Exception:
            continue
    return discovered


def _csv_has_data_rows(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
            reader = csv.reader(fp)
            next(reader, None)  # header
            return next(reader, None) is not None
    except Exception:
        return False


def _latest_integrity_path(reports_root: Path) -> Path | None:
    candidates = sorted((reports_root / "event_store").glob("integrity_*.json"))
    return candidates[-1] if candidates else None


def _latest_events_jsonl_path(reports_root: Path) -> Path | None:
    candidates = sorted((reports_root / "event_store").glob("events_*.jsonl"))
    return candidates[-1] if candidates else None


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _source_check(
    discovered: dict[str, Path],
    required_sources: list[str],
    max_age_s: int,
) -> tuple[bool, bool, bool, list[str], dict[str, dict[str, object]]]:
    missing_required = [source for source in required_sources if source not in discovered]
    target_sources = required_sources if required_sources else sorted(discovered.keys())
    if not target_sources:
        return False, False, False, missing_required, {}

    rows_ok = True
    fresh_ok = True
    details: dict[str, dict[str, object]] = {}
    for source in target_sources:
        path = discovered.get(source)
        if path is None:
            rows_ok = False
            fresh_ok = False
            continue
        has_rows = _csv_has_data_rows(path)
        age_s = _age_seconds(path)
        rows_ok = rows_ok and has_rows
        fresh_ok = fresh_ok and age_s <= float(max_age_s)
        details[source] = {
            "path": str(path),
            "has_rows": has_rows,
            "age_s": age_s,
        }
    required_present = len(missing_required) == 0
    return True, required_present, rows_ok and required_present, missing_required, details


def run(
    root: Path,
    *,
    strict: bool,
    max_data_age_s: int,
    required_grafana_bot_variants: str,
) -> dict[str, object]:
    data_root = root / "data"
    reports_root = root / "reports"

    required_grafana = _parse_required_sources(required_grafana_bot_variants)

    minute_sources = _discover_sources(sorted(data_root.glob("*/logs/epp_v24/*/minute.csv")))

    (
        grafana_discovered,
        grafana_required_present,
        grafana_rows_ok,
        grafana_missing_required,
        grafana_details,
    ) = _source_check(minute_sources, required_grafana, max_data_age_s)

    grafana_fresh_ok = True
    for source in (required_grafana if required_grafana else sorted(minute_sources.keys())):
        path = minute_sources.get(source)
        if path is None:
            grafana_fresh_ok = False
            continue
        grafana_fresh_ok = grafana_fresh_ok and (_age_seconds(path) <= float(max_data_age_s))

    ops_db_writer_path = reports_root / "ops_db_writer" / "latest.json"
    ops_db_writer = _read_json(ops_db_writer_path)
    ops_db_writer_present = ops_db_writer_path.exists()
    ops_db_writer_ok = str(ops_db_writer.get("status", "fail")).strip().lower() == "pass"

    integrity_path = _latest_integrity_path(reports_root)
    integrity_present = integrity_path is not None and integrity_path.exists()
    integrity_fresh = bool(integrity_present and _age_seconds(integrity_path) <= float(max_data_age_s * 2))
    integrity_total_events = 0.0
    if integrity_present:
        integrity_payload = _read_json(integrity_path) if integrity_path is not None else {}
        try:
            integrity_total_events = float(integrity_payload.get("total_events", 0) or 0)
        except Exception:
            integrity_total_events = 0.0
    events_present = integrity_total_events > 0
    if not events_present:
        events_path = _latest_events_jsonl_path(reports_root)
        events_present = bool(events_path is not None and events_path.exists() and events_path.stat().st_size > 0)

    exchange_snapshots_path = reports_root / "exchange_snapshots" / "latest.json"
    exchange_snapshots_present = exchange_snapshots_path.exists()

    checks = {
        "grafana_minute_sources_discovered": bool(grafana_discovered),
        "grafana_required_sources_present": bool(grafana_required_present),
        "grafana_minute_rows_present": bool(grafana_rows_ok),
        "grafana_minute_fresh": bool(grafana_fresh_ok),
        "ops_db_writer_report_present": bool(ops_db_writer_present),
        "ops_db_writer_status_ok": bool(ops_db_writer_ok),
        "event_store_integrity_present": bool(integrity_present),
        "event_store_integrity_fresh": bool(integrity_fresh),
        "event_store_events_present": bool(events_present),
        "grafana_exporter_snapshots_present": bool(exchange_snapshots_present),
        "grafana_exporter_core_metrics_present": bool(exchange_snapshots_present),
        "grafana_exporter_open_trade_metrics_present": bool(exchange_snapshots_present),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]

    grafana_ready = all(
        checks[name]
        for name in (
            "grafana_minute_sources_discovered",
            "grafana_required_sources_present",
            "grafana_minute_rows_present",
            "grafana_minute_fresh",
            "ops_db_writer_report_present",
            "ops_db_writer_status_ok",
            "event_store_integrity_present",
            "event_store_integrity_fresh",
            "event_store_events_present",
            "grafana_exporter_snapshots_present",
            "grafana_exporter_core_metrics_present",
            "grafana_exporter_open_trade_metrics_present",
        )
    )
    status = "pass" if grafana_ready else "fail"

    payload = {
        "ts_utc": _utc_now_iso(),
        "status": status,
        "grafana_ready": grafana_ready,
        "failed_checks": failed_checks,
        "checks": checks,
        "details": {
            "grafana": {
                "required_sources": required_grafana,
                "missing_required_sources": grafana_missing_required,
                "minute_sources": sorted(minute_sources.keys()),
                "minute_analysis": grafana_details,
                "ops_db_writer_report_path": str(ops_db_writer_path),
                "ops_db_writer_age_s": _age_seconds(ops_db_writer_path) if ops_db_writer_present else float("inf"),
                "ops_db_writer_status": str(ops_db_writer.get("status", "")),
                "event_store_integrity_path": str(integrity_path) if integrity_path is not None else "",
                "event_store_integrity_total_events": integrity_total_events,
                "event_store_integrity_age_s": _age_seconds(integrity_path) if integrity_present else float("inf"),
                "exporter_error": "",
            },
        },
    }

    ops_reports = reports_root / "ops"
    ops_reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = ops_reports / f"dashboard_data_ready_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (ops_reports / "dashboard_data_ready_latest.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    print(f"[dashboard-ready] status={status}")
    print(f"[dashboard-ready] evidence={out_path}")
    if failed_checks:
        print(f"[dashboard-ready] failed_checks={','.join(failed_checks)}")

    if strict and status != "pass":
        return payload | {"exit_code": 2}
    return payload | {"exit_code": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate dashboard data readiness for Grafana.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when readiness status is fail.")
    parser.add_argument("--max-data-age-s", type=int, default=180)
    parser.add_argument(
        "--required-grafana-bot-variants",
        default=os.getenv("DASHBOARD_REQUIRED_BOT_VARIANTS", "bot1:a,bot3:a,bot4:a"),
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    payload = run(
        root,
        strict=bool(args.strict),
        max_data_age_s=max(30, int(args.max_data_age_s)),
        required_grafana_bot_variants=str(args.required_grafana_bot_variants),
    )
    return int(payload.get("exit_code", 2))


if __name__ == "__main__":
    raise SystemExit(main())
