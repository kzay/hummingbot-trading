from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from services.bot_metrics_exporter import BotMetricsExporter
from platform_lib.logging.log_namespace import iter_bot_log_files
from platform_lib.core.utils import safe_float as _safe_float


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _minutes_since(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(UTC) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _minutes_since_file_mtime(path: Path) -> float:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return (datetime.now(UTC) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _report_age_min(path: Path | None, payload: dict[str, object]) -> float:
    ts = str(payload.get("ts_utc") or payload.get("last_update_utc") or "").strip()
    if ts:
        return _minutes_since(ts)
    if path is not None:
        return _minutes_since_file_mtime(path)
    return 1e9


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    q = max(0.0, min(1.0, float(q)))
    idx = q * (len(ordered) - 1)
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return float(ordered[low])
    weight = idx - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _summarize(values: Sequence[float]) -> dict[str, float]:
    ordered = [float(v) for v in values if float(v) >= 0.0]
    return {
        "samples": float(len(ordered)),
        "p50_ms": _percentile(ordered, 0.50),
        "p95_ms": _percentile(ordered, 0.95),
        "p99_ms": _percentile(ordered, 0.99),
        "max_ms": max(ordered) if ordered else 0.0,
    }


def _latest_json(paths: Sequence[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    def _sort_key(path: Path) -> tuple[str, float]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        ts = ""
        if isinstance(payload, dict):
            ts = str(payload.get("ts_utc") or payload.get("last_update_utc") or "").strip()
        return ts, path.stat().st_mtime
    return max(existing, key=_sort_key)


def _collect_controller_latency_samples(data_root: Path) -> dict[str, list[float]]:
    tick: list[float] = []
    indicator: list[float] = []
    connector: list[float] = []
    for minute_file in iter_bot_log_files(data_root, "minute.csv"):
        try:
            with minute_file.open("r", encoding="utf-8", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    tick_val = _safe_float(row.get("_tick_duration_ms"))
                    indicator_val = _safe_float(row.get("_indicator_duration_ms"))
                    connector_val = _safe_float(row.get("_connector_io_duration_ms"))
                    if tick_val > 0:
                        tick.append(tick_val)
                    if indicator_val > 0:
                        indicator.append(indicator_val)
                    if connector_val > 0:
                        connector.append(connector_val)
        except Exception:
            continue
    return {
        "controller_tick_ms": tick,
        "indicator_ms": indicator,
        "connector_io_ms": connector,
    }


def _latest_controller_source_age_min(data_root: Path) -> tuple[float, str]:
    latest_path: Path | None = None
    latest_mtime = float("-inf")
    for minute_file in iter_bot_log_files(data_root, "minute.csv"):
        try:
            mtime = minute_file.stat().st_mtime
        except Exception:
            continue
        if latest_path is None or mtime > latest_mtime:
            latest_path = minute_file
            latest_mtime = mtime
    if latest_path is None:
        return 1e9, ""
    return _minutes_since_file_mtime(latest_path), str(latest_path)


def _measure_exporter_render(data_root: Path, *, samples: int) -> dict[str, float]:
    exporter = BotMetricsExporter(data_root=data_root, cache_ttl_seconds=1)
    exporter.render_prometheus()
    exporter._last_render_monotonic -= 10.0
    runs = max(1, int(samples))
    for _ in range(runs):
        exporter.render_prometheus()
        exporter._last_render_monotonic -= 10.0
    return _summarize(exporter._render_duration_samples_ms[-runs:])


def _read_event_store_ingest_summary(reports_root: Path) -> tuple[dict[str, float], str, float]:
    candidates = list((reports_root / "event_store").glob("integrity_*.json"))
    latest = _latest_json(candidates)
    if latest is None:
        return _summarize([]), "", 1e9
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return _summarize([]), str(latest), _minutes_since_file_mtime(latest)
    recent = payload.get("ingest_duration_ms_recent", [])
    values = [float(v) for v in recent] if isinstance(recent, list) else []
    return _summarize(values), str(latest), _report_age_min(latest, payload if isinstance(payload, dict) else {})


def _load_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _read_hot_path_metrics(reports_root: Path) -> tuple[dict[str, dict[str, float]], dict[str, object]]:
    verification_root = reports_root / "verification"
    report_paths = {
        "strategy_hot_path": verification_root / "strategy_hot_path_latest.json",
        "hb_bridge_hot_path": verification_root / "hb_bridge_hot_path_latest.json",
        "paper_exchange_hot_path": verification_root / "paper_exchange_hot_path_latest.json",
    }
    metrics: dict[str, dict[str, float]] = {}
    diagnostics: dict[str, object] = {}
    for report_name, report_path in report_paths.items():
        if not report_path.exists():
            continue
        payload = _load_json_file(report_path)
        metrics_payload = payload.get("metrics", {})
        if isinstance(metrics_payload, dict):
            for metric_name, summary in metrics_payload.items():
                if isinstance(summary, dict):
                    metrics[str(metric_name)] = {
                        "samples": float(summary.get("samples", 0.0) or 0.0),
                        "p50_ms": float(summary.get("p50_ms", 0.0) or 0.0),
                        "p95_ms": float(summary.get("p95_ms", 0.0) or 0.0),
                        "p99_ms": float(summary.get("p99_ms", 0.0) or 0.0),
                        "max_ms": float(summary.get("max_ms", 0.0) or 0.0),
                        "last_ms": float(summary.get("last_ms", 0.0) or 0.0),
                    }
        diagnostics[f"{report_name}_path"] = str(report_path)
        diagnostics[f"{report_name}_age_min"] = round(_report_age_min(report_path, payload), 3)
    return metrics, diagnostics


def _check(ok: bool, name: str, reason: str) -> dict[str, object]:
    return {"name": name, "pass": bool(ok), "reason": reason}


def run(
    root: Path,
    *,
    exporter_render_samples: int,
    max_controller_tick_p95_ms: float,
    max_exporter_render_p95_ms: float,
    max_event_store_ingest_p95_ms: float,
    max_source_age_min: float = 20.0,
    max_strategy_super_on_tick_p95_ms: float = 250.0,
    max_bus_publish_p95_ms: float = 50.0,
    max_intent_consume_p95_ms: float = 50.0,
    max_controller_risk_eval_p95_ms: float = 25.0,
    max_hb_bridge_command_publish_p95_ms: float = 50.0,
    max_paper_exchange_process_command_p95_ms: float = 50.0,
) -> dict[str, object]:
    reports_root = root / "reports"
    controller = _collect_controller_latency_samples(root / "data")
    controller_source_age_min, controller_source_path = _latest_controller_source_age_min(root / "data")
    controller_tick_summary = _summarize(controller["controller_tick_ms"])
    indicator_summary = _summarize(controller["indicator_ms"])
    connector_summary = _summarize(controller["connector_io_ms"])
    exporter_summary = _measure_exporter_render(root / "data", samples=exporter_render_samples)
    event_store_summary, event_store_stats_path, event_store_stats_age_min = _read_event_store_ingest_summary(reports_root)
    hot_path_metrics, hot_path_diagnostics = _read_hot_path_metrics(reports_root)

    controller_tick_present = controller_tick_summary["samples"] > 0
    exporter_present = exporter_summary["samples"] > 0
    event_store_present = event_store_summary["samples"] > 0
    controller_source_fresh = bool(controller_source_path) and controller_source_age_min <= float(max_source_age_min)
    event_store_source_fresh = bool(event_store_stats_path) and event_store_stats_age_min <= float(max_source_age_min)
    controller_tick_ok = controller_tick_present and controller_tick_summary["p95_ms"] <= float(max_controller_tick_p95_ms)
    exporter_ok = exporter_present and exporter_summary["p95_ms"] <= float(max_exporter_render_p95_ms)
    event_store_ok = event_store_present and event_store_summary["p95_ms"] <= float(max_event_store_ingest_p95_ms)
    strategy_super_on_tick = hot_path_metrics.get("strategy_super_on_tick_ms", {})
    bus_publish_summary = hot_path_metrics.get("bus_publish_market_state_ms", {})
    intent_consume_summary = hot_path_metrics.get("bus_consume_execution_intents_ms", {})
    controller_risk_summary = hot_path_metrics.get("controller_risk_eval_ms", {})
    hb_bridge_publish_summary = hot_path_metrics.get("hb_bridge_command_publish_ms", {})
    paper_exchange_command_summary = hot_path_metrics.get("paper_exchange_process_command_rows_ms", {})

    checks = [
        _check(
            controller_source_fresh,
            "controller_source_fresh",
            (
                f"path={controller_source_path or 'missing'} "
                f"age_min={controller_source_age_min:.3f} "
                f"max={float(max_source_age_min):.3f}"
            ),
        ),
        _check(
            event_store_source_fresh,
            "event_store_source_fresh",
            (
                f"path={event_store_stats_path or 'missing'} "
                f"age_min={event_store_stats_age_min:.3f} "
                f"max={float(max_source_age_min):.3f}"
            ),
        ),
        _check(
            controller_tick_ok,
            "controller_tick_p95_budget",
            (
                f"samples={int(controller_tick_summary['samples'])} "
                f"p95_ms={controller_tick_summary['p95_ms']:.3f} "
                f"max={float(max_controller_tick_p95_ms):.3f}"
            ),
        ),
        _check(
            exporter_ok,
            "exporter_render_p95_budget",
            (
                f"samples={int(exporter_summary['samples'])} "
                f"p95_ms={exporter_summary['p95_ms']:.3f} "
                f"max={float(max_exporter_render_p95_ms):.3f}"
            ),
        ),
        _check(
            event_store_ok,
            "event_store_ingest_p95_budget",
            (
                f"samples={int(event_store_summary['samples'])} "
                f"p95_ms={event_store_summary['p95_ms']:.3f} "
                f"max={float(max_event_store_ingest_p95_ms):.3f}"
            ),
        ),
    ]
    optional_budget_checks = [
        ("strategy_super_on_tick_p95_budget", strategy_super_on_tick, float(max_strategy_super_on_tick_p95_ms)),
        ("bus_publish_p95_budget", bus_publish_summary, float(max_bus_publish_p95_ms)),
        ("intent_consume_p95_budget", intent_consume_summary, float(max_intent_consume_p95_ms)),
        ("controller_risk_eval_p95_budget", controller_risk_summary, float(max_controller_risk_eval_p95_ms)),
        ("hb_bridge_command_publish_p95_budget", hb_bridge_publish_summary, float(max_hb_bridge_command_publish_p95_ms)),
        ("paper_exchange_process_command_p95_budget", paper_exchange_command_summary, float(max_paper_exchange_process_command_p95_ms)),
    ]
    for check_name, summary, threshold in optional_budget_checks:
        samples = int(float(summary.get("samples", 0.0) or 0.0)) if isinstance(summary, dict) else 0
        if samples <= 0:
            continue
        p95_ms = float(summary.get("p95_ms", 0.0) or 0.0)
        checks.append(
            _check(
                p95_ms <= threshold,
                check_name,
                f"samples={samples} p95_ms={p95_ms:.3f} max={threshold:.3f}",
            )
        )

    missing_families = [
        name
        for name, summary in (
            ("controller_tick", controller_tick_summary),
            ("exporter_render", exporter_summary),
            ("event_store_ingest", event_store_summary),
        )
        if int(summary["samples"]) <= 0
    ]
    stale_sources = [
        name
        for name, ok in (
            ("controller_source", controller_source_fresh),
            ("event_store_source", event_store_source_fresh),
        )
        if not ok
    ]
    hard_fail = any(
        (
            not controller_source_fresh,
            not event_store_source_fresh,
            controller_tick_present and not controller_tick_ok,
            exporter_present and not exporter_ok,
            event_store_present and not event_store_ok,
            any(check["name"].endswith("_budget") and not check["pass"] for check in checks[5:]),
        )
    )
    status = "fail" if hard_fail else "pass"
    if missing_families and not hard_fail:
        status = "warning"

    report = {
        "status": status,
        "ts_utc": _utc_now(),
        "checks": checks,
        "controller_tick_ms": controller_tick_summary,
        "indicator_ms": indicator_summary,
        "connector_io_ms": connector_summary,
        "exporter_render_ms": exporter_summary,
        "event_store_ingest_ms": event_store_summary,
        "hot_path_metrics_ms": hot_path_metrics,
        "diagnostics": {
            "missing_families": missing_families,
            "stale_sources": stale_sources,
            "max_source_age_min": float(max_source_age_min),
            "controller_source_path": controller_source_path,
            "controller_source_age_min": round(controller_source_age_min, 3),
            "event_store_stats_path": event_store_stats_path,
            "event_store_stats_age_min": round(event_store_stats_age_min, 3),
            "exporter_render_samples_requested": int(exporter_render_samples),
            **hot_path_diagnostics,
        },
    }
    out_dir = reports_root / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stamped = out_dir / f"runtime_performance_budgets_{stamp}.json"
    latest = out_dir / "runtime_performance_budgets_latest.json"
    stamped.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check runtime performance budgets from fresh artifacts.")
    parser.add_argument("--exporter-render-samples", type=int, default=5)
    parser.add_argument("--max-controller-tick-p95-ms", type=float, default=250.0)
    parser.add_argument("--max-exporter-render-p95-ms", type=float, default=500.0)
    parser.add_argument("--max-event-store-ingest-p95-ms", type=float, default=250.0)
    parser.add_argument("--max-source-age-min", type=float, default=20.0)
    parser.add_argument("--max-strategy-super-on-tick-p95-ms", type=float, default=250.0)
    parser.add_argument("--max-bus-publish-p95-ms", type=float, default=50.0)
    parser.add_argument("--max-intent-consume-p95-ms", type=float, default=50.0)
    parser.add_argument("--max-controller-risk-eval-p95-ms", type=float, default=25.0)
    parser.add_argument("--max-hb-bridge-command-publish-p95-ms", type=float, default=50.0)
    parser.add_argument("--max-paper-exchange-process-command-p95-ms", type=float, default=50.0)
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    report = run(
        root,
        exporter_render_samples=int(args.exporter_render_samples),
        max_controller_tick_p95_ms=float(args.max_controller_tick_p95_ms),
        max_exporter_render_p95_ms=float(args.max_exporter_render_p95_ms),
        max_event_store_ingest_p95_ms=float(args.max_event_store_ingest_p95_ms),
        max_source_age_min=float(args.max_source_age_min),
        max_strategy_super_on_tick_p95_ms=float(args.max_strategy_super_on_tick_p95_ms),
        max_bus_publish_p95_ms=float(args.max_bus_publish_p95_ms),
        max_intent_consume_p95_ms=float(args.max_intent_consume_p95_ms),
        max_controller_risk_eval_p95_ms=float(args.max_controller_risk_eval_p95_ms),
        max_hb_bridge_command_publish_p95_ms=float(args.max_hb_bridge_command_publish_p95_ms),
        max_paper_exchange_process_command_p95_ms=float(args.max_paper_exchange_process_command_p95_ms),
    )
    print(json.dumps({"status": report["status"], "path": "reports/verification/runtime_performance_budgets_latest.json"}))
    return 0 if str(report.get("status", "fail")).lower() in {"pass", "warning"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
