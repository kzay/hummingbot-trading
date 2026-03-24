from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from services.common.exchange_profiles import resolve_profile


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        # Minimal fallback parser for environments without PyYAML.
        text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        result: Dict[str, Any] = {"paper_trade": {"paper_trade_exchanges": []}}
        in_paper = False
        in_exchanges = False
        for line in text:
            if re.match(r"^\s*paper_trade:\s*$", line):
                in_paper = True
                in_exchanges = False
                continue
            if in_paper and re.match(r"^\S", line):
                in_paper = False
                in_exchanges = False
            if in_paper and re.match(r"^\s{2}paper_trade_exchanges:\s*$", line):
                in_exchanges = True
                continue
            if in_exchanges and re.match(r"^\s{2}[a-zA-Z0-9_]+\s*:", line):
                in_exchanges = False
            if in_exchanges:
                m = re.match(r"^\s*-\s*([a-zA-Z0-9_]+)\s*$", line)
                if m:
                    result["paper_trade"]["paper_trade_exchanges"].append(m.group(1))
        return result


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f) or {}
    return payload if isinstance(payload, dict) else {}


def run_controller_preflight(controller_cfg: Any) -> List[str]:
    errors: List[str] = []
    connector_name = str(getattr(controller_cfg, "connector_name", "") or "")
    trading_pair = str(getattr(controller_cfg, "trading_pair", "") or "")
    fee_profile = str(getattr(controller_cfg, "fee_profile", "vip0") or "vip0")

    if connector_name == "":
        errors.append("connector_name is missing")
    if trading_pair == "" or "-" not in trading_pair:
        errors.append(f"trading_pair is invalid: {trading_pair!r}")

    conf_client_path = Path("/home/hummingbot/conf/conf_client.yml")
    fee_profiles_path = Path("/home/hummingbot/project_config/fee_profiles.json")
    conf_client = _read_yaml(conf_client_path)
    fee_profiles = _read_json(fee_profiles_path)

    profile = resolve_profile(connector_name)
    if profile is None:
        errors.append(f"connector '{connector_name}' is not mapped in exchange_profiles.json")
    else:
        required_paper = profile.get("requires_paper_trade_exchange")
        if required_paper:
            paper_exchanges = (
                conf_client.get("paper_trade", {}).get("paper_trade_exchanges", [])
                if isinstance(conf_client.get("paper_trade", {}), dict)
                else []
            )
            if required_paper not in paper_exchanges:
                errors.append(
                    f"connector '{connector_name}' requires paper_trade_exchanges to include '{required_paper}'"
                )

    profiles = fee_profiles.get("profiles", {})
    fee_profile_cfg = profiles.get(fee_profile, {}) if isinstance(profiles, dict) else {}
    if not isinstance(fee_profile_cfg, dict) or connector_name not in fee_profile_cfg:
        errors.append(f"fee profile '{fee_profile}' missing connector '{connector_name}' in fee_profiles.json")

    return errors
