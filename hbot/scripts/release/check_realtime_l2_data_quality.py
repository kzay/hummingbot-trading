from __future__ import annotations

import argparse
import json
import os
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_lib.contracts.stream_names import MARKET_DEPTH_STREAM


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _stream_entry_id_to_ms(entry_id: str) -> int | None:
    raw = str(entry_id or "").strip()
    if not raw:
        return None
    ms_part = raw.split("-", 1)[0].strip()
    if not ms_part.lstrip("-").isdigit():
        return None
    try:
        return int(ms_part)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except Exception:
        return []
    return out


def _check(ok: bool, name: str, reason: str) -> dict[str, Any]:
    return {"name": name, "pass": bool(ok), "reason": reason}


def run(
    root: Path,
    max_age_sec: int,
    max_sequence_gap: int,
    min_sampled_events: int,
    max_raw_to_sampled_ratio: float,
    max_depth_stream_share: float,
    max_depth_event_bytes: int,
    lookback_depth_events: int,
) -> tuple[int, dict[str, Any]]:
    reports = root / "reports"
    event_store = reports / "event_store"
    verification = reports / "verification"
    verification.mkdir(parents=True, exist_ok=True)

    now_s = datetime.now(UTC).timestamp()
    checks: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}

    integrity_candidates = sorted(event_store.glob("integrity_*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    integrity_path = integrity_candidates[-1] if integrity_candidates else None
    integrity = _read_json(integrity_path) if integrity_path is not None else {}
    integrity_age_sec = 1e9
    if integrity_path is not None and integrity_path.exists():
        integrity_age_sec = max(0.0, now_s - integrity_path.stat().st_mtime)
    freshness_ok = integrity_path is not None and integrity_age_sec <= float(max_age_sec)
    checks.append(
        _check(
            freshness_ok,
            "ingest_freshness",
            f"integrity_age_sec={integrity_age_sec:.1f} max_age_sec={max_age_sec}",
        )
    )

    events_by_stream = integrity.get("events_by_stream", {})
    if not isinstance(events_by_stream, dict):
        events_by_stream = {}
    total_events = _safe_int(integrity.get("total_events", 0), 0)
    depth_events_total = _safe_int(events_by_stream.get(MARKET_DEPTH_STREAM, 0), 0)
    depth_stream_share = (float(depth_events_total) / float(total_events)) if total_events > 0 else 0.0
    storage_share_ok = depth_stream_share <= float(max_depth_stream_share)
    checks.append(
        _check(
            storage_share_ok,
            "storage_budget_stream_share",
            f"depth_stream_share={depth_stream_share:.4f} max={max_depth_stream_share:.4f}",
        )
    )

    event_files = sorted(event_store.glob("events_*.jsonl"))
    sequence_duplicates = 0
    sequence_out_of_order = 0
    sequence_large_gap_violations = 0
    sequence_max_gap_observed = 0
    max_payload_bytes_observed = 0
    recent_depth_rows: deque[dict[str, Any]] = deque(maxlen=max(100, int(lookback_depth_events)))

    for path in event_files:
        for row in _iter_jsonl(path):
            if str(row.get("stream", "")).strip() != MARKET_DEPTH_STREAM:
                continue
            recent_depth_rows.append(row)

    seq_by_key: dict[tuple[str, str, str], int] = {}
    latest_depth_age_sec: float | None = None
    sequence_rows_scanned = 0
    for row in recent_depth_rows:
        entry_ms = _stream_entry_id_to_ms(str(row.get("stream_entry_id", "")))
        row_age_sec: float | None = None
        if entry_ms is not None:
            row_age_sec = max(0.0, now_s - (entry_ms / 1000.0))
            latest_depth_age_sec = row_age_sec if latest_depth_age_sec is None else min(latest_depth_age_sec, row_age_sec)
        # Sequence checks should focus on fresh depth flow, not stale backlog rows.
        if row_age_sec is None or row_age_sec > float(max_age_sec):
            continue
        sequence_rows_scanned += 1
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        payload_bytes = len(json.dumps(payload, ensure_ascii=True))
        if payload_bytes > max_payload_bytes_observed:
            max_payload_bytes_observed = payload_bytes

        key = (
            str(row.get("instance_name") or payload.get("instance_name") or "").strip(),
            str(row.get("controller_id") or payload.get("controller_id") or "").strip(),
            str(row.get("trading_pair") or payload.get("trading_pair") or "").strip(),
        )
        seq = payload.get("market_sequence")
        if seq is not None:
            seq_val = _safe_int(seq, -1)
            if seq_val >= 0:
                prev = seq_by_key.get(key)
                if prev is not None:
                    delta = seq_val - prev
                    if delta == 0:
                        sequence_duplicates += 1
                    elif delta < 0:
                        sequence_out_of_order += 1
                    elif delta > 1:
                        gap = delta - 1
                        sequence_max_gap_observed = max(sequence_max_gap_observed, gap)
                        if gap > int(max_sequence_gap):
                            sequence_large_gap_violations += 1
                seq_by_key[key] = seq_val

    sequence_ok = (
        sequence_duplicates == 0
        and sequence_out_of_order == 0
        and sequence_large_gap_violations == 0
    )
    checks.append(
        _check(
            sequence_ok,
            "sequence_integrity",
            (
                f"duplicates={sequence_duplicates} out_of_order={sequence_out_of_order} "
                f"max_gap_observed={sequence_max_gap_observed} gap_violations={sequence_large_gap_violations}"
            ),
        )
    )

    payload_size_ok = max_payload_bytes_observed <= int(max_depth_event_bytes)
    checks.append(
        _check(
            payload_size_ok,
            "storage_budget_payload_size",
            f"max_payload_bytes_observed={max_payload_bytes_observed} max={max_depth_event_bytes}",
        )
    )

    depth_freshness_ok = latest_depth_age_sec is not None and latest_depth_age_sec <= float(max_age_sec)
    checks.append(
        _check(
            depth_freshness_ok,
            "depth_event_freshness",
            f"latest_depth_age_sec={latest_depth_age_sec if latest_depth_age_sec is not None else 'n/a'} max_age_sec={max_age_sec}",
        )
    )

    ops_db_writer_latest = _read_json(reports / "ops_db_writer" / "latest.json")
    counts = ops_db_writer_latest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    market_depth_counts = counts.get("market_depth", {})
    market_depth_counts = market_depth_counts if isinstance(market_depth_counts, dict) else {}
    raw_inserted = _safe_int(market_depth_counts.get("raw_inserted", 0), 0)
    sampled_inserted = _safe_int(market_depth_counts.get("sampled_inserted", 0), 0)
    ratio = float(raw_inserted) / float(max(1, sampled_inserted))
    sampling_evidence_present = depth_events_total > 0 and raw_inserted > 0 and sampled_inserted > 0
    sampling_ok = sampling_evidence_present and sampled_inserted >= int(min_sampled_events) and sampled_inserted <= raw_inserted
    parity_ok = sampled_inserted <= raw_inserted and ratio <= float(max_raw_to_sampled_ratio)
    checks.append(
        _check(
            sampling_ok,
            "sampling_coverage",
            (
                f"raw_inserted={raw_inserted} sampled_inserted={sampled_inserted} "
                f"depth_events_total={depth_events_total} min_sampled={min_sampled_events}"
            ),
        )
    )
    checks.append(
        _check(
            parity_ok,
            "raw_sample_parity",
            (
                f"raw_inserted={raw_inserted} sampled_inserted={sampled_inserted} "
                f"raw_to_sample_ratio={ratio:.2f} max_ratio={max_raw_to_sampled_ratio:.2f}"
            ),
        )
    )

    status = "pass" if all(bool(item.get("pass", False)) for item in checks) else "fail"
    diagnostics = {
        "integrity_path": str(integrity_path) if integrity_path else "",
        "event_files_scanned": [str(p) for p in event_files[-3:]],
        "total_events": total_events,
        "depth_events_total": depth_events_total,
        "depth_stream_share": depth_stream_share,
        "recent_depth_events_scanned": len(recent_depth_rows),
        "sequence_rows_scanned": sequence_rows_scanned,
        "sequence_duplicates": sequence_duplicates,
        "sequence_out_of_order": sequence_out_of_order,
        "sequence_large_gap_violations": sequence_large_gap_violations,
        "sequence_max_gap_observed": sequence_max_gap_observed,
        "max_payload_bytes_observed": max_payload_bytes_observed,
        "latest_depth_age_sec": latest_depth_age_sec,
        "ops_db_market_depth_counts": market_depth_counts,
    }

    report = {
        "ts_utc": _utc_now_iso(),
        "status": status,
        "checks": checks,
        "diagnostics": diagnostics,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = verification / f"realtime_l2_data_quality_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (verification / "realtime_l2_data_quality_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return (0 if status == "pass" else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate realtime/L2 depth data quality evidence.")
    parser.add_argument("--max-age-sec", type=int, default=int(os.getenv("REALTIME_L2_MAX_AGE_SEC", "180")))
    parser.add_argument("--max-sequence-gap", type=int, default=int(os.getenv("REALTIME_L2_MAX_SEQUENCE_GAP", "50")))
    parser.add_argument("--min-sampled-events", type=int, default=int(os.getenv("REALTIME_L2_MIN_SAMPLED_EVENTS", "1")))
    parser.add_argument(
        "--max-raw-to-sampled-ratio",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_RAW_TO_SAMPLED_RATIO", "100.0")),
    )
    parser.add_argument(
        "--max-depth-stream-share",
        type=float,
        default=float(os.getenv("REALTIME_L2_MAX_DEPTH_STREAM_SHARE", "0.95")),
    )
    parser.add_argument(
        "--max-depth-event-bytes",
        type=int,
        default=int(os.getenv("REALTIME_L2_MAX_DEPTH_EVENT_BYTES", "4000")),
    )
    parser.add_argument(
        "--lookback-depth-events",
        type=int,
        default=int(os.getenv("REALTIME_L2_LOOKBACK_EVENTS", "5000")),
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    rc, report = run(
        root=root,
        max_age_sec=max(30, int(args.max_age_sec)),
        max_sequence_gap=max(0, int(args.max_sequence_gap)),
        min_sampled_events=max(0, int(args.min_sampled_events)),
        max_raw_to_sampled_ratio=max(1.0, float(args.max_raw_to_sampled_ratio)),
        max_depth_stream_share=max(0.0, min(1.0, float(args.max_depth_stream_share))),
        max_depth_event_bytes=max(200, int(args.max_depth_event_bytes)),
        lookback_depth_events=max(100, int(args.lookback_depth_events)),
    )
    print(f"[realtime-l2-data-quality] status={report.get('status')} rc={rc}")
    print(f"[realtime-l2-data-quality] checks={len(report.get('checks', []))}")
    print("[realtime-l2-data-quality] evidence=reports/verification/realtime_l2_data_quality_latest.json")
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
