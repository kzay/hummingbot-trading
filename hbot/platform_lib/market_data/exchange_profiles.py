from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


_DEFAULT_PROFILES = {
    "binance_demo_perp": {
        "connector_name": "binance_perpetual_testnet",
        "market_type": "perpetual",
        "is_demo": True,
        "requires_paper_trade_exchange": None,
        "notes": "Binance futures demo environment through binance_perpetual_testnet connector.",
    },
    "bitget_spot_live": {
        "connector_name": "bitget",
        "market_type": "spot",
        "is_demo": False,
        "requires_paper_trade_exchange": None,
        "notes": "Bitget live spot connector.",
    },
    "bitget_spot_paper": {
        "connector_name": "bitget_paper_trade",
        "market_type": "spot",
        "is_demo": True,
        "requires_paper_trade_exchange": "bitget",
        "notes": "Bitget paper connector that needs bitget in paper_trade_exchanges.",
    },
}


def _load_profiles_file(profiles_file: Path) -> Dict[str, Any]:
    if not profiles_file.exists():
        return {"profiles": _DEFAULT_PROFILES}
    with profiles_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "profiles" not in payload:
        return {"profiles": _DEFAULT_PROFILES}
    profiles = payload.get("profiles")
    return {"profiles": profiles if isinstance(profiles, dict) else _DEFAULT_PROFILES}


def resolve_profile(connector_name: str, profiles_file: Optional[str] = None) -> Optional[Dict[str, Any]]:
    profiles_path = Path(profiles_file) if profiles_file else Path("/home/hummingbot/project_config/exchange_profiles.json")
    profiles = _load_profiles_file(profiles_path).get("profiles", {})
    if not isinstance(profiles, dict):
        return None
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        if profile.get("connector_name") == connector_name:
            return {"name": profile_name, **profile}
    return None
