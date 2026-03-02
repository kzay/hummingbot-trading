#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.bot_metrics_exporter import BotMetricsExporter


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _parse_ts(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _file_age_s(path: Path, now_ts: float) -> float:
    if not path.exists():
        return 1e9
    return max(0.0, now_ts - path.stat().st_mtime)


def _iter_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _required_fill_columns() -> List[str]:
    return [
        "ts",
        "exchange",
        "trading_pair",
        "side",
        "price",
        "amount_base",
        "notional_quote",
        "fee_quote",
        "order_id",
        "is_maker",
    ]


def _analyze_fill_file(path: Path, now_ts: float) -> Dict[str, object]:
    rows = list(_iter_csv_rows(path))
    required = _required_fill_columns()
    cols = list(rows[0].keys()) if rows else []
    missing_cols = [c for c in required if c not in cols]

    valid_rows = 0
    last_ts: Optional[datetime] = None
    for row in rows:
        ts = _parse_ts(row.get("ts", ""))
        side = str(row.get("side", "")).strip().lower()
        pair = str(row.get("trading_pair", "")).strip()
        price = _safe_float(row.get("price"), 0.0)
        amount_base = _safe_float(row.get("amount_base"), 0.0)
        notional_quote = _safe_float(row.get("notional_quote"), 0.0)
        fee_quote = _safe_float(row.get("fee_quote"), -1.0)
        if ts is None:
            continue
        if side not in {"buy", "sell"}:
            continue
        if not pair or price <= 0 or amount_base <= 0 or notional_quote <= 0 or fee_quote < 0:
            continue
        valid_rows += 1
        if last_ts is None or ts > last_ts:
            last_ts = ts

    last_ts_utc = last_ts.isoformat() if last_ts is not None else ""
    age_s = max(0.0, now_ts - last_ts.timestamp()) if last_ts is not None else 1e9
    return {
        "path": str(path),
        "rows_total": len(rows),
        "rows_valid_tradenote": valid_rows,
        "missing_required_columns": missing_cols,
        "last_fill_ts_utc": last_ts_utc,
        "last_fill_age_s": age_s,
    }


def _discover_fill_files(data_root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for path in sorted(data_root.glob("*/logs/epp_v24/*/fills.csv")):
        try:
            bot = path.parents[3].name.lower()
            folder = path.parent.name.lower()
            variant = folder.split("_", 1)[1] if "_" in folder else "a"
            out[f"{bot}:{variant}"] = path
        except Exception:
            continue
    return out


def _discover_minute_files(data_root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for path in sorted(data_root.glob("*/logs/epp_v24/*/minute.csv")):
        try:
            bot = path.parents[3].name.lower()
            folder = path.parent.name.lower()
            variant = folder.split("_", 1)[1] if "_" in folder else "a"
            out[f"{bot}:{variant}"] = path
        except Exception:
            continue
    return out


def _minute_freshness(path: Path, now_ts: float) -> Dict[str, object]:
    rows = list(_iter_csv_rows(path))
    if not rows:
        return {
            "path": str(path),
            "rows_total": 0,
            "last_minute_ts_utc": "",
            "last_minute_age_s": 1e9,
        }
    last_ts = _parse_ts(rows[-1].get("ts", ""))
    if last_ts is None:
        return {
            "path": str(path),
            "rows_total": len(rows),
            "last_minute_ts_utc": "",
            "last_minute_age_s": 1e9,
        }
    return {
        "path": str(path),
        "rows_total": len(rows),
        "last_minute_ts_utc": last_ts.isoformat(),
        "last_minute_age_s": max(0.0, now_ts - last_ts.timestamp()),
    }


def _event_store_integrity_latest(root: Path) -> Optional[Path]:
    candidates = sorted((root / "reports" / "event_store").glob("integrity_*.json"))
    return candidates[-1] if candidates else None


def _contains_metrics(rendered: str, names: Iterable[str]) -> Dict[str, bool]:
    lines = rendered.splitlines()
    out: Dict[str, bool] = {}
    for name in names:
        out[name] = any(line.startswith(name + "{") or line.startswith(name + " ") for line in lines)
    return out


def _parse_csv_list(raw: str) -> List[str]:
    return [item.strip().lower() for item in str(raw).split(",") if item.strip()]


def build_report(
    root: Path,
    *,
    max_data_age_s: int,
    tradenote_report_max_age_s: int,
    tradenote_fill_max_age_s: int,
    required_grafana_bot_variants: Optional[List[str]] = None,
    required_tradenote_bot_variants: Optional[List[str]] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, object]:
    now_ts = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    data_root = root / "data"
    reports_root = root / "reports"

    checks: Dict[str, bool] = {}
    details: Dict[str, object] = {}

    # ---- TradeNote readiness -------------------------------------------------
    discovered_fills = _discover_fill_files(data_root)
    required_tradenote_sources = [s for s in (required_tradenote_bot_variants or []) if s]
    fill_analysis = {key: _analyze_fill_file(path, now_ts) for key, path in discovered_fills.items()}
    targeted_fill_sources = required_tradenote_sources or sorted(fill_analysis.keys())
    targeted_fill_analysis = {k: fill_analysis[k] for k in targeted_fill_sources if k in fill_analysis}
    missing_fill_sources = [k for k in targeted_fill_sources if k not in fill_analysis]
    checks["tradenote_sources_discovered"] = len(discovered_fills) > 0
    checks["tradenote_required_sources_present"] = len(missing_fill_sources) == 0
    checks["tradenote_fill_schema_ok"] = all(
        len(list(info.get("missing_required_columns", []))) == 0
        for info in targeted_fill_analysis.values()
    )
    checks["tradenote_fill_rows_present"] = all(
        int(info.get("rows_valid_tradenote", 0)) > 0 for info in targeted_fill_analysis.values()
    ) if targeted_fill_analysis else False
    checks["tradenote_fill_fresh"] = all(
        float(info.get("last_fill_age_s", 1e9)) <= float(tradenote_fill_max_age_s)
        for info in targeted_fill_analysis.values()
    ) if targeted_fill_analysis else False

    tradenote_sync_path = reports_root / "tradenote" / "sync_latest.json"
    tradenote_sync = _read_json(tradenote_sync_path)
    tradenote_sync_status = str(tradenote_sync.get("status", "missing")).lower()
    checks["tradenote_sync_report_present"] = tradenote_sync_path.exists()
    checks["tradenote_sync_ok"] = tradenote_sync_status == "ok"
    checks["tradenote_sync_fresh"] = _file_age_s(tradenote_sync_path, now_ts) <= float(tradenote_report_max_age_s)

    details["tradenote"] = {
        "required_sources": targeted_fill_sources,
        "missing_required_sources": missing_fill_sources,
        "fills_sources": sorted(discovered_fills.keys()),
        "fills_analysis": fill_analysis,
        "sync_report_path": str(tradenote_sync_path),
        "sync_report_age_s": _file_age_s(tradenote_sync_path, now_ts),
        "sync_report_status": tradenote_sync_status,
        "sync_report_error": str(tradenote_sync.get("error", "")),
    }

    # ---- Grafana data readiness ---------------------------------------------
    discovered_minutes = _discover_minute_files(data_root)
    minute_analysis = {key: _minute_freshness(path, now_ts) for key, path in discovered_minutes.items()}
    required_grafana_sources = [s for s in (required_grafana_bot_variants or []) if s]
    targeted_minute_sources = required_grafana_sources or sorted(minute_analysis.keys())
    targeted_minute_analysis = {k: minute_analysis[k] for k in targeted_minute_sources if k in minute_analysis}
    missing_minute_sources = [k for k in targeted_minute_sources if k not in minute_analysis]
    checks["grafana_minute_sources_discovered"] = len(discovered_minutes) > 0
    checks["grafana_required_sources_present"] = len(missing_minute_sources) == 0
    checks["grafana_minute_rows_present"] = all(
        int(info.get("rows_total", 0)) > 0 for info in targeted_minute_analysis.values()
    ) if targeted_minute_analysis else False
    checks["grafana_minute_fresh"] = all(
        float(info.get("last_minute_age_s", 1e9)) <= float(max_data_age_s)
        for info in targeted_minute_analysis.values()
    ) if targeted_minute_analysis else False

    ops_db_writer_path = reports_root / "ops_db_writer" / "latest.json"
    ops_db_writer = _read_json(ops_db_writer_path)
    checks["ops_db_writer_report_present"] = ops_db_writer_path.exists()
    checks["ops_db_writer_status_ok"] = str(ops_db_writer.get("status", "")).lower() == "pass"

    event_integrity_path = _event_store_integrity_latest(root)
    event_integrity = _read_json(event_integrity_path) if event_integrity_path is not None else {}
    checks["event_store_integrity_present"] = event_integrity_path is not None
    checks["event_store_integrity_fresh"] = (
        _file_age_s(event_integrity_path, now_ts) <= float(max_data_age_s)
        if event_integrity_path is not None
        else False
    )
    checks["event_store_events_present"] = int(event_integrity.get("total_events", 0)) > 0

    # Verify Prometheus payload shape from exporter.
    exporter_error = ""
    metric_presence: Dict[str, bool] = {}
    try:
        exporter = BotMetricsExporter(data_root=data_root)
        snapshots = exporter.collect()
        rendered = exporter.render_prometheus()
        core_metric_presence = _contains_metrics(
            rendered,
            [
                "hbot_bot_open_pnl_quote",
                "hbot_bot_closed_pnl_quote_total",
                "hbot_bot_trades_total",
                "hbot_bot_trade_winrate",
                "hbot_bot_realized_pnl_week_quote",
                "hbot_bot_realized_pnl_month_quote",
                "hbot_bot_equity_start_quote",
            ],
        )
        open_trade_metric_presence = _contains_metrics(
            rendered,
            [
                "hbot_bot_position_quantity_base",
                "hbot_bot_position_unrealized_pnl_quote",
            ],
        )
        metric_presence = {
            **{f"core:{k}": v for k, v in core_metric_presence.items()},
            **{f"open_trade:{k}": v for k, v in open_trade_metric_presence.items()},
        }
        open_positions_present = False
        for snap in snapshots:
            portfolio = getattr(snap, "portfolio", None)
            positions = getattr(portfolio, "positions", []) if portfolio is not None else []
            if positions:
                open_positions_present = True
                break
        checks["grafana_exporter_snapshots_present"] = len(snapshots) > 0
        checks["grafana_exporter_core_metrics_present"] = all(core_metric_presence.values())
        checks["grafana_exporter_open_trade_metrics_present"] = (
            all(open_trade_metric_presence.values()) if open_positions_present else True
        )
    except Exception as exc:
        exporter_error = f"{type(exc).__name__}: {exc}"
        checks["grafana_exporter_snapshots_present"] = False
        checks["grafana_exporter_core_metrics_present"] = False
        checks["grafana_exporter_open_trade_metrics_present"] = False

    details["grafana"] = {
        "required_sources": targeted_minute_sources,
        "missing_required_sources": missing_minute_sources,
        "minute_sources": sorted(discovered_minutes.keys()),
        "minute_analysis": minute_analysis,
        "ops_db_writer_report_path": str(ops_db_writer_path),
        "ops_db_writer_age_s": _file_age_s(ops_db_writer_path, now_ts),
        "ops_db_writer_status": str(ops_db_writer.get("status", "")),
        "event_store_integrity_path": str(event_integrity_path) if event_integrity_path is not None else "",
        "event_store_integrity_total_events": int(event_integrity.get("total_events", 0)),
        "event_store_integrity_age_s": _file_age_s(event_integrity_path, now_ts) if event_integrity_path else 1e9,
        "metric_presence": metric_presence,
        "exporter_error": exporter_error,
    }

    tradenote_checks = [k for k in checks if k.startswith("tradenote_")]
    grafana_checks = [k for k in checks if not k.startswith("tradenote_")]
    tradenote_ready = all(checks[k] for k in tradenote_checks)
    grafana_ready = all(checks[k] for k in grafana_checks)

    failed_checks = sorted([name for name, ok in checks.items() if not ok])
    return {
        "ts_utc": _utc_now(),
        "status": "pass" if tradenote_ready and grafana_ready else "fail",
        "tradenote_ready": tradenote_ready,
        "grafana_ready": grafana_ready,
        "failed_checks": failed_checks,
        "checks": checks,
        "details": details,
    }


def _write_report(report: Dict[str, object], out_latest: Path) -> Tuple[Path, Path]:
    out_latest.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_stamped = out_latest.parent / f"dashboard_data_ready_{stamp}.json"
    out_stamped.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_stamped, out_latest


def _list_panels(root: Path, dashboard_rel_path: str) -> int:
    path = root / dashboard_rel_path
    payload = _read_json(path)
    if not payload:
        print(f"[verify-dashboard] failed to read dashboard json: {path}")
        return 2
    panels = payload.get("panels", [])
    if not isinstance(panels, list):
        print(f"[verify-dashboard] invalid panel payload: {path}")
        return 2
    new_panels = [
        (p.get("id", 0), str(p.get("title", "")), int((p.get("gridPos") or {}).get("y", 0)))
        for p in panels
        if int(p.get("id", 0)) >= 200
    ]
    print("New FreqText panels:")
    for pid, title, y in new_panels:
        print(f"  id={pid:3d}  y={y:3d}  {title}")
    print()
    print(
        f"uid={payload.get('uid', '')}  version={payload.get('version', '')}  total_panels={len(panels)}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify dashboard data readiness for TradeNote and Grafana.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when readiness fails.")
    parser.add_argument("--max-data-age-s", type=int, default=int(os.getenv("DASHBOARD_DATA_MAX_AGE_S", "180")))
    parser.add_argument(
        "--tradenote-report-max-age-s",
        type=int,
        default=int(os.getenv("TRADENOTE_SYNC_HEALTH_MAX_SEC", "5400")),
    )
    parser.add_argument(
        "--tradenote-fill-max-age-s",
        type=int,
        default=int(os.getenv("TRADENOTE_FILL_MAX_AGE_S", str(7 * 24 * 3600))),
    )
    parser.add_argument(
        "--required-grafana-bot-variants",
        default=os.getenv("DASHBOARD_REQUIRED_BOT_VARIANTS", "bot1:a,bot3:a,bot4:a"),
        help="Comma-separated bot:variant keys that must be Grafana-ready.",
    )
    parser.add_argument(
        "--required-tradenote-bot-variants",
        default=os.getenv("TRADENOTE_SYNC_BOT_VARIANTS", ""),
        help="Comma-separated bot:variant keys that must be TradeNote-ready (empty = all discovered fills sources).",
    )
    parser.add_argument(
        "--out",
        default="reports/ops/dashboard_data_ready_latest.json",
        help="Output report path relative to repo root.",
    )
    parser.add_argument(
        "--list-panels",
        action="store_true",
        help="List FreqText panel IDs/titles (legacy helper mode).",
    )
    parser.add_argument(
        "--dashboard-path",
        default="monitoring/grafana/dashboards/ftui_bot_monitor.json",
        help="Dashboard file relative to repo root for --list-panels mode.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    if args.list_panels:
        return _list_panels(root=root, dashboard_rel_path=str(args.dashboard_path))

    report = build_report(
        root=root,
        max_data_age_s=int(args.max_data_age_s),
        tradenote_report_max_age_s=int(args.tradenote_report_max_age_s),
        tradenote_fill_max_age_s=int(args.tradenote_fill_max_age_s),
        required_grafana_bot_variants=_parse_csv_list(args.required_grafana_bot_variants),
        required_tradenote_bot_variants=_parse_csv_list(args.required_tradenote_bot_variants),
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_stamped, out_latest = _write_report(report, out_latest=out_path)

    print(
        f"[verify-dashboard] status={report.get('status')} "
        f"tradenote_ready={report.get('tradenote_ready')} "
        f"grafana_ready={report.get('grafana_ready')}"
    )
    print(f"[verify-dashboard] failed_checks={report.get('failed_checks', [])}")
    print(f"[verify-dashboard] evidence={out_stamped}")
    print(f"[verify-dashboard] latest={out_latest}")

    if args.strict and str(report.get("status", "fail")).lower() != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
