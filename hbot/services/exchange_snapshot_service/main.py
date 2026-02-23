from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None


from services.common.utils import (
    read_last_csv_row as _read_last_csv_row,
    safe_float as _safe_float,
    utc_now as _utc_now,
)


def _get_bitget_credentials(prefix: str = "") -> Tuple[str, str, str]:
    pfx = f"{prefix.strip().upper()}_" if prefix and not prefix.endswith("_") else prefix.strip().upper()
    api_key = os.getenv(f"{pfx}BITGET_API_KEY", os.getenv("BITGET_API_KEY", "")).strip()
    secret = os.getenv(f"{pfx}BITGET_SECRET", os.getenv("BITGET_SECRET", "")).strip()
    passphrase = os.getenv(f"{pfx}BITGET_PASSPHRASE", os.getenv("BITGET_PASSPHRASE", "")).strip()
    return api_key, secret, passphrase


def _redact_sensitive(text: str, credential_prefix: str = "") -> str:
    if not text:
        return text
    redacted = str(text)
    api_key, secret, passphrase = _get_bitget_credentials(credential_prefix)
    for token in (api_key, secret, passphrase):
        if token and len(token) >= 6:
            redacted = redacted.replace(token, "***redacted***")
    return redacted


def _fetch_bitget_balances_ccxt(assets: list[str], credential_prefix: str = "") -> Dict[str, object]:
    if ccxt is None:
        return {"status": "ccxt_unavailable", "balances": {}, "error": "ccxt_not_installed"}

    api_key, secret, passphrase = _get_bitget_credentials(credential_prefix)
    if not api_key or not secret or not passphrase:
        return {"status": "missing_credentials", "balances": {}, "error": f"bitget_credentials_not_set:{credential_prefix or 'GLOBAL'}"}

    try:
        exchange = ccxt.bitget(
            {
                "apiKey": api_key,
                "secret": secret,
                "password": passphrase,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )
        balances = exchange.fetch_balance()
        total = balances.get("total", {}) if isinstance(balances, dict) else {}
        free = balances.get("free", {}) if isinstance(balances, dict) else {}

        snapshot = {}
        for asset in assets:
            snapshot[asset] = {
                "total": _safe_float(total.get(asset), 0.0),
                "free": _safe_float(free.get(asset), 0.0),
            }
        return {"status": "ok", "balances": snapshot, "error": ""}
    except Exception as e:
        return {
            "status": "fetch_failed",
            "balances": {},
            "error": _redact_sensitive(str(e), credential_prefix),
        }


def _load_account_map(path: Path) -> Dict[str, object]:
    default = {
        "defaults": {"exchange": "bitget", "credential_prefix": "BOT1"},
        "bots": {},
    }
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return default
        return {
            "defaults": payload.get("defaults", default["defaults"]),
            "bots": payload.get("bots", {}),
        }
    except Exception:
        return default


def _resolve_bot_account(account_map: Dict[str, object], bot: str) -> Dict[str, str]:
    defaults = account_map.get("defaults", {}) if isinstance(account_map.get("defaults"), dict) else {}
    bots = account_map.get("bots", {}) if isinstance(account_map.get("bots"), dict) else {}
    row = bots.get(bot, {}) if isinstance(bots.get(bot, {}), dict) else {}
    exchange = str(row.get("exchange", defaults.get("exchange", "bitget"))).strip().lower()
    credential_prefix = str(row.get("credential_prefix", defaults.get("credential_prefix", "BOT1"))).strip().upper()
    account_mode = str(row.get("account_mode", defaults.get("account_mode", "probe"))).strip().lower()
    return {"exchange": exchange, "credential_prefix": credential_prefix, "account_mode": account_mode}


def run() -> None:
    root = Path("/workspace/hbot")
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    out_path = Path(os.getenv("EXCHANGE_SNAPSHOT_OUT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json")))
    interval_sec = int(os.getenv("EXCHANGE_SNAPSHOT_INTERVAL_SEC", "120"))
    snapshot_mode = os.getenv("EXCHANGE_SNAPSHOT_MODE", "proxy_local").strip().lower()
    assets = [a.strip().upper() for a in os.getenv("EXCHANGE_SNAPSHOT_ASSETS", "BTC,USDT").split(",") if a.strip()]
    account_map_path = Path(
        os.getenv("EXCHANGE_ACCOUNT_MAP_PATH", str(root / "config" / "exchange_account_map.json"))
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        account_map = _load_account_map(account_map_path)
        account_probe = {"status": "disabled", "balances": {}, "error": ""}
        probe_cache: Dict[str, Dict[str, object]] = {}
        if snapshot_mode == "bitget_ccxt_private":
            account_probe = _fetch_bitget_balances_ccxt(assets, "")

        bots: Dict[str, Dict[str, object]] = {}
        for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
            bot = minute_file.parts[-5]
            row = _read_last_csv_row(minute_file)
            if row is None:
                continue
            exchange_name = str(row.get("exchange", ""))
            bots[bot] = {
                "base_pct": _safe_float(row.get("base_pct"), 0.0),
                "equity_quote": _safe_float(row.get("equity_quote"), 0.0),
                "exchange": exchange_name,
                "trading_pair": str(row.get("trading_pair", "")),
                "source": "local_minute_proxy" if snapshot_mode == "proxy_local" else f"{snapshot_mode}_with_local_reference",
            }
            if snapshot_mode == "bitget_ccxt_private" and "bitget" in exchange_name:
                account_cfg = _resolve_bot_account(account_map, bot)
                prefix = account_cfg["credential_prefix"]
                mode = account_cfg.get("account_mode", "probe")
                if mode == "disabled":
                    bot_probe = {"status": "disabled", "balances": {}, "error": "account_probe_disabled"}
                elif mode == "paper_only":
                    bot_probe = {"status": "paper_only", "balances": {}, "error": "paper_validation_mode_no_private_probe"}
                else:
                    if prefix not in probe_cache:
                        probe_cache[prefix] = _fetch_bitget_balances_ccxt(assets, prefix)
                    bot_probe = probe_cache[prefix]
                bots[bot]["account_scope"] = f"mapped:{prefix}"
                bots[bot]["account_probe_status"] = bot_probe.get("status", "unknown")
                bots[bot]["account_balances"] = bot_probe.get("balances", {})
                bots[bot]["account_probe_error"] = bot_probe.get("error", "")
                bots[bot]["account_exchange"] = account_cfg["exchange"]
                bots[bot]["account_credential_prefix"] = prefix
                bots[bot]["account_mode"] = mode

        payload = {
            "ts_utc": _utc_now(),
            "source": "exchange_snapshot_service",
            "mode": snapshot_mode,
            "account_map_path": str(account_map_path),
            "note": "Snapshot uses local minute.csv references plus optional exchange probe. For per-bot exchange truth, use dedicated account mapping and direct API pull.",
            "account_probe": account_probe,
            "account_probe_cache": probe_cache if snapshot_mode == "bitget_ccxt_private" else {},
            "bots": bots,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    run()
