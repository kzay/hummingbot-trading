from __future__ import annotations

import glob
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_lib.contracts.stream_names import MARKET_DATA_STREAM, MARKET_DEPTH_STREAM, MARKET_QUOTE_STREAM

_TRIM_SENSITIVE_STREAMS = {
    MARKET_DATA_STREAM,
    MARKET_QUOTE_STREAM,
    MARKET_DEPTH_STREAM,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _latest_source_compare(path: Path) -> Path | None:
    files = sorted(glob.glob(str(path / "source_compare_*.json")))
    if not files:
        return None
    return Path(files[-1])


def _latest_integrity(path: Path) -> Path | None:
    files = sorted(glob.glob(str(path / "integrity_*.json")))
    if not files:
        return None
    return Path(files[-1])


def _refresh_integrity(root: Path) -> None:
    """Run the local integrity refresh script before evaluating to prevent stale-state false failures."""
    import subprocess
    import sys
    refresh_script = root / "scripts" / "utils" / "refresh_event_store_integrity_local.py"
    if not refresh_script.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(refresh_script)],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass  # Non-fatal — gate evaluation proceeds with whatever integrity file exists


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _should_exclude_trimmed_stream(stream: str, latest_compare: dict[str, object]) -> bool:
    if stream not in _TRIM_SENSITIVE_STREAMS:
        return False
    source_length_map = latest_compare.get("source_length_by_stream", {})
    source_events_map = latest_compare.get("source_events_by_stream", {})
    stored_events_map = latest_compare.get("stored_events_by_stream", {})
    if not isinstance(source_length_map, dict) or not isinstance(source_events_map, dict) or not isinstance(stored_events_map, dict):
        return False
    source_length = _safe_int(source_length_map.get(stream), -1)
    source_events = _safe_int(source_events_map.get(stream), -1)
    stored_events = _safe_int(stored_events_map.get(stream), -1)
    if source_length <= 0 or source_events <= 0 or stored_events < 0:
        return False
    # entries-added is lifetime monotonic while XLEN is retention-capped; once stored history
    # exceeds live retention and entries-added also exceeds XLEN, the absolute delta is no
    # longer a meaningful backlog signal for these high-volume market streams.
    return source_events > source_length and stored_events >= source_length


