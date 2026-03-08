from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency in lightweight environments.
    psycopg = None  # type: ignore[assignment]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minutes_since(ts: str) -> float:
    raw = str(ts or "").strip()
    if not raw:
        return 1e9
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return 1e9
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _count_csv_rows(paths: List[Path]) -> int:
    total = 0
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as fp:
                for _ in csv.DictReader(fp):
                    total += 1
        except Exception:
            continue
    return total


def _event_key_digest(event: Dict[str, object], line_hash_fallback: str) -> bytes:
    stream = str(event.get("stream", "")).strip()
    stream_entry_id = str(event.get("stream_entry_id", "")).strip()
    ts_utc = str(event.get("ts_utc", "")).strip()
    if not stream_entry_id:
        stream_entry_id = str(event.get("event_id", "")).strip()
    if not stream_entry_id:
        stream_entry_id = f"line:{line_hash_fallback}"
    raw = f"{stream}|{stream_entry_id}|{ts_utc}"
    return hashlib.sha1(raw.encode("utf-8")).digest()


def _count_event_jsonl(paths: List[Path]) -> Tuple[int, int]:
    total = 0
    unique_keys: set[bytes] = set()
    for path in paths:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fp:
                for idx, line in enumerate(fp, start=1):
                    raw = line.strip()
                    if not raw:
                        continue
                    total += 1
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    digest = _event_key_digest(
                        payload,
                        line_hash_fallback=hashlib.sha1(f"{path}:{idx}".encode("utf-8")).hexdigest(),
                    )
                    unique_keys.add(digest)
        except Exception:
            continue
    return total, len(unique_keys)


def _parity_delta_ratio(db_count: int, csv_count: int) -> float:
    denom = max(1, int(csv_count))
    return abs(int(db_count) - int(csv_count)) / float(denom)


def _duplicate_suppression_metrics(total_source: int, unique_source: int, db_event_count: int) -> Dict[str, float]:
    duplicate_source = max(0, int(total_source) - int(unique_source))
    retained_duplicates = max(0, int(db_event_count) - int(unique_source))
    if duplicate_source <= 0:
        suppression_rate = 1.0
    else:
        suppressed = max(0, duplicate_source - retained_duplicates)
        suppression_rate = suppressed / float(duplicate_source)
    return {
        "source_total_events": float(total_source),
        "source_unique_events": float(unique_source),
        "source_duplicate_events": float(duplicate_source),
        "db_retained_duplicates": float(retained_duplicates),
        "duplicate_suppression_rate": float(suppression_rate),
    }


def _max_replay_lag_from_day2(day2_payload: Dict[str, object], reports_root: Path) -> int:
    lag = day2_payload.get("lag_diagnostics")
    if isinstance(lag, dict) and "max_delta_observed" in lag:
        try:
            return int(lag.get("max_delta_observed", 0) or 0)
        except Exception:
            pass
    source_compare_path_raw = str(day2_payload.get("source_compare_file", "")).strip()
    source_compare_path = Path(source_compare_path_raw) if source_compare_path_raw else None
    if source_compare_path is None or not source_compare_path.exists():
        candidates = sorted((reports_root / "event_store").glob("source_compare_*.json"))
        source_compare_path = candidates[-1] if candidates else None
    if source_compare_path is None or not source_compare_path.exists():
        return 10**9
    source_compare = _read_json(source_compare_path, {})
    delta_map = source_compare.get("lag_produced_minus_ingested_since_baseline")
    if not isinstance(delta_map, dict) or not delta_map:
        delta_map = source_compare.get("delta_produced_minus_ingested_since_baseline")
    if not isinstance(delta_map, dict):
        return 10**9
    values: List[int] = []
    for value in delta_map.values():
        try:
            values.append(max(0, int(value)))
        except Exception:
            continue
    return max(values or [0])


def _connect_db():
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(
        host=os.getenv("OPS_DB_HOST", "postgres"),
        port=int(os.getenv("OPS_DB_PORT", "5432")),
        dbname=os.getenv("OPS_DB_NAME", "kzay_capital_ops"),
        user=os.getenv("OPS_DB_USER", "hbot"),
        password=os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password"),
    )


def _fetch_db_counts() -> Dict[str, int]:
    conn = _connect_db()
    try:
        out: Dict[str, int] = {}
        with conn.cursor() as cur:
            for table, key in (
                ("bot_snapshot_minute", "minute"),
                ("fills", "fills"),
                ("event_envelope_raw", "events"),
            ):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                row = cur.fetchone()
                out[key] = int(row[0] if row else 0)
        return out
    finally:
        conn.close()


