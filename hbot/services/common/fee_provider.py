from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass
class FeeRates:
    maker: Decimal
    taker: Decimal
    source: str


class FeeResolver:
    @staticmethod
    def _canonical_connector(connector_name: str) -> str:
        name = (connector_name or "").strip()
        if name.endswith("_paper_trade"):
            return name.replace("_paper_trade", "")
        return name

    @staticmethod
    def _pair_tokens(trading_pair: str) -> Tuple[str, str]:
        raw = (trading_pair or "").replace("/", "-").upper()
        if "-" in raw:
            base, quote = raw.split("-", 1)
            return base, quote
        if raw.endswith("USDT") and len(raw) > 4:
            return raw[:-4], "USDT"
        return raw, "USDT"

    @staticmethod
    def _extract_bitget_credentials(connector: Any) -> Optional[Tuple[str, str, str]]:
        if connector is None:
            return None
        candidates = [connector, getattr(connector, "auth", None), getattr(connector, "_auth", None)]
        for obj in candidates:
            if obj is None:
                continue
            api_key = None
            secret_key = None
            passphrase = None
            for attr in ("api_key", "_api_key", "bitget_api_key", "_bitget_api_key"):
                value = getattr(obj, attr, None)
                if value:
                    api_key = str(value)
                    break
            for attr in ("secret_key", "_secret_key", "bitget_secret_key", "_bitget_secret_key"):
                value = getattr(obj, attr, None)
                if value:
                    secret_key = str(value)
                    break
            for attr in ("passphrase", "_passphrase", "bitget_passphrase", "_bitget_passphrase"):
                value = getattr(obj, attr, None)
                if value:
                    passphrase = str(value)
                    break
            if api_key and secret_key and passphrase:
                return api_key, secret_key, passphrase
        return None

    @classmethod
    def from_exchange_api(cls, connector: Any, connector_name: str, trading_pair: str) -> Optional[FeeRates]:
        canonical = cls._canonical_connector(connector_name)
        if not canonical.startswith("bitget"):
            return None
        creds = cls._extract_bitget_credentials(connector)
        if creds is None:
            return None
        api_key, secret_key, passphrase = creds

        is_perp = "perpetual" in canonical
        business = "mix" if is_perp else "spot"
        base, quote = cls._pair_tokens(trading_pair)
        symbol = f"{base}{quote}_{'UMCBL' if is_perp else 'SPBL'}"
        path = "/api/user/v1/fee/query"
        query = urlencode({"symbol": symbol, "business": business})
        request_path = f"{path}?{query}"
        ts_ms = str(int(time.time() * 1000))
        prehash = f"{ts_ms}GET{request_path}"
        signature = base64.b64encode(
            hmac.new(secret_key.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-PASSPHRASE": passphrase,
            "ACCESS-TIMESTAMP": ts_ms,
            "locale": "en-US",
            "Content-Type": "application/json",
            "User-Agent": "hbot-epp-fee-resolver/1.0",
        }
        try:
            with urlopen(Request(f"https://api.bitget.com{request_path}", headers=headers, method="GET"), timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if str(payload.get("code")) != "00000":
                return None
            data = payload.get("data") or {}
            maker = _d(data.get("makerRate"))
            taker = _d(data.get("takerRate"))
            if maker <= 0 or taker <= 0:
                return None
            return FeeRates(maker=maker, taker=taker, source="api:bitget:user_fee_query")
        except Exception:
            return None

    @staticmethod
    def _candidate_profile_paths() -> Tuple[Path, ...]:
        env_path = os.getenv("HB_FEE_PROFILE_PATH", "").strip()
        paths = []
        if env_path:
            paths.append(Path(env_path))
        paths.append(Path("/home/hummingbot/project_config/fee_profiles.json"))
        paths.append(Path(__file__).resolve().parents[2] / "config" / "fee_profiles.json")
        return tuple(paths)

    @classmethod
    def from_project_profile(cls, connector_name: str, profile: str) -> Optional[FeeRates]:
        canonical = cls._canonical_connector(connector_name)
        profile_key = (profile or "vip0").strip()
        for path in cls._candidate_profile_paths():
            if not path.exists():
                continue
            try:
                payload: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
                table = (payload.get("profiles") or {}).get(profile_key, {})
                row = table.get(canonical)
                if not row:
                    continue
                maker = _d(row.get("maker"))
                taker = _d(row.get("taker"))
                if maker <= 0 or taker <= 0:
                    continue
                return FeeRates(maker=maker, taker=taker, source=f"project:{path}")
            except Exception:
                continue
        return None

    @staticmethod
    def from_connector_runtime(connector: Any, trading_pair: str) -> Optional[FeeRates]:
        if connector is None:
            return None
        try:
            trading_fees = getattr(connector, "trading_fees", None)
            if isinstance(trading_fees, dict):
                row = trading_fees.get(trading_pair)
                if row is not None:
                    maker = getattr(row, "maker_fee", None) or getattr(row, "maker_fee_rate", None)
                    taker = getattr(row, "taker_fee", None) or getattr(row, "taker_fee_rate", None)
                    if maker is not None and taker is not None:
                        maker_d = _d(maker)
                        taker_d = _d(taker)
                        if maker_d > 0 and taker_d > 0:
                            return FeeRates(maker=maker_d, taker=taker_d, source="connector:trading_fees")
        except Exception:
            pass

        for maker_attr, taker_attr in (
            ("maker_fee_pct", "taker_fee_pct"),
            ("maker_fee_rate", "taker_fee_rate"),
            ("maker_fee", "taker_fee"),
        ):
            try:
                maker = getattr(connector, maker_attr, None)
                taker = getattr(connector, taker_attr, None)
                if maker is None or taker is None:
                    continue
                maker_d = _d(maker)
                taker_d = _d(taker)
                if maker_d > 0 and taker_d > 0:
                    return FeeRates(maker=maker_d, taker=taker_d, source=f"connector:{maker_attr}")
            except Exception:
                continue
        return None