def _lag_diagnostics(latest_compare: dict[str, object], max_allowed_delta: int) -> dict[str, object]:
    delta_since = latest_compare.get("lag_produced_minus_ingested_since_baseline")
    if not isinstance(delta_since, dict) or not delta_since:
        delta_since = latest_compare.get("delta_produced_minus_ingested_since_baseline", {})
    if not isinstance(delta_since, dict):
        delta_since = {}
    lag_by_stream_abs: dict[str, int] = {}
    lag_by_stream_signed: dict[str, int] = {}
    raw_lag_by_stream_abs: dict[str, int] = {}
    excluded_streams: dict[str, dict[str, object]] = {}
    consumer_group_lag_map = latest_compare.get("consumer_group_lag_by_stream", {})
    source_length_map = latest_compare.get("source_length_by_stream", {})
    source_events_map = latest_compare.get("source_events_by_stream", {})
    stored_events_map = latest_compare.get("stored_events_by_stream", {})
    if not isinstance(consumer_group_lag_map, dict):
        consumer_group_lag_map = {}
    stream_names = sorted({str(stream) for stream in delta_since.keys()} | {str(stream) for stream in consumer_group_lag_map.keys()})
    for stream_name in stream_names:
        value = delta_since.get(stream_name, 0)
        try:
            signed = int(value)
        except Exception:
            signed = 0
        positive_lag = max(0, signed)
        raw_lag_by_stream_abs[stream_name] = positive_lag
        consumer_group_lag = _safe_int(consumer_group_lag_map.get(stream_name), -1)
        if consumer_group_lag >= 0:
            lag_by_stream_signed[stream_name] = consumer_group_lag
            lag_by_stream_abs[stream_name] = max(0, consumer_group_lag)
            continue
        if _should_exclude_trimmed_stream(stream_name, latest_compare):
            excluded_streams[stream_name] = {
                "reason": "trimmed_retention_entries_added_not_comparable",
                "lag_value": positive_lag,
                "source_length": _safe_int(source_length_map.get(stream_name)) if isinstance(source_length_map, dict) else 0,
                "source_events": _safe_int(source_events_map.get(stream_name)) if isinstance(source_events_map, dict) else 0,
                "stored_events": _safe_int(stored_events_map.get(stream_name)) if isinstance(stored_events_map, dict) else 0,
            }
            continue
        lag_by_stream_signed[stream_name] = signed
        lag_by_stream_abs[stream_name] = positive_lag
    max_delta_observed = max(list(lag_by_stream_abs.values()) or [0])
    worst_stream = ""
    if lag_by_stream_abs:
        worst_stream = max(sorted(lag_by_stream_abs.keys()), key=lambda k: lag_by_stream_abs.get(k, 0))
    offending_streams = {k: v for k, v in lag_by_stream_abs.items() if v > max_allowed_delta}
    return {
        "max_delta_observed": max_delta_observed,
        "max_allowed_delta": max_allowed_delta,
        "worst_stream": worst_stream,
        "lag_by_stream_abs": lag_by_stream_abs,
        "lag_by_stream_signed": lag_by_stream_signed,
        "raw_lag_by_stream_abs": raw_lag_by_stream_abs,
        "offending_streams": offending_streams,
        "excluded_streams": excluded_streams,
        "consumer_group_lag_by_stream": consumer_group_lag_map,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    reports = root / "reports" / "event_store"
    reports.mkdir(parents=True, exist_ok=True)

    # Always refresh local integrity snapshot first so the delta check uses
    # up-to-date counts rather than a potentially hours-old snapshot.
    if os.getenv("DAY2_GATE_SKIP_INTEGRITY_REFRESH", "").lower() not in ("1", "true", "yes"):
        _refresh_integrity(root)

    gate_hours = float(os.getenv("DAY2_GATE_MIN_HOURS", "24"))
    max_allowed_delta = int(os.getenv("DAY2_GATE_MAX_DELTA", "5"))

    baseline = _load_json(reports / "baseline_counts.json", {})
    latest_integrity_path = _latest_integrity(reports)
    integrity = _load_json(latest_integrity_path, {"missing_correlation_count": 999999}) if latest_integrity_path else {"missing_correlation_count": 999999}
    latest_compare_path = _latest_source_compare(reports)
    latest_compare = _load_json(latest_compare_path, {}) if latest_compare_path else {}

    baseline_created = baseline.get("created_at_utc")
    elapsed_hours = 0.0
    if isinstance(baseline_created, str) and baseline_created:
        try:
            started = datetime.fromisoformat(baseline_created.replace("Z", "+00:00"))
            elapsed_hours = (_utc_now() - started).total_seconds() / 3600.0
        except Exception:
            elapsed_hours = 0.0

    missing_corr = int(integrity.get("missing_correlation_count", 0))
    lag_diagnostics = _lag_diagnostics(latest_compare, max_allowed_delta=max_allowed_delta)
    max_delta_observed = int(lag_diagnostics.get("max_delta_observed", 0) or 0)
    worst_stream = str(lag_diagnostics.get("worst_stream", "") or "")
    offending_streams = lag_diagnostics.get("offending_streams", {})

    checks: list[dict[str, object]] = []
    checks.append({"name": "elapsed_window", "pass": elapsed_hours >= gate_hours, "value_hours": round(elapsed_hours, 2), "required_hours": gate_hours})
    checks.append({"name": "missing_correlation", "pass": missing_corr == 0, "value": missing_corr, "required": 0})
    checks.append(
        {
            "name": "delta_since_baseline_tolerance",
            "pass": max_delta_observed <= max_allowed_delta,
            "max_delta_observed": max_delta_observed,
            "max_allowed_delta": max_allowed_delta,
            "worst_stream": worst_stream,
            "offending_streams": offending_streams,
        }
    )

    go = all(bool(c.get("pass")) for c in checks)
    result = {
        "ts_utc": _utc_now().isoformat(),
        "go": go,
        "gate": "day2_event_store",
        "baseline_file": str(reports / "baseline_counts.json"),
        "integrity_file": str(latest_integrity_path) if latest_integrity_path else "",
        "source_compare_file": str(latest_compare_path) if latest_compare_path else "",
        "lag_diagnostics": lag_diagnostics,
        "checks": checks,
    }
    if max_delta_observed > max_allowed_delta:
        result["remediation"] = [
            "Run scripts/release/run_bus_recovery_check.py --label strict_cycle --max-delta <tolerance> --enforce-absolute-delta",
            "Ensure event_store service is running and catching up pending stream entries",
            "Re-run day2_gate_evaluator after catch-up and verify lag_diagnostics.offending_streams is empty",
        ]
    out = reports / "day2_gate_eval_latest.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