def run(
    root: Path,
    data_root: Path,
    reports_root: Path,
    max_db_ingest_age_min: float,
    max_parity_delta_ratio: float,
    min_duplicate_suppression_rate: float,
    max_replay_lag_delta: int,
) -> Dict[str, object]:
    checks: List[Dict[str, object]] = []
    metrics: Dict[str, object] = {}

    ops_db_writer_path = reports_root / "ops_db_writer" / "latest.json"
    ops_db_writer = _read_json(ops_db_writer_path, {})
    db_age_min = _minutes_since(str(ops_db_writer.get("ts_utc", "")).strip())
    db_ingest_fresh = (
        str(ops_db_writer.get("status", "fail")).strip().lower() == "pass"
        and db_age_min <= float(max_db_ingest_age_min)
    )
    checks.append(
        {
            "name": "db_ingest_freshness",
            "severity": "critical",
            "pass": db_ingest_fresh,
            "reason": (
                f"ops_db_writer age={db_age_min:.2f}m within threshold"
                if db_ingest_fresh
                else f"ops_db_writer stale/fail age={db_age_min:.2f}m threshold={max_db_ingest_age_min:.2f}m"
            ),
            "evidence_paths": [str(ops_db_writer_path)],
        }
    )

    minute_csv_paths = sorted(data_root.glob("*/logs/epp_v24/*/minute.csv"))
    fills_csv_paths = sorted(data_root.glob("*/logs/epp_v24/*/fills.csv"))
    event_jsonl_paths = sorted((reports_root / "event_store").glob("events_*.jsonl"))
    csv_counts = {
        "minute": _count_csv_rows(minute_csv_paths),
        "fills": _count_csv_rows(fills_csv_paths),
    }
    events_total, events_unique = _count_event_jsonl(event_jsonl_paths)
    csv_counts["events_total"] = events_total
    csv_counts["events_unique"] = events_unique

    db_counts_error = ""
    db_counts: Dict[str, int] = {"minute": 0, "fills": 0, "events": 0}
    try:
        db_counts = _fetch_db_counts()
    except Exception as exc:
        db_counts_error = str(exc)

    if db_counts_error:
        checks.append(
            {
                "name": "db_vs_csv_parity_thresholds",
                "severity": "critical",
                "pass": False,
                "reason": f"db_count_query_failed:{db_counts_error}",
                "evidence_paths": [str(reports_root / "event_store")],
            }
        )
    else:
        evidence_present = (
            csv_counts["minute"] > 0
            and csv_counts["events_unique"] > 0
            and db_counts["minute"] > 0
            and db_counts["events"] > 0
        )
        checks.append(
            {
                "name": "nonzero_ingestion_evidence",
                "severity": "critical",
                "pass": evidence_present,
                "reason": (
                    "canonical plane has non-zero csv and db evidence"
                    if evidence_present
                    else (
                        "canonical plane missing non-zero evidence "
                        f"(csv_minute={csv_counts['minute']} csv_events={csv_counts['events_unique']} "
                        f"db_minute={db_counts['minute']} db_events={db_counts['events']})"
                    )
                ),
                "metrics": {
                    "csv_minute": int(csv_counts["minute"]),
                    "csv_events_unique": int(csv_counts["events_unique"]),
                    "db_minute": int(db_counts["minute"]),
                    "db_events": int(db_counts["events"]),
                },
                "evidence_paths": [
                    str(reports_root / "ops_db_writer" / "latest.json"),
                    str(reports_root / "event_store"),
                ],
            }
        )
        parity = {
            "minute_delta_ratio": _parity_delta_ratio(db_counts["minute"], csv_counts["minute"]),
            "fills_delta_ratio": _parity_delta_ratio(db_counts["fills"], csv_counts["fills"]),
            "events_delta_ratio": _parity_delta_ratio(db_counts["events"], csv_counts["events_unique"]),
            "threshold": float(max_parity_delta_ratio),
        }
        parity_pass = all(float(v) <= float(max_parity_delta_ratio) for k, v in parity.items() if k.endswith("_delta_ratio"))
        checks.append(
            {
                "name": "db_vs_csv_parity_thresholds",
                "severity": "critical",
                "pass": parity_pass,
                "reason": (
                    f"parity delta ratios within threshold={max_parity_delta_ratio:.4f}"
                    if parity_pass
                    else f"parity delta ratio exceeded threshold={max_parity_delta_ratio:.4f}"
                ),
                "metrics": parity,
                "evidence_paths": [
                    str(reports_root / "ops_db_writer" / "latest.json"),
                    str(reports_root / "event_store"),
                ],
            }
        )
        metrics["parity"] = parity

        dup_metrics = _duplicate_suppression_metrics(
            total_source=csv_counts["events_total"],
            unique_source=csv_counts["events_unique"],
            db_event_count=db_counts["events"],
        )
        dup_pass = float(dup_metrics["duplicate_suppression_rate"]) >= float(min_duplicate_suppression_rate)
        checks.append(
            {
                "name": "duplicate_suppression_rate",
                "severity": "critical",
                "pass": dup_pass,
                "reason": (
                    f"duplicate suppression rate={dup_metrics['duplicate_suppression_rate']:.4f} >= {min_duplicate_suppression_rate:.4f}"
                    if dup_pass
                    else f"duplicate suppression rate={dup_metrics['duplicate_suppression_rate']:.4f} < {min_duplicate_suppression_rate:.4f}"
                ),
                "metrics": dup_metrics,
                "evidence_paths": [str(reports_root / "event_store")],
            }
        )
        metrics["duplicate_suppression"] = dup_metrics

    day2_path = reports_root / "event_store" / "day2_gate_eval_latest.json"
    day2 = _read_json(day2_path, {})
    replay_lag_delta = _max_replay_lag_from_day2(day2, reports_root=reports_root)
    replay_ok = int(replay_lag_delta) <= int(max_replay_lag_delta)
    checks.append(
        {
            "name": "event_store_replay_lag_threshold",
            "severity": "critical",
            "pass": replay_ok,
            "reason": (
                f"replay lag delta={replay_lag_delta} <= {max_replay_lag_delta}"
                if replay_ok
                else f"replay lag delta={replay_lag_delta} > {max_replay_lag_delta}"
            ),
            "metrics": {
                "max_replay_lag_delta": int(replay_lag_delta),
                "threshold": int(max_replay_lag_delta),
            },
            "evidence_paths": [str(day2_path)],
        }
    )

    status = "PASS" if all(bool(c.get("pass")) for c in checks if str(c.get("severity")) == "critical") else "FAIL"
    out = {
        "ts_utc": _utc_now_iso(),
        "status": status,
        "checks": checks,
        "metrics": metrics,
        "inputs": {
            "max_db_ingest_age_min": float(max_db_ingest_age_min),
            "max_parity_delta_ratio": float(max_parity_delta_ratio),
            "min_duplicate_suppression_rate": float(min_duplicate_suppression_rate),
            "max_replay_lag_delta": int(max_replay_lag_delta),
            "root": str(root),
            "data_root": str(data_root),
            "reports_root": str(reports_root),
        },
    }

    ops_reports = reports_root / "ops"
    ops_reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = ops_reports / f"canonical_plane_gate_{stamp}.json"
    out_file.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (ops_reports / "canonical_plane_gate_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical-plane cutover gate checks.")
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser.add_argument("--root", default=str(root))
    parser.add_argument("--data-root", default=str(root / "data"))
    parser.add_argument("--reports-root", default=str(root / "reports"))
    parser.add_argument("--max-db-ingest-age-min", type=float, default=20.0)
    parser.add_argument("--max-parity-delta-ratio", type=float, default=0.10)
    parser.add_argument("--min-duplicate-suppression-rate", type=float, default=0.99)
    parser.add_argument("--max-replay-lag-delta", type=int, default=5)
    args = parser.parse_args()

    payload = run(
        root=Path(args.root),
        data_root=Path(args.data_root),
        reports_root=Path(args.reports_root),
        max_db_ingest_age_min=float(args.max_db_ingest_age_min),
        max_parity_delta_ratio=float(args.max_parity_delta_ratio),
        min_duplicate_suppression_rate=float(args.min_duplicate_suppression_rate),
        max_replay_lag_delta=int(args.max_replay_lag_delta),
    )
    print(
        f"[canonical-plane-gate] status={payload.get('status')} "
        f"checks={len(payload.get('checks', []))}",
        flush=True,
    )
    return 0 if str(payload.get("status", "FAIL")) == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
