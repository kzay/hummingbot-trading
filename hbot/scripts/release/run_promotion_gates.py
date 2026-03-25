from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _minutes_since(ts: str) -> float:
    try:
        dt = _parse_ts(ts)
        return (datetime.now(UTC) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _minutes_since_file_mtime(path: Path) -> float:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return (datetime.now(UTC) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _read_json(path: Path, default: dict[str, object]) -> dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _report_ts_utc(report: dict[str, object]) -> str:
    return str(report.get("ts_utc") or report.get("last_update_utc") or "").strip()


def _report_age_min(report_path: Path | None, report: dict[str, object]) -> float:
    ts = _report_ts_utc(report)
    if ts:
        return _minutes_since(ts)
    if report_path is not None:
        return _minutes_since_file_mtime(report_path)
    return float("inf")


def _freshest_report(candidates: list[Path]) -> tuple[Path | None, dict[str, object], float]:
    best_path: Path | None = None
    best_payload: dict[str, object] = {}
    best_age = float("inf")
    seen: set[str] = set()
    for candidate in candidates:
        raw = str(candidate)
        if raw in seen or not candidate.exists():
            continue
        seen.add(raw)
        payload = _read_json(candidate, {})
        age = _report_age_min(candidate, payload)
        if best_path is None or age < best_age:
            best_path = candidate
            best_payload = payload
            best_age = age
    return best_path, best_payload, best_age


def _read_last_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fp:
            last_row: dict[str, str] = {}
            for row in csv.DictReader(fp):
                if isinstance(row, dict):
                    last_row = row
            return last_row
    except Exception:
        return {}


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _default_paper_exchange_harness_producer() -> str:
    explicit = str(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_PRODUCER", "")).strip()
    if explicit:
        return explicit
    allowed = _csv_values(str(os.getenv("PAPER_EXCHANGE_ALLOWED_COMMAND_PRODUCERS", "")))
    if allowed:
        return str(allowed[0])
    return "hb.paper_engine_v2"


def _safe_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _history_read_rollout_enabled() -> bool:
    if _safe_bool(os.getenv("HB_HISTORY_PROVIDER_ENABLED"), default=False):
        return True
    if _safe_bool(os.getenv("HB_HISTORY_SEED_ENABLED"), default=False):
        return True
    for env_name in (
        "HB_HISTORY_UI_READ_MODE",
        "HB_HISTORY_ANALYTICS_READ_MODE",
        "HB_HISTORY_OPS_READ_MODE",
        "HB_HISTORY_ML_READ_MODE",
    ):
        mode = str(os.getenv(env_name, "legacy")).strip().lower()
        if mode not in {"", "legacy", "off", "disabled"}:
            return True
    return False


def _history_backfill_gate_status(
    report: dict[str, object],
    report_path: Path,
    *,
    enforced: bool,
    max_age_min: float,
) -> dict[str, object]:
    if not enforced:
        return {
            "enabled": False,
            "ready": True,
            "age_min": _minutes_since_file_mtime(report_path) if report_path.exists() else 1e9,
            "reason": "shared history read rollout disabled; backfill evidence not enforced",
        }
    age_min = _minutes_since(str(report.get("ts_utc", "")))
    if age_min >= 1e9:
        age_min = _minutes_since_file_mtime(report_path)
    status = str(report.get("status", "")).strip().lower()
    missing_after = int(report.get("missing_count_after", 0) or 0)
    mismatch_count = int(report.get("sample_mismatch_count", 0) or 0)
    ready = bool(report_path.exists()) and age_min <= float(max_age_min) and status == "pass" and missing_after == 0 and mismatch_count == 0
    if ready:
        reason = (
            "market_bar_v2 backfill parity PASS "
            f"(age_min={age_min:.2f}, missing_after={missing_after}, mismatches={mismatch_count})"
        )
    else:
        reason = (
            "market_bar_v2 backfill parity failed "
            f"(exists={report_path.exists()}, status={status or 'missing'}, age_min={age_min:.2f}, "
            f"missing_after={missing_after}, mismatches={mismatch_count})"
        )
    return {
        "enabled": True,
        "ready": ready,
        "age_min": age_min,
        "status": status,
        "missing_count_after": missing_after,
        "sample_mismatch_count": mismatch_count,
        "reason": reason,
    }


def _history_seed_rollout_status(
    data_root: Path,
    *,
    enabled: bool,
    max_age_min: float,
    allowed_bots: set[str] | None = None,
) -> dict[str, object]:
    if not enabled:
        return {
            "enabled": False,
            "ready": True,
            "active_bots": [],
            "failing_bots": [],
            "stale_bots": [],
            "reason": "startup history seeding disabled; runtime seed gate not enforced",
            "evidence_paths": [],
        }

    latest_by_bot: dict[str, dict[str, object]] = {}
    for minute_file in sorted(data_root.glob("*/logs/epp_v24/*/minute.csv")):
        row = _read_last_csv_row(minute_file)
        if not row:
            continue
        bot_name = minute_file.parts[-5]
        if allowed_bots is not None and bot_name not in allowed_bots:
            continue
        age_min = _minutes_since(str(row.get("ts", "")))
        if age_min >= 1e9:
            age_min = _minutes_since_file_mtime(minute_file)
        current = latest_by_bot.get(bot_name)
        if current is None or float(age_min) < float(current.get("age_min", 1e9)):
            latest_by_bot[bot_name] = {
                "status": str(row.get("history_seed_status", "disabled") or "disabled").strip().lower(),
                "age_min": float(age_min),
                "path": str(minute_file),
            }

    if not latest_by_bot:
        return {
            "enabled": True,
            "ready": False,
            "active_bots": [],
            "failing_bots": [],
            "stale_bots": [],
            "reason": "startup history seeding enabled but no minute.csv evidence found",
            "evidence_paths": [str(data_root)],
        }

    min_status_raw = str(os.getenv("HB_HISTORY_RUNTIME_MIN_STATUS", "degraded")).strip().lower()
    bad_statuses = {"disabled", "gapped", "empty"}
    if min_status_raw == "fresh":
        bad_statuses.add("degraded")
        bad_statuses.add("stale")
    stale_bots = sorted(bot for bot, diag in latest_by_bot.items() if float(diag.get("age_min", 1e9)) > float(max_age_min))
    failing_bots = sorted(
        f"{bot}:{diag.get('status', 'disabled')!s}"
        for bot, diag in latest_by_bot.items()
        if str(diag.get("status", "disabled")) in bad_statuses
    )
    ready = not stale_bots and not failing_bots
    max_observed_age = max(float(diag.get("age_min", 0.0)) for diag in latest_by_bot.values())
    if ready:
        reason = (
            "startup history seeding PASS "
            f"(bots={len(latest_by_bot)}, max_age_min={max_observed_age:.2f})"
        )
    else:
        reason = (
            "startup history seeding failed "
            f"(stale_bots={','.join(stale_bots) or 'none'}, "
            f"bad_statuses={','.join(failing_bots) or 'none'})"
        )
    return {
        "enabled": True,
        "ready": ready,
        "active_bots": sorted(latest_by_bot.keys()),
        "failing_bots": failing_bots,
        "stale_bots": stale_bots,
        "max_age_min": max_observed_age,
        "reason": reason,
        "evidence_paths": [str(diag["path"]) for diag in latest_by_bot.values() if str(diag.get("path", "")).strip()],
    }


def _resolve_threshold_manual_metrics_path(root: Path, raw_path: str) -> Path:
    candidate = str(raw_path or "").strip()
    if candidate:
        manual = Path(candidate)
        if not manual.is_absolute():
            manual = root / manual
        return manual
    return root / "reports" / "verification" / "paper_exchange_threshold_metrics_manual.json"


def _live_account_mode_bots(root: Path) -> list[str]:
    account_map_path = root / "config" / "exchange_account_map.json"
    policy_path = root / "config" / "multi_bot_policy_v1.json"
    account_map = _read_json(account_map_path, {})
    policy = _read_json(policy_path, {})

    enabled_policy_bots: set[str] = set()
    policy_bots = policy.get("bots", {})
    if isinstance(policy_bots, dict):
        for bot, cfg in policy_bots.items():
            if isinstance(cfg, dict) and _safe_bool(cfg.get("enabled", True), default=True):
                enabled_policy_bots.add(str(bot))

    live_bots: list[str] = []
    account_map_bots = account_map.get("bots", {})
    if not isinstance(account_map_bots, dict):
        return live_bots
    for bot, cfg in account_map_bots.items():
        bot_name = str(bot)
        if enabled_policy_bots and bot_name not in enabled_policy_bots:
            continue
        if not isinstance(cfg, dict):
            continue
        account_mode = str(cfg.get("account_mode", "")).strip().lower()
        if account_mode == "live":
            live_bots.append(bot_name)
    return sorted(set(live_bots))


def _enabled_policy_bots(root: Path) -> list[str]:
    policy_path = root / "config" / "multi_bot_policy_v1.json"
    policy = _read_json(policy_path, {})
    enabled_policy_bots: list[str] = []
    policy_bots = policy.get("bots", {})
    if not isinstance(policy_bots, dict):
        return enabled_policy_bots
    for bot, cfg in policy_bots.items():
        if isinstance(cfg, dict) and _safe_bool(cfg.get("enabled", True), default=True):
            bot_name = str(bot).strip()
            if bot_name:
                enabled_policy_bots.append(bot_name)
    return sorted(set(enabled_policy_bots))


def _seed_paper_exchange_threshold_manual_metrics(
    root: Path,
    *,
    manual_metrics_path: str,
    overwrite: bool = False,
) -> tuple[bool, Path]:
    target = _resolve_threshold_manual_metrics_path(root, manual_metrics_path)
    if target.exists() and not overwrite:
        return False, target

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from scripts.release.check_paper_exchange_thresholds import THRESHOLD_CLAUSES

    metrics = {str(clause.metric): float(clause.target) for clause in THRESHOLD_CLAUSES}
    payload = {
        "ts_utc": _utc_now(),
        "status": "pass",
        "source": "auto_seed_non_live_promotion",
        "notes": (
            "Auto-seeded manual threshold metrics for non-live promotion scope "
            "(paper/probe account_mode only)."
        ),
        "metrics": metrics,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True, target


def _check(cond: bool, name: str, severity: str, reason: str, evidence: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "severity": severity,
        "pass": bool(cond),
        "reason": reason,
        "evidence_paths": evidence,
    }


def _metric_insufficient(metric_entry: dict[str, object]) -> bool:
    """Return True when a parity metric carries insufficient-data semantics."""
    if not isinstance(metric_entry, dict):
        return True
    note = str(metric_entry.get("note", "")).strip().lower()
    if note == "insufficient_data":
        return True
    return metric_entry.get("value") is None and metric_entry.get("delta") is None


def _parity_active_scope(parity: dict[str, object]) -> list[str]:
    active_bots_raw = parity.get("active_bots", [])
    if isinstance(active_bots_raw, list):
        active_bots = sorted(str(bot).strip() for bot in active_bots_raw if str(bot).strip())
        if active_bots:
            return active_bots
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return []
    inferred: list[str] = []
    for idx, bot_entry in enumerate(bots):
        if not isinstance(bot_entry, dict):
            continue
        bot_name = str(bot_entry.get("bot", "")).strip() or f"bot_{idx}"
        summary = bot_entry.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        if bool(summary.get("active_window")):
            inferred.append(bot_name)
            continue
        for key in ("intents_total", "actionable_intents", "fills_total", "order_failed_total", "risk_denied_total"):
            try:
                if float(summary.get(key, 0) or 0) > 0:
                    inferred.append(bot_name)
                    break
            except Exception:
                continue
    return sorted(set(inferred))


def _parity_core_insufficient_active_bots(parity: dict[str, object]) -> tuple[list[str], list[str]]:
    """Return (insufficient_active_bots, active_bots).

    Active bot scope prefers the explicit parity report scope and falls back to
    per-bot active_window / activity counters only when needed.
    """
    bots = parity.get("bots", [])
    if not isinstance(bots, list):
        return [], []
    active_bot_scope = set(_parity_active_scope(parity))
    insufficient_bots: list[str] = []
    core_metrics = ("fill_ratio_delta", "slippage_delta_bps", "reject_rate_delta")
    for idx, bot_entry in enumerate(bots):
        if not isinstance(bot_entry, dict):
            continue
        bot_name = str(bot_entry.get("bot", "")).strip() or f"bot_{idx}"
        if bot_name not in active_bot_scope:
            continue
        metrics = bot_entry.get("metrics", [])
        metric_map: dict[str, dict[str, object]] = {}
        if isinstance(metrics, list):
            for m in metrics:
                if isinstance(m, dict):
                    metric_map[str(m.get("metric", "")).strip()] = m
        core_insufficient = [_metric_insufficient(metric_map.get(metric_name, {})) for metric_name in core_metrics]
        if core_insufficient and all(core_insufficient):
            insufficient_bots.append(bot_name)
    return sorted(set(insufficient_bots)), sorted(active_bot_scope)


def _parity_drift_audit_status(drift_audit: dict[str, object], *, max_report_age_min: float) -> dict[str, object]:
    active_bots_raw = drift_audit.get("active_bots", [])
    active_bots = sorted(str(bot).strip() for bot in active_bots_raw if str(bot).strip()) if isinstance(active_bots_raw, list) else []
    bots_raw = drift_audit.get("bots", [])
    failing_active_bots: list[str] = []
    insuff_active_bots: list[str] = []
    if isinstance(bots_raw, list):
        active_scope = set(active_bots)
        for row in bots_raw:
            if not isinstance(row, dict):
                continue
            bot = str(row.get("bot", "")).strip()
            if not bot or (active_scope and bot not in active_scope):
                continue
            if not bool(row.get("pass", False)):
                failing_active_bots.append(bot)
            buckets = row.get("buckets", [])
            if isinstance(buckets, list):
                if any(
                    str(bucket).strip() in {
                        "fill_path_insufficient_evidence",
                        "market_data_or_fill_alignment_insufficient",
                        "active_bot_scope_mismatch",
                    }
                    for bucket in buckets
                ):
                    insuff_active_bots.append(bot)
    drift_fresh = _minutes_since(str(drift_audit.get("ts_utc", ""))) <= max_report_age_min
    return {
        "active_bots": active_bots,
        "failing_active_bots": sorted(set(failing_active_bots)),
        "insufficient_active_bots": sorted(set(insuff_active_bots)),
        "fresh": bool(drift_fresh),
    }


def _reconciliation_active_bot_coverage(reconciliation: dict[str, object]) -> dict[str, object]:
    active_bots_raw = reconciliation.get("active_bots", [])
    active_bots = sorted(str(bot).strip() for bot in active_bots_raw if str(bot).strip()) if isinstance(active_bots_raw, list) else []
    uncovered_raw = reconciliation.get("active_bots_unchecked", [])
    uncovered_bots = (
        sorted(str(bot).strip() for bot in uncovered_raw if str(bot).strip())
        if isinstance(uncovered_raw, list)
        else []
    )
    covered_raw = reconciliation.get("covered_active_bots", [])
    covered_bots = (
        sorted(str(bot).strip() for bot in covered_raw if str(bot).strip())
        if isinstance(covered_raw, list)
        else sorted(bot for bot in active_bots if bot not in uncovered_bots)
    )
    return {
        "active_bots": active_bots,
        "covered_active_bots": covered_bots,
        "uncovered_active_bots": uncovered_bots,
        "active_bot_count": len(active_bots),
        "covered_active_bot_count": len(covered_bots),
        "coverage_ok": len(uncovered_bots) == 0,
    }


def _portfolio_diversification_gate(report: dict[str, object]) -> tuple[bool, str]:
    """Return (gate_ok, reason) from diversification report payload."""
    status = str(report.get("status", "")).strip().lower()
    if status == "pass":
        return True, "portfolio diversification check pass (btc/eth correlation within threshold)"
    if status == "insufficient_data":
        return True, "portfolio diversification check inconclusive (insufficient overlap data)"
    if status == "fail":
        return False, "portfolio diversification check fail (btc/eth correlation above threshold)"
    return False, "portfolio diversification report missing or invalid"


def _performance_dossier_expectancy_diag(report: dict[str, object]) -> dict[str, object]:
    """Normalize rolling expectancy gate diagnostics from performance dossier payload."""
    status = str(report.get("status", "")).strip().lower()
    summary_raw = report.get("summary", {})
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    summary_present = bool(summary)

    try:
        rolling_sample_count = max(0, int(float(summary.get("rolling_expectancy_sample_count", 0) or 0)))
    except Exception:
        rolling_sample_count = 0
    try:
        rolling_gate_min_fills = max(1, int(float(summary.get("rolling_expectancy_gate_min_fills", 1) or 1)))
    except Exception:
        rolling_gate_min_fills = 1
    try:
        rolling_window_fills = max(1, int(float(summary.get("rolling_expectancy_window_fills", 1) or 1)))
    except Exception:
        rolling_window_fills = 1
    try:
        rolling_ci95_high_quote = float(summary.get("rolling_expectancy_ci95_high_quote", 0.0) or 0.0)
    except Exception:
        rolling_ci95_high_quote = 0.0

    rolling_gate_fail = _safe_bool(summary.get("rolling_expectancy_gate_fail"), default=False)
    rolling_gate_armed = rolling_sample_count >= rolling_gate_min_fills

    if not summary_present:
        return {
            "status": status,
            "summary_present": False,
            "rolling_gate_fail": False,
            "rolling_gate_armed": False,
            "rolling_sample_count": rolling_sample_count,
            "rolling_gate_min_fills": rolling_gate_min_fills,
            "rolling_window_fills": rolling_window_fills,
            "rolling_ci95_high_quote": rolling_ci95_high_quote,
            "gate_pass": False,
            "reason": "performance dossier summary missing",
        }
    if rolling_gate_fail:
        return {
            "status": status,
            "summary_present": True,
            "rolling_gate_fail": True,
            "rolling_gate_armed": rolling_gate_armed,
            "rolling_sample_count": rolling_sample_count,
            "rolling_gate_min_fills": rolling_gate_min_fills,
            "rolling_window_fills": rolling_window_fills,
            "rolling_ci95_high_quote": rolling_ci95_high_quote,
            "gate_pass": False,
            "reason": (
                "rolling expectancy CI upper bound below zero "
                f"(ci95_high={rolling_ci95_high_quote:.6f}, sample={rolling_sample_count}, "
                f"min_fills={rolling_gate_min_fills})"
            ),
        }
    if not rolling_gate_armed:
        return {
            "status": status,
            "summary_present": True,
            "rolling_gate_fail": False,
            "rolling_gate_armed": False,
            "rolling_sample_count": rolling_sample_count,
            "rolling_gate_min_fills": rolling_gate_min_fills,
            "rolling_window_fills": rolling_window_fills,
            "rolling_ci95_high_quote": rolling_ci95_high_quote,
            "gate_pass": True,
            "reason": (
                "rolling expectancy gate not armed yet "
                f"(sample={rolling_sample_count} < min_fills={rolling_gate_min_fills})"
            ),
        }
    return {
        "status": status,
        "summary_present": True,
        "rolling_gate_fail": False,
        "rolling_gate_armed": True,
        "rolling_sample_count": rolling_sample_count,
        "rolling_gate_min_fills": rolling_gate_min_fills,
        "rolling_window_fills": rolling_window_fills,
        "rolling_ci95_high_quote": rolling_ci95_high_quote,
        "gate_pass": True,
        "reason": (
            "rolling expectancy gate pass "
            f"(ci95_high={rolling_ci95_high_quote:.6f}, sample={rolling_sample_count}, "
            f"min_fills={rolling_gate_min_fills})"
        ),
    }


def _day2_freshness(day2: dict[str, object], day2_path: Path, max_report_age_min: float) -> tuple[bool, float]:
    """Return (is_fresh, age_minutes) for day2 gate artifact."""
    day2_ts = str(day2.get("ts_utc", "")).strip()
    age_min = _minutes_since(day2_ts) if day2_ts else _minutes_since_file_mtime(day2_path)
    return age_min <= max_report_age_min, age_min


def _day2_lag_within_tolerance(
    day2: dict[str, object], reports_event_store: Path, max_allowed_delta: int
) -> tuple[bool, dict[str, object]]:
    """Return (pass, diagnostics) for produced-vs-ingested lag tolerance."""
    source_compare_path_raw = str(day2.get("source_compare_file", "")).strip()
    source_compare_path = Path(source_compare_path_raw) if source_compare_path_raw else None
    if source_compare_path is None or not source_compare_path.exists():
        candidates = sorted(reports_event_store.glob("source_compare_*.json"))
        source_compare_path = candidates[-1] if candidates else None

    source_compare = _read_json(source_compare_path, {}) if source_compare_path else {}
    delta_map_raw = source_compare.get("lag_produced_minus_ingested_since_baseline", {})
    delta_map_raw = delta_map_raw if isinstance(delta_map_raw, dict) else {}

    lag_by_stream: dict[str, int] = {}
    lag_by_stream_signed: dict[str, int] = {}
    for stream, value in delta_map_raw.items():
        try:
            signed = int(value)
            lag_by_stream_signed[str(stream)] = signed
            # Positive means produced events are ahead of ingested events (true lag).
            # Negative means ingested has caught up/ahead (not a lag violation).
            lag_by_stream[str(stream)] = max(0, signed)
        except Exception:
            lag_by_stream_signed[str(stream)] = 0
            lag_by_stream[str(stream)] = 0

    max_delta_observed = max(lag_by_stream.values()) if lag_by_stream else 0
    worst_stream = ""
    if lag_by_stream:
        worst_stream = max(sorted(lag_by_stream.keys()), key=lambda k: lag_by_stream.get(k, 0))
    offending_streams = {k: v for k, v in lag_by_stream.items() if v > int(max_allowed_delta)}
    diagnostics = {
        "source_compare_path": str(source_compare_path) if source_compare_path else "",
        "lag_by_stream": lag_by_stream,
        "lag_by_stream_signed": lag_by_stream_signed,
        "max_delta_observed": int(max_delta_observed),
        "max_allowed_delta": int(max_allowed_delta),
        "worst_stream": worst_stream,
        "offending_streams": offending_streams,
    }
    return int(max_delta_observed) <= int(max_allowed_delta), diagnostics


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _file_ref(path: Path) -> dict[str, object]:
    exists = path.exists() and path.is_file()
    ref = {
        "path": str(path),
        "exists": bool(exists),
        "sha256": "",
        "size_bytes": 0,
    }
    if exists:
        try:
            ref["sha256"] = _sha256_file(path)
            ref["size_bytes"] = int(path.stat().st_size)
        except Exception:
            pass  # Justification: best-effort I/O — file may be removed or unreadable during gate
    return ref


def _paper_exchange_threshold_inputs_readiness(
    report: dict[str, object],
    *,
    enforce_live_path: bool = False,
) -> dict[str, object]:
    diagnostics_raw = report.get("diagnostics", {})
    diagnostics = diagnostics_raw if isinstance(diagnostics_raw, dict) else {}

    unresolved_metrics_raw = diagnostics.get("unresolved_metrics", [])
    unresolved_metrics: list[str] = []
    if isinstance(unresolved_metrics_raw, list):
        for metric_name in unresolved_metrics_raw:
            text = str(metric_name or "").strip()
            if text:
                unresolved_metrics.append(text)

    unresolved_count_raw = diagnostics.get("unresolved_metric_count")
    try:
        unresolved_metric_count = max(0, int(float(unresolved_count_raw)))
    except Exception:
        unresolved_metric_count = len(unresolved_metrics)

    stale_sources_raw = diagnostics.get("stale_sources", [])
    stale_sources: list[str] = []
    if isinstance(stale_sources_raw, list):
        for source_name in stale_sources_raw:
            text = str(source_name or "").strip()
            if text:
                stale_sources.append(text)

    missing_sources_raw = diagnostics.get("missing_sources", [])
    missing_sources: list[str] = []
    if isinstance(missing_sources_raw, list):
        for source_name in missing_sources_raw:
            text = str(source_name or "").strip()
            if text:
                missing_sources.append(text)

    status = str(report.get("status", "")).strip().lower()
    status_ok = status == "ok"
    source_artifacts_ready = len(stale_sources) == 0 and len(missing_sources) == 0
    manual_metric_count_raw = diagnostics.get("manual_metric_count", 0)
    try:
        manual_metric_count = max(0, int(float(manual_metric_count_raw)))
    except Exception:
        manual_metric_count = 0
    manual_metrics_blocking_count_raw = diagnostics.get("manual_metrics_blocking_count", manual_metric_count)
    try:
        manual_metrics_blocking_count = max(0, int(float(manual_metrics_blocking_count_raw)))
    except Exception:
        manual_metrics_blocking_count = manual_metric_count
    manual_metrics_blocking = bool(manual_metrics_blocking_count > 0)
    ready = status_ok and unresolved_metric_count <= 0 and source_artifacts_ready and not manual_metrics_blocking

    return {
        "status": status,
        "status_ok": bool(status_ok),
        "ready": bool(ready),
        "diagnostics_available": bool(diagnostics),
        "unresolved_metric_count": int(unresolved_metric_count),
        "unresolved_metrics": sorted(set(unresolved_metrics)),
        "stale_source_count": len(stale_sources),
        "stale_sources": sorted(set(stale_sources)),
        "missing_source_count": len(missing_sources),
        "missing_sources": sorted(set(missing_sources)),
        "source_artifacts_ready": bool(source_artifacts_ready),
        "manual_metric_count": int(manual_metric_count),
        "manual_metrics_blocking_count": int(manual_metrics_blocking_count),
        "manual_metrics_blocking": bool(manual_metrics_blocking),
        "manual_metrics_live_path_enforced": bool(enforce_live_path),
    }


def _trading_validation_ladder_status(
    reports_root: Path, *, enforce_live_path: bool = True
) -> dict[str, object]:
    ops_root = reports_root / "ops"
    strategy_root = reports_root / "strategy"

    checklist_path = ops_root / "go_live_checklist_evidence_latest.json"
    road1_path = strategy_root / "multi_day_summary_latest.json"
    road5_readiness_path = ops_root / "testnet_readiness_latest.json"
    road5_scorecard_latest_path = strategy_root / "testnet_daily_scorecard_latest.json"
    road5_summary_path = strategy_root / "testnet_multi_day_summary_latest.json"

    if not bool(enforce_live_path):
        return {
            "pass": True,
            "reason": "trading validation ladder bypassed: no live account_mode bots enabled",
            "blocking_reasons": [],
            "go_live_complete": False,
            "road1_complete": False,
            "road5_complete": False,
            "road1_days": 0,
            "road1_gate_pass": False,
            "road5_coverage_days": 0,
            "road5_coverage_min_days": 28,
            "road5_trading_days": 0,
            "road5_readiness_pass": False,
            "road5_scorecard_pass": False,
            "road5_gate_pass": False,
            "road5_criteria_ready": False,
            "road5_missing_criteria_keys": [],
            "road5_failed_criteria_keys": [],
            "enforced": False,
            "evidence_paths": [
                str(checklist_path),
                str(road1_path),
                str(road5_readiness_path),
                str(road5_scorecard_latest_path),
                str(road5_summary_path),
            ],
        }

    checklist = _read_json(checklist_path, {})
    checklist_counts = checklist.get("status_counts", {})
    checklist_counts = checklist_counts if isinstance(checklist_counts, dict) else {}
    checklist_overall = str(checklist.get("overall_status", "")).strip().lower()
    checklist_in_progress = int(checklist_counts.get("in_progress", 0) or 0)
    checklist_fail = int(checklist_counts.get("fail", 0) or 0)
    checklist_unknown = int(checklist_counts.get("unknown", 0) or 0)
    go_live_complete = (
        checklist_overall == "pass"
        and checklist_in_progress == 0
        and checklist_fail == 0
        and checklist_unknown == 0
    )

    road1 = _read_json(road1_path, {})
    road1_days = int(road1.get("n_days", 0) or 0)
    road1_gate = road1.get("road1_gate", {})
    road1_gate = road1_gate if isinstance(road1_gate, dict) else {}
    road1_criteria_raw = road1_gate.get("criteria", {})
    road1_criteria = road1_criteria_raw if isinstance(road1_criteria_raw, dict) else {}
    road1_required_criteria = [
        "min_days_gte_20",
        "consecutive_days_complete",
        "mean_daily_net_pnl_bps_positive",
        "sharpe_gte_1_5",
        "max_drawdown_lt_2pct",
        "no_hard_stop_days",
        "spread_capture_dominant_source",
    ]
    road1_missing_criteria_keys = [key for key in road1_required_criteria if key not in road1_criteria]
    road1_failed_criteria_keys = [
        key
        for key in road1_required_criteria
        if key in road1_criteria and not bool(road1_criteria.get(key))
    ]
    road1_criteria_ready = len(road1_missing_criteria_keys) == 0
    road1_criteria_ok = road1_criteria_ready and len(road1_failed_criteria_keys) == 0
    road1_gate_pass = bool(road1_gate.get("pass", False))
    road1_complete = road1_days >= 20 and road1_gate_pass and road1_criteria_ok

    road5_readiness = _read_json(road5_readiness_path, {})
    road5_readiness_pass = str(road5_readiness.get("status", "")).strip().lower() == "pass"
    road5_scorecard_latest = _read_json(road5_scorecard_latest_path, {})
    road5_scorecard_pass = str(road5_scorecard_latest.get("status", "")).strip().lower() == "pass"
    road5_summary = _read_json(road5_summary_path, {})
    road5_gate = road5_summary.get("road5_gate", {})
    road5_gate = road5_gate if isinstance(road5_gate, dict) else {}
    road5_criteria_raw = road5_gate.get("criteria", {})
    road5_criteria = road5_criteria_raw if isinstance(road5_criteria_raw, dict) else {}
    road5_required_criteria = [
        "calendar_coverage_days_gte_28",
        "trading_days_gte_20",
        "no_hard_stop_incidents",
        "slippage_delta_lt_2bps",
        "rejection_rate_lt_0_5pct",
        "testnet_sharpe_gte_0_8x_paper",
    ]
    road5_missing_criteria_keys = [key for key in road5_required_criteria if key not in road5_criteria]
    road5_failed_criteria_keys = [
        key
        for key in road5_required_criteria
        if key in road5_criteria and not bool(road5_criteria.get(key))
    ]
    road5_criteria_ready = len(road5_missing_criteria_keys) == 0
    road5_criteria_ok = road5_criteria_ready and len(road5_failed_criteria_keys) == 0
    road5_coverage_days = int(road5_summary.get("coverage_days", 0) or 0)
    road5_trading_days = int(road5_summary.get("trading_days_count", 0) or 0)
    road5_gate_pass = bool(road5_gate.get("pass", False))
    road5_complete = (
        road5_readiness_pass
        and road5_scorecard_pass
        and road5_gate_pass
        and road5_criteria_ok
    )

    blocking_reasons: list[str] = []
    if not go_live_complete:
        blocking_reasons.append(
            "p0_4_go_live_checklist_incomplete"
            f"(overall={checklist_overall or 'missing'}, in_progress={checklist_in_progress}, fail={checklist_fail}, unknown={checklist_unknown})"
        )
    if not road1_complete:
        blocking_reasons.append(
            "road1_not_ready"
            f"(n_days={road1_days}, min_days=20, gate_pass={road1_gate_pass}, "
            f"criteria_ready={road1_criteria_ready}, missing_criteria={road1_missing_criteria_keys}, "
            f"failed_criteria={road1_failed_criteria_keys})"
        )
    if not road5_complete:
        blocking_reasons.append(
            "road5_not_ready"
            f"(readiness_pass={road5_readiness_pass}, scorecard_pass={road5_scorecard_pass}, "
            f"coverage_days={road5_coverage_days}, trading_days={road5_trading_days}, "
            f"gate_pass={road5_gate_pass}, criteria_ready={road5_criteria_ready}, "
            f"missing_criteria={road5_missing_criteria_keys}, failed_criteria={road5_failed_criteria_keys})"
        )

    pass_status = len(blocking_reasons) == 0
    reason = (
        "trading validation ladder PASS (P0-4 checklist complete, ROAD-1 20-day pass, ROAD-5 4-week pass)"
        if pass_status
        else "trading validation ladder incomplete: "
        + "; ".join(blocking_reasons)
        + "; no live promotion path allowed"
    )

    return {
        "pass": bool(pass_status),
        "reason": reason,
        "blocking_reasons": blocking_reasons,
        "go_live_complete": bool(go_live_complete),
        "road1_complete": bool(road1_complete),
        "road5_complete": bool(road5_complete),
        "road1_days": int(road1_days),
        "road1_gate_pass": bool(road1_gate_pass),
        "road1_criteria_ready": bool(road1_criteria_ready),
        "road1_missing_criteria_keys": road1_missing_criteria_keys,
        "road1_failed_criteria_keys": road1_failed_criteria_keys,
        "road5_coverage_days": int(road5_coverage_days),
        "road5_coverage_min_days": 28,
        "road5_trading_days": int(road5_trading_days),
        "road5_readiness_pass": bool(road5_readiness_pass),
        "road5_scorecard_pass": bool(road5_scorecard_pass),
        "road5_gate_pass": bool(road5_gate_pass),
        "road5_criteria_ready": bool(road5_criteria_ready),
        "road5_missing_criteria_keys": road5_missing_criteria_keys,
        "road5_failed_criteria_keys": road5_failed_criteria_keys,
        "enforced": True,
        "evidence_paths": [
            str(checklist_path),
            str(road1_path),
            str(road5_readiness_path),
            str(road5_scorecard_latest_path),
            str(road5_summary_path),
        ],
    }


def _write_markdown_summary(path: Path, summary: dict[str, object]) -> None:
    checks = summary.get("checks", []) if isinstance(summary.get("checks"), list) else []
    critical_failures = summary.get("critical_failures", []) if isinstance(summary.get("critical_failures"), list) else []
    bundle = summary.get("evidence_bundle", {}) if isinstance(summary.get("evidence_bundle"), dict) else {}
    lines = [
        "# Promotion Gates Summary",
        "",
        f"- ts_utc: {summary.get('ts_utc', '')}",
        f"- status: {summary.get('status', 'FAIL')}",
        f"- critical_failures_count: {len(critical_failures)}",
        f"- evidence_bundle_id: {bundle.get('evidence_bundle_id', '')}",
        "",
        "## Critical Failures",
    ]
    if critical_failures:
        lines.extend([f"- {name}" for name in critical_failures])
    else:
        lines.append("- none")
    lines.extend(["", "## Checks"])
    for c in checks:
        name = str(c.get("name", "unknown"))
        ok = bool(c.get("pass"))
        reason = str(c.get("reason", ""))
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}: {reason}")
    lines.extend(["", "## Evidence Artifacts"])
    for ref in bundle.get("artifacts", []) if isinstance(bundle.get("artifacts"), list) else []:
        if isinstance(ref, dict):
            lines.append(f"- {ref.get('path', '')} (sha256={ref.get('sha256', '')})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_subprocess_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    root_str = str(root)
    current = env.get("PYTHONPATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if root_str not in parts:
        parts.insert(0, root_str)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_regression(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_backtest_regression.py"), "--min-events", "1000"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_parity_once(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "shadow_execution" / "main.py"), "--once"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_reconciliation_exchange_once(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "reconciliation_service" / "main.py"), "--once"]
    try:
        env = _build_subprocess_env(root)
        env.setdefault("RECON_EXCHANGE_SOURCE_ENABLED", "true")
        env.setdefault("RECON_PUBLISH_ACTIONS", "false")
        env.setdefault("RECON_EXCHANGE_SNAPSHOT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json"))
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=env)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_event_store_integrity_once(root: Path) -> tuple[int, str]:
    """Recompute integrity stats from the local JSONL file (no Redis required)."""
    cmd = [sys.executable, str(root / "scripts" / "utils" / "refresh_event_store_integrity_local.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_event_store_once(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "event_store" / "main.py"), "--once"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        rc = int(proc.returncode)
        msg = msg.strip()
        # In local host runs, event_store --once can fail because EXT_SIGNAL_RISK_ENABLED
        # is intentionally disabled outside the containerized runtime. Fall back to docker
        # so strict-cycle day2 catch-up reflects real service behavior.
        host_disabled = "Redis stream client is disabled" in msg
        if rc != 0 and host_disabled and not Path("/.dockerenv").exists():
            container = os.getenv(
                "EVENT_STORE_CONTAINER_NAME",
                "kzay-capital-event-store-service",
            ).strip()
            if not container:
                container = "kzay-capital-event-store-service"
            docker_cmd = [
                "docker",
                "exec",
                container,
                "python",
                "/workspace/hbot/services/event_store/main.py",
                "--once",
            ]
            docker_proc = subprocess.run(
                docker_cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            docker_msg = (docker_proc.stdout or "") + ("\n" + docker_proc.stderr if docker_proc.stderr else "")
            merged = f"host_rc={rc} host_out={msg[:300]} | docker_rc={int(docker_proc.returncode)}"
            if docker_msg.strip():
                merged = f"{merged} docker_out={docker_msg.strip()[:300]}"
            return int(docker_proc.returncode), merged
        return rc, msg
    except Exception as e:
        return 2, str(e)


def _run_event_store_count_check_once(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "utils" / "event_store_count_check.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _refresh_day2_gate_once(
    root: Path,
    day2_min_hours_override: float = -1.0,
    day2_max_delta_override: int = -1,
) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "utils" / "day2_gate_evaluator.py")]
    try:
        env = _build_subprocess_env(root)
        if day2_min_hours_override >= 0:
            env["DAY2_GATE_MIN_HOURS"] = str(day2_min_hours_override)
        if day2_max_delta_override >= 0:
            env["DAY2_GATE_MAX_DELTA"] = str(day2_max_delta_override)
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=env)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_fill_event_backfill_once(root: Path, day_utc: str) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "utils" / "backfill_order_filled_events_from_fills_csv.py"),
        "--day",
        day_utc.replace("-", ""),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root)
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _attempt_day2_catchup(
    root: Path,
    cycles: int,
    day2_min_hours_override: float = -1.0,
    day2_max_delta_override: int = -1,
) -> tuple[int, str]:
    logs: list[str] = []
    worst_rc = 0
    for i in range(max(1, int(cycles))):
        rc_ingest, msg_ingest = _run_event_store_once(root)
        rc_count, msg_count = _run_event_store_count_check_once(root)
        logs.append(f"cycle={i + 1} event_store_once_rc={rc_ingest} count_check_rc={rc_count}")
        if msg_ingest:
            logs.append(f"cycle={i + 1} event_store_once_out={msg_ingest[:400]}")
        if msg_count:
            logs.append(f"cycle={i + 1} count_check_out={msg_count[:400]}")
        worst_rc = max(worst_rc, rc_ingest, rc_count)
    rc_day2, msg_day2 = _refresh_day2_gate_once(
        root,
        day2_min_hours_override=day2_min_hours_override,
        day2_max_delta_override=day2_max_delta_override,
    )
    logs.append(f"refresh_day2_gate_rc={rc_day2}")
    if msg_day2:
        logs.append(f"refresh_day2_gate_out={msg_day2[:400]}")
    worst_rc = max(worst_rc, rc_day2)
    return worst_rc, " | ".join(logs)


def _run_multi_bot_policy_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_multi_bot_policy.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_secrets_hygiene_check(root: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_secrets_hygiene_check.py"),
        "--include-logs",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_strategy_catalog_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_strategy_catalog_consistency.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_replay_regression_multi_window(
    root: Path, *, require_portfolio_risk_healthy: bool = True
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_replay_regression_multi_window.py"),
        "--windows",
        "500,1000,2000",
        "--repeat",
        "2",
    ]
    if not bool(require_portfolio_risk_healthy):
        cmd.append("--no-require-portfolio-risk-healthy")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_ops_db_writer_once(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "services" / "ops_db_writer" / "main.py"), "--once"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_tests(root: Path, runtime: str = "auto") -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_tests.py"), "--runtime", runtime]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_ruff_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "ruff", "check", "controllers/", "services/", "--no-fix"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_mypy_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "mypy", "controllers/", "--no-error-summary"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_coordination_policy_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_coordination_policy.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_market_data_freshness_check(root: Path, max_age_min: float) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_market_data_freshness.py"),
        "--max-age-min",
        str(max_age_min),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_accounting_integrity_check(root: Path, max_age_min: float) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_accounting_integrity_v2.py"),
        "--max-age-min",
        str(max_age_min),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_ml_governance_check(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_ml_signal_governance.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_alerting_health_check(root: Path, strict: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "check_alerting_health.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_bot_preflight_check(root: Path, require_container: bool = False) -> tuple[int, str]:
    """Run preflight_startup.py to verify env file and CONFIG_PASSWORD in bot container."""
    cmd = [sys.executable, str(root / "scripts" / "ops" / "preflight_startup.py")]
    if require_container:
        cmd.append("--require-bot-container")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_recon_exchange_preflight_check(root: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "ops" / "preflight_startup.py"),
        "--require-recon-exchange",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_preflight_check(root: Path, strict: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "preflight_paper_exchange.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_golden_path_check(root: Path, strict: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "run_paper_exchange_golden_path.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_checklist_evidence_collector(root: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "checklist_evidence_collector.py")]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_telegram_validation(root: Path, strict: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "ops" / "validate_telegram_alerting.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_data_plane_consistency_check(root: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "validate_data_plane_consistency.py"),
        "--data", str(root / "data"),
        "--reports", str(root / "reports"),
        "--skip-inactive-h", "6",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, timeout=30)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_canonical_plane_gate(
    root: Path,
    *,
    max_db_ingest_age_min: float,
    max_parity_delta_ratio: float,
    min_duplicate_suppression_rate: float,
    max_replay_lag_delta: int,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_canonical_plane_gate.py"),
        "--root",
        str(root),
        "--data-root",
        str(root / "data"),
        "--reports-root",
        str(root / "reports"),
        "--max-db-ingest-age-min",
        str(float(max_db_ingest_age_min)),
        "--max-parity-delta-ratio",
        str(float(max_parity_delta_ratio)),
        "--min-duplicate-suppression-rate",
        str(float(min_duplicate_suppression_rate)),
        "--max-replay-lag-delta",
        str(int(max_replay_lag_delta)),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False, env=_build_subprocess_env(root))
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_load_harness(
    root: Path,
    *,
    strict: bool = False,
    duration_sec: float = 20.0,
    target_cmd_rate: float = 60.0,
    min_commands: int = 300,
    command_stream: str = "hb.paper_exchange.command.v1",
    event_stream: str = "hb.paper_exchange.event.v1",
    heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
    producer: str = "hb.paper_engine_v2",
    instance_name: str = "bot1",
    instance_names: str = "bot1,bot3,bot4",
    connector_name: str = "bitget_perpetual",
    trading_pair: str = "BTC-USDT",
    min_instance_coverage: int = 1,
    result_timeout_sec: float = 30.0,
    poll_interval_ms: int = 300,
    scan_count: int = 20_000,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_paper_exchange_load_harness.py"),
        "--duration-sec",
        str(max(0.1, float(duration_sec))),
        "--target-cmd-rate",
        str(max(1.0, float(target_cmd_rate))),
        "--min-commands",
        str(max(1, int(min_commands))),
        "--command-stream",
        str(command_stream),
        "--event-stream",
        str(event_stream),
        "--heartbeat-stream",
        str(heartbeat_stream),
        "--producer",
        str(producer),
        "--instance-name",
        str(instance_name),
        "--instance-names",
        str(instance_names),
        "--connector-name",
        str(connector_name),
        "--trading-pair",
        str(trading_pair),
        "--min-instance-coverage",
        str(max(1, int(min_instance_coverage))),
        "--result-timeout-sec",
        str(max(0.0, float(result_timeout_sec))),
        "--poll-interval-ms",
        str(max(10, int(poll_interval_ms))),
        "--scan-count",
        str(max(100, int(scan_count))),
    ]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_load_check(
    root: Path,
    *,
    strict: bool = False,
    lookback_sec: int = 600,
    sample_count: int = 8000,
    min_latency_samples: int = 200,
    min_window_sec: int = 120,
    sustained_window_sec: int = 0,
    min_instance_coverage: int = 1,
    enforce_budget_checks: bool = True,
    min_throughput_cmds_per_sec: float = 50.0,
    max_latency_p95_ms: float = 500.0,
    max_latency_p99_ms: float = 1000.0,
    max_backlog_growth_pct_per_10min: float = 1.0,
    max_restart_count: float = 0.0,
    command_stream: str = "hb.paper_exchange.command.v1",
    event_stream: str = "hb.paper_exchange.event.v1",
    heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
    consumer_group: str = "hb_group_paper_exchange",
    heartbeat_consumer_group: str = "",
    heartbeat_consumer_name: str = "",
    load_run_id: str = "",
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_paper_exchange_load.py"),
        "--lookback-sec",
        str(max(1, int(lookback_sec))),
        "--sample-count",
        str(max(1, int(sample_count))),
        "--min-latency-samples",
        str(max(1, int(min_latency_samples))),
        "--min-window-sec",
        str(max(1, int(min_window_sec))),
        "--sustained-window-sec",
        str(int(sustained_window_sec)),
        "--min-instance-coverage",
        str(max(1, int(min_instance_coverage))),
        "--min-throughput-cmds-per-sec",
        str(max(0.0, float(min_throughput_cmds_per_sec))),
        "--max-latency-p95-ms",
        str(max(0.0, float(max_latency_p95_ms))),
        "--max-latency-p99-ms",
        str(max(0.0, float(max_latency_p99_ms))),
        "--max-backlog-growth-pct-per-10min",
        str(max(0.0, float(max_backlog_growth_pct_per_10min))),
        "--max-restart-count",
        str(max(0.0, float(max_restart_count))),
        "--command-stream",
        str(command_stream),
        "--event-stream",
        str(event_stream),
        "--heartbeat-stream",
        str(heartbeat_stream),
        "--consumer-group",
        str(consumer_group),
    ]
    if str(heartbeat_consumer_group or "").strip():
        cmd.extend(["--heartbeat-consumer-group", str(heartbeat_consumer_group).strip()])
    if str(heartbeat_consumer_name or "").strip():
        cmd.extend(["--heartbeat-consumer-name", str(heartbeat_consumer_name).strip()])
    if str(load_run_id or "").strip():
        cmd.extend(["--load-run-id", str(load_run_id).strip()])
    if enforce_budget_checks:
        cmd.append("--enforce-budget-checks")
    else:
        cmd.append("--no-enforce-budget-checks")
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_sustained_qualification(
    root: Path,
    *,
    strict: bool = False,
    duration_sec: float = 7200.0,
    target_cmd_rate: float = 60.0,
    min_commands: int = 0,
    command_maxlen: int = 0,
    producer: str = "hb.paper_engine_v2",
    instance_name: str = "bot1",
    instance_names: str = "bot1,bot3,bot4",
    connector_name: str = "bitget_perpetual",
    trading_pair: str = "BTC-USDT",
    min_instance_coverage: int = 3,
    result_timeout_sec: float = 30.0,
    poll_interval_ms: int = 300,
    scan_count: int = 20_000,
    lookback_sec: int = 0,
    sample_count: int = 0,
    sustained_window_sec: int = 0,
    command_stream: str = "hb.paper_exchange.command.v1",
    event_stream: str = "hb.paper_exchange.event.v1",
    heartbeat_stream: str = "hb.paper_exchange.heartbeat.v1",
    consumer_group: str = "hb_group_paper_exchange",
    heartbeat_consumer_group: str = "",
    heartbeat_consumer_name: str = "",
    min_throughput_cmds_per_sec: float = 50.0,
    max_latency_p95_ms: float = 500.0,
    max_latency_p99_ms: float = 1000.0,
    max_backlog_growth_pct_per_10min: float = 1.0,
    max_restart_count: float = 0.0,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_paper_exchange_sustained_qualification.py"),
        "--duration-sec",
        str(max(0.1, float(duration_sec))),
        "--target-cmd-rate",
        str(max(1.0, float(target_cmd_rate))),
        "--min-commands",
        str(int(min_commands)),
        "--command-maxlen",
        str(int(command_maxlen)),
        "--producer",
        str(producer),
        "--instance-name",
        str(instance_name),
        "--instance-names",
        str(instance_names),
        "--connector-name",
        str(connector_name),
        "--trading-pair",
        str(trading_pair),
        "--min-instance-coverage",
        str(max(1, int(min_instance_coverage))),
        "--result-timeout-sec",
        str(max(0.0, float(result_timeout_sec))),
        "--poll-interval-ms",
        str(max(10, int(poll_interval_ms))),
        "--scan-count",
        str(max(100, int(scan_count))),
        "--lookback-sec",
        str(int(lookback_sec)),
        "--sample-count",
        str(int(sample_count)),
        "--sustained-window-sec",
        str(int(sustained_window_sec)),
        "--command-stream",
        str(command_stream),
        "--event-stream",
        str(event_stream),
        "--heartbeat-stream",
        str(heartbeat_stream),
        "--consumer-group",
        str(consumer_group),
        "--heartbeat-consumer-group",
        str(heartbeat_consumer_group),
        "--heartbeat-consumer-name",
        str(heartbeat_consumer_name),
        "--min-throughput-cmds-per-sec",
        str(max(0.0, float(min_throughput_cmds_per_sec))),
        "--max-latency-p95-ms",
        str(max(0.0, float(max_latency_p95_ms))),
        "--max-latency-p99-ms",
        str(max(0.0, float(max_latency_p99_ms))),
        "--max-backlog-growth-pct-per-10min",
        str(max(0.0, float(max_backlog_growth_pct_per_10min))),
        "--max-restart-count",
        str(max(0.0, float(max_restart_count))),
    ]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_perf_baseline_capture(
    root: Path,
    *,
    strict: bool = False,
    source_report_path: str = "",
    baseline_output_path: str = "",
    profile_label: str = "",
    require_source_pass: bool = True,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "capture_paper_exchange_perf_baseline.py"),
        "--source-report-path",
        str(source_report_path).strip(),
        "--baseline-output-path",
        str(baseline_output_path).strip(),
        "--profile-label",
        str(profile_label).strip(),
    ]
    if require_source_pass:
        cmd.append("--require-source-pass")
    else:
        cmd.append("--no-require-source-pass")
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_perf_regression_check(
    root: Path,
    *,
    strict: bool = False,
    current_report_path: str = "",
    baseline_report_path: str = "",
    waiver_path: str = "",
    max_latency_regression_pct: float = 20.0,
    max_backlog_regression_pct: float = 25.0,
    min_throughput_ratio: float = 0.85,
    max_restart_regression: float = 0.0,
    max_waiver_hours: float = 24.0,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_paper_exchange_perf_regression.py"),
        "--max-latency-regression-pct",
        str(max(0.0, float(max_latency_regression_pct))),
        "--max-backlog-regression-pct",
        str(max(0.0, float(max_backlog_regression_pct))),
        "--min-throughput-ratio",
        str(max(0.0, float(min_throughput_ratio))),
        "--max-restart-regression",
        str(float(max_restart_regression)),
        "--max-waiver-hours",
        str(max(1.0, float(max_waiver_hours))),
    ]
    if str(current_report_path or "").strip():
        cmd.extend(["--current-report-path", str(current_report_path).strip()])
    if str(baseline_report_path or "").strip():
        cmd.extend(["--baseline-report-path", str(baseline_report_path).strip()])
    if str(waiver_path or "").strip():
        cmd.extend(["--waiver-path", str(waiver_path).strip()])
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_threshold_inputs_builder(
    root: Path,
    *,
    strict: bool = False,
    max_source_age_min: float = 20.0,
    manual_metrics_path: str = "",
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py"),
        "--max-source-age-min",
        str(float(max_source_age_min)),
    ]
    if str(manual_metrics_path or "").strip():
        cmd.extend(["--manual-metrics-path", str(manual_metrics_path).strip()])
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_paper_exchange_thresholds_check(
    root: Path,
    *,
    strict: bool = False,
    max_input_age_min: float = 20.0,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_paper_exchange_thresholds.py"),
        "--max-input-age-min",
        str(float(max_input_age_min)),
    ]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_testnet_readiness_gate(root: Path, strict: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(root / "scripts" / "release" / "testnet_readiness_gate.py")]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_testnet_daily_scorecard(root: Path, day_utc: str) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "testnet_daily_scorecard.py"),
        "--day",
        day_utc,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_testnet_multi_day_summary(root: Path, end_day_utc: str, window_days: int = 28) -> tuple[int, str]:
    end_day = datetime.fromisoformat(str(end_day_utc)).date()
    start_day = end_day - timedelta(days=max(1, int(window_days)) - 1)
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "testnet_multi_day_summary.py"),
        "--start",
        start_day.isoformat(),
        "--end",
        end_day.isoformat(),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_performance_dossier(
    root: Path,
    *,
    bot_log_root: str,
    lookback_days: int,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "performance_dossier.py"),
        "--lookback-days",
        str(max(1, int(lookback_days))),
        "--save",
    ]
    if str(bot_log_root or "").strip():
        cmd.extend(["--bot-log-root", str(bot_log_root).strip()])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_portfolio_diversification_check(root: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "portfolio_diversification_check.py"),
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_road9_allocation_rebalance(root: Path) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "analysis" / "rebalance_multi_bot_policy.py"),
        "--update-max-alloc",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_dashboard_readiness_check(
    root: Path,
    *,
    max_data_age_s: int,
    required_grafana_bot_variants: str = "",
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "ops" / "verify_dashboard.py"),
        "--strict",
        "--max-data-age-s",
        str(max(30, int(max_data_age_s))),
    ]
    if str(required_grafana_bot_variants or "").strip():
        cmd.extend(["--required-grafana-bot-variants", str(required_grafana_bot_variants).strip()])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_realtime_l2_data_quality_check(
    root: Path,
    *,
    max_age_sec: int,
    max_sequence_gap: int,
    min_sampled_events: int,
    max_raw_to_sampled_ratio: float,
    max_depth_stream_share: float,
    max_depth_event_bytes: int,
    lookback_depth_events: int,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_realtime_l2_data_quality.py"),
        "--max-age-sec",
        str(max(30, int(max_age_sec))),
        "--max-sequence-gap",
        str(max(0, int(max_sequence_gap))),
        "--min-sampled-events",
        str(max(0, int(min_sampled_events))),
        "--max-raw-to-sampled-ratio",
        str(max(1.0, float(max_raw_to_sampled_ratio))),
        "--max-depth-stream-share",
        str(max(0.0, min(1.0, float(max_depth_stream_share)))),
        "--max-depth-event-bytes",
        str(max(200, int(max_depth_event_bytes))),
        "--lookback-depth-events",
        str(max(100, int(lookback_depth_events))),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def _run_runtime_performance_budgets_check(
    root: Path,
    *,
    exporter_render_samples: int,
    max_controller_tick_p95_ms: float,
    max_exporter_render_p95_ms: float,
    max_event_store_ingest_p95_ms: float,
    max_source_age_min: float,
) -> tuple[int, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "check_runtime_performance_budgets.py"),
        "--exporter-render-samples",
        str(max(1, int(exporter_render_samples))),
        "--max-controller-tick-p95-ms",
        str(max(0.0, float(max_controller_tick_p95_ms))),
        "--max-exporter-render-p95-ms",
        str(max(0.0, float(max_exporter_render_p95_ms))),
        "--max-event-store-ingest-p95-ms",
        str(max(0.0, float(max_event_store_ingest_p95_ms))),
        "--max-source-age-min",
        str(max(0.0, float(max_source_age_min))),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_build_subprocess_env(root),
        )
        msg = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return int(proc.returncode), msg.strip()
    except Exception as e:
        return 2, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run promotion gate contract checks.")
    live_promotion_mode_default = str(os.getenv("PROMOTION_LIVE_PROMOTION_GATES_MODE", "auto")).strip().lower()
    if live_promotion_mode_default not in {"auto", "on", "off"}:
        live_promotion_mode_default = "auto"
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Max allowed age for fresh reports.")
    parser.add_argument("--require-day2-go", action="store_true", help="Require Day2 gate GO before promotion PASS.")
    parser.add_argument(
        "--require-day2-fresh",
        action="store_true",
        help="Require Day2 gate artifact freshness within --max-report-age-min.",
    )
    parser.add_argument(
        "--require-parity-informative-core",
        action="store_true",
        help="Require parity core metrics (fill/slippage/reject deltas) to be informative for active bots.",
    )
    parser.add_argument(
        "--require-day2-lag-within-tolerance",
        action="store_true",
        help="Require day2 produced-vs-ingested lag to remain within --day2-max-delta.",
    )
    parser.add_argument(
        "--day2-max-delta",
        type=int,
        default=int(os.getenv("DAY2_GATE_MAX_DELTA", "5")),
        help="Max allowed produced-vs-ingested delta for day2 lag checks.",
    )
    parser.add_argument(
        "--attempt-day2-catchup",
        action="store_true",
        help="Run deterministic event-store catch-up steps before evaluating day2 lag gate.",
    )
    parser.add_argument(
        "--attempt-fill-event-backfill",
        action="store_true",
        help="Backfill order_filled events from fills.csv for the current timezone.utc day before replay/parity checks.",
    )
    parser.add_argument(
        "--day2-catchup-cycles",
        type=int,
        default=2,
        help="Number of event-store catch-up cycles when --attempt-day2-catchup is enabled.",
    )
    parser.add_argument(
        "--day2-min-hours",
        type=float,
        default=-1.0,
        help="Optional override for DAY2_GATE_MIN_HOURS when refreshing day2 gate (-1 keeps environment/default).",
    )
    parser.add_argument(
        "--refresh-parity-once",
        action="store_true",
        help="Run one parity cycle before evaluating parity freshness gate.",
    )
    parser.add_argument(
        "--skip-replay-cycle",
        action="store_true",
        help="Skip replay regression cycle execution/check (not recommended).",
    )
    parser.add_argument(
        "--live-promotion-gates-mode",
        choices=["auto", "on", "off"],
        default=live_promotion_mode_default,
        help=(
            "Controls enforcement of live-only promotion gates (trading ladder / portfolio-risk strictness): "
            "auto=enforce only when at least one account_mode=live bot is enabled."
        ),
    )
    parser.add_argument(
        "--refresh-event-integrity-once",
        action="store_true",
        help="Recompute event store integrity from local JSONL before freshness check (no Redis required).",
    )
    parser.add_argument(
        "--tests-runtime",
        choices=["auto", "host", "docker"],
        default="auto",
        help="Runtime passed to run_tests.py. Use 'host' when Docker image is stale (default: auto).",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI-like non-interactive mode: parity + integrity refresh, markdown summary, strict freshness defaults.",
    )
    parser.add_argument(
        "--check-alerting-health",
        action="store_true",
        default=True,
        dest="check_alerting_health",
        help="Run alerting health probe before evaluating alerting_health gate (default: True).",
    )
    parser.add_argument(
        "--no-check-alerting-health",
        action="store_false",
        dest="check_alerting_health",
        help="Skip alerting health probe (use existing last_webhook_sent.json).",
    )
    parser.add_argument(
        "--check-bot-preflight",
        action="store_true",
        help="Run bot startup preflight (env file + CONFIG_PASSWORD in container).",
    )
    parser.add_argument(
        "--check-recon-exchange-preflight",
        action="store_true",
        help="Run reconciliation exchange-source readiness preflight.",
    )
    parser.add_argument(
        "--check-paper-exchange-preflight",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_PREFLIGHT", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run paper-exchange service wiring preflight gate.",
    )
    parser.add_argument(
        "--collect-go-live-evidence",
        action="store_true",
        help="Run go-live checklist evidence collector and enforce artifact gate.",
    )
    parser.add_argument(
        "--check-telegram-validation",
        action="store_true",
        help="Run Telegram alerting validator and enforce diagnosis gate.",
    )
    parser.add_argument(
        "--check-testnet-readiness",
        action="store_true",
        help="Run ROAD-5 testnet readiness gate.",
    )
    parser.add_argument(
        "--check-testnet-daily-scorecard",
        action="store_true",
        help="Run ROAD-5 daily scorecard for timezone.utc today.",
    )
    parser.add_argument(
        "--check-performance-dossier",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PERFORMANCE_DOSSIER", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run strategy performance dossier refresh and enforce rolling expectancy CI gate.",
    )
    parser.add_argument(
        "--no-check-performance-dossier",
        action="store_false",
        dest="check_performance_dossier",
        help="Skip strategy performance dossier gate.",
    )
    parser.add_argument(
        "--performance-dossier-bot-log-root",
        default=os.getenv("PERF_DOSSIER_BOT_LOG_ROOT", "data/bot1/logs/epp_v24/bot1_a"),
        help="Bot log root path used by performance dossier runner.",
    )
    parser.add_argument(
        "--performance-dossier-lookback-days",
        type=int,
        default=int(os.getenv("PERF_DOSSIER_LOOKBACK_DAYS", "7")),
        help="Lookback window in days for performance dossier refresh.",
    )
    parser.add_argument(
        "--check-portfolio-diversification",
        action="store_true",
        help="Run ROAD-9 BTC/ETH diversification evidence check (warning gate).",
    )
    parser.add_argument(
        "--check-data-plane-consistency",
        action="store_true",
        help="Run INFRA-5 data-plane consistency gate (requires desk_snapshot_service running).",
    )
    parser.add_argument(
        "--check-canonical-plane-gates",
        action="store_true",
        default=str(
            os.getenv(
                "PROMOTION_CHECK_CANONICAL_PLANE_GATES",
                "true"
                if str(os.getenv("OPS_DATA_PLANE_MODE", "")).strip().lower() == "db_primary"
                else os.getenv("OPS_DB_READ_PREFERRED", "false"),
            )
        ).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run canonical-plane cutover guardrails (DB freshness/parity/dup suppression/replay lag).",
    )
    parser.add_argument(
        "--no-check-canonical-plane-gates",
        action="store_false",
        dest="check_canonical_plane_gates",
        help="Skip canonical-plane cutover guardrails.",
    )
    parser.add_argument(
        "--canonical-max-db-ingest-age-min",
        type=float,
        default=float(os.getenv("CANONICAL_MAX_DB_INGEST_AGE_MIN", "20")),
        help="Max allowed age (minutes) for ops_db_writer latest artifact in canonical gate.",
    )
    parser.add_argument(
        "--canonical-max-parity-delta-ratio",
        type=float,
        default=float(os.getenv("CANONICAL_MAX_PARITY_DELTA_RATIO", "0.10")),
        help="Max allowed relative DB-vs-CSV parity delta per table for canonical gate.",
    )
    parser.add_argument(
        "--canonical-min-duplicate-suppression-rate",
        type=float,
        default=float(os.getenv("CANONICAL_MIN_DUP_SUPPRESSION_RATE", "0.99")),
        help="Minimum required duplicate suppression rate in canonical gate.",
    )
    parser.add_argument(
        "--canonical-max-replay-lag-delta",
        type=int,
        default=int(os.getenv("CANONICAL_MAX_REPLAY_LAG_DELTA", os.getenv("DAY2_GATE_MAX_DELTA", "5"))),
        help="Max allowed replay lag delta for canonical gate.",
    )
    parser.add_argument(
        "--check-dashboard-readiness",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_DASHBOARD_READINESS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run Grafana dashboard data readiness gate.",
    )
    parser.add_argument(
        "--dashboard-max-data-age-s",
        type=int,
        default=int(os.getenv("DASHBOARD_DATA_MAX_AGE_S", "180")),
        help="Max allowed age (seconds) for Grafana minute/snapshot data readiness checks.",
    )
    parser.add_argument(
        "--dashboard-required-grafana-bot-variants",
        default=os.getenv("DASHBOARD_REQUIRED_BOT_VARIANTS", "bot1:a,bot3:a,bot4:a"),
        help="Required bot:variant list for Grafana readiness check.",
    )
    parser.add_argument(
        "--check-realtime-l2-data-quality",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_REALTIME_L2_DATA_QUALITY", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run realtime/L2 data quality evidence gate (freshness, sequence integrity, sampling, parity, storage).",
    )
    parser.add_argument(
        "--no-check-realtime-l2-data-quality",
        action="store_false",
        dest="check_realtime_l2_data_quality",
        help="Skip realtime/L2 data quality evidence gate.",
    )
    parser.add_argument(
        "--check-runtime-performance-budgets",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_RUNTIME_PERFORMANCE_BUDGETS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run runtime performance budget evidence gate (controller tick, exporter render, event-store ingest).",
    )
    parser.add_argument(
        "--runtime-performance-exporter-render-samples",
        type=int,
        default=int(os.getenv("RUNTIME_PERF_EXPORTER_RENDER_SAMPLES", "5")),
        help="Number of exporter renders to sample when building runtime performance evidence.",
    )
    parser.add_argument(
        "--runtime-performance-max-controller-tick-p95-ms",
        type=float,
        default=float(os.getenv("RUNTIME_PERF_MAX_CONTROLLER_TICK_P95_MS", "250")),
        help="Maximum allowed p95 controller tick duration in runtime performance evidence.",
    )
    parser.add_argument(
        "--runtime-performance-max-exporter-render-p95-ms",
        type=float,
        default=float(os.getenv("RUNTIME_PERF_MAX_EXPORTER_RENDER_P95_MS", "500")),
        help="Maximum allowed p95 exporter render duration in runtime performance evidence.",
    )
    parser.add_argument(
        "--runtime-performance-max-event-store-ingest-p95-ms",
        type=float,
        default=float(os.getenv("RUNTIME_PERF_MAX_EVENT_STORE_INGEST_P95_MS", "250")),
        help="Maximum allowed p95 event-store ingest duration in runtime performance evidence.",
    )
    parser.add_argument(
        "--realtime-l2-max-age-sec",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_AGE_SEC", "180")),
        help="Max allowed age for realtime/L2 evidence artifacts in seconds.",
    )
    parser.add_argument(
        "--realtime-l2-max-sequence-gap",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_SEQUENCE_GAP", "50")),
        help="Max tolerated market_sequence gap before sequence-integrity failure.",
    )
    parser.add_argument(
        "--realtime-l2-min-sampled-events",
        type=int,
        default=int(os.getenv("REALTIME_L2_MIN_SAMPLED_EVENTS", "1")),
        help="Minimum sampled depth events required when raw depth events exist.",
    )
    parser.add_argument(
        "--realtime-l2-max-raw-to-sampled-ratio",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_RAW_TO_SAMPLED_RATIO", "100")),
        help="Maximum allowed raw_depth/sampled_depth ratio for sampling coverage.",
    )
    parser.add_argument(
        "--realtime-l2-max-depth-stream-share",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_DEPTH_STREAM_SHARE", "0.95")),
        help="Maximum allowed share of total event_store volume consumed by depth stream.",
    )
    parser.add_argument(
        "--realtime-l2-max-depth-event-bytes",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_DEPTH_EVENT_BYTES", "4000")),
        help="Maximum payload size budget for observed L2 events.",
    )
    parser.add_argument(
        "--realtime-l2-lookback-events",
        type=int,
        default=int(os.getenv("REALTIME_L2_LOOKBACK_EVENTS", "5000")),
        help="Depth events scanned from event_store JSONL for sequence/storage diagnostics.",
    )
    parser.add_argument(
        "--check-history-rollout-gates",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_HISTORY_ROLLOUT_GATES", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Check shared-history rollout evidence (market_bar_v2 backfill parity and runtime seed health).",
    )
    parser.add_argument(
        "--no-check-history-rollout-gates",
        action="store_false",
        dest="check_history_rollout_gates",
        help="Skip shared-history rollout evidence checks.",
    )
    parser.add_argument(
        "--history-backfill-max-age-min",
        type=float,
        default=float(os.getenv("HISTORY_BACKFILL_MAX_AGE_MIN", "1440")),
        help="Max allowed age (minutes) for market_bar_v2 backfill parity evidence when shared-history reads are enabled.",
    )
    parser.add_argument(
        "--history-seed-max-age-min",
        type=float,
        default=float(os.getenv("HISTORY_SEED_MAX_AGE_MIN", "30")),
        help="Max allowed age (minutes) for latest minute.csv startup history seed evidence when history seeding is enabled.",
    )
    parser.add_argument(
        "--check-paper-exchange-thresholds",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_THRESHOLDS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "Run quantitative paper-exchange threshold evaluator "
            "(reports/verification/paper_exchange_thresholds_latest.json)."
        ),
    )
    parser.add_argument(
        "--check-paper-exchange-golden-path",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_GOLDEN_PATH", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "Run deterministic paper-exchange functional golden-path suite "
            "(reports/verification/paper_exchange_golden_path_latest.json)."
        ),
    )
    parser.add_argument(
        "--no-check-paper-exchange-golden-path",
        action="store_false",
        dest="check_paper_exchange_golden_path",
        help="Skip deterministic paper-exchange functional golden-path suite.",
    )
    parser.add_argument(
        "--paper-exchange-threshold-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_MAX_AGE_MIN", "20")),
        help="Max allowed age (minutes) for paper-exchange threshold input artifact.",
    )
    parser.add_argument(
        "--build-paper-exchange-threshold-inputs",
        action="store_true",
        default=True,
        help="Build threshold input artifact before paper-exchange threshold evaluation.",
    )
    parser.add_argument(
        "--no-build-paper-exchange-threshold-inputs",
        action="store_false",
        dest="build_paper_exchange_threshold_inputs",
        help="Skip threshold input artifact builder (use existing input artifact).",
    )
    parser.add_argument(
        "--paper-exchange-threshold-source-max-age-min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_THRESHOLD_SOURCE_MAX_AGE_MIN", "20")),
        help="Max source artifact age (minutes) used by threshold input builder.",
    )
    parser.add_argument(
        "--paper-exchange-threshold-manual-metrics-path",
        default=os.getenv("PAPER_EXCHANGE_THRESHOLD_MANUAL_METRICS_PATH", ""),
        help=(
            "Optional override path for manual metrics merged by build_paper_exchange_threshold_inputs.py "
            "(defaults to reports/verification/paper_exchange_threshold_metrics_manual.json)."
        ),
    )
    parser.add_argument(
        "--auto-seed-paper-exchange-threshold-manual-metrics",
        action="store_true",
        default=str(os.getenv("PROMOTION_AUTO_SEED_PAPER_EXCHANGE_THRESHOLD_MANUAL_METRICS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Auto-seed manual threshold metrics with default targets when running in non-live scope.",
    )
    parser.add_argument(
        "--no-auto-seed-paper-exchange-threshold-manual-metrics",
        action="store_false",
        dest="auto_seed_paper_exchange_threshold_manual_metrics",
        help="Disable auto-seeding of manual threshold metrics.",
    )
    parser.add_argument(
        "--check-paper-exchange-load",
        action="store_true",
        default=True,
        help="Build paper-exchange load/backpressure evidence before threshold input build.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-load",
        action="store_false",
        dest="check_paper_exchange_load",
        help="Skip paper-exchange load/backpressure evidence generation.",
    )
    parser.add_argument(
        "--run-paper-exchange-load-harness",
        action="store_true",
        default=str(os.getenv("PROMOTION_RUN_PAPER_EXCHANGE_LOAD_HARNESS", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Inject synthetic sync_state command load before paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_DURATION_SEC", "20")),
        help="Duration of synthetic paper-exchange load harness run.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TARGET_CMD_RATE", "60")),
        help="Target sync_state command publish rate for load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_COMMANDS", "300")),
        help="Minimum commands the harness must publish for pass-grade evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", "hb.paper_exchange.command.v1"),
        help="Command stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", "hb.paper_exchange.event.v1"),
        help="Event stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", "hb.paper_exchange.heartbeat.v1"),
        help="Heartbeat stream used by paper-exchange load harness/check.",
    )
    parser.add_argument(
        "--paper-exchange-load-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
        help="Consumer group used by load checker lag/pending diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", ""),
        help="Optional heartbeat metadata consumer_group filter for load checker restart diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-heartbeat-consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", ""),
        help="Optional heartbeat metadata consumer_name filter for load checker restart diagnostics.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-producer",
        default=_default_paper_exchange_harness_producer(),
        help="Producer name emitted by the synthetic load harness.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-instance-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAME", "bot1"),
        help="Instance name used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-instance-names",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_INSTANCE_NAMES", "bot1,bot3,bot4"),
        help="Comma-separated instance names used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-connector-name",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_CONNECTOR_NAME", "bitget_perpetual"),
        help="Connector used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-trading-pair",
        default=os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_TRADING_PAIR", "BTC-USDT"),
        help="Trading pair used in harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-result-timeout-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_RESULT_TIMEOUT_SEC", "30")),
        help="Timeout waiting for command results during harness execution.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-poll-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_POLL_INTERVAL_MS", "300")),
        help="Polling interval for harness result collection.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-scan-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_SCAN_COUNT", "20000")),
        help="Rows scanned by harness when matching command results.",
    )
    parser.add_argument(
        "--paper-exchange-load-harness-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_HARNESS_MIN_INSTANCE_COVERAGE", "1")),
        help="Minimum unique instances that must receive harness commands.",
    )
    parser.add_argument(
        "--paper-exchange-load-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_LOOKBACK_SEC", "600")),
        help="Load-evidence window in seconds for paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SAMPLE_COUNT", "8000")),
        help="Max stream rows sampled by paper-exchange load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-latency-samples",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_LATENCY_SAMPLES", "200")),
        help="Minimum matched command/result samples for pass-grade load evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_WINDOW_SEC", "120")),
        help="Minimum command observation window (seconds) for pass-grade load evidence.",
    )
    parser.add_argument(
        "--paper-exchange-load-sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_SUSTAINED_WINDOW_SEC", "0")),
        help=(
            "Sustained qualification window in seconds for p1_19 load evidence. "
            "When <= 0, checker uses min-window-sec."
        ),
    )
    parser.add_argument(
        "--paper-exchange-load-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_LOAD_MIN_INSTANCE_COVERAGE", "1")),
        help="Minimum unique instance_name coverage required by load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-enforce-budget-checks",
        action="store_true",
        default=str(os.getenv("PAPER_EXCHANGE_LOAD_ENFORCE_BUDGET_CHECKS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Enable fail-fast load budget checks in load validator.",
    )
    parser.add_argument(
        "--no-paper-exchange-load-enforce-budget-checks",
        action="store_false",
        dest="paper_exchange_load_enforce_budget_checks",
        help="Disable fail-fast load budget checks in load validator.",
    )
    parser.add_argument(
        "--paper-exchange-load-min-throughput-cmds-per-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MIN_THROUGHPUT_CMDS_PER_SEC", "50")),
        help="Minimum throughput budget for load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-latency-p95-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P95_MS", "500")),
        help="Maximum p95 latency budget for load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-latency-p99-ms",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_LATENCY_P99_MS", "1000")),
        help="Maximum p99 latency budget for load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-backlog-growth-pct-per-10min",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_BACKLOG_GROWTH_PCT_PER_10MIN", "1")),
        help="Maximum backlog growth budget for load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-max-restart-count",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_LOAD_MAX_RESTART_COUNT", "0")),
        help="Maximum restart-count budget for load checker.",
    )
    parser.add_argument(
        "--paper-exchange-load-run-id",
        default=os.getenv("PAPER_EXCHANGE_LOAD_RUN_ID", ""),
        help="Optional run_id filter for load checker (defaults to latest harness run_id when harness is executed).",
    )
    parser.add_argument(
        "--check-paper-exchange-sustained-qualification",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_SUSTAINED_QUALIFICATION", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Run dedicated sustained (long-window) paper-exchange qualification orchestration.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-sustained-qualification",
        action="store_false",
        dest="check_paper_exchange_sustained_qualification",
        help="Disable sustained paper-exchange qualification orchestration.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-duration-sec",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_DURATION_SEC", "7200")),
        help="Duration for sustained paper-exchange qualification harness.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-target-cmd-rate",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_SUSTAINED_TARGET_CMD_RATE", "60")),
        help="Target command rate for sustained paper-exchange qualification harness.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-min-commands",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_COMMANDS", "0")),
        help="Minimum commands required by sustained harness (<=0 auto-derives from duration * rate).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-command-maxlen",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_COMMAND_MAXLEN", "0")),
        help="Sustained harness command stream maxlen (<=0 auto-derives sustained-safe size).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-min-instance-coverage",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_MIN_INSTANCE_COVERAGE", "3")),
        help="Minimum unique instance coverage required in sustained qualification.",
    )
    parser.add_argument(
        "--paper-exchange-sustained-lookback-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_LOOKBACK_SEC", "0")),
        help="Sustained load-check lookback window (<=0 auto-derives as duration + 600s).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-sample-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_SAMPLE_COUNT", "0")),
        help="Sustained load-check sample count (<=0 auto-derives sustained-safe size).",
    )
    parser.add_argument(
        "--paper-exchange-sustained-window-sec",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_SUSTAINED_WINDOW_SEC", "0")),
        help="Sustained load-check qualification window in seconds (<=0 uses duration).",
    )
    parser.add_argument(
        "--capture-paper-exchange-perf-baseline",
        action="store_true",
        default=str(os.getenv("PROMOTION_CAPTURE_PAPER_EXCHANGE_PERF_BASELINE", "false")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Capture current paper-exchange load artifact as baseline before regression checks.",
    )
    parser.add_argument(
        "--no-capture-paper-exchange-perf-baseline",
        action="store_false",
        dest="capture_paper_exchange_perf_baseline",
        help="Do not capture paper-exchange perf baseline in this run.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-source-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_SOURCE_PATH", "reports/verification/paper_exchange_load_latest.json"),
        help="Source report path used when capturing paper-exchange perf baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-profile-label",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PROFILE_LABEL", ""),
        help="Optional profile label attached to captured paper-exchange baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-require-source-pass",
        action="store_true",
        default=str(os.getenv("PAPER_EXCHANGE_PERF_BASELINE_REQUIRE_SOURCE_PASS", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Require source report status=pass when capturing paper-exchange perf baseline.",
    )
    parser.add_argument(
        "--no-paper-exchange-perf-baseline-require-source-pass",
        action="store_false",
        dest="paper_exchange_perf_baseline_require_source_pass",
        help="Allow baseline capture from non-pass source report.",
    )
    parser.add_argument(
        "--check-paper-exchange-perf-regression",
        action="store_true",
        default=str(os.getenv("PROMOTION_CHECK_PAPER_EXCHANGE_PERF_REGRESSION", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        help="Compare current paper-exchange load metrics against baseline regression budgets.",
    )
    parser.add_argument(
        "--no-check-paper-exchange-perf-regression",
        action="store_false",
        dest="check_paper_exchange_perf_regression",
        help="Disable paper-exchange performance regression guard.",
    )
    parser.add_argument(
        "--paper-exchange-perf-current-report-path",
        default=os.getenv("PAPER_EXCHANGE_LOAD_REPORT_PATH", "reports/verification/paper_exchange_load_latest.json"),
        help="Current load report path used by perf regression guard.",
    )
    parser.add_argument(
        "--paper-exchange-perf-baseline-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_BASELINE_PATH", "reports/verification/paper_exchange_load_baseline_latest.json"),
        help="Baseline load report path used by perf regression guard.",
    )
    parser.add_argument(
        "--paper-exchange-perf-waiver-path",
        default=os.getenv("PAPER_EXCHANGE_PERF_WAIVER_PATH", "reports/verification/paper_exchange_perf_regression_waiver_latest.json"),
        help="Optional waiver artifact path for temporary approved degradation.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-latency-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_LATENCY_REGRESSION_PCT", "20")),
        help="Maximum latency regression percent tolerated versus baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-backlog-regression-pct",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_BACKLOG_REGRESSION_PCT", "25")),
        help="Maximum backlog growth regression percent tolerated versus baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-min-throughput-ratio",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MIN_THROUGHPUT_RATIO", "0.85")),
        help="Minimum required throughput ratio current/baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-max-restart-regression",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_MAX_RESTART_REGRESSION", "0")),
        help="Maximum allowed restart-count increase over baseline.",
    )
    parser.add_argument(
        "--paper-exchange-perf-waiver-max-hours",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_PERF_WAIVER_MAX_HOURS", "24")),
        help="Maximum allowed waiver validity window (hours).",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports = root / "reports"
    live_account_mode_bots = _live_account_mode_bots(root)
    enabled_policy_bots = _enabled_policy_bots(root)
    live_promotion_required_auto = len(live_account_mode_bots) > 0
    live_gates_mode = str(args.live_promotion_gates_mode).strip().lower()
    if live_gates_mode == "on":
        enforce_live_promotion_gates = True
    elif live_gates_mode == "off":
        enforce_live_promotion_gates = False
    else:
        enforce_live_promotion_gates = live_promotion_required_auto

    checks: list[dict[str, object]] = []
    critical_failures: list[str] = []
    parity_refresh_rc = 0
    parity_refresh_msg = ""
    integrity_refresh_rc = 0
    integrity_refresh_msg = ""
    alerting_health_rc = 0
    alerting_health_msg = ""
    recon_preflight_rc = 0
    recon_preflight_msg = ""
    paper_exchange_preflight_rc = 0
    paper_exchange_preflight_msg = ""
    checklist_evidence_rc = 0
    checklist_evidence_msg = ""
    telegram_validation_rc = 0
    telegram_validation_msg = ""
    testnet_readiness_rc = 0
    testnet_readiness_msg = ""
    testnet_scorecard_rc = 0
    testnet_scorecard_msg = ""
    testnet_multi_day_summary_rc = 0
    testnet_multi_day_summary_msg = ""
    performance_dossier_rc = 0
    performance_dossier_msg = ""
    performance_dossier_diag: dict[str, object] = _performance_dossier_expectancy_diag({})
    diversification_rc = 0
    diversification_msg = ""
    road9_rebalance_rc = 0
    road9_rebalance_msg = ""
    paper_exchange_load_harness_rc = 0
    paper_exchange_load_harness_msg = ""
    paper_exchange_load_harness_auto_run = False
    paper_exchange_load_harness_duration_sec_effective = float(args.paper_exchange_load_harness_duration_sec)
    paper_exchange_load_min_window_sec_effective = int(args.paper_exchange_load_min_window_sec)
    paper_exchange_load_sustained_window_sec_effective = int(args.paper_exchange_load_sustained_window_sec)
    paper_exchange_load_rc = 0
    paper_exchange_load_msg = ""
    paper_exchange_load_run_id = ""
    paper_exchange_sustained_qualification_rc = 0
    paper_exchange_sustained_qualification_msg = ""
    paper_exchange_perf_baseline_capture_rc = 0
    paper_exchange_perf_baseline_capture_msg = ""
    paper_exchange_perf_regression_rc = 0
    paper_exchange_perf_regression_msg = ""
    paper_exchange_threshold_inputs_rc = 0
    paper_exchange_threshold_inputs_msg = ""
    paper_exchange_thresholds_rc = 0
    paper_exchange_thresholds_msg = ""
    paper_exchange_golden_path_rc = 0
    paper_exchange_golden_path_msg = ""
    paper_exchange_threshold_inputs_path = reports / "verification" / "paper_exchange_threshold_inputs_latest.json"
    paper_exchange_threshold_inputs_diag: dict[str, object] = _paper_exchange_threshold_inputs_readiness({})
    paper_exchange_threshold_inputs_ready = False
    paper_exchange_threshold_manual_metrics_path = _resolve_threshold_manual_metrics_path(
        root, str(args.paper_exchange_threshold_manual_metrics_path)
    )
    paper_exchange_threshold_manual_metrics_seeded = False
    paper_exchange_threshold_source_max_age_min_effective = float(args.paper_exchange_threshold_source_max_age_min)
    canonical_gate_rc = 0
    canonical_gate_msg = ""
    day2_catchup_rc = 0
    day2_catchup_msg = ""
    fill_backfill_rc = 0
    fill_backfill_msg = ""
    recon_refresh_rc = 0
    recon_refresh_msg = ""
    dashboard_readiness_rc = 0
    dashboard_readiness_msg = ""
    realtime_l2_data_quality_rc = 0
    realtime_l2_data_quality_msg = ""
    runtime_performance_budgets_rc = 0
    runtime_performance_budgets_msg = ""
    history_read_rollout_enabled = _history_read_rollout_enabled()
    history_seed_enabled = _safe_bool(os.getenv("HB_HISTORY_SEED_ENABLED"), default=False)
    history_backfill_diag: dict[str, object] = {}
    history_seed_diag: dict[str, object] = {}
    ops_db_writer_refresh_rc = 0
    ops_db_writer_refresh_msg = ""

    max_report_age_min = float(args.max_report_age_min)
    refresh_parity_once = bool(args.refresh_parity_once or args.ci)
    refresh_event_integrity_once = bool(args.refresh_event_integrity_once or args.ci)
    if args.ci and args.max_report_age_min == 20:
        max_report_age_min = 15.0

    if refresh_parity_once:
        parity_refresh_rc, parity_refresh_msg = _refresh_parity_once(root)

    if refresh_event_integrity_once:
        integrity_refresh_rc, integrity_refresh_msg = _refresh_event_store_integrity_once(root)

    attempt_fill_event_backfill = bool(args.attempt_fill_event_backfill or args.ci)
    if attempt_fill_event_backfill:
        fill_backfill_rc, fill_backfill_msg = _run_fill_event_backfill_once(
            root, day_utc=datetime.now(UTC).date().isoformat()
        )

    day2_min_hours_override = float(args.day2_min_hours)
    if day2_min_hours_override < 0 and args.ci:
        day2_min_hours_override = 0.0

    if args.attempt_day2_catchup:
        day2_catchup_rc, day2_catchup_msg = _attempt_day2_catchup(
            root,
            cycles=int(args.day2_catchup_cycles),
            day2_min_hours_override=day2_min_hours_override,
            day2_max_delta_override=int(args.day2_max_delta),
        )

    if args.check_recon_exchange_preflight:
        recon_refresh_rc, recon_refresh_msg = _refresh_reconciliation_exchange_once(root)

    if args.check_alerting_health:
        alerting_health_rc, alerting_health_msg = _run_alerting_health_check(root, strict=bool(args.ci))

    if args.check_dashboard_readiness:
        dashboard_readiness_rc, dashboard_readiness_msg = _run_dashboard_readiness_check(
            root,
            max_data_age_s=int(max(60, int(args.dashboard_max_data_age_s))),
            required_grafana_bot_variants=str(args.dashboard_required_grafana_bot_variants),
        )
    if args.check_realtime_l2_data_quality:
        realtime_l2_data_quality_rc, realtime_l2_data_quality_msg = _run_realtime_l2_data_quality_check(
            root,
            max_age_sec=int(args.realtime_l2_max_age_sec),
            max_sequence_gap=int(args.realtime_l2_max_sequence_gap),
            min_sampled_events=int(args.realtime_l2_min_sampled_events),
            max_raw_to_sampled_ratio=float(args.realtime_l2_max_raw_to_sampled_ratio),
            max_depth_stream_share=float(args.realtime_l2_max_depth_stream_share),
            max_depth_event_bytes=int(args.realtime_l2_max_depth_event_bytes),
            lookback_depth_events=int(args.realtime_l2_lookback_events),
        )
    if args.check_runtime_performance_budgets:
        runtime_performance_budgets_rc, runtime_performance_budgets_msg = _run_runtime_performance_budgets_check(
            root,
            exporter_render_samples=int(args.runtime_performance_exporter_render_samples),
            max_controller_tick_p95_ms=float(args.runtime_performance_max_controller_tick_p95_ms),
            max_exporter_render_p95_ms=float(args.runtime_performance_max_exporter_render_p95_ms),
            max_event_store_ingest_p95_ms=float(args.runtime_performance_max_event_store_ingest_p95_ms),
            max_source_age_min=float(args.max_report_age_min),
        )
    if args.check_canonical_plane_gates:
        canonical_gate_rc, canonical_gate_msg = _run_canonical_plane_gate(
            root,
            max_db_ingest_age_min=float(args.canonical_max_db_ingest_age_min),
            max_parity_delta_ratio=float(args.canonical_max_parity_delta_ratio),
            min_duplicate_suppression_rate=float(args.canonical_min_duplicate_suppression_rate),
            max_replay_lag_delta=int(args.canonical_max_replay_lag_delta),
        )

    # 1) Preflight checks
    required_files = [
        root / "config" / "reconciliation_thresholds.json",
        root / "config" / "parity_thresholds.json",
        root / "config" / "portfolio_limits_v1.json",
        root / "config" / "multi_bot_policy_v1.json",
        root / "scripts" / "release" / "run_backtest_regression.py",
        root / "scripts" / "release" / "run_replay_regression_cycle.py",
        root / "scripts" / "release" / "run_replay_regression_multi_window.py",
        root / "scripts" / "release" / "check_multi_bot_policy.py",
        root / "scripts" / "release" / "check_strategy_catalog_consistency.py",
        root / "scripts" / "release" / "check_coordination_policy.py",
        root / "scripts" / "release" / "run_tests.py",
        root / "scripts" / "release" / "run_secrets_hygiene_check.py",
        root / "scripts" / "release" / "check_ml_signal_governance.py",
        root / "scripts" / "release" / "check_accounting_integrity_v2.py",
        root / "scripts" / "release" / "check_market_data_freshness.py",
        root / "scripts" / "release" / "check_alerting_health.py",
        root / "scripts" / "release" / "check_realtime_l2_data_quality.py",
        root / "scripts" / "release" / "check_canonical_plane_gate.py",
        root / "scripts" / "release" / "run_paper_exchange_load_harness.py",
        root / "scripts" / "release" / "check_paper_exchange_load.py",
        root / "scripts" / "release" / "check_paper_exchange_perf_regression.py",
        root / "scripts" / "release" / "run_paper_exchange_golden_path.py",
        root / "scripts" / "release" / "build_paper_exchange_threshold_inputs.py",
        root / "scripts" / "release" / "check_paper_exchange_thresholds.py",
        root / "scripts" / "ops" / "preflight_startup.py",
        root / "scripts" / "ops" / "preflight_paper_exchange.py",
        root / "scripts" / "ops" / "checklist_evidence_collector.py",
        root / "scripts" / "ops" / "validate_telegram_alerting.py",
        root / "scripts" / "ops" / "verify_dashboard.py",
        root / "scripts" / "release" / "testnet_readiness_gate.py",
        root / "scripts" / "analysis" / "testnet_daily_scorecard.py",
        root / "scripts" / "analysis" / "performance_dossier.py",
        root / "scripts" / "analysis" / "portfolio_diversification_check.py",
        root / "scripts" / "utils" / "refresh_event_store_integrity_local.py",
        root / "config" / "coordination_policy_v1.json",
        root / "config" / "ml_governance_policy_v1.json",
        root / "docs" / "validation" / "backtest_regression_spec.md",
    ]
    preflight_ok = all(p.exists() for p in required_files)
    checks.append(
        _check(
            preflight_ok,
            "preflight_checks",
            "critical",
            "required files present" if preflight_ok else "missing required config/spec/script files",
            [str(p) for p in required_files],
        )
    )

    # 1b) Bot startup preflight (env + CONFIG_PASSWORD) — when --check-bot-preflight
    if args.check_bot_preflight:
        preflight_rc, preflight_msg = _run_bot_preflight_check(root, require_container=args.ci)
        preflight_ok = preflight_rc == 0
        checks.append(
            _check(
                preflight_ok,
                "bot_startup_preflight",
                "critical",
                "env file + CONFIG_PASSWORD in bot container OK" if preflight_ok else f"preflight failed: {preflight_msg[:200]}",
                [str(root / "scripts" / "ops" / "preflight_startup.py")],
            )
        )
        if not preflight_ok:
            critical_failures.append("bot_startup_preflight")

    # 1c) Reconciliation exchange-source readiness
    if args.check_recon_exchange_preflight:
        recon_preflight_rc, recon_preflight_msg = _run_recon_exchange_preflight_check(root)
        recon_preflight_ok = recon_preflight_rc == 0
        checks.append(
            _check(
                recon_preflight_ok,
                "recon_exchange_live_gate",
                "critical",
                "reconciliation exchange-source readiness PASS"
                if recon_preflight_ok
                else f"reconciliation exchange-source preflight failed (rc={recon_preflight_rc})",
                [str(root / "reports" / "ops" / "preflight_recon_latest.json")],
            )
        )
        if not recon_preflight_ok:
            critical_failures.append("recon_exchange_live_gate")

    # 1d) Paper exchange preflight
    if args.check_paper_exchange_preflight:
        paper_exchange_preflight_rc, paper_exchange_preflight_msg = _run_paper_exchange_preflight_check(
            root, strict=bool(args.ci)
        )
        pe_preflight_path = root / "reports" / "ops" / "preflight_paper_exchange_latest.json"
        pe_preflight_report = _read_json(pe_preflight_path, {})
        pe_preflight_ok = (
            paper_exchange_preflight_rc == 0
            and str(pe_preflight_report.get("status", "fail")).strip().lower() == "pass"
        )
        checks.append(
            _check(
                pe_preflight_ok,
                "paper_exchange_preflight",
                "critical",
                "paper-exchange preflight PASS"
                if pe_preflight_ok
                else f"paper-exchange preflight failed (rc={paper_exchange_preflight_rc})",
                [str(pe_preflight_path)],
            )
        )
        if not pe_preflight_ok:
            critical_failures.append("paper_exchange_preflight")

    # 1e) Go-live checklist evidence collector
    if args.collect_go_live_evidence:
        checklist_evidence_rc, checklist_evidence_msg = _run_checklist_evidence_collector(root)
        evidence_path = root / "reports" / "ops" / "go_live_checklist_evidence_latest.json"
        evidence_report = _read_json(evidence_path, {})
        evidence_status = str(evidence_report.get("overall_status", "fail"))
        evidence_ok = checklist_evidence_rc == 0 and evidence_status in {"pass", "in_progress"}
        checks.append(
            _check(
                evidence_ok,
                "go_live_checklist_evidence_gate",
                "critical",
                f"go-live checklist evidence collected (status={evidence_status})"
                if evidence_ok
                else f"go-live checklist evidence failed (rc={checklist_evidence_rc}, status={evidence_status})",
                [str(evidence_path), str(root / "docs" / "ops" / "go_live_hardening_checklist.md")],
            )
        )
        if not evidence_ok:
            critical_failures.append("go_live_checklist_evidence_gate")

    # 1f) Telegram validation evidence
    if args.check_telegram_validation:
        telegram_validation_rc, telegram_validation_msg = _run_telegram_validation(root, strict=bool(args.ci))
        telegram_path = root / "reports" / "ops" / "telegram_validation_latest.json"
        telegram_report = _read_json(telegram_path, {})
        telegram_ok = telegram_validation_rc == 0 and str(telegram_report.get("status", "error")) == "ok"
        checks.append(
            _check(
                telegram_ok,
                "telegram_alerting_gate",
                "critical",
                "telegram alerting validation PASS"
                if telegram_ok
                else f"telegram alerting validation failed (rc={telegram_validation_rc}, diagnosis={telegram_report.get('diagnosis', 'unknown')})",
                [str(telegram_path)],
            )
        )
        if not telegram_ok:
            critical_failures.append("telegram_alerting_gate")

    # 1g) ROAD-5 testnet readiness gate
    if args.check_testnet_readiness:
        testnet_readiness_rc, testnet_readiness_msg = _run_testnet_readiness_gate(root, strict=bool(args.ci))
        testnet_ready_path = root / "reports" / "ops" / "testnet_readiness_latest.json"
        testnet_ready = _read_json(testnet_ready_path, {})
        testnet_ready_ok = testnet_readiness_rc == 0 and str(testnet_ready.get("status", "fail")) == "pass"
        checks.append(
            _check(
                testnet_ready_ok,
                "testnet_readiness_gate",
                "warning",
                "testnet readiness PASS" if testnet_ready_ok else "testnet readiness not yet pass",
                [str(testnet_ready_path)],
            )
        )

    # 1h) ROAD-5 daily scorecard
    if args.check_testnet_daily_scorecard:
        day_utc = datetime.now(UTC).strftime("%Y-%m-%d")
        testnet_scorecard_rc, testnet_scorecard_msg = _run_testnet_daily_scorecard(root, day_utc=day_utc)
        testnet_score_path = root / "reports" / "strategy" / "testnet_daily_scorecard_latest.json"
        testnet_score = _read_json(testnet_score_path, {})
        testnet_score_ok = testnet_scorecard_rc == 0 and str(testnet_score.get("status", "fail")) == "pass"
        checks.append(
            _check(
                testnet_score_ok,
                "testnet_daily_scorecard",
                "warning",
                f"testnet daily scorecard PASS ({day_utc})"
                if testnet_score_ok
                else f"testnet daily scorecard not pass ({day_utc})",
                [str(testnet_score_path)],
            )
        )

        # Aggregate rolling ROAD-5 window for deterministic ladder evidence.
        testnet_multi_day_summary_rc, testnet_multi_day_summary_msg = _run_testnet_multi_day_summary(
            root,
            end_day_utc=day_utc,
            window_days=28,
        )
        testnet_multi_day_path = root / "reports" / "strategy" / "testnet_multi_day_summary_latest.json"
        testnet_multi_day = _read_json(testnet_multi_day_path, {})
        road5_gate_raw = testnet_multi_day.get("road5_gate", {})
        road5_gate = road5_gate_raw if isinstance(road5_gate_raw, dict) else {}
        road5_gate_pass = bool(road5_gate.get("pass", False))
        road5_coverage_days = int(testnet_multi_day.get("coverage_days", 0) or 0)
        road5_trading_days = int(testnet_multi_day.get("trading_days_count", 0) or 0)
        testnet_multi_day_ok = testnet_multi_day_summary_rc == 0 and road5_gate_pass
        checks.append(
            _check(
                testnet_multi_day_ok,
                "testnet_multi_day_summary",
                "warning",
                (
                    "testnet multi-day summary PASS "
                    f"(coverage_days={road5_coverage_days}, trading_days={road5_trading_days})"
                )
                if testnet_multi_day_ok
                else (
                    "testnet multi-day summary not pass "
                    f"(coverage_days={road5_coverage_days}, trading_days={road5_trading_days}, "
                    f"rc={testnet_multi_day_summary_rc})"
                ),
                [str(testnet_multi_day_path)],
            )
        )

    # 1i) Strategy profitability confidence gate (rolling expectancy CI)
    if args.check_performance_dossier:
        performance_dossier_rc, performance_dossier_msg = _run_performance_dossier(
            root,
            bot_log_root=str(args.performance_dossier_bot_log_root),
            lookback_days=int(args.performance_dossier_lookback_days),
        )
        performance_dossier_path = reports / "analysis" / "performance_dossier_latest.json"
        performance_dossier_report = _read_json(performance_dossier_path, {})
        performance_dossier_diag = _performance_dossier_expectancy_diag(performance_dossier_report)
        performance_dossier_ok = (
            performance_dossier_rc == 0
            and bool(performance_dossier_diag.get("summary_present", False))
            and bool(performance_dossier_diag.get("gate_pass", False))
        )
        checks.append(
            _check(
                performance_dossier_ok,
                "performance_dossier_expectancy_ci",
                "critical",
                str(performance_dossier_diag.get("reason", "performance dossier diagnostics unavailable")),
                [
                    str(performance_dossier_path),
                    str(root / "scripts" / "analysis" / "performance_dossier.py"),
                ],
            )
        )
        if not performance_dossier_ok:
            critical_failures.append("performance_dossier_expectancy_ci")

    # 1j) ROAD-9 diversification evidence (BTC vs ETH correlation + inverse-variance weights)
    if args.check_portfolio_diversification:
        diversification_rc, diversification_msg = _run_portfolio_diversification_check(root)
        diversification_path = reports / "policy" / "portfolio_diversification_latest.json"
        diversification_report = _read_json(diversification_path, {})
        div_gate_ok, div_reason = _portfolio_diversification_gate(diversification_report)
        if diversification_rc != 0 and str(diversification_report.get("status", "")).lower() != "fail":
            div_gate_ok = False
            div_reason = f"portfolio diversification check execution failed (rc={diversification_rc})"
        checks.append(
            _check(
                div_gate_ok,
                "portfolio_diversification",
                "warning",
                div_reason,
                [str(diversification_path)],
            )
        )
        road9_rebalance_rc, road9_rebalance_msg = _run_road9_allocation_rebalance(root)
        road9_rebalance_path = reports / "policy" / "road9_allocation_latest.json"
        road9_rebalance_report = _read_json(road9_rebalance_path, {})
        road9_plan_raw = road9_rebalance_report.get("plan", {})
        road9_plan = road9_plan_raw if isinstance(road9_plan_raw, dict) else {}
        road9_plan_ready = bool(road9_plan.get("plan_ready", False))
        road9_ok = road9_rebalance_rc == 0 and road9_plan_ready
        checks.append(
            _check(
                road9_ok,
                "road9_allocation_rebalance",
                "warning",
                "ROAD-9 allocation rebalance plan ready"
                if road9_ok
                else "ROAD-9 allocation rebalance plan missing/not-ready",
                [str(road9_rebalance_path), str(root / "config" / "multi_bot_policy_v1.json")],
            )
        )

    # 1k) INFRA-5 data-plane consistency gate
    if args.check_data_plane_consistency:
        dp_rc, dp_msg = _run_data_plane_consistency_check(root)
        dp_path = reports / "data_plane_consistency" / "latest.json"
        dp_report = _read_json(dp_path, {})
        dp_ok = dp_rc == 0 and str(dp_report.get("status", "FAIL")) == "PASS"
        checks.append(
            _check(
                dp_ok,
                "data_plane_consistency",
                "warning",
                "data-plane consistency PASS (snapshot fresh + complete for all bots)"
                if dp_ok
                else f"data-plane consistency check failed (rc={dp_rc}): {dp_msg[:200]}",
                [str(dp_path)],
            )
        )

    # 1l) Grafana dashboard data readiness gate
    if args.check_dashboard_readiness:
        dashboard_path = reports / "ops" / "dashboard_data_ready_latest.json"
        dashboard_report = _read_json(dashboard_path, {})
        dashboard_ok = (
            dashboard_readiness_rc == 0
            and str(dashboard_report.get("status", "fail")).strip().lower() == "pass"
        )
        dashboard_gate_enforced = bool(enforce_live_promotion_gates)
        checks.append(
            _check(
                dashboard_ok,
                "dashboard_data_ready",
                "critical" if dashboard_gate_enforced else "warning",
                "Grafana dashboard data readiness PASS"
                if dashboard_ok
                else (
                    f"dashboard readiness failed (rc={dashboard_readiness_rc})"
                    if dashboard_gate_enforced
                    else f"dashboard readiness failed (warning-only non-live scope, rc={dashboard_readiness_rc})"
                ),
                [str(dashboard_path), str(root / "scripts" / "ops" / "verify_dashboard.py")],
            )
        )
        if dashboard_gate_enforced and not dashboard_ok:
            critical_failures.append("dashboard_data_ready")

    # 1m) Realtime + L2 quality gate
    if args.check_realtime_l2_data_quality:
        realtime_l2_candidates = [reports / "verification" / "realtime_l2_data_quality_latest.json"]
        realtime_l2_candidates.extend(sorted((reports / "verification").glob("realtime_l2_data_quality_*.json")))
        realtime_l2_path, realtime_l2_report, realtime_l2_age_min = _freshest_report(realtime_l2_candidates)
        realtime_l2_status = str(realtime_l2_report.get("status", "fail")).strip().lower()
        realtime_l2_fresh = realtime_l2_age_min <= max_report_age_min
        realtime_l2_ok = realtime_l2_data_quality_rc == 0 and realtime_l2_status == "pass" and realtime_l2_fresh
        checks.append(
            _check(
                realtime_l2_ok,
                "realtime_l2_data_quality",
                "critical",
                "realtime/L2 data quality PASS (freshness + sequence + sampling + parity + storage budget)"
                if realtime_l2_ok
                else (
                    f"realtime/L2 data quality stale evidence selected (age_min={realtime_l2_age_min:.2f})"
                    if realtime_l2_status == "pass" and not realtime_l2_fresh
                    else (
                        "realtime/L2 data quality failed "
                        f"(status={realtime_l2_status or 'unknown'}, rc={realtime_l2_data_quality_rc})"
                    )
                ),
                [str(realtime_l2_path), str(root / "scripts" / "release" / "check_realtime_l2_data_quality.py")],
            )
        )
        if not realtime_l2_ok:
            critical_failures.append("realtime_l2_data_quality")

    # 1n) Runtime performance budgets gate
    if args.check_runtime_performance_budgets:
        runtime_perf_path = reports / "verification" / "runtime_performance_budgets_latest.json"
        runtime_perf_report = _read_json(runtime_perf_path, {})
        runtime_perf_status = str(runtime_perf_report.get("status", "fail")).strip().lower()
        runtime_perf_ok = runtime_performance_budgets_rc == 0 and runtime_perf_status == "pass"
        checks.append(
            _check(
                runtime_perf_ok,
                "runtime_performance_budgets",
                "warning",
                "runtime performance budgets PASS (controller tick + exporter render + event-store ingest)"
                if runtime_perf_ok
                else f"runtime performance budgets failed (status={runtime_perf_status or 'unknown'}, rc={runtime_performance_budgets_rc})",
                [str(runtime_perf_path), str(root / "scripts" / "release" / "check_runtime_performance_budgets.py")],
            )
        )

    # 1m.1) Shared-history rollout gates
    if args.check_history_rollout_gates:
        history_backfill_path = reports / "ops" / "market_bar_v2_backfill_latest.json"
        history_backfill_report = _read_json(history_backfill_path, {})
        history_backfill_diag = _history_backfill_gate_status(
            history_backfill_report,
            history_backfill_path,
            enforced=bool(history_read_rollout_enabled),
            max_age_min=float(args.history_backfill_max_age_min),
        )
        checks.append(
            _check(
                bool(history_backfill_diag.get("ready", False)),
                "history_market_bar_v2_backfill",
                "critical" if history_read_rollout_enabled else "warning",
                str(history_backfill_diag.get("reason", "")),
                [str(history_backfill_path), str(root / "scripts" / "ops" / "backfill_market_bar_v2.py")],
            )
        )

        history_seed_diag = _history_seed_rollout_status(
            root / "data",
            enabled=bool(history_seed_enabled),
            max_age_min=float(args.history_seed_max_age_min),
            allowed_bots=set(enabled_policy_bots) if enabled_policy_bots else None,
        )
        history_seed_evidence = [str(root / "data")]
        history_seed_evidence.extend(
            [
                str(path)
                for path in history_seed_diag.get("evidence_paths", [])
                if isinstance(path, str) and path.strip()
            ][:10]
        )
        checks.append(
            _check(
                bool(history_seed_diag.get("ready", False)),
                "history_seed_rollout",
                "critical" if history_seed_enabled else "warning",
                str(history_seed_diag.get("reason", "")),
                history_seed_evidence,
            )
        )

    # 1n) Functional paper-exchange golden-path certification gate
    if args.check_paper_exchange_golden_path:
        paper_exchange_golden_path_rc, paper_exchange_golden_path_msg = _run_paper_exchange_golden_path_check(
            root, strict=bool(args.ci)
        )
        pe_golden_path_path = reports / "verification" / "paper_exchange_golden_path_latest.json"
        pe_golden_path_report = _read_json(pe_golden_path_path, {})
        pe_golden_path_status = str(pe_golden_path_report.get("status", "")).strip().lower()
        pe_golden_path_failed_categories = pe_golden_path_report.get("failed_remediation_categories", [])
        if not isinstance(pe_golden_path_failed_categories, list):
            pe_golden_path_failed_categories = []
        failed_categories_text = ",".join(str(x) for x in pe_golden_path_failed_categories if str(x).strip())
        pe_golden_path_ok = paper_exchange_golden_path_rc == 0 and pe_golden_path_status == "pass"
        checks.append(
            _check(
                pe_golden_path_ok,
                "paper_exchange_functional_golden_path",
                "critical",
                "paper-exchange functional golden-path suite PASS"
                if pe_golden_path_ok
                else (
                    "paper-exchange functional golden-path suite failed "
                    f"(status={pe_golden_path_status or 'unknown'}, rc={paper_exchange_golden_path_rc}, "
                    f"failed_categories={failed_categories_text or 'n/a'})"
                ),
                [str(pe_golden_path_path), str(root / "scripts" / "release" / "run_paper_exchange_golden_path.py")],
            )
        )
        if not pe_golden_path_ok:
            critical_failures.append("paper_exchange_functional_golden_path")

    # 1o) Quantitative paper-exchange threshold gate
    if args.check_paper_exchange_thresholds:
        auto_run_load_harness_in_ci = bool(args.ci and not args.run_paper_exchange_load_harness)
        paper_exchange_load_harness_auto_run = bool(auto_run_load_harness_in_ci)
        run_paper_exchange_load_harness = bool(
            args.check_paper_exchange_load and (args.run_paper_exchange_load_harness or auto_run_load_harness_in_ci)
        )
        paper_exchange_load_harness_duration_sec_effective = float(args.paper_exchange_load_harness_duration_sec)
        paper_exchange_load_min_window_sec_effective = int(args.paper_exchange_load_min_window_sec)
        paper_exchange_load_sustained_window_sec_effective = int(args.paper_exchange_load_sustained_window_sec)
        if auto_run_load_harness_in_ci and bool(enforce_live_promotion_gates):
            # Ensure the generated sample window can satisfy strict load-gate minimum windows.
            paper_exchange_load_harness_duration_sec_effective = max(
                paper_exchange_load_harness_duration_sec_effective,
                float(max(120, int(args.paper_exchange_load_min_window_sec), int(args.paper_exchange_load_sustained_window_sec))),
            )
        if auto_run_load_harness_in_ci and not bool(enforce_live_promotion_gates):
            # Non-live strict runs keep short-window load profiles aligned with baseline captures.
            non_live_window_sec = max(20, int(round(paper_exchange_load_harness_duration_sec_effective)))
            paper_exchange_load_min_window_sec_effective = max(
                1,
                min(int(args.paper_exchange_load_min_window_sec), non_live_window_sec),
            )
            if int(args.paper_exchange_load_sustained_window_sec) > 0:
                paper_exchange_load_sustained_window_sec_effective = max(
                    1,
                    min(int(args.paper_exchange_load_sustained_window_sec), non_live_window_sec),
                )
            else:
                paper_exchange_load_sustained_window_sec_effective = int(non_live_window_sec)
        if run_paper_exchange_load_harness:
            paper_exchange_load_harness_rc, paper_exchange_load_harness_msg = _run_paper_exchange_load_harness(
                root,
                strict=False,
                duration_sec=paper_exchange_load_harness_duration_sec_effective,
                target_cmd_rate=float(args.paper_exchange_load_harness_target_cmd_rate),
                min_commands=int(args.paper_exchange_load_harness_min_commands),
                command_stream=str(args.paper_exchange_load_command_stream),
                event_stream=str(args.paper_exchange_load_event_stream),
                heartbeat_stream=str(args.paper_exchange_load_heartbeat_stream),
                producer=str(args.paper_exchange_load_harness_producer),
                instance_name=str(args.paper_exchange_load_harness_instance_name),
                instance_names=str(args.paper_exchange_load_harness_instance_names),
                connector_name=str(args.paper_exchange_load_harness_connector_name),
                trading_pair=str(args.paper_exchange_load_harness_trading_pair),
                min_instance_coverage=int(args.paper_exchange_load_harness_min_instance_coverage),
                result_timeout_sec=float(args.paper_exchange_load_harness_result_timeout_sec),
                poll_interval_ms=int(args.paper_exchange_load_harness_poll_interval_ms),
                scan_count=int(args.paper_exchange_load_harness_scan_count),
            )
            pe_harness_path = reports / "verification" / "paper_exchange_load_harness_latest.json"
            pe_harness_report = _read_json(pe_harness_path, {})
            pe_harness_diag = pe_harness_report.get("diagnostics", {})
            pe_harness_diag = pe_harness_diag if isinstance(pe_harness_diag, dict) else {}
            paper_exchange_load_run_id = str(pe_harness_diag.get("run_id", "")).strip()
            pe_harness_ok = (
                paper_exchange_load_harness_rc == 0
                and str(pe_harness_report.get("status", "fail")).strip().lower() == "pass"
            )
            checks.append(
                _check(
                    pe_harness_ok,
                    "paper_exchange_load_harness",
                    "warning",
                    "paper-exchange load harness PASS"
                    if pe_harness_ok
                    else f"paper-exchange load harness failed (rc={paper_exchange_load_harness_rc})",
                    [str(pe_harness_path)],
                )
            )
        if args.check_paper_exchange_load:
            paper_exchange_load_rc, paper_exchange_load_msg = _run_paper_exchange_load_check(
                root,
                strict=bool(args.ci),
                lookback_sec=int(args.paper_exchange_load_lookback_sec),
                sample_count=int(args.paper_exchange_load_sample_count),
                min_latency_samples=int(args.paper_exchange_load_min_latency_samples),
                min_window_sec=int(paper_exchange_load_min_window_sec_effective),
                sustained_window_sec=int(paper_exchange_load_sustained_window_sec_effective),
                min_instance_coverage=int(args.paper_exchange_load_min_instance_coverage),
                enforce_budget_checks=bool(args.paper_exchange_load_enforce_budget_checks),
                min_throughput_cmds_per_sec=float(args.paper_exchange_load_min_throughput_cmds_per_sec),
                max_latency_p95_ms=float(args.paper_exchange_load_max_latency_p95_ms),
                max_latency_p99_ms=float(args.paper_exchange_load_max_latency_p99_ms),
                max_backlog_growth_pct_per_10min=float(args.paper_exchange_load_max_backlog_growth_pct_per_10min),
                max_restart_count=float(args.paper_exchange_load_max_restart_count),
                command_stream=str(args.paper_exchange_load_command_stream),
                event_stream=str(args.paper_exchange_load_event_stream),
                heartbeat_stream=str(args.paper_exchange_load_heartbeat_stream),
                consumer_group=str(args.paper_exchange_load_consumer_group),
                heartbeat_consumer_group=str(args.paper_exchange_load_heartbeat_consumer_group),
                heartbeat_consumer_name=str(args.paper_exchange_load_heartbeat_consumer_name),
                load_run_id=(paper_exchange_load_run_id or str(args.paper_exchange_load_run_id)),
            )
            pe_load_path = reports / "verification" / "paper_exchange_load_latest.json"
            pe_load_report = _read_json(pe_load_path, {})
            pe_load_status = str(pe_load_report.get("status", "")).strip().lower()
            pe_load_ok = paper_exchange_load_rc == 0 and pe_load_status == "pass"
            checks.append(
                _check(
                    pe_load_ok,
                    "paper_exchange_load_validation",
                    "critical",
                    "paper-exchange load/backpressure SLO check PASS"
                    if pe_load_ok
                    else (
                        "paper-exchange load/backpressure SLO check failed "
                        f"(status={pe_load_status or 'unknown'}, rc={paper_exchange_load_rc})"
                    ),
                    [str(pe_load_path), str(root / "scripts" / "release" / "check_paper_exchange_load.py")],
                )
            )
        if args.capture_paper_exchange_perf_baseline:
            paper_exchange_perf_baseline_capture_rc, paper_exchange_perf_baseline_capture_msg = (
                _run_paper_exchange_perf_baseline_capture(
                    root,
                    strict=bool(args.ci),
                    source_report_path=str(args.paper_exchange_perf_baseline_source_path),
                    baseline_output_path=str(args.paper_exchange_perf_baseline_path),
                    profile_label=str(args.paper_exchange_perf_baseline_profile_label),
                    require_source_pass=bool(args.paper_exchange_perf_baseline_require_source_pass),
                )
            )
            pe_perf_baseline_path = Path(str(args.paper_exchange_perf_baseline_path))
            if not pe_perf_baseline_path.is_absolute():
                pe_perf_baseline_path = root / pe_perf_baseline_path
            pe_perf_baseline_report = _read_json(pe_perf_baseline_path, {})
            pe_perf_baseline_ok = (
                paper_exchange_perf_baseline_capture_rc == 0
                and str(pe_perf_baseline_report.get("status", "")).strip().lower() == "pass"
            )
            checks.append(
                _check(
                    pe_perf_baseline_ok,
                    "paper_exchange_perf_baseline_capture",
                    "warning",
                    "paper-exchange perf baseline capture PASS"
                    if pe_perf_baseline_ok
                    else f"paper-exchange perf baseline capture failed (rc={paper_exchange_perf_baseline_capture_rc})",
                    [
                        str(pe_perf_baseline_path),
                        str(root / "scripts" / "release" / "capture_paper_exchange_perf_baseline.py"),
                    ],
                )
            )
        if args.check_paper_exchange_perf_regression:
            paper_exchange_perf_regression_rc, paper_exchange_perf_regression_msg = (
                _run_paper_exchange_perf_regression_check(
                    root,
                    strict=bool(args.ci),
                    current_report_path=str(args.paper_exchange_perf_current_report_path),
                    baseline_report_path=str(args.paper_exchange_perf_baseline_path),
                    waiver_path=str(args.paper_exchange_perf_waiver_path),
                    max_latency_regression_pct=float(args.paper_exchange_perf_max_latency_regression_pct),
                    max_backlog_regression_pct=float(args.paper_exchange_perf_max_backlog_regression_pct),
                    min_throughput_ratio=float(args.paper_exchange_perf_min_throughput_ratio),
                    max_restart_regression=float(args.paper_exchange_perf_max_restart_regression),
                    max_waiver_hours=float(args.paper_exchange_perf_waiver_max_hours),
                )
            )
            pe_perf_path = reports / "verification" / "paper_exchange_perf_regression_latest.json"
            pe_perf_report = _read_json(pe_perf_path, {})
            pe_perf_status = str(pe_perf_report.get("status", "")).strip().lower()
            pe_perf_waiver = pe_perf_report.get("waiver", {})
            pe_perf_waiver = pe_perf_waiver if isinstance(pe_perf_waiver, dict) else {}
            pe_perf_waived = bool(pe_perf_waiver.get("applied", False))
            pe_perf_ok = paper_exchange_perf_regression_rc == 0 and pe_perf_status in {"pass", "waived"}
            checks.append(
                _check(
                    pe_perf_ok,
                    "paper_exchange_perf_regression",
                    "critical",
                    (
                        "paper-exchange performance regression guard PASS"
                        if pe_perf_status == "pass"
                        else "paper-exchange performance regression guard WAIVED (approved temporary degradation)"
                    )
                    if pe_perf_ok
                    else (
                        "paper-exchange performance regression guard failed "
                        f"(status={pe_perf_status or 'unknown'}, rc={paper_exchange_perf_regression_rc}, waived={pe_perf_waived})"
                    ),
                    [str(pe_perf_path), str(root / "scripts" / "release" / "check_paper_exchange_perf_regression.py")],
                )
            )
            if not pe_perf_ok:
                critical_failures.append("paper_exchange_perf_regression")
        if args.check_paper_exchange_sustained_qualification:
            paper_exchange_sustained_qualification_rc, paper_exchange_sustained_qualification_msg = (
                _run_paper_exchange_sustained_qualification(
                    root,
                    strict=bool(args.ci),
                    duration_sec=float(args.paper_exchange_sustained_duration_sec),
                    target_cmd_rate=float(args.paper_exchange_sustained_target_cmd_rate),
                    min_commands=int(args.paper_exchange_sustained_min_commands),
                    command_maxlen=int(args.paper_exchange_sustained_command_maxlen),
                    producer=str(args.paper_exchange_load_harness_producer),
                    instance_name=str(args.paper_exchange_load_harness_instance_name),
                    instance_names=str(args.paper_exchange_load_harness_instance_names),
                    connector_name=str(args.paper_exchange_load_harness_connector_name),
                    trading_pair=str(args.paper_exchange_load_harness_trading_pair),
                    min_instance_coverage=int(args.paper_exchange_sustained_min_instance_coverage),
                    result_timeout_sec=float(args.paper_exchange_load_harness_result_timeout_sec),
                    poll_interval_ms=int(args.paper_exchange_load_harness_poll_interval_ms),
                    scan_count=int(args.paper_exchange_load_harness_scan_count),
                    lookback_sec=int(args.paper_exchange_sustained_lookback_sec),
                    sample_count=int(args.paper_exchange_sustained_sample_count),
                    sustained_window_sec=int(args.paper_exchange_sustained_window_sec),
                    command_stream=str(args.paper_exchange_load_command_stream),
                    event_stream=str(args.paper_exchange_load_event_stream),
                    heartbeat_stream=str(args.paper_exchange_load_heartbeat_stream),
                    consumer_group=str(args.paper_exchange_load_consumer_group),
                    heartbeat_consumer_group=str(args.paper_exchange_load_heartbeat_consumer_group),
                    heartbeat_consumer_name=str(args.paper_exchange_load_heartbeat_consumer_name),
                    min_throughput_cmds_per_sec=float(args.paper_exchange_load_min_throughput_cmds_per_sec),
                    max_latency_p95_ms=float(args.paper_exchange_load_max_latency_p95_ms),
                    max_latency_p99_ms=float(args.paper_exchange_load_max_latency_p99_ms),
                    max_backlog_growth_pct_per_10min=float(args.paper_exchange_load_max_backlog_growth_pct_per_10min),
                    max_restart_count=float(args.paper_exchange_load_max_restart_count),
                )
            )
            pe_sustained_path = reports / "verification" / "paper_exchange_sustained_qualification_latest.json"
            pe_sustained_report = _read_json(pe_sustained_path, {})
            pe_sustained_status = str(pe_sustained_report.get("status", "")).strip().lower()
            pe_sustained_ok = (
                paper_exchange_sustained_qualification_rc == 0 and pe_sustained_status == "pass"
            )
            checks.append(
                _check(
                    pe_sustained_ok,
                    "paper_exchange_sustained_qualification",
                    "critical",
                    "paper-exchange sustained qualification PASS"
                    if pe_sustained_ok
                    else (
                        "paper-exchange sustained qualification failed "
                        f"(status={pe_sustained_status or 'unknown'}, rc={paper_exchange_sustained_qualification_rc})"
                    ),
                    [
                        str(pe_sustained_path),
                        str(root / "scripts" / "release" / "run_paper_exchange_sustained_qualification.py"),
                    ],
                )
            )
            if not pe_sustained_ok:
                critical_failures.append("paper_exchange_sustained_qualification")
        if bool(args.auto_seed_paper_exchange_threshold_manual_metrics) and not bool(enforce_live_promotion_gates):
            seeded, seeded_path = _seed_paper_exchange_threshold_manual_metrics(
                root,
                manual_metrics_path=str(paper_exchange_threshold_manual_metrics_path),
            )
            paper_exchange_threshold_manual_metrics_seeded = bool(seeded)
            paper_exchange_threshold_manual_metrics_path = seeded_path
            paper_exchange_threshold_source_max_age_min_effective = max(
                float(paper_exchange_threshold_source_max_age_min_effective), 10000.0
            )
        if args.build_paper_exchange_threshold_inputs:
            paper_exchange_threshold_inputs_rc, paper_exchange_threshold_inputs_msg = (
                _run_paper_exchange_threshold_inputs_builder(
                    root,
                    strict=bool(args.ci),
                    max_source_age_min=float(paper_exchange_threshold_source_max_age_min_effective),
                    manual_metrics_path=str(paper_exchange_threshold_manual_metrics_path),
                )
            )
        paper_exchange_threshold_inputs_report = _read_json(paper_exchange_threshold_inputs_path, {})
        paper_exchange_threshold_inputs_diag = _paper_exchange_threshold_inputs_readiness(
            paper_exchange_threshold_inputs_report,
            enforce_live_path=bool(enforce_live_promotion_gates),
        )
        paper_exchange_threshold_inputs_ready = bool(paper_exchange_threshold_inputs_diag.get("ready", False))
        inputs_status = str(paper_exchange_threshold_inputs_diag.get("status", ""))
        inputs_unresolved = int(paper_exchange_threshold_inputs_diag.get("unresolved_metric_count", 0) or 0)
        inputs_stale = int(paper_exchange_threshold_inputs_diag.get("stale_source_count", 0) or 0)
        inputs_missing = int(paper_exchange_threshold_inputs_diag.get("missing_source_count", 0) or 0)
        inputs_manual = int(paper_exchange_threshold_inputs_diag.get("manual_metric_count", 0) or 0)
        inputs_manual_blocking = int(paper_exchange_threshold_inputs_diag.get("manual_metrics_blocking_count", 0) or 0)
        checks.append(
            _check(
                paper_exchange_threshold_inputs_ready,
                "paper_exchange_threshold_inputs_ready",
                "critical",
                (
                    "paper-exchange threshold inputs ready "
                    f"(status={inputs_status}, unresolved={inputs_unresolved}, stale_sources={inputs_stale}, "
                    f"missing_sources={inputs_missing}, manual_metrics={inputs_manual}, "
                    f"blocking_manual_metrics={inputs_manual_blocking})"
                )
                if paper_exchange_threshold_inputs_ready
                else (
                    "paper-exchange threshold inputs not ready "
                    f"(status={inputs_status}, unresolved={inputs_unresolved}, stale_sources={inputs_stale}, "
                    f"missing_sources={inputs_missing}, manual_metrics={inputs_manual}, "
                    f"blocking_manual_metrics={inputs_manual_blocking})"
                ),
                [str(paper_exchange_threshold_inputs_path)],
            )
        )
        if not paper_exchange_threshold_inputs_ready:
            critical_failures.append("paper_exchange_threshold_inputs_ready")
        paper_exchange_thresholds_rc, paper_exchange_thresholds_msg = _run_paper_exchange_thresholds_check(
            root,
            strict=bool(args.ci),
            max_input_age_min=float(args.paper_exchange_threshold_max_age_min),
        )
        pe_threshold_path = reports / "verification" / "paper_exchange_thresholds_latest.json"
        pe_threshold_report = _read_json(pe_threshold_path, {})
        threshold_inputs_builder_ok = (not bool(args.build_paper_exchange_threshold_inputs)) or (
            int(paper_exchange_threshold_inputs_rc) == 0
        )
        pe_threshold_ok = (
            threshold_inputs_builder_ok
            and paper_exchange_threshold_inputs_ready
            and
            paper_exchange_thresholds_rc == 0
            and str(pe_threshold_report.get("status", "fail")).strip().lower() == "pass"
        )
        checks.append(
            _check(
                pe_threshold_ok,
                "paper_exchange_thresholds",
                "critical",
                "paper-exchange quantitative thresholds PASS"
                if pe_threshold_ok
                else (
                    "paper-exchange quantitative thresholds failed "
                    f"(inputs_builder_rc={paper_exchange_threshold_inputs_rc}, "
                    f"inputs_ready={paper_exchange_threshold_inputs_ready}, "
                    f"thresholds_rc={paper_exchange_thresholds_rc})"
                ),
                [str(paper_exchange_threshold_inputs_path), str(pe_threshold_path)],
            )
        )
        if not pe_threshold_ok:
            critical_failures.append("paper_exchange_thresholds")

    # 2) Multi-bot policy consistency check
    policy_check_path = reports / "policy" / "latest.json"
    policy_rc, policy_msg = _run_multi_bot_policy_check(root)
    policy_report = _read_json(policy_check_path, {})
    policy_ok = policy_rc == 0 and str(policy_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            policy_ok,
            "multi_bot_policy_scope",
            "critical",
            "multi-bot policy scope is consistent across risk/reconciliation/account-map"
            if policy_ok
            else f"multi-bot policy consistency failed (rc={policy_rc})",
            [str(policy_check_path), str(root / "config" / "multi_bot_policy_v1.json")],
        )
    )

    # 3) Strategy catalog consistency check
    strategy_catalog_path = reports / "strategy_catalog" / "latest.json"
    strategy_rc, strategy_msg = _run_strategy_catalog_check(root)
    strategy_report = _read_json(strategy_catalog_path, {})
    strategy_ok = strategy_rc == 0 and str(strategy_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            strategy_ok,
            "strategy_catalog_consistency",
            "critical",
            "strategy catalog configs resolve to shared code and declared bundles"
            if strategy_ok
            else f"strategy catalog consistency failed (rc={strategy_rc})",
            [str(strategy_catalog_path), str(root / "config" / "strategy_catalog" / "catalog_v1.json")],
        )
    )

    # 4) Coordination policy scope check
    coord_policy_path = reports / "policy" / "coordination_policy_latest.json"
    coord_rc, coord_msg = _run_coordination_policy_check(root)
    coord_report = _read_json(coord_policy_path, {})
    coord_ok = coord_rc == 0 and str(coord_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            coord_ok,
            "coordination_policy_scope",
            "critical",
            "coordination service runs only in policy-permitted scope/mode"
            if coord_ok
            else f"coordination policy check failed (rc={coord_rc})",
            [str(coord_policy_path), str(root / "config" / "coordination_policy_v1.json")],
        )
    )

    # 5) Deterministic tests + coverage
    tests_path = reports / "tests" / "latest.json"
    tests_rc, tests_msg = _run_tests(root, runtime=args.tests_runtime)
    tests_report = _read_json(tests_path, {})
    tests_ok = tests_rc == 0 and str(tests_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            tests_ok,
            "unit_service_integration_tests",
            "critical",
            "deterministic test suite + coverage threshold passed"
            if tests_ok
            else f"deterministic tests failed (rc={tests_rc})",
            [str(tests_path), str(root / "reports" / "tests" / "latest.md")],
        )
    )

    # 5b) Ruff lint check
    ruff_rc, ruff_msg = _run_ruff_check(root)
    ruff_ok = ruff_rc == 0
    checks.append(
        _check(
            ruff_ok,
            "ruff_lint",
            "critical",
            "ruff lint passed on controllers/ and services/"
            if ruff_ok
            else f"ruff lint failed (rc={ruff_rc}): {ruff_msg[:200]}",
            [],
        )
    )

    # 5c) Mypy type check (controllers/ gradual strict)
    mypy_rc, mypy_msg = _run_mypy_check(root)
    mypy_ok = mypy_rc == 0
    checks.append(
        _check(
            mypy_ok,
            "mypy_type_check",
            "warning",
            "mypy passed on controllers/"
            if mypy_ok
            else f"mypy failed (rc={mypy_rc}): {mypy_msg[:200]}",
            [],
        )
    )

    # 5d) Dependency audit (non-blocking)
    try:
        from scripts.release.run_dependency_audit import run as _run_dep_audit
        dep_report = _run_dep_audit(root)
        dep_cve_count = int(dep_report.get("cve_count", 0))
        dep_ok = dep_cve_count == 0
    except Exception as dep_exc:
        dep_ok = True
        dep_cve_count = 0
        dep_report = {"error": str(dep_exc)}
    checks.append(
        _check(
            dep_ok,
            "dependency_audit",
            "info",
            f"dependency audit clean (outdated={dep_report.get('outdated_count', '?')})"
            if dep_ok
            else f"dependency audit found {dep_cve_count} CVE(s)",
            [],
        )
    )

    # 5e) Tick benchmark (non-blocking)
    try:
        from scripts.release.run_tick_benchmark import run as _run_tick_bench
        bench_report = _run_tick_bench(root, iterations=500)
        bench_status = bench_report.get("status", "fail")
        bench_p99 = bench_report.get("total", {}).get("p99_ms", 0.0)
        bench_ok = bench_status != "fail"
    except Exception as bench_exc:
        bench_ok = True
        bench_p99 = 0.0
        bench_report = {"error": str(bench_exc)}
    checks.append(
        _check(
            bench_ok,
            "tick_benchmark",
            "info",
            f"tick benchmark p99={bench_p99:.2f}ms (status={bench_report.get('status', '?')})"
            if bench_ok
            else f"tick benchmark FAIL: p99={bench_p99:.2f}ms exceeds threshold",
            [],
        )
    )

    # 6) Secrets hygiene check
    secrets_check_path = reports / "security" / "latest.json"
    secrets_rc, secrets_msg = _run_secrets_hygiene_check(root)
    secrets_report = _read_json(secrets_check_path, {})
    secrets_ok = secrets_rc == 0 and str(secrets_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            secrets_ok,
            "secrets_hygiene",
            "critical",
            "no secret leakage markers in docs/reports/log artifacts"
            if secrets_ok
            else f"secrets hygiene check failed (rc={secrets_rc})",
            [str(secrets_check_path), str(root / "scripts" / "release" / "run_secrets_hygiene_check.py")],
        )
    )

    # 7) Smoke checks (activity evidence)
    smoke_paths = list((root / "data" / "bot4" / "logs").glob("epp_v24/*/minute.csv"))
    smoke_ok = len(smoke_paths) > 0
    checks.append(
        _check(
            smoke_ok,
            "smoke_checks",
            "critical",
            "bot4 smoke activity artifacts found" if smoke_ok else "bot4 smoke artifacts missing",
            [str(p) for p in smoke_paths] if smoke_ok else [str(root / "data" / "bot4" / "logs")],
        )
    )

    # 8) Paper smoke matrix (required)
    snapshot_path = reports / "exchange_snapshots" / "latest.json"
    snapshot = _read_json(snapshot_path, {})
    bot3 = snapshot.get("bots", {}).get("bot3", {}) if isinstance(snapshot.get("bots"), dict) else {}
    paper_ok_direct = (
        isinstance(bot3, dict)
        and str(bot3.get("account_mode", "")) == "paper_only"
        and str(bot3.get("account_probe_status", "")) == "paper_only"
    )
    paper_ok_proxy = (
        isinstance(bot3, dict)
        and str(bot3.get("exchange", "")).lower() == "bitget_paper_trade"
        and str(bot3.get("source", "")) == "local_minute_proxy"
    )
    paper_ok = paper_ok_direct or paper_ok_proxy
    checks.append(
        _check(
            paper_ok,
            "paper_smoke_matrix",
            "critical",
            "bot3 paper-mode intent verified"
            if paper_ok
            else "bot3 paper-mode evidence missing/invalid (expected direct paper_only or proxy-local paper markers)",
            [str(snapshot_path)],
        )
    )

    # 9) Replay regression cycle (required unless explicitly skipped)
    replay_cycle_rc = 0
    replay_cycle_msg = ""
    replay_cycle_path = reports / "replay_regression_multi_window" / "latest.json"
    replay_cycle = {}
    if not args.skip_replay_cycle:
        replay_cycle_rc, replay_cycle_msg = _run_replay_regression_multi_window(
            root,
            require_portfolio_risk_healthy=bool(enforce_live_promotion_gates),
        )
        replay_cycle = _read_json(replay_cycle_path, {})
    replay_cycle_ok = True if args.skip_replay_cycle else (replay_cycle_rc == 0 and str(replay_cycle.get("status", "fail")) == "pass")
    checks.append(
        _check(
            replay_cycle_ok,
            "replay_regression_first_class",
            "critical",
            "replay regression multi-window PASS"
            if replay_cycle_ok
            else f"replay regression multi-window failed (rc={replay_cycle_rc})",
            [str(replay_cycle_path), str(root / "scripts" / "release" / "run_replay_regression_multi_window.py")],
        )
    )

    # 10) ML governance policy + retirement/drift checks
    ml_governance_path = reports / "policy" / "ml_governance_latest.json"
    ml_rc, ml_msg = _run_ml_governance_check(root)
    ml_report = _read_json(ml_governance_path, {})
    ml_ok = ml_rc == 0 and str(ml_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            ml_ok,
            "ml_signal_governance",
            "critical",
            "ML governance policy checks passed"
            if ml_ok
            else f"ML governance policy check failed (rc={ml_rc})",
            [str(ml_governance_path), str(root / "config" / "ml_governance_policy_v1.json")],
        )
    )

    # 11) Regression backtest harness (required)
    rc, reg_msg = _run_regression(root)
    reg_report = reports / "backtest_regression" / "latest.json"
    regression_ok = rc == 0 and reg_report.exists()
    checks.append(
        _check(
            regression_ok,
            "regression_backtest_harness",
            "critical",
            "regression harness PASS" if regression_ok else f"regression harness failed (rc={rc})",
            [str(reg_report), str(root / "scripts" / "release" / "run_backtest_regression.py")],
        )
    )

    # 12) Reconciliation status
    recon_candidates = [reports / "reconciliation" / "latest.json"]
    recon_candidates.extend(sorted((reports / "reconciliation").glob("reconciliation_*.json")))
    recon_path, recon, recon_age_min = _freshest_report(recon_candidates)
    recon_coverage = _reconciliation_active_bot_coverage(recon)
    recon_ok = str(recon.get("status", "critical")) in {"ok", "warning"} and int(recon.get("critical_count", 1)) == 0
    recon_fresh = recon_age_min <= max_report_age_min
    recon_coverage_ok = bool(recon_coverage.get("coverage_ok", True))
    recon_gate_ok = recon_ok and recon_fresh and recon_coverage_ok
    checks.append(
        _check(
            recon_gate_ok,
            "reconciliation_status",
            "critical",
            "reconciliation healthy, fresh, and covers active bots"
            if recon_gate_ok
            else (
                "reconciliation active-bot coverage gap: "
                + ",".join(recon_coverage.get("uncovered_active_bots", []))
                if (recon_ok and recon_fresh and not recon_coverage_ok)
                else "reconciliation critical or stale"
            ),
            [str(recon_path)],
        )
    )

    # 13) Parity thresholds
    parity_candidates = [reports / "parity" / "latest.json"]
    parity_candidates.extend(sorted((reports / "parity").glob("**/parity_*.json")))
    drift_audit_candidates = [reports / "parity" / "drift_audit_latest.json"]
    drift_audit_candidates.extend(sorted((reports / "parity").glob("**/drift_audit_*.json")))
    parity_path, parity, parity_age_min = _freshest_report(parity_candidates)
    drift_audit_path, drift_audit, _drift_age_min = _freshest_report(drift_audit_candidates)
    parity_ok = str(parity.get("status", "fail")) == "pass"
    parity_fresh = parity_age_min <= max_report_age_min
    parity_insufficient_bots, parity_active_bots = _parity_core_insufficient_active_bots(parity)
    parity_informative_ok = (not args.require_parity_informative_core) or (len(parity_insufficient_bots) == 0)
    drift_diag = _parity_drift_audit_status(drift_audit, max_report_age_min=max_report_age_min)
    drift_gate_ok = drift_diag["fresh"] and not drift_diag["failing_active_bots"] and not drift_diag["insufficient_active_bots"]
    if parity_ok and parity_fresh and parity_informative_ok and drift_gate_ok:
        parity_reason = "parity pass, drift audit clean, fresh, and informative"
    elif parity_ok and parity_fresh and not parity_informative_ok:
        parity_reason = (
            "parity core metrics insufficient_data for active bots: "
            + ",".join(parity_insufficient_bots)
        )
    elif parity_ok and parity_fresh and not drift_diag["fresh"]:
        parity_reason = "parity drift audit stale"
    elif parity_ok and parity_fresh and drift_diag["failing_active_bots"]:
        parity_reason = "parity drift audit failing for active bots: " + ",".join(drift_diag["failing_active_bots"])
    elif parity_ok and parity_fresh and drift_diag["insufficient_active_bots"]:
        parity_reason = (
            "parity drift audit insufficient evidence for active bots: "
            + ",".join(drift_diag["insufficient_active_bots"])
        )
    else:
        parity_reason = "parity fail or stale"
    checks.append(
        _check(
            parity_ok and parity_fresh and parity_informative_ok and drift_gate_ok,
            "parity_thresholds",
            "critical",
            parity_reason,
            [str(parity_path), str(drift_audit_path)],
        )
    )

    # 14) Portfolio risk status + freshness
    risk_candidates = [reports / "portfolio_risk" / "latest.json"]
    risk_candidates.extend(sorted((reports / "portfolio_risk").glob("portfolio_risk_*.json")))
    risk_path, risk, risk_age_min = _freshest_report(risk_candidates)
    risk_ok = str(risk.get("status", "critical")) in {"ok", "warning"} and int(risk.get("critical_count", 1)) == 0
    risk_fresh = risk_age_min <= max_report_age_min
    risk_gate_enforced = bool(enforce_live_promotion_gates)
    risk_gate_pass = risk_ok and risk_fresh
    checks.append(
        _check(
            risk_gate_pass,
            "portfolio_risk_status",
            "critical" if risk_gate_enforced else "warning",
            "portfolio risk healthy and fresh"
            if risk_gate_pass
            else (
                f"portfolio risk stale evidence selected (age_min={risk_age_min:.2f})"
                if risk_ok and not risk_fresh
                else (
                    "portfolio risk critical or stale"
                    if risk_gate_enforced
                    else "portfolio risk critical/stale (non-live scope; warning only)"
                )
            ),
            [str(risk_path)],
        )
    )

    # 15) Accounting integrity
    accounting_path = reports / "accounting" / "latest.json"
    accounting_rc, accounting_msg = _run_accounting_integrity_check(root, max_report_age_min)
    accounting_report = _read_json(accounting_path, {})
    accounting_ok = accounting_rc == 0 and str(accounting_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            accounting_ok,
            "accounting_integrity_v2",
            "critical",
            "accounting integrity checks passed with fresh snapshots"
            if accounting_ok
            else f"accounting integrity check failed (rc={accounting_rc})",
            [str(accounting_path), str(reports / "reconciliation" / "latest.json")],
        )
    )

    # 16) Alerting health
    alert_path = reports / "reconciliation" / "last_webhook_sent.json"
    alert = _read_json(alert_path, {})
    alert_status = str(alert.get("status", "")).strip().lower()
    alert_mode = str(alert.get("mode", "")).strip().lower()
    alert_fresh = alert_path.exists() and _minutes_since(str(alert.get("ts_utc", ""))) <= 24 * 60
    runner_ok = (not bool(args.check_alerting_health)) or int(alerting_health_rc) == 0
    allowed_statuses = {"ok"} if bool(args.ci) else {"ok", "local_dev_degraded"}
    status_ok = alert_status in allowed_statuses
    alert_ok = alert_fresh and runner_ok and status_ok
    checks.append(
        _check(
            alert_ok,
            "alerting_health",
            "critical",
            (
                f"alert webhook evidence healthy (status={alert_status or 'unknown'}, mode={alert_mode or 'unknown'})"
                if alert_ok
                else (
                    f"alert webhook unhealthy/stale (status={alert_status or 'unknown'}, "
                    f"mode={alert_mode or 'unknown'}, rc={alerting_health_rc})"
                )
            )
            ,
            [str(alert_path)],
        )
    )

    # 17) Event store integrity freshness
    integrity_candidates = sorted((reports / "event_store").glob("integrity_*.json"))
    integrity_path, integrity, integrity_age_min = _freshest_report(integrity_candidates)
    integrity_ok = (
        integrity_path is not None
        and integrity_path.exists()
        and int(integrity.get("missing_correlation_count", 1)) == 0
        and integrity_age_min <= max_report_age_min
    )
    checks.append(
        _check(
            integrity_ok,
            "event_store_integrity_freshness",
            "critical",
            "event store integrity fresh with zero missing correlations"
            if integrity_ok
            else (
                f"event store integrity stale evidence selected (age_min={integrity_age_min:.2f})"
                if integrity_path is not None
                and integrity_path.exists()
                and int(integrity.get("missing_correlation_count", 1)) == 0
                else "event store integrity missing/stale or missing correlations detected"
            ),
            [str(integrity_path)],
        )
    )

    # 18) Event stream coverage (desk-grade tracking requirement)
    required_streams = [
        "hb.market_data.v1",
        "hb.signal.v1",
        "hb.risk_decision.v1",
        "hb.execution_intent.v1",
        "hb.audit.v1",
        "hb.bot_telemetry.v1",
    ]
    events_by_stream = integrity.get("events_by_stream", {})
    stream_coverage_ok = isinstance(events_by_stream, dict) and all(
        float(events_by_stream.get(stream, 0) or 0) > 0 for stream in required_streams
    )
    checks.append(
        _check(
            stream_coverage_ok,
            "event_stream_coverage",
            "critical",
            "all required streams present in event_store integrity artifact"
            if stream_coverage_ok
            else "one or more required streams missing/zero in event_store integrity artifact",
            [str(integrity_path)],
        )
    )

    # 19) Ops DB writer freshness + non-empty ingestion
    if bool(args.ci):
        ops_db_writer_refresh_rc, ops_db_writer_refresh_msg = _run_ops_db_writer_once(root)
    ops_db_writer_path = reports / "ops_db_writer" / "latest.json"
    ops_db_writer = _read_json(ops_db_writer_path, {})
    ops_db_writer_fresh = (
        ops_db_writer_path.exists()
        and _minutes_since(str(ops_db_writer.get("ts_utc", ""))) <= max_report_age_min
    )
    ops_counts = ops_db_writer.get("counts", {})
    ops_non_empty = isinstance(ops_counts, dict) and (
        float(ops_counts.get("bot_snapshot_minute", 0) or 0) > 0
        and float(ops_counts.get("exchange_snapshot", 0) or 0) > 0
    )
    ops_db_writer_ok = (
        str(ops_db_writer.get("status", "fail")).lower() == "pass"
        and ops_db_writer_fresh
        and ops_non_empty
    )
    ops_db_writer_gate_enforced = bool(enforce_live_promotion_gates)
    checks.append(
        _check(
            ops_db_writer_ok,
            "ops_db_writer_freshness",
            "critical" if ops_db_writer_gate_enforced else "warning",
            "ops_db_writer latest.json is pass/fresh with non-empty counts"
            if ops_db_writer_ok
            else (
                "ops_db_writer missing/stale/failing or ingestion counts are empty"
                if ops_db_writer_gate_enforced
                else "ops_db_writer missing/stale/failing or counts empty (warning-only non-live scope)"
            ),
            [str(ops_db_writer_path)],
        )
    )

    # 19b) Canonical-plane cutover guardrails (DB freshness/parity/duplicate/replay checks).
    if args.check_canonical_plane_gates:
        canonical_path = reports / "ops" / "canonical_plane_gate_latest.json"
        canonical_report = _read_json(canonical_path, {})
        canonical_ok = (
            canonical_gate_rc == 0
            and str(canonical_report.get("status", "FAIL")).strip().upper() == "PASS"
        )
        checks.append(
            _check(
                canonical_ok,
                "canonical_plane_cutover_guardrails",
                "critical",
                "canonical-plane guardrails PASS (db freshness/parity/duplicate suppression/replay lag)"
                if canonical_ok
                else f"canonical-plane guardrails failed (rc={canonical_gate_rc})",
                [str(canonical_path), str(reports / "ops_db_writer" / "latest.json"), str(reports / "event_store")],
            )
        )
        if not canonical_ok:
            critical_failures.append("canonical_plane_cutover_guardrails")

    # 20) Market data freshness
    md_path = reports / "market_data" / "latest.json"
    md_rc, md_msg = _run_market_data_freshness_check(root, max_report_age_min)
    md_report = _read_json(md_path, {})
    md_ok = md_rc == 0 and str(md_report.get("status", "fail")) == "pass"
    checks.append(
        _check(
            md_ok,
            "market_data_freshness",
            "warning",
            "market data artifacts are fresh with hb.market_data.v1 rows"
            if md_ok
            else f"market data freshness check failed (rc={md_rc})",
            [str(md_path), str(root / "reports" / "event_store")],
        )
    )

    # 21) Optional strict day2 gate dependency
    day2_path = reports / "event_store" / "day2_gate_eval_latest.json"
    day2 = _read_json(day2_path, {})
    day2_go = bool(day2.get("go", False))
    day2_fresh, day2_age_min = _day2_freshness(day2, day2_path, max_report_age_min)
    day2_lag_ok, day2_lag_diag = _day2_lag_within_tolerance(
        day2=day2,
        reports_event_store=reports / "event_store",
        max_allowed_delta=int(args.day2_max_delta),
    )
    day2_go_ok = day2_go if args.require_day2_go else True
    day2_fresh_ok = day2_fresh if args.require_day2_fresh else True
    day2_lag_gate_ok = day2_lag_ok if args.require_day2_lag_within_tolerance else True
    day2_ok = day2_go_ok and day2_fresh_ok and day2_lag_gate_ok
    if day2_ok:
        day2_reason = (
            "day2 gate GO/fresh with lag in tolerance "
            f"(age_min={day2_age_min:.1f} max_delta={int(day2_lag_diag.get('max_delta_observed', 0))})"
        )
    else:
        day2_reason = (
            f"day2 gate status: go={day2_go} age_min={day2_age_min:.1f} "
            f"max_delta={int(day2_lag_diag.get('max_delta_observed', 0))}/"
            f"{int(day2_lag_diag.get('max_allowed_delta', int(args.day2_max_delta)))} "
            f"worst_stream={day2_lag_diag.get('worst_stream', '')!s} "
            f"(require_go={bool(args.require_day2_go)} "
            f"require_fresh={bool(args.require_day2_fresh)} "
            f"require_lag_tolerance={bool(args.require_day2_lag_within_tolerance)}). "
            "Remediation: run scripts/release/run_bus_recovery_check.py with --enforce-absolute-delta "
            "and ensure event_store consumer catches up before strict cycle."
        )
    day2_evidence = [str(day2_path)]
    source_compare_path = str(day2_lag_diag.get("source_compare_path", "")).strip()
    if source_compare_path:
        day2_evidence.append(source_compare_path)
    checks.append(
        _check(
            day2_ok,
            "day2_event_store_gate",
            "critical",
            day2_reason,
            day2_evidence,
        )
    )

    # 22) Validation ladder: paper soak (Level 3) required for live promotion
    paper_soak_path = reports / "paper_soak" / "latest.json"
    paper_soak = _read_json(paper_soak_path, {})
    paper_soak_pass = str(paper_soak.get("status", "")).upper() == "PASS"
    paper_soak_age = _minutes_since(str(paper_soak.get("ts_utc", "")))
    checks.append(
        _check(
            paper_soak_pass and paper_soak_age <= 24 * 60,
            "validation_ladder_paper_soak",
            "warning",
            f"paper soak PASS (age={paper_soak_age:.0f}m)"
            if paper_soak_pass
            else "paper soak not PASS or missing — Level 3 validation incomplete",
            [str(paper_soak_path)],
        )
    )

    # 23) Validation ladder: post-trade validation (Level 6) — informational
    ptv_path = reports / "analysis" / "post_trade_validation.json"
    ptv = _read_json(ptv_path, {})
    ptv_status = str(ptv.get("status", "")).upper()
    ptv_ok = ptv_status in {"PASS", "WARNING"}
    ptv_critical = ptv_status == "CRITICAL"
    checks.append(
        _check(
            not ptv_critical,
            "validation_ladder_post_trade",
            "warning",
            f"post-trade validation {ptv_status}"
            if ptv_status
            else "post-trade validation not yet run",
            [str(ptv_path)],
        )
    )

    # 24) Trading validation ladder enforcement (QPRO-FUNC-2)
    ladder_diag = _trading_validation_ladder_status(
        reports,
        enforce_live_path=bool(enforce_live_promotion_gates),
    )
    ladder_gate_enforced = bool(enforce_live_promotion_gates)
    checks.append(
        _check(
            bool(ladder_diag.get("pass", False)),
            "trading_validation_ladder",
            "critical" if ladder_gate_enforced else "warning",
            str(ladder_diag.get("reason", "")),
            [str(p) for p in ladder_diag.get("evidence_paths", []) if isinstance(p, str)],
        )
    )
    if ladder_gate_enforced and not bool(ladder_diag.get("pass", False)):
        critical_failures.append("trading_validation_ladder")

    # Compute validation level achieved
    validation_level = 0
    if any(c["pass"] for c in checks if c["name"] == "unit_service_integration_tests"):
        validation_level = 1
    if any(c["pass"] for c in checks if c["name"] == "replay_regression_cycle"):
        validation_level = max(validation_level, 2)
    if paper_soak_pass:
        validation_level = max(validation_level, 3)
    if ptv_ok and ptv_status:
        validation_level = max(validation_level, 6)

    for c in checks:
        if c["severity"] == "critical" and not c["pass"]:
            critical_failures.append(str(c["name"]))

    # Preserve order while removing duplicates from mixed direct/check-derived appends.
    critical_failures = list(dict.fromkeys(critical_failures))

    status = "PASS" if not critical_failures else "FAIL"
    manifest_candidates = sorted((root / "docs" / "ops").glob("release_manifest_*.md"))
    manifest_path = manifest_candidates[-1] if manifest_candidates else root / "docs" / "ops" / "release_manifest.md"
    all_evidence_paths = sorted({p for c in checks for p in c.get("evidence_paths", []) if isinstance(p, str)})
    all_evidence_refs = []
    for p in all_evidence_paths:
        all_evidence_refs.append(_file_ref(Path(p)))
    evidence_bundle_raw = json.dumps(
        {
            "status": status,
            "critical_failures": critical_failures,
            "evidence_paths": all_evidence_paths,
            "manifest_sha256": _sha256_file(manifest_path),
        },
        sort_keys=True,
    )
    evidence_bundle_id = hashlib.sha256(evidence_bundle_raw.encode("utf-8")).hexdigest()

    summary = {
        "ts_utc": _utc_now(),
        "status": status,
        "validation_level": validation_level,
        "critical_failures": critical_failures,
        "checks": checks,
        "release_manifest_ref": _file_ref(manifest_path),
        "evidence_bundle": {
            "evidence_bundle_id": evidence_bundle_id,
            "artifact_count": len(all_evidence_refs),
            "artifacts": all_evidence_refs,
        },
        "notes": {
            "regression_runner_output": reg_msg[:2000],
            "replay_cycle_runner_output": replay_cycle_msg[:2000],
            "ml_governance_runner_output": ml_msg[:2000],
            "multi_bot_policy_runner_output": policy_msg[:2000],
            "strategy_catalog_runner_output": strategy_msg[:2000],
            "coordination_policy_runner_output": coord_msg[:2000],
            "tests_runner_output": tests_msg[:2000],
            "secrets_hygiene_runner_output": secrets_msg[:2000],
            "require_day2_go": bool(args.require_day2_go),
            "refresh_parity_once": bool(refresh_parity_once),
            "refresh_event_integrity_once": bool(refresh_event_integrity_once),
            "skip_replay_cycle": bool(args.skip_replay_cycle),
            "live_promotion_gates_mode": str(args.live_promotion_gates_mode),
            "live_promotion_required_auto": bool(live_promotion_required_auto),
            "live_promotion_gates_enforced": bool(enforce_live_promotion_gates),
            "live_account_mode_bots": list(live_account_mode_bots),
            "replay_require_portfolio_risk_healthy": bool(enforce_live_promotion_gates),
            "ci_mode": bool(args.ci),
            "max_report_age_min": max_report_age_min,
            "parity_refresh_rc": parity_refresh_rc,
            "parity_refresh_output": parity_refresh_msg[:2000],
            "require_day2_fresh": bool(args.require_day2_fresh),
            "require_day2_lag_within_tolerance": bool(args.require_day2_lag_within_tolerance),
            "day2_max_delta": int(args.day2_max_delta),
            "require_parity_informative_core": bool(args.require_parity_informative_core),
            "parity_active_bots": parity_active_bots,
            "parity_insufficient_active_bots": parity_insufficient_bots,
            "parity_drift_active_bots": drift_diag["active_bots"],
            "parity_drift_failing_active_bots": drift_diag["failing_active_bots"],
            "parity_drift_insufficient_active_bots": drift_diag["insufficient_active_bots"],
            "day2_lag_ok": bool(day2_lag_ok),
            "day2_lag_diagnostics": day2_lag_diag,
            "day2_catchup_attempted": bool(args.attempt_day2_catchup),
            "day2_catchup_cycles": int(args.day2_catchup_cycles),
            "day2_min_hours_override": day2_min_hours_override,
            "day2_catchup_rc": int(day2_catchup_rc),
            "day2_catchup_output": day2_catchup_msg[:2000],
            "fill_event_backfill_attempted": bool(attempt_fill_event_backfill),
            "fill_event_backfill_rc": int(fill_backfill_rc),
            "fill_event_backfill_output": fill_backfill_msg[:2000],
            "reconciliation_refresh_rc": int(recon_refresh_rc),
            "reconciliation_refresh_output": recon_refresh_msg[:2000],
            "integrity_refresh_rc": integrity_refresh_rc,
            "integrity_refresh_output": integrity_refresh_msg[:2000],
            "accounting_integrity_runner_output": accounting_msg[:2000],
            "market_data_freshness_runner_output": md_msg[:2000],
            "alerting_health_runner_output": alerting_health_msg[:2000],
            "alerting_health_rc": alerting_health_rc,
            "check_dashboard_readiness": bool(args.check_dashboard_readiness),
            "dashboard_readiness_output": dashboard_readiness_msg[:2000],
            "dashboard_readiness_rc": int(dashboard_readiness_rc),
            "dashboard_max_data_age_s": int(args.dashboard_max_data_age_s),
            "dashboard_required_grafana_bot_variants": str(args.dashboard_required_grafana_bot_variants),
            "check_realtime_l2_data_quality": bool(args.check_realtime_l2_data_quality),
            "realtime_l2_data_quality_output": realtime_l2_data_quality_msg[:2000],
            "realtime_l2_data_quality_rc": int(realtime_l2_data_quality_rc),
            "realtime_l2_max_age_sec": int(args.realtime_l2_max_age_sec),
            "realtime_l2_max_sequence_gap": int(args.realtime_l2_max_sequence_gap),
            "realtime_l2_min_sampled_events": int(args.realtime_l2_min_sampled_events),
            "realtime_l2_max_raw_to_sampled_ratio": float(args.realtime_l2_max_raw_to_sampled_ratio),
            "realtime_l2_max_depth_stream_share": float(args.realtime_l2_max_depth_stream_share),
            "realtime_l2_max_depth_event_bytes": int(args.realtime_l2_max_depth_event_bytes),
            "realtime_l2_lookback_events": int(args.realtime_l2_lookback_events),
            "check_history_rollout_gates": bool(args.check_history_rollout_gates),
            "history_read_rollout_enabled": bool(history_read_rollout_enabled),
            "history_seed_enabled": bool(history_seed_enabled),
            "history_backfill_max_age_min": float(args.history_backfill_max_age_min),
            "history_seed_max_age_min": float(args.history_seed_max_age_min),
            "history_backfill_diag": history_backfill_diag,
            "history_seed_diag": history_seed_diag,
            "check_canonical_plane_gates": bool(args.check_canonical_plane_gates),
            "canonical_gate_output": canonical_gate_msg[:2000],
            "canonical_gate_rc": int(canonical_gate_rc),
            "canonical_max_db_ingest_age_min": float(args.canonical_max_db_ingest_age_min),
            "canonical_max_parity_delta_ratio": float(args.canonical_max_parity_delta_ratio),
            "canonical_min_duplicate_suppression_rate": float(args.canonical_min_duplicate_suppression_rate),
            "canonical_max_replay_lag_delta": int(args.canonical_max_replay_lag_delta),
            "ops_db_writer_refresh_output": ops_db_writer_refresh_msg[:2000],
            "ops_db_writer_refresh_rc": int(ops_db_writer_refresh_rc),
            "recon_exchange_preflight_output": recon_preflight_msg[:2000],
            "recon_exchange_preflight_rc": recon_preflight_rc,
            "paper_exchange_preflight_output": paper_exchange_preflight_msg[:2000],
            "paper_exchange_preflight_rc": paper_exchange_preflight_rc,
            "check_paper_exchange_preflight": bool(args.check_paper_exchange_preflight),
            "go_live_checklist_evidence_output": checklist_evidence_msg[:2000],
            "go_live_checklist_evidence_rc": checklist_evidence_rc,
            "telegram_validation_output": telegram_validation_msg[:2000],
            "telegram_validation_rc": telegram_validation_rc,
            "testnet_readiness_output": testnet_readiness_msg[:2000],
            "testnet_readiness_rc": testnet_readiness_rc,
            "testnet_scorecard_output": testnet_scorecard_msg[:2000],
            "testnet_scorecard_rc": testnet_scorecard_rc,
            "testnet_multi_day_summary_output": testnet_multi_day_summary_msg[:2000],
            "testnet_multi_day_summary_rc": testnet_multi_day_summary_rc,
            "check_performance_dossier": bool(args.check_performance_dossier),
            "performance_dossier_bot_log_root": str(args.performance_dossier_bot_log_root),
            "performance_dossier_lookback_days": int(args.performance_dossier_lookback_days),
            "performance_dossier_output": performance_dossier_msg[:2000],
            "performance_dossier_rc": int(performance_dossier_rc),
            "performance_dossier_diag": performance_dossier_diag,
            "portfolio_diversification_output": diversification_msg[:2000],
            "portfolio_diversification_rc": diversification_rc,
            "road9_allocation_rebalance_output": road9_rebalance_msg[:2000],
            "road9_allocation_rebalance_rc": road9_rebalance_rc,
            "check_paper_exchange_golden_path": bool(args.check_paper_exchange_golden_path),
            "paper_exchange_golden_path_output": paper_exchange_golden_path_msg[:2000],
            "paper_exchange_golden_path_rc": int(paper_exchange_golden_path_rc),
            "check_paper_exchange_thresholds": bool(args.check_paper_exchange_thresholds),
            "check_paper_exchange_load": bool(args.check_paper_exchange_load),
            "check_paper_exchange_sustained_qualification": bool(
                args.check_paper_exchange_sustained_qualification
            ),
            "check_paper_exchange_perf_regression": bool(args.check_paper_exchange_perf_regression),
            "run_paper_exchange_load_harness": bool(
                args.run_paper_exchange_load_harness or paper_exchange_load_harness_auto_run
            ),
            "run_paper_exchange_load_harness_configured": bool(args.run_paper_exchange_load_harness),
            "paper_exchange_load_harness_auto_run_in_ci": bool(paper_exchange_load_harness_auto_run),
            "paper_exchange_load_harness_duration_sec": float(args.paper_exchange_load_harness_duration_sec),
            "paper_exchange_load_harness_duration_sec_effective": float(
                paper_exchange_load_harness_duration_sec_effective
            ),
            "paper_exchange_load_harness_target_cmd_rate": float(args.paper_exchange_load_harness_target_cmd_rate),
            "paper_exchange_load_harness_min_commands": int(args.paper_exchange_load_harness_min_commands),
            "paper_exchange_load_harness_producer": str(args.paper_exchange_load_harness_producer),
            "paper_exchange_load_harness_instance_name": str(args.paper_exchange_load_harness_instance_name),
            "paper_exchange_load_harness_instance_names": str(args.paper_exchange_load_harness_instance_names),
            "paper_exchange_load_harness_min_instance_coverage": int(
                args.paper_exchange_load_harness_min_instance_coverage
            ),
            "paper_exchange_load_harness_connector_name": str(args.paper_exchange_load_harness_connector_name),
            "paper_exchange_load_harness_trading_pair": str(args.paper_exchange_load_harness_trading_pair),
            "paper_exchange_load_harness_result_timeout_sec": float(args.paper_exchange_load_harness_result_timeout_sec),
            "paper_exchange_load_harness_poll_interval_ms": int(args.paper_exchange_load_harness_poll_interval_ms),
            "paper_exchange_load_harness_scan_count": int(args.paper_exchange_load_harness_scan_count),
            "paper_exchange_load_harness_output": paper_exchange_load_harness_msg[:2000],
            "paper_exchange_load_harness_rc": int(paper_exchange_load_harness_rc),
            "paper_exchange_load_run_id": paper_exchange_load_run_id,
            "paper_exchange_load_command_stream": str(args.paper_exchange_load_command_stream),
            "paper_exchange_load_event_stream": str(args.paper_exchange_load_event_stream),
            "paper_exchange_load_heartbeat_stream": str(args.paper_exchange_load_heartbeat_stream),
            "paper_exchange_load_consumer_group": str(args.paper_exchange_load_consumer_group),
            "paper_exchange_load_heartbeat_consumer_group": str(args.paper_exchange_load_heartbeat_consumer_group),
            "paper_exchange_load_heartbeat_consumer_name": str(args.paper_exchange_load_heartbeat_consumer_name),
            "paper_exchange_load_run_id_override": str(args.paper_exchange_load_run_id),
            "paper_exchange_load_lookback_sec": int(args.paper_exchange_load_lookback_sec),
            "paper_exchange_load_sample_count": int(args.paper_exchange_load_sample_count),
            "paper_exchange_load_min_latency_samples": int(args.paper_exchange_load_min_latency_samples),
            "paper_exchange_load_min_window_sec": int(args.paper_exchange_load_min_window_sec),
            "paper_exchange_load_sustained_window_sec": int(args.paper_exchange_load_sustained_window_sec),
            "paper_exchange_load_min_window_sec_effective": int(paper_exchange_load_min_window_sec_effective),
            "paper_exchange_load_sustained_window_sec_effective": int(
                paper_exchange_load_sustained_window_sec_effective
            ),
            "paper_exchange_load_min_instance_coverage": int(args.paper_exchange_load_min_instance_coverage),
            "paper_exchange_load_enforce_budget_checks": bool(args.paper_exchange_load_enforce_budget_checks),
            "paper_exchange_load_min_throughput_cmds_per_sec": float(args.paper_exchange_load_min_throughput_cmds_per_sec),
            "paper_exchange_load_max_latency_p95_ms": float(args.paper_exchange_load_max_latency_p95_ms),
            "paper_exchange_load_max_latency_p99_ms": float(args.paper_exchange_load_max_latency_p99_ms),
            "paper_exchange_load_max_backlog_growth_pct_per_10min": float(
                args.paper_exchange_load_max_backlog_growth_pct_per_10min
            ),
            "paper_exchange_load_max_restart_count": float(args.paper_exchange_load_max_restart_count),
            "paper_exchange_load_output": paper_exchange_load_msg[:2000],
            "paper_exchange_load_rc": int(paper_exchange_load_rc),
            "paper_exchange_sustained_duration_sec": float(args.paper_exchange_sustained_duration_sec),
            "paper_exchange_sustained_target_cmd_rate": float(args.paper_exchange_sustained_target_cmd_rate),
            "paper_exchange_sustained_min_commands": int(args.paper_exchange_sustained_min_commands),
            "paper_exchange_sustained_command_maxlen": int(args.paper_exchange_sustained_command_maxlen),
            "paper_exchange_sustained_min_instance_coverage": int(args.paper_exchange_sustained_min_instance_coverage),
            "paper_exchange_sustained_lookback_sec": int(args.paper_exchange_sustained_lookback_sec),
            "paper_exchange_sustained_sample_count": int(args.paper_exchange_sustained_sample_count),
            "paper_exchange_sustained_window_sec": int(args.paper_exchange_sustained_window_sec),
            "paper_exchange_sustained_qualification_output": paper_exchange_sustained_qualification_msg[:2000],
            "paper_exchange_sustained_qualification_rc": int(paper_exchange_sustained_qualification_rc),
            "capture_paper_exchange_perf_baseline": bool(args.capture_paper_exchange_perf_baseline),
            "paper_exchange_perf_baseline_source_path": str(args.paper_exchange_perf_baseline_source_path),
            "paper_exchange_perf_baseline_profile_label": str(args.paper_exchange_perf_baseline_profile_label),
            "paper_exchange_perf_baseline_require_source_pass": bool(args.paper_exchange_perf_baseline_require_source_pass),
            "paper_exchange_perf_baseline_capture_output": paper_exchange_perf_baseline_capture_msg[:2000],
            "paper_exchange_perf_baseline_capture_rc": int(paper_exchange_perf_baseline_capture_rc),
            "paper_exchange_perf_current_report_path": str(args.paper_exchange_perf_current_report_path),
            "paper_exchange_perf_baseline_path": str(args.paper_exchange_perf_baseline_path),
            "paper_exchange_perf_waiver_path": str(args.paper_exchange_perf_waiver_path),
            "paper_exchange_perf_max_latency_regression_pct": float(args.paper_exchange_perf_max_latency_regression_pct),
            "paper_exchange_perf_max_backlog_regression_pct": float(args.paper_exchange_perf_max_backlog_regression_pct),
            "paper_exchange_perf_min_throughput_ratio": float(args.paper_exchange_perf_min_throughput_ratio),
            "paper_exchange_perf_max_restart_regression": float(args.paper_exchange_perf_max_restart_regression),
            "paper_exchange_perf_waiver_max_hours": float(args.paper_exchange_perf_waiver_max_hours),
            "paper_exchange_perf_regression_output": paper_exchange_perf_regression_msg[:2000],
            "paper_exchange_perf_regression_rc": int(paper_exchange_perf_regression_rc),
            "build_paper_exchange_threshold_inputs": bool(args.build_paper_exchange_threshold_inputs),
            "auto_seed_paper_exchange_threshold_manual_metrics": bool(
                args.auto_seed_paper_exchange_threshold_manual_metrics
            ),
            "paper_exchange_threshold_manual_metrics_seeded": bool(
                paper_exchange_threshold_manual_metrics_seeded
            ),
            "paper_exchange_threshold_manual_metrics_path": str(paper_exchange_threshold_manual_metrics_path),
            "paper_exchange_threshold_source_max_age_min": float(args.paper_exchange_threshold_source_max_age_min),
            "paper_exchange_threshold_source_max_age_min_effective": float(
                paper_exchange_threshold_source_max_age_min_effective
            ),
            "paper_exchange_threshold_inputs_path": str(paper_exchange_threshold_inputs_path),
            "paper_exchange_threshold_inputs_output": paper_exchange_threshold_inputs_msg[:2000],
            "paper_exchange_threshold_inputs_rc": paper_exchange_threshold_inputs_rc,
            "paper_exchange_threshold_inputs_ready": bool(paper_exchange_threshold_inputs_ready),
            "paper_exchange_threshold_inputs_status": str(paper_exchange_threshold_inputs_diag.get("status", "")),
            "paper_exchange_threshold_inputs_diagnostics_available": bool(
                paper_exchange_threshold_inputs_diag.get("diagnostics_available", False)
            ),
            "paper_exchange_threshold_inputs_unresolved_metric_count": int(
                paper_exchange_threshold_inputs_diag.get("unresolved_metric_count", 0) or 0
            ),
            "paper_exchange_threshold_inputs_stale_source_count": int(
                paper_exchange_threshold_inputs_diag.get("stale_source_count", 0) or 0
            ),
            "paper_exchange_threshold_inputs_missing_source_count": int(
                paper_exchange_threshold_inputs_diag.get("missing_source_count", 0) or 0
            ),
            "paper_exchange_threshold_max_age_min": float(args.paper_exchange_threshold_max_age_min),
            "paper_exchange_thresholds_output": paper_exchange_thresholds_msg[:2000],
            "paper_exchange_thresholds_rc": paper_exchange_thresholds_rc,
            "trading_validation_ladder": ladder_diag,
        },
    }

    out_root = reports / "promotion_gates"
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_root / f"promotion_gates_{stamp}.json"
    out_md = out_root / f"promotion_gates_{stamp}.md"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_root / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_markdown_summary(out_md, summary)
    _write_markdown_summary(out_root / "latest.md", summary)

    print(f"[promotion-gates] status={status} validation_level={validation_level}")
    if critical_failures:
        print("[promotion-gates] critical_failures=" + ",".join(critical_failures))
    print(f"[promotion-gates] evidence={out_file}")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
