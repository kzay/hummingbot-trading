#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sys

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from services.common.retry import with_retry
from services.common.utils import read_json, safe_bool, safe_float, write_json


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_ts(raw: object) -> Optional[datetime]:
    if raw in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _iter_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _normalize_pair_token(token: str) -> str:
    t = token.strip().lower()
    if not t:
        return ""
    if ":" in t:
        return t
    if "_" in t:
        parts = t.split("_", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"{parts[0]}:{parts[1]}"
    return t


def _discover_fill_files(data_root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for path in sorted(data_root.glob("*/logs/epp_v24/*/fills.csv")):
        # Example:
        #   data/bot1/logs/epp_v24/bot1_a/fills.csv
        try:
            bot = path.parents[3].name.lower()
            folder = path.parent.name.lower()
            variant = folder.split("_", 1)[1] if "_" in folder else "a"
            source_key = f"{bot}:{variant}"
            out[source_key] = path
        except Exception:
            continue
    return out


def _select_fill_files(discovered: Dict[str, Path], bot_variants: str) -> Dict[str, Path]:
    spec = (bot_variants or "").strip()
    if not spec:
        return discovered
    wanted = {_normalize_pair_token(x) for x in spec.split(",")}
    wanted = {x for x in wanted if x}
    return {k: v for k, v in discovered.items() if k in wanted}


def _account_name(source_key: str, account_prefix: str) -> str:
    bot, variant = source_key.split(":", 1)
    base = f"{bot}_{variant}"
    prefix = account_prefix.strip()
    return f"{prefix}_{base}" if prefix else base


def _quote_currency(trading_pair: str) -> str:
    if "-" in trading_pair:
        parts = trading_pair.split("-", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip().upper()
    if "/" in trading_pair:
        parts = trading_pair.split("/", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip().upper()
    return "USD"


def _scoped_symbol(trading_pair: str, account: str, scope_symbol_by_account: bool) -> str:
    if not scope_symbol_by_account:
        return trading_pair
    pair = str(trading_pair).strip()
    acct = str(account).strip()
    if not pair or not acct:
        return pair
    return f"{pair}__{acct}"


def _to_tradenote_execution(
    row: Dict[str, str],
    account: str,
    security_type: str,
    settlement_days: int,
    exec_time_offset_sec: int = 0,
    scope_symbol_by_account: bool = False,
) -> Tuple[Optional[str], Optional[Dict[str, object]]]:
    ts = _parse_iso_ts(row.get("ts"))
    if ts is None:
        return None, None

    side_raw = str(row.get("side", "")).strip().lower()
    if side_raw == "buy":
        side = "B"
    elif side_raw == "sell":
        side = "S"
    else:
        return None, None

    trading_pair = str(row.get("trading_pair", "")).strip()
    if not trading_pair:
        return None, None

    qty = safe_float(row.get("amount_base"), 0.0)
    price = safe_float(row.get("price"), 0.0)
    notional = safe_float(row.get("notional_quote"), 0.0)
    fee = safe_float(row.get("fee_quote"), 0.0)
    if qty <= 0 or price <= 0:
        return None, None

    gross = notional if side == "S" else -notional
    net = gross - fee
    td = ts.strftime("%m/%d/%Y")
    sd = (ts + timedelta(days=max(0, settlement_days))).strftime("%m/%d/%Y")
    liq = "M" if safe_bool(row.get("is_maker")) else "T"
    order_id = str(row.get("order_id", "")).strip()
    note = f"hbot_order_id={order_id}" if order_id else "hbot_fill"
    # TradeNote derives execution/trade ids from date-time + symbol + side.
    # Offset per source keeps ids deterministic while avoiding cross-bot collisions.
    offset = max(0, int(exec_time_offset_sec))
    sec_of_day = ts.hour * 3600 + ts.minute * 60 + ts.second
    shifted_sec = (sec_of_day + offset) % 86400
    exec_hour, rem = divmod(shifted_sec, 3600)
    exec_minute, exec_second = divmod(rem, 60)
    exec_time = f"{exec_hour:02d}:{exec_minute:02d}:{exec_second:02d}"

    execution: Dict[str, object] = {
        "Account": account,
        "T/D": td,
        "S/D": sd,
        "Currency": _quote_currency(trading_pair),
        "Type": str(security_type),
        "Side": side,
        "Symbol": _scoped_symbol(trading_pair=trading_pair, account=account, scope_symbol_by_account=scope_symbol_by_account),
        "Qty": qty,
        "Price": price,
        "Exec Time": exec_time,
        "Comm": fee,
        "SEC": 0.0,
        "TAF": 0.0,
        "NSCC": 0.0,
        "Nasdaq": 0.0,
        "ECN Remove": 0.0,
        "ECN Add": 0.0,
        "Gross Proceeds": gross,
        "Net Proceeds": net,
        "Clr Broker": str(row.get("exchange", "")).strip(),
        "Liq": liq,
        "Note": note,
    }
    return ts.date().isoformat(), execution


def _collect_daily_payloads(
    fill_files: Dict[str, Path],
    imported_days: set[str],
    include_today: bool,
    lookback_days: int,
    account_prefix: str,
    security_type: str,
    settlement_days: int,
    scope_symbol_by_account: bool,
) -> Tuple[Dict[str, List[Dict[str, object]]], Dict[str, int], List[str]]:
    today = datetime.now(timezone.utc).date()
    min_day = today - timedelta(days=max(0, lookback_days)) if lookback_days > 0 else None

    rows_by_day: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    rows_by_source: Dict[str, int] = defaultdict(int)
    skipped_imported_days: set[str] = set()

    for source_idx, (source_key, fill_path) in enumerate(sorted(fill_files.items())):
        account = _account_name(source_key=source_key, account_prefix=account_prefix)
        # 10-second spacing prevents same-second id collisions across bot variants.
        source_exec_time_offset_sec = source_idx * 10
        for row in _iter_csv_rows(fill_path):
            day_key, execution = _to_tradenote_execution(
                row=row,
                account=account,
                security_type=security_type,
                settlement_days=settlement_days,
                exec_time_offset_sec=source_exec_time_offset_sec,
                scope_symbol_by_account=scope_symbol_by_account,
            )
            if not day_key or execution is None:
                continue
            day_obj = date.fromisoformat(day_key)
            if not include_today and day_obj >= today:
                continue
            if min_day is not None and day_obj < min_day:
                continue
            if day_key in imported_days:
                skipped_imported_days.add(day_key)
                continue
            rows_by_day[day_key].append(execution)
            rows_by_source[source_key] += 1

    return dict(rows_by_day), dict(rows_by_source), sorted(skipped_imported_days)


def _post_trades(
    base_url: str,
    api_key: str,
    selected_broker: str,
    upload_mfe_prices: bool,
    rows: List[Dict[str, object]],
    timeout_sec: float,
    max_attempts: int,
) -> str:
    payload = {
        "uploadMfePrices": upload_mfe_prices,
        "selectedBroker": selected_broker,
        "data": rows,
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = f"{base_url.rstrip('/')}/api/trades"

    def _do_request() -> str:
        req = Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout_sec) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                if resp.status != 200:
                    raise RuntimeError(f"http_{resp.status}: {text}")
                return text
        except HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise RuntimeError(f"http_{e.code}: {detail}") from e
        except URLError as e:
            raise RuntimeError(f"url_error: {e}") from e

    def _is_retryable(exc: Exception) -> bool:
        low = str(exc).lower()
        return any(x in low for x in ("http_429", "http_500", "http_502", "http_503", "http_504", "timeout", "url_error"))

    return with_retry(
        fn=_do_request,
        max_attempts=max(1, max_attempts),
        base_delay_s=1.0,
        max_delay_s=15.0,
        retryable=_is_retryable,
    )


def _chunk_rows(rows: List[Dict[str, object]], max_rows_per_post: int) -> List[List[Dict[str, object]]]:
    size = max(1, int(max_rows_per_post))
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def _load_state(path: Path) -> Dict[str, object]:
    payload = read_json(path, default={"imported_days": [], "last_success_utc": None, "last_error": None})
    imported_days = payload.get("imported_days", [])
    if not isinstance(imported_days, list):
        imported_days = []
    payload["imported_days"] = [str(x) for x in imported_days if str(x).strip()]
    return payload


def _save_state(path: Path, state: Dict[str, object]) -> None:
    write_json(path, state)


def run_once(
    data_root: Path,
    state_path: Path,
    report_path: Path,
    tradenote_url: str,
    tradenote_api_key: str,
    selected_broker: str,
    upload_mfe_prices: bool,
    include_today: bool,
    lookback_days: int,
    account_prefix: str,
    security_type: str,
    settlement_days: int,
    max_days_per_run: int,
    request_timeout_sec: float,
    request_max_attempts: int,
    max_rows_per_post: int,
    bot_variants: str,
    scope_symbol_by_account: bool,
) -> Dict[str, object]:
    state = _load_state(state_path)
    imported_days = set(str(x) for x in state.get("imported_days", []))
    discovered = _discover_fill_files(data_root=data_root)
    selected_files = _select_fill_files(discovered=discovered, bot_variants=bot_variants)

    rows_by_day, rows_by_source, skipped_imported_days = _collect_daily_payloads(
        fill_files=selected_files,
        imported_days=imported_days,
        include_today=include_today,
        lookback_days=lookback_days,
        account_prefix=account_prefix,
        security_type=security_type,
        settlement_days=settlement_days,
        scope_symbol_by_account=scope_symbol_by_account,
    )
    candidate_days = sorted(rows_by_day.keys())
    if max_days_per_run > 0:
        candidate_days = candidate_days[:max_days_per_run]

    report: Dict[str, object] = {
        "ts_utc": _utc_now_iso(),
        "status": "ok",
        "tradenote_url": tradenote_url,
        "selected_broker": selected_broker,
        "upload_mfe_prices": upload_mfe_prices,
        "include_today": include_today,
        "lookback_days": lookback_days,
        "discovered_sources": sorted(selected_files.keys()),
        "rows_by_source": rows_by_source,
        "candidate_days": candidate_days,
        "skipped_imported_days": skipped_imported_days,
        "imported_days_total_before": len(imported_days),
        "imported_days_total_after": len(imported_days),
        "imported_this_run": [],
        "rows_posted_by_day": {},
        "state_path": str(state_path),
        "max_rows_per_post": max(1, int(max_rows_per_post)),
        "chunks_posted_by_day": {},
        "scope_symbol_by_account": bool(scope_symbol_by_account),
    }

    if not tradenote_api_key.strip():
        report["status"] = "config_error"
        report["error"] = "missing_tradenote_api_key"
        write_json(report_path, report)
        return report

    for day_key in candidate_days:
        day_rows = rows_by_day.get(day_key, [])
        if not day_rows:
            continue
        try:
            posted_chunks = 0
            for chunk in _chunk_rows(day_rows, max_rows_per_post=max_rows_per_post):
                _post_trades(
                    base_url=tradenote_url,
                    api_key=tradenote_api_key,
                    selected_broker=selected_broker,
                    upload_mfe_prices=upload_mfe_prices,
                    rows=chunk,
                    timeout_sec=request_timeout_sec,
                    max_attempts=request_max_attempts,
                )
                posted_chunks += 1
            imported_days.add(day_key)
            report["imported_this_run"].append(day_key)
            report["rows_posted_by_day"][day_key] = len(day_rows)
            report["chunks_posted_by_day"][day_key] = posted_chunks
            state["imported_days"] = sorted(imported_days)
            state["last_success_utc"] = _utc_now_iso()
            state["last_error"] = None
            _save_state(state_path, state)
        except Exception as e:
            state["last_error"] = str(e)
            _save_state(state_path, state)
            report["status"] = "error"
            report["error"] = f"post_failed_day_{day_key}: {e}"
            break

    report["imported_days_total_after"] = len(imported_days)
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-sync completed fills.csv days to self-hosted TradeNote.")
    parser.add_argument("--interval-sec", type=int, default=int(os.getenv("TRADENOTE_SYNC_INTERVAL_SEC", "1800")))
    parser.add_argument("--max-runs", type=int, default=0, help="0 means run forever.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    report_path = Path(os.getenv("TRADENOTE_SYNC_REPORT_PATH", str(root / "reports" / "tradenote" / "sync_latest.json")))
    state_path = Path(os.getenv("TRADENOTE_SYNC_STATE_PATH", str(root / "reports" / "tradenote" / "sync_state.json")))

    run_count = 0
    while True:
        run_count += 1
        report = run_once(
            data_root=data_root,
            state_path=state_path,
            report_path=report_path,
            tradenote_url=os.getenv("TRADENOTE_URL", "http://tradenote:8080"),
            tradenote_api_key=os.getenv("TRADENOTE_API_KEY", ""),
            selected_broker=os.getenv("TRADENOTE_SELECTED_BROKER", "template"),
            upload_mfe_prices=safe_bool(os.getenv("TRADENOTE_UPLOAD_MFE", "false")),
            include_today=safe_bool(os.getenv("TRADENOTE_SYNC_INCLUDE_TODAY", "false")),
            lookback_days=int(os.getenv("TRADENOTE_SYNC_LOOKBACK_DAYS", "14")),
            account_prefix=os.getenv("TRADENOTE_ACCOUNT_PREFIX", "hbot"),
            security_type=os.getenv("TRADENOTE_SECURITY_TYPE", "0"),
            settlement_days=int(os.getenv("TRADENOTE_SETTLEMENT_DAYS", "0")),
            max_days_per_run=int(os.getenv("TRADENOTE_SYNC_MAX_DAYS_PER_RUN", "2")),
            request_timeout_sec=safe_float(os.getenv("TRADENOTE_SYNC_REQUEST_TIMEOUT_SEC", "20"), 20.0),
            request_max_attempts=int(os.getenv("TRADENOTE_SYNC_REQUEST_MAX_ATTEMPTS", "3")),
            max_rows_per_post=int(os.getenv("TRADENOTE_SYNC_MAX_ROWS_PER_POST", "100")),
            bot_variants=os.getenv("TRADENOTE_SYNC_BOT_VARIANTS", ""),
            scope_symbol_by_account=safe_bool(os.getenv("TRADENOTE_SCOPE_SYMBOL_BY_ACCOUNT", "true")),
        )
        print(
            f"[tradenote-sync] run={run_count} status={report.get('status')} "
            f"candidates={len(report.get('candidate_days', []))} "
            f"imported={len(report.get('imported_this_run', []))}",
            flush=True,
        )
        if report.get("status") == "error":
            print(f"[tradenote-sync] error={report.get('error')}", flush=True)

        if args.max_runs > 0 and run_count >= args.max_runs:
            break
        time.sleep(max(30, args.interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
