"""Backfill `order_filled` events into the local event store from fills.csv.

Why:
- `reconciliation_service` validates fill parity by counting `event_type=="order_filled"`
  rows in `reports/event_store/events_YYYYMMDD.jsonl`.
- Paper Engine v2 historically wrote `fills.csv` but did not emit `order_filled` events,
  causing persistent warnings like:
  `fills_present_without_order_filled_events`.

This script converts existing `fills.csv` rows into deterministic `order_filled` event
envelopes and appends any missing ones to the corresponding daily JSONL file.

Safe to run repeatedly:
- Uses a deterministic `event_id` (sha256 of fill row identity) and skips existing IDs.

Usage:
  python scripts/utils/backfill_order_filled_events_from_fills_csv.py --bot bot1 --variant a --day 20260225
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_iso(ts: str) -> Optional[datetime]:
    ts = (ts or "").strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _iter_fill_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    import csv

    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _deterministic_event_id(bot: str, variant: str, row: Dict[str, str]) -> str:
    raw = "|".join(
        [
            "fills_csv_backfill_v1",
            bot,
            variant,
            str(row.get("ts", "")).strip(),
            str(row.get("order_id", "")).strip(),
            str(row.get("side", "")).strip().lower(),
            str(row.get("price", "")).strip(),
            str(row.get("amount_base", "")).strip(),
            str(row.get("fee_quote", "")).strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_existing_event_ids(path: Path) -> Set[str]:
    ids: Set[str] = set()
    if not path.exists():
        return ids
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                eid = str(obj.get("event_id", "")).strip()
                if eid:
                    ids.add(eid)
    except Exception:
        return ids
    return ids


def _build_envelope(
    *,
    event_id: str,
    bot: str,
    connector_name: str,
    trading_pair: str,
    ts_utc: str,
    row: Dict[str, str],
) -> Dict[str, object]:
    def _f(key: str) -> float:
        try:
            return float(str(row.get(key, "")).strip() or 0.0)
        except Exception:
            return 0.0

    side = str(row.get("side", "")).strip().lower() or "unknown"
    return {
        "event_id": event_id,
        "event_type": "order_filled",
        "event_version": "v1",
        "ts_utc": ts_utc,
        "producer": "backfill.fills_csv",
        "instance_name": bot,
        "controller_id": "",
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "correlation_id": event_id,
        "stream": "local.backfill",
        "stream_entry_id": "",
        "payload": {
            "order_id": str(row.get("order_id", "")).strip(),
            "side": side,
            "price": _f("price"),
            "amount_base": _f("amount_base"),
            "notional_quote": _f("notional_quote"),
            "fee_quote": _f("fee_quote"),
            "is_maker": str(row.get("is_maker", "")).strip().lower() == "true",
        },
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

    def _variant_suffix(folder_name: str) -> str:
        # epp logger uses "{instance}_{variant}" directory naming, e.g. "bot1_a"
        name = (folder_name or "").strip()
        if "_" not in name:
            return name
        return name.split("_")[-1]

    # Find fills.csv files
    files = list(data_root.glob("*/logs/epp_v24/*/fills.csv"))
    if bot:
        files = [p for p in files if p.parts[-5] == bot]
    if variant:
        files = [p for p in files if _variant_suffix(p.parts[-2]) == variant or p.parts[-2] == variant]

    total_rows = 0
    appended = 0

    # Cache per-day existing IDs to avoid rereads
    existing_by_day: Dict[str, Set[str]] = {}
    fp_by_day: Dict[str, object] = {}

    def _get_day_file(day_key: str) -> Path:
        return store_dir / f"events_{day_key}.jsonl"

    try:
        for fills_path in files:
            try:
                bot_name = fills_path.parts[-5]
                var = _variant_suffix(fills_path.parts[-2])
            except Exception:
                continue
            rows = list(_iter_fill_rows(fills_path))
            for row in rows:
                ts = str(row.get("ts", "")).strip()
                dt = _parse_iso(ts)
                if dt is None:
                    continue
                day_key = dt.strftime("%Y%m%d")
                if day and day_key != day:
                    continue
                total_rows += 1

                if day_key not in existing_by_day:
                    existing_by_day[day_key] = _load_existing_event_ids(_get_day_file(day_key))

                event_id = _deterministic_event_id(bot_name, var, row)
                if event_id in existing_by_day[day_key]:
                    continue

                env = _build_envelope(
                    event_id=event_id,
                    bot=bot_name,
                    connector_name=str(row.get("exchange", "")).strip(),
                    trading_pair=str(row.get("trading_pair", "")).strip(),
                    ts_utc=dt.isoformat(),
                    row=row,
                )

                # Append
                out_path = _get_day_file(day_key)
                if day_key not in fp_by_day:
                    fp_by_day[day_key] = out_path.open("a", encoding="utf-8")
                fp = fp_by_day[day_key]
                fp.write(json.dumps(env, ensure_ascii=True) + "\n")

                existing_by_day[day_key].add(event_id)
                appended += 1
    finally:
        for fp in fp_by_day.values():
            try:
                fp.close()
            except Exception:
                pass

    return total_rows, appended


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill order_filled events from fills.csv")
    parser.add_argument("--bot", default="", help="Filter by bot name (e.g. bot1)")
    parser.add_argument("--variant", default="", help="Filter by variant (e.g. a)")
    parser.add_argument("--day", default="", help="Filter by UTC day YYYYMMDD (e.g. 20260225)")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    bot = args.bot.strip() or None
    variant = args.variant.strip() or None
    day = args.day.strip() or None

    total, appended = backfill(root=root, bot=bot, variant=variant, day=day)
    logger.info("fills_rows_scanned=%d appended_events=%d", total, appended)


if __name__ == "__main__":
    main()

