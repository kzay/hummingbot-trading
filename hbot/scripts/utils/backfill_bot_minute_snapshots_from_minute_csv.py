"""Backfill `bot_minute_snapshot` events into the local event store from minute.csv.

Why:
- `reconciliation_service` warns when active bots have minute log activity but no
  persisted `bot_minute_snapshot` evidence in `reports/event_store/events_YYYYMMDD.jsonl`.
- Runtime fallback should normally write these snapshots, but older/stale desks can
  still be missing them for active bots.

This script converts minute.csv rows into deterministic `bot_minute_snapshot`
event envelopes and appends only the missing rows for the selected UTC day.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_iso(ts: str) -> Optional[datetime]:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _iter_minute_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _variant_suffix(folder_name: str) -> str:
    name = str(folder_name or "").strip()
    if "_" not in name:
        return name
    return name.split("_")[-1]


def _deterministic_event_id(bot: str, variant: str, row: Dict[str, str]) -> str:
    raw = "|".join(
        [
            "minute_csv_backfill_v1",
            bot,
            variant,
            str(row.get("ts", "")).strip(),
            str(row.get("connector_name", row.get("exchange", ""))).strip(),
            str(row.get("trading_pair", "")).strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_existing_event_ids(path: Path) -> Set[str]:
    ids: Set[str] = set()
    if not path.exists():
        return ids
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                event_id = str(payload.get("event_id", "")).strip()
                if event_id:
                    ids.add(event_id)
    except Exception:
        return ids
    return ids


def _build_envelope(
    *,
    event_id: str,
    bot: str,
    variant: str,
    ts_utc: str,
    row: Dict[str, str],
) -> Dict[str, object]:
    connector_name = str(row.get("connector_name", row.get("exchange", ""))).strip()
    trading_pair = str(row.get("trading_pair", "")).strip()
    payload = dict(row)
    payload.update(
        {
            "event_type": "bot_minute_snapshot",
            "event_version": "v1",
            "schema_version": "1.0",
            "ts": str(row.get("ts", "")).strip(),
            "ts_utc": ts_utc,
            "producer": "backfill.minute_csv",
            "instance_name": bot,
            "controller_id": f"backfill.minute_csv.{bot}.{variant}",
            "connector_name": connector_name,
            "trading_pair": trading_pair,
        }
    )
    return {
        "event_id": event_id,
        "event_type": "bot_minute_snapshot",
        "event_version": "v1",
        "ts_utc": ts_utc,
        "producer": "backfill.minute_csv",
        "instance_name": bot,
        "controller_id": f"backfill.minute_csv.{bot}.{variant}",
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "correlation_id": event_id,
        "stream": "local.backfill.minute_snapshot",
        "stream_entry_id": "",
        "payload": payload,
        "ingest_ts_utc": datetime.now(timezone.utc).isoformat(),
        "schema_validation_status": "ok",
    }


def backfill(
    *,
    root: Path,
    bot: Optional[str],
    variant: Optional[str],
    day: Optional[str],
) -> Tuple[int, int]:
    data_root = root / "data"
    store_dir = root / "reports" / "event_store"
    store_dir.mkdir(parents=True, exist_ok=True)

    files = list(data_root.glob("*/logs/epp_v24/*/minute.csv"))
    if bot:
        files = [path for path in files if path.parts[-5] == bot]
    if variant:
        files = [path for path in files if _variant_suffix(path.parts[-2]) == variant or path.parts[-2] == variant]

    total_rows = 0
    appended = 0
    existing_by_day: Dict[str, Set[str]] = {}
    handles_by_day: Dict[str, object] = {}

    def _day_file(day_key: str) -> Path:
        return store_dir / f"events_{day_key}.jsonl"

    try:
        for minute_path in files:
            try:
                bot_name = minute_path.parts[-5]
                bot_variant = _variant_suffix(minute_path.parts[-2])
            except Exception:
                continue
            rows = list(_iter_minute_rows(minute_path))
            for row in rows:
                dt = _parse_iso(str(row.get("ts", "")).strip())
                if dt is None:
                    continue
                day_key = dt.strftime("%Y%m%d")
                if day and day_key != day:
                    continue
                total_rows += 1
                if day_key not in existing_by_day:
                    existing_by_day[day_key] = _load_existing_event_ids(_day_file(day_key))
                event_id = _deterministic_event_id(bot_name, bot_variant, row)
                if event_id in existing_by_day[day_key]:
                    continue
                envelope = _build_envelope(
                    event_id=event_id,
                    bot=bot_name,
                    variant=bot_variant,
                    ts_utc=dt.isoformat(),
                    row=row,
                )
                out_path = _day_file(day_key)
                if day_key not in handles_by_day:
                    handles_by_day[day_key] = out_path.open("a", encoding="utf-8")
                handle = handles_by_day[day_key]
                handle.write(json.dumps(envelope, ensure_ascii=True) + "\n")
                existing_by_day[day_key].add(event_id)
                appended += 1
    finally:
        for handle in handles_by_day.values():
            try:
                handle.close()
            except Exception:
                pass

    return total_rows, appended


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill bot_minute_snapshot events from minute.csv")
    parser.add_argument("--bot", default="", help="Filter by bot name (e.g. bot5)")
    parser.add_argument("--variant", default="", help="Filter by variant (e.g. a)")
    parser.add_argument("--day", default="", help="Filter by UTC day YYYYMMDD (e.g. 20260309)")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    total, appended = backfill(
        root=root,
        bot=args.bot.strip() or None,
        variant=args.variant.strip() or None,
        day=args.day.strip() or None,
    )
    logger.info("minute_rows_scanned=%d appended_events=%d", total, appended)


if __name__ == "__main__":
    main()
