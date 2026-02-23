from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object in {path}")
    return payload


def _set_from_list(value: object) -> Set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if str(item).strip()}


def _extract_portfolio_action_scope(policy_bots: Dict[str, object]) -> Set[str]:
    action_scope: Set[str] = set()
    for bot, cfg in policy_bots.items():
        if not isinstance(cfg, dict):
            continue
        if bool(cfg.get("portfolio_action_enabled", False)):
            action_scope.add(str(bot))
    return action_scope


def _extract_disabled_bot_scope(policy_bots: Dict[str, object]) -> Set[str]:
    disabled_scope: Set[str] = set()
    for bot, cfg in policy_bots.items():
        if not isinstance(cfg, dict):
            continue
        mode = str(cfg.get("mode", "")).strip().lower()
        enabled = bool(cfg.get("enabled", False))
        if (not enabled) or mode == "disabled":
            disabled_scope.add(str(bot))
    return disabled_scope


def _check_policy(root: Path) -> Tuple[bool, List[str], Dict[str, object]]:
    policy_path = root / "config" / "multi_bot_policy_v1.json"
    account_map_path = root / "config" / "exchange_account_map.json"
    portfolio_path = root / "config" / "portfolio_limits_v1.json"
    recon_path = root / "config" / "reconciliation_thresholds.json"

    errors: List[str] = []
    policy = _read_json(policy_path)
    account_map = _read_json(account_map_path)
    portfolio = _read_json(portfolio_path)
    recon = _read_json(recon_path)

    policy_bots = policy.get("bots", {})
    if not isinstance(policy_bots, dict) or not policy_bots:
        raise ValueError("multi_bot_policy_v1.json must contain a non-empty 'bots' object")

    policy_bot_set = {str(k) for k in policy_bots.keys()}
    account_bot_set = {str(k) for k in account_map.get("bots", {}).keys()} if isinstance(account_map.get("bots"), dict) else set()
    recon_bot_set = {str(k) for k in recon.get("bots", {}).keys()} if isinstance(recon.get("bots"), dict) else set()

    if policy_bot_set != account_bot_set:
        errors.append(
            f"policy bots mismatch exchange account map: policy={sorted(policy_bot_set)} account_map={sorted(account_bot_set)}"
        )
    if not policy_bot_set.issubset(recon_bot_set):
        errors.append(
            f"policy bots missing in reconciliation thresholds: missing={sorted(policy_bot_set - recon_bot_set)}"
        )

    action_scope_policy = _extract_portfolio_action_scope(policy_bots)
    action_scope_portfolio = _set_from_list(portfolio.get("bot_action_scope", []))
    if action_scope_policy != action_scope_portfolio:
        errors.append(
            f"portfolio action scope mismatch: policy={sorted(action_scope_policy)} portfolio={sorted(action_scope_portfolio)}"
        )

    disabled_scope = _extract_disabled_bot_scope(policy_bots)
    for bot in sorted(policy_bot_set):
        bot_policy = policy_bots.get(bot, {})
        bot_map = account_map.get("bots", {}).get(bot, {}) if isinstance(account_map.get("bots"), dict) else {}
        bot_recon = recon.get("bots", {}).get(bot, {}) if isinstance(recon.get("bots"), dict) else {}

        if isinstance(bot_policy, dict) and isinstance(bot_map, dict):
            policy_mode = str(bot_policy.get("mode", "")).strip().lower()
            map_mode = str(bot_map.get("account_mode", "")).strip().lower()
            if policy_mode == "paper_only" and map_mode != "paper_only":
                errors.append(f"{bot}: expected account_mode=paper_only, got {map_mode or 'unset'}")
            if policy_mode == "disabled" and map_mode != "disabled":
                errors.append(f"{bot}: expected account_mode=disabled, got {map_mode or 'unset'}")

        if bot in disabled_scope:
            enabled = bool(bot_recon.get("enabled", True)) if isinstance(bot_recon, dict) else True
            if enabled:
                errors.append(f"{bot}: disabled bot must set reconciliation bots.{bot}.enabled=false")

    status = len(errors) == 0
    details = {
        "policy_bots": sorted(policy_bot_set),
        "portfolio_action_scope_policy": sorted(action_scope_policy),
        "portfolio_action_scope_portfolio": sorted(action_scope_portfolio),
        "disabled_scope": sorted(disabled_scope),
        "paths": {
            "policy": str(policy_path),
            "exchange_account_map": str(account_map_path),
            "portfolio_limits": str(portfolio_path),
            "reconciliation_thresholds": str(recon_path),
        },
    }
    return status, errors, details


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "policy"
    reports_root.mkdir(parents=True, exist_ok=True)

    try:
        ok, errors, details = _check_policy(root)
        payload = {
            "ts_utc": _utc_now(),
            "status": "pass" if ok else "fail",
            "errors": errors,
            "details": details,
        }
    except Exception as exc:
        payload = {
            "ts_utc": _utc_now(),
            "status": "fail",
            "errors": [f"policy check exception: {exc}"],
            "details": {},
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = reports_root / f"multi_bot_policy_check_{stamp}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (reports_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[multi-bot-policy] status={payload['status']}")
    print(f"[multi-bot-policy] evidence={out_file}")
    if payload.get("errors"):
        for error in payload["errors"]:
            print(f"[multi-bot-policy] error={error}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
